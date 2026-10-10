import asyncio
import json
from threading import Barrier

import httpx
import pytest

from app.config import Settings
from app.core.analysis_cache import AnalysisCache


def test_streaming_chat_preserves_content_and_reports_activity():
    from app.llm.ollama_transport import stream_chat

    async def scenario():
        events = []
        def reply(request):
            assert json.loads(request.content)['stream'] is True
            return httpx.Response(200, text='\n'.join(json.dumps(row) for row in [
                {'message': {'content': '{"x":'}, 'done': False},
                {'message': {'content': '1}'}, 'done': False},
                {'message': {'content': ''}, 'done': True, 'done_reason': 'stop', 'eval_count': 4}]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url='http://test') as client:
            payload = {'stream': False, 'messages': []}
            result = await stream_chat(client, payload, events.append)
        assert payload['stream'] is False  # Cache identity does not change with transport.
        assert result['message']['content'] == '{"x":1}'
        assert result['eval_count'] == 4
        assert events[-1]['received_chars'] == 7
    asyncio.run(scenario())


@pytest.mark.parametrize('initial_cpu', [False, True])
def test_query_cache_reuses_only_fully_verified_plan(tmp_path, initial_cpu):
    from app.search.search_pipeline import generate_search

    class Fake:
        def __init__(self):
            self.cache = AnalysisCache(tmp_path, 'digest')
            self.calls = 0
            self.force_cpu = initial_cpu
            self.updates = []
            self.progress = self.updates.append
        async def chat(self, payload):
            assert ('num_gpu' in payload['options']) is initial_cpu
            if initial_cpu:
                assert payload['options']['num_gpu'] == 0
            self.calls += 1
            data = json.loads(payload['messages'][1]['content'])
            value = ({'event': '대만해협 군사활동', 'event_date': None, 'place': '대만해협',
                      'parties': [], 'focus': ['활동'],
                      'targets': [{'id': 'activity', 'label': '활동', 'subject': '군사활동'}]}
                     if 'question' in data else
                     {'translations': ['Taiwan Strait military activities', 'Taiwan Strait', 'activities']})
            return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(value)},
                    'total_duration': 99000000000}
    async def scenario():
        llm = Fake()
        for attempt in range(2):
            if attempt:
                llm.force_cpu = False
            trace = {'request': {}, 'response': {}}
            await generate_search(llm, {'question': '대만해협 군사활동에 대해 알려줘',
                                      'languages': ['ko', 'en']}, 'model', trace)
        assert llm.calls == 2
        assert trace['response']['stages'][0]['cache_hit'] is True
        assert trace['response']['stages'][0].get('cpu_cache_reused', False) is initial_cpu
        assert trace['response']['total_duration'] == 0
        assert llm.updates[-1]['completed'] == llm.updates[-1]['total'] == 2
    asyncio.run(scenario())


def test_parallel_collection_uses_isolated_workers_and_deterministic_dedup(monkeypatch):
    from app.collection.parallel_collection import ParallelOSINTCollector
    from frame.collector import OSINTCollector

    barrier = Barrier(2, timeout=3)
    workers = []
    def collect(self, **kwargs):
        workers.append(self)
        barrier.wait()  # This fails if languages run sequentially.
        self.filter_rejections.append({'url': kwargs['query'], 'reason': 'body_unavailable'})
        return [{'url': 'https://www.reuters.com/world/common-article/', 'title': 'common',
                 'article_text': 'same evidence', 'language': kwargs['query']}]
    monkeypatch.setattr(OSINTCollector, 'collect', collect)
    collector = ParallelOSINTCollector(api_key='test')
    updates = []
    collector.progress = updates.append
    docs = collector.collect_multilingual({'ja': 'ja', 'en': 'en'}, selected_languages=['ja', 'en'])
    assert len(docs) == 1 and docs[0]['language'] == 'ja'
    assert len({id(worker) for worker in workers}) == 2
    assert len(collector.filter_rejections) == 2
    assert updates[-1]['completed'] == updates[-1]['total'] == 2


def test_analysis_total_can_exceed_one_call_timeout(tmp_path, monkeypatch):
    from app.claims.ollama_source_analysis import OllamaSourceAnalysis

    async def scenario():
        async def analyze(*args, **kwargs):
            # Several short calls must not share a single call's deadline.
            for _ in range(4):
                await asyncio.sleep(0.015)
            return {'timings': {}}
        monkeypatch.setattr('app.claims.ollama_source_analysis.analyze_sources', analyze)
        provider = OllamaSourceAnalysis(Settings(database=tmp_path/'db', ollama_timeout=0.03))
        await provider.http.aclose()
        def reply(request):
            return httpx.Response(200, json={'models': [{'name': 'gemma4:e2b'}]})
        provider.http = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(reply))
        result = await provider.analyze('question', [], [])
        assert result['timings']['total_seconds'] >= 0.06
    asyncio.run(scenario())


def test_individual_stream_call_has_wall_clock_deadline():
    from app.claims.ollama_source_analysis import OllamaSourceAnalysis
    from app.core.errors import AnalysisError

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.01)
                yield b'{"message":{"content":"x"},"done":false}\n'
    async def scenario():
        provider = OllamaSourceAnalysis(Settings(ollama_timeout=0.04))
        await provider.http.aclose()
        provider.http = httpx.AsyncClient(base_url='http://test', timeout=0.04,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream())))
        with pytest.raises(AnalysisError, match='개별 LLM 호출'):
            await provider.chat({'messages': []})
        await provider.http.aclose()
    asyncio.run(scenario())


def test_parallel_peer_failure_signals_running_workers(monkeypatch):
    from app.collection.parallel_collection import ParallelOSINTCollector
    from frame.collector import OSINTCollector

    collector = ParallelOSINTCollector(api_key='test', raise_on_error=True)
    barrier = Barrier(2, timeout=3)
    calls = []
    def collect(self, **kwargs):
        self._check_cancelled()
        calls.append(kwargs['query'])
        barrier.wait()
        if kwargs['query'] == 'ja':
            raise RuntimeError('primary failed')
        assert self.cancel_event.wait(2), 'Sibling failure must stop subsequent retrieval.'
        self._check_cancelled()
        return []
    monkeypatch.setattr(OSINTCollector, 'collect', collect)
    with pytest.raises(RuntimeError, match='primary failed'):
        collector.collect_multilingual({'ja': 'ja', 'en': 'en'}, fallback_queries={'en': 'fallback'})
    assert sorted(calls) == ['en', 'ja']


def test_completed_success_cannot_mask_peer_failure(monkeypatch):
    from concurrent.futures import wait

    from app.collection.parallel_collection import ParallelOSINTCollector
    from frame.collector import OSINTCollector

    barrier = Barrier(2, timeout=3)
    def collect(self, **kwargs):
        barrier.wait()
        if kwargs['query'] == 'ja':
            raise RuntimeError('original search failure')
        return [{'url': 'https://www.reuters.com/world/article/', 'title': 'article',
                 'article_text': 'evidence', 'language': 'en'}]
    def success_first(futures):
        futures = list(futures)
        wait(futures)
        return iter([futures[1], futures[0]])
    monkeypatch.setattr(OSINTCollector, 'collect', collect)
    monkeypatch.setattr('app.collection.parallel_collection.as_completed', success_first)
    with pytest.raises(RuntimeError, match='original search failure'):
        ParallelOSINTCollector(api_key='test').collect_multilingual({'ja': 'ja', 'en': 'en'})


def test_shutdown_signals_parallel_collector():
    from threading import Event
    from types import SimpleNamespace

    from app.collection.collection_flow import CollectionFlow

    async def scenario():
        flow = CollectionFlow(Settings())
        stop = Event()
        flow._active_collector = SimpleNamespace(cancel_event=stop)
        flow.task = asyncio.create_task(asyncio.Event().wait())
        await asyncio.sleep(0)
        await flow.close()
        assert stop.is_set()
    asyncio.run(scenario())
