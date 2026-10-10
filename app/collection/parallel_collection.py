"""언어별 Tavily 작업만 제한적으로 병렬 실행하고 결과는 입력 순서로 병합한다."""
from asyncio import CancelledError
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock

from frame.collector import OSINTCollector


class SearchWorker(OSINTCollector):
    """수집기 내부 상태와 중단 신호를 각 작업자에 연결한다."""
    def __init__(self, api_key=None, raise_on_error=False, cancel_event=None):
        super().__init__(api_key, raise_on_error)
        self.cancel_event = cancel_event if cancel_event is not None else Event()

    def _check_cancelled(self):
        if self.cancel_event.is_set():
            raise CancelledError

    def collect(self, *args, **kwargs):
        self._check_cancelled()
        result = super().collect(*args, **kwargs)
        self._check_cancelled()
        return result

    def _recover_search_bodies(self, *args, **kwargs):
        self._check_cancelled()
        result = super()._recover_search_bodies(*args, **kwargs)
        self._check_cancelled()
        return result


class ParallelOSINTCollector(SearchWorker):
    def __init__(self, api_key=None, raise_on_error=False, cancel_event=None):
        cancel_event = cancel_event if cancel_event is not None else Event()
        super().__init__(api_key, raise_on_error, cancel_event)
        self._worker_arguments = dict(api_key=api_key, raise_on_error=raise_on_error,
                                      cancel_event=cancel_event)
        self.progress = None

    def collect_multilingual(self, queries, **kwargs):
        items = list(queries.items()) if isinstance(queries, dict) else [
            (f'query_{i+1}', q) for i, q in enumerate(queries)]
        if not items:
            return []
        completed = 0
        failures, failure_lock = [], Lock()
        def emit(detail):
            if self.progress:
                self.progress({'completed': completed, 'total': len(items), 'detail': detail})
        def run(item):
            worker = SearchWorker(**self._worker_arguments)
            try:
                worker._check_cancelled()
                docs = worker.collect_multilingual(dict([item]), **kwargs)
                return docs, worker
            except BaseException as exc:
                # 취소가 원래 검색 오류를 가리지 않게 먼저 기록하고, 동료의 후속 요청을 막는다.
                if not isinstance(exc, CancelledError):
                    with failure_lock:
                        if not failures:
                            failures.append(exc)
                self.cancel_event.set()
                raise
        emit('언어별 검색·본문 수집을 시작합니다. 최대 2개 언어를 동시에 처리합니다.')
        results = {}
        with ThreadPoolExecutor(max_workers=min(2, len(items))) as pool:
            futures = {pool.submit(run, item): index for index, item in enumerate(items)}
            try:
                for future in as_completed(futures):
                    index = futures[future]
                    results[index] = future.result()
                    self._check_cancelled()
                    completed += 1
                    emit(f'{items[index][0]} 검색·본문 수집 완료')
            except BaseException:
                self.cancel_event.set()
                for future in futures:
                    future.cancel()
                if failures:
                    raise failures[0] from None
                raise
        # 공유 Tavily 클라이언트·필터 상태의 경쟁을 피한다. 중복 선택 순서는 항상 입력 순서다.
        docs, urls, titles, fingerprints = [], set(), set(), set()
        for index in range(len(items)):
            candidates, worker = results[index]
            self.filter_rejections.extend(worker.filter_rejections)
            self.search_attempts.extend(worker.search_attempts)
            for key in self.body_recovery:
                self.body_recovery[key] += worker.body_recovery[key]
            for doc in candidates:
                url = self._canonicalize_url(doc['url'])
                title = self._canonicalize_title(doc.get('title', ''))
                fingerprint = self._content_fingerprint(doc.get('article_text', ''))
                if url in urls or (title and title in titles) or (fingerprint and fingerprint in fingerprints):
                    continue
                urls.add(url)
                if title:
                    titles.add(title)
                if fingerprint:
                    fingerprints.add(fingerprint)
                docs.append(doc)
        return docs
