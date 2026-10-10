"""사용자 질문 → 로컬 검색 계획 → frame 요청 → 실제 수집 결과."""

import asyncio
import json
import time
from datetime import UTC, datetime
from threading import Event
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from frame.schemas import SearchPlanRequest

from app.collection.collection_export import collection_export
from app.config import Settings
from app.core.errors import AnalysisError
from app.search.ollama_search import OllamaSearch
from app.collection.parallel_collection import ParallelOSINTCollector as OSINTCollector
from app.search.search_schemas import CollectionRequest


class CollectionFlow:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.directory = settings.database.parent / 'collections'
        self.jobs: dict[str, dict] = {}
        self.task: asyncio.Task | None = None
        self.cancel_event: Event | None = None
        self.started = False
        self.lock = asyncio.Lock()

    def path(self, rid: str):
        return self.directory / (rid + '.json')

    def save(self, job: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path(job['id'])
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)

    async def execute(self, job: dict, body: CollectionRequest, cancel_event: Event) -> None:
        final_status = 'failed'
        started = time.perf_counter()
        collection_started = None
        job['timings'] = {}
        loop = asyncio.get_running_loop()
        def progress(update):
            if job.get('cancel_requested') or job['status'] != 'running':
                return
            values = {**job.get('progress', {}), **update}
            total = values.get('total', 0)
            values['percent'] = round(values.get('completed', 0) / total * 100, 1) if total else None
            job['progress'] = values
        try:
            self.started = True
            if cancel_event.is_set():
                raise asyncio.CancelledError
            provider = OllamaSearch(self.settings)
            provider.progress = progress
            provider.activity = progress
            plan = await asyncio.wait_for(provider.generate(
                body.question, body.languages, job['llm_trace']),
                timeout=self.settings.ollama_timeout)
            job['timings']['query_seconds'] = round(time.perf_counter() - started, 3)
            if body.event_date and plan.event_date and body.event_date.isoformat() != plan.event_date:
                raise AnalysisError('입력한 사건 날짜와 질문에 명시된 날짜가 다릅니다.')
            event_date = body.event_date.isoformat() if body.event_date else plan.event_date
            if event_date:
                for query in plan.queries:
                    if event_date not in query.query:
                        query.query += '; ' + event_date
            retrieval_queries = job['llm_trace']['response']['retrieval_queries']
            if event_date:
                for language, query in retrieval_queries.items():
                    if event_date not in query:
                        retrieval_queries[language] = query + ' ' + event_date
            request = SearchPlanRequest(event=plan.event, event_date=event_date,
                                       queries=[{**q.model_dump(), 'search_query': retrieval_queries[q.language]}
                                                for q in plan.queries],
                                       selected_languages=body.languages,
                                       relevance_context=job['llm_trace']['response']['relevance_context'])
            job.update(search_plan=plan.model_dump(), collection_request=request.model_dump(),
                       stage='collecting', progress={})
            collection_started = time.perf_counter()
            collector = OSINTCollector(api_key=self.settings.tavily_key, raise_on_error=True,
                                       cancel_event=cancel_event)
            self._active_collector = collector
            collector.progress = lambda update: loop.call_soon_threadsafe(progress, update)
            if collector.client is None:
                raise AnalysisError('Tavily 수집 클라이언트를 준비하지 못했습니다.')
            job['output'] = await asyncio.to_thread(collector.collect_plan,
                plan=request.model_dump(), days_back=body.days_back,
                max_docs_per_country=body.max_docs_per_country,
                max_results_per_query=body.max_docs_per_country,
                min_score=body.min_score, strict_min_score=body.strict_min_score)
            final_status = 'completed'
        except asyncio.CancelledError:
            if not job.get('cancel_requested'):
                job.update(stage='interrupted', error='서버 종료로 수집 작업이 중단됐습니다.')
                raise
        except AnalysisError as exc:
            job.update(error=str(exc))
        except TimeoutError:
            job.update(error='검색어 생성 시간 제한을 초과했습니다.')
        except Exception:
            job.update(error='수집 요청에 실패했습니다. Tavily 인증·연결 상태를 확인하세요.')
        finally:
            finished = time.perf_counter()
            job['timings']['total_seconds'] = round(finished - started, 3)
            if collection_started is None:
                job['timings']['query_seconds'] = round(finished - started, 3)
            else:
                job['timings']['collection_seconds'] = round(finished - collection_started, 3)
            # Serialize terminal persistence with cancellation to avoid accepting
            # a stop request after a completed result has already been saved.
            async with self.lock:
                if job.get('cancel_requested'):
                    final_status = 'cancelled'
                    job.update(stage='cancelled', output=None, error='사용자가 검색·수집을 취소했습니다.')
                job['finished_at'] = datetime.now(UTC).isoformat()
                try:
                    completed = {**job, 'status': final_status,
                                 'stage': 'completed' if final_status == 'completed' else job['stage']}
                    await asyncio.to_thread(self.save, completed)
                    job.update(completed)
                except OSError:
                    job.update(status='failed', error='수집 결과 파일을 저장하지 못했습니다.')

    async def close(self):
        if self.task and not self.task.done():
            collector = getattr(self, '_active_collector', None)
            if collector is not None:
                collector.cancel_event.set()
            if self.cancel_event:
                self.cancel_event.set()
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def router(self) -> APIRouter:
        router = APIRouter(prefix='/api/collections', tags=['실제 수집'])

        @router.post('', status_code=202)
        async def start(body: CollectionRequest):
            if not self.settings.tavily_key:
                raise HTTPException(503, '서버 .env에 TAVILY_API_KEY를 설정하세요.')
            async with self.lock:
                if self.task and not self.task.done():
                    raise HTTPException(409, '한 번에 하나의 검색·수집만 실행할 수 있습니다.')
                while len(self.jobs) >= 10:
                    self.jobs.pop(next(iter(self.jobs)))
                job = {'id': uuid4().hex, 'status': 'running', 'stage': 'generating_queries',
                       'created_at': datetime.now(UTC).isoformat(),
                       'input': body.model_dump(mode='json'), 'error': '',
                       'search_plan': None, 'collection_request': None, 'output': None,
                       'llm_trace': {'request': {}, 'response': {}}}
                self.jobs[job['id']] = job
                self.cancel_event = Event()
                self.started = False
                self.task = asyncio.create_task(self.execute(job, body, self.cancel_event),
                                                name=job['id'])
                return job

        @router.get('/{rid}')
        def read(rid: str):
            if rid not in self.jobs:
                raise HTTPException(404, '이 서버 실행의 수집 기록을 찾지 못했습니다.')
            return self.jobs[rid]

        @router.post('/{rid}/cancel', status_code=202)
        async def cancel(rid: str):
            async with self.lock:
                job = read(rid)
                if job['status'] != 'running' or job.get('cancel_requested'):
                    return job
                if not self.task or self.task.done() or self.task.get_name() != rid:
                    raise HTTPException(409, '실행 중인 수집 작업을 찾지 못했습니다.')
                stage = job['stage']
                job.update(cancel_requested=True, stage='cancelling')
                self.cancel_event.set()
                # A synchronous Tavily call cannot be interrupted mid-request.
                # Keep its task reserved until the worker observes the stop event.
                if stage == 'generating_queries' and self.started:
                    self.task.cancel()
                return job

        @router.get('/{rid}/download')
        def download(rid: str, format: Literal['full', 'collection'] = 'full'):
            job = read(rid)
            if job['status'] == 'running' or not self.path(rid).is_file():
                raise HTTPException(409, '수집 요청 처리가 아직 끝나지 않았습니다.')
            if format == 'collection':
                if job['status'] != 'completed':
                    raise HTTPException(409, '완료된 수집만 공유 JSON으로 내보낼 수 있습니다.')
                return JSONResponse(collection_export(job), headers={
                    'Content-Disposition': 'attachment; filename="collective_live.json"'})
            return FileResponse(self.path(rid), media_type='application/json',
                                filename='collected-' + rid + '.json')

        return router
