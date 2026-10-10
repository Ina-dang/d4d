import asyncio
import copy
import json

import httpx
from test_reliability_report import Model, inputs

from app.config import Settings
from app.core.errors import AnalysisError
from app.main import create_app
from app.reporting.reliability_report import generate_report
from app.search.search_schemas import CollectionRequest, SearchPlan

QUESTION = '대만해협 양측 발표'
BODY = {'question': QUESTION, 'languages': ['zh', 'zh-Hant'], 'max_docs_per_country': 20}


def prepare(tmp_path, monkeypatch):
    collection, analysis, _ = inputs()
    documents = collection['output']['documents']
    output = {'total_count': 2, 'korean_question': QUESTION, 'reference_date': None,
              'by_country': {'CN': [documents[0]], 'TW': [documents[1]]}}
    calls = {'queries': 0, 'collection': 0, 'analysis': 0, 'report': 0}

    async def search(self, question, languages, trace):
        calls['queries'] += 1
        trace['response'] = {'retrieval_queries': {lang: '台湾海峡' for lang in languages},
                             'relevance_context': {}}
        await self.http.aclose()
        return SearchPlan(event='台湾海峡', event_date=None, targets=[],
                          queries=[{'language': lang, 'query': '台湾海峡'} for lang in languages])

    class Collector:
        def __init__(self, **kwargs):
            self.client = True
            self.cancel_event = kwargs['cancel_event']

        def collect_plan(self, **kwargs):
            calls['collection'] += 1
            return copy.deepcopy(output)

    async def analyze(self, question, docs, trace):
        calls['analysis'] += 1
        assert len(docs) == 2 and question == QUESTION
        self.progress({'stage': 'extracting', 'completed': 1, 'total': 2})
        self.progress({'stage': 'comparing', 'stage_completed': 1, 'stage_total': 1})
        await self.http.aclose()
        return copy.deepcopy(analysis)

    async def report(settings, packet, trace, progress=None):
        calls['report'] += 1
        return await generate_report(Model(), 'test', packet, trace)

    monkeypatch.setattr('app.collection.collection_flow.OllamaSearch.generate', search)
    monkeypatch.setattr('app.collection.collection_flow.OSINTCollector', Collector)
    monkeypatch.setattr('app.api.source_analysis_api.OllamaSourceAnalysis.analyze', analyze)
    monkeypatch.setattr('app.api.reliability_report_api.create_report', report)
    app = create_app(Settings(database=tmp_path / 'test.db', tavily_key='test-only',
                              reliability_function='analysis.reliability:run'))
    return app, calls


async def wait_done(client, rid):
    for _ in range(300):
        state = (await client.get(f'/api/scenarios/{rid}')).json()
        if state['status'] not in {'running', 'cancelling'}:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError('작업이 종료되지 않음')


def test_one_request_runs_all_stages_and_survives_disconnected_client(tmp_path, monkeypatch):
    app, calls = prepare(tmp_path, monkeypatch)

    async def run():
        transport = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.post('/api/scenarios', json=BODY)
            assert response.status_code == 202
            rid = response.json()['id']
            assert response.json()['estimated_remaining_seconds'] is None
        # 시작 요청의 브라우저 연결이 사라져도 서버가 모든 후속 단계를 소유한다.
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            done = await wait_done(client, rid)
            assert done['status'] == 'completed', done
            assert done['percent'] == 100 and done['counts'] == {'articles': 2, 'claims': 2}
            assert len(done['artifacts']) == 7
            for url in done['artifacts'].values():
                assert (await client.get(url)).status_code == 200
            data = (await client.get(done['artifacts']['verification'])).json()
            assert set(data) == {'docs', 'claims'} and len(data['docs']) == len(data['claims']) == 2
            scores = (await client.get(done['artifacts']['reliability'])).json()
            assert [c['reliability'] for c in scores['claims']] == [0.4, 0.4]
            report = (await client.get(f'/api/collections/{rid}/analysis/report')).json()
            assert report['status'] == 'draft' and report['audit'] == []
            approved = await client.post(f'/api/collections/{rid}/analysis/report/review', json={
                'action': 'approve', 'reviewer': '사용자', 'note': '원문 대조 완료', 'version': 1})
            assert approved.json()['status'] == 'approved'
            assert (await client.get('/api/scenarios/active')).json() is None
            assert calls == {'queries': 1, 'collection': 1, 'analysis': 1, 'report': 1}
            _, estimate, samples = app.state.scenarios.estimate(CollectionRequest.model_validate(BODY))
            assert estimate and samples == 1 and set(estimate) == {
                'queries', 'collecting', 'extracting', 'comparing', 'reliability', 'report'}
            assert sum(estimate.values()) > 0
            different = {**BODY, 'languages': ['en']}
            assert app.state.scenarios.estimate(CollectionRequest.model_validate(different))[1] is None
        # 서버 재시작 후에도 원문과 각 다운로드 링크를 읽을 수 있다.
        restored = create_app(app.state.scenarios.settings)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(restored), base_url='http://testserver') as client:
            assert (await client.get(f'/api/collections/{rid}')).json()['status'] == 'completed'
            assert (await client.get(f'/api/scenarios/{rid}')).json()['status'] == 'completed'

    asyncio.run(run())


def test_immediate_cancel_before_background_task_starts_releases_reservation(tmp_path, monkeypatch):
    app, calls = prepare(tmp_path, monkeypatch)

    async def run():
        flow = app.state.scenarios
        state = await flow.start(CollectionRequest.model_validate(BODY))
        stopped = await flow.stop(state['id'])
        assert stopped['status'] == 'cancelling'
        await flow.task
        assert flow.load(state['id'])['status'] == 'cancelled'
        assert flow.collections.scenario_id is None
        assert not any(calls.values())

    asyncio.run(run())


def test_progress_exclusion_and_resume_reuse_saved_collection_analysis(tmp_path, monkeypatch):
    app, calls = prepare(tmp_path, monkeypatch)

    async def run():
        reached, release = asyncio.Event(), asyncio.Event()
        original = app.state.scenarios.generate

        async def interrupted_report(rid, progress=None):
            reached.set()
            await release.wait()
            raise AnalysisError('보고서 모델 응답 확인 실패')

        app.state.scenarios.generate = interrupted_report
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            rid = (await client.post('/api/scenarios', json=BODY)).json()['id']
            await asyncio.wait_for(reached.wait(), 3)
            state = (await client.get(f'/api/scenarios/{rid}')).json()
            assert state['stage'] == 'reliability'
            assert set(state['artifacts']) == {'queries', 'collection', 'analysis', 'verification'}
            assert (await client.get('/api/scenarios/active')).json()['id'] == rid
            assert (await client.post('/api/scenarios', json=BODY)).status_code == 409
            assert (await client.post('/api/collections', json=BODY)).status_code == 409
            assert (await client.post(f'/api/collections/{rid}/analysis')).status_code == 409
            assert (await client.post(f'/api/collections/{rid}/analysis/verify-report')).status_code == 409
            release.set()
            assert (await wait_done(client, rid))['status'] == 'failed'
            app.state.scenarios.generate = original
            assert (await client.post(f'/api/scenarios/{rid}/resume')).status_code == 202
            assert (await wait_done(client, rid))['status'] == 'completed'
            assert calls == {'queries': 1, 'collection': 1, 'analysis': 1, 'report': 1}

    asyncio.run(run())


def test_cancel_during_analysis_prevents_report_and_preserves_originals(tmp_path, monkeypatch):
    app, calls = prepare(tmp_path, monkeypatch)

    async def run():
        reached = asyncio.Event()

        async def analyze(rid, progress=None):
            reached.set()
            await asyncio.Event().wait()

        app.state.scenarios.analyze = analyze
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            rid = (await client.post('/api/scenarios', json=BODY)).json()['id']
            await asyncio.wait_for(reached.wait(), 3)
            assert (await client.post(f'/api/scenarios/{rid}/cancel')).status_code == 202
            state = await wait_done(client, rid)
            assert state['status'] == 'cancelled'
            assert 'collection' in state['artifacts'] and 'report_json' not in state['artifacts']
            assert calls['report'] == 0 and app.state.scenarios.collections.scenario_id is None

    asyncio.run(run())


def test_restart_marks_orphan_running_job_interrupted_and_path_ids_rejected(tmp_path, monkeypatch):
    app, _ = prepare(tmp_path, monkeypatch)
    flow = app.state.scenarios
    flow.save({'id': 'abc', 'status': 'running', 'stage': 'queries', 'started_at_epoch': 0,
               'input': BODY, 'stage_seconds': {}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            state = (await client.get('/api/scenarios/abc')).json()
            assert state['status'] == 'interrupted' and '다시 시작' in state['error']
            assert (await client.get('/api/scenarios/a%5Cb')).status_code == 422
            assert (await client.get('/api/collections/a%5Cb')).status_code == 422
            saved = json.loads(flow.path('abc').read_text(encoding='utf-8'))
            assert saved['status'] == 'interrupted'

    asyncio.run(run())
