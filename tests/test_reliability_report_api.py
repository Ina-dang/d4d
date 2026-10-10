import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_reliability_report import Model, inputs

from app.config import Settings
from app.main import create_app
from app.reliability_report import ReliabilityResponse, generate_report, input_digest


def setup(tmp_path, monkeypatch, function=''):
    collection, analysis, response = inputs()
    for folder, value in [('collections', collection), ('source-analyses', analysis)]:
        path = tmp_path / folder / 'abc.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    calls = []

    async def create(settings, packet, trace):
        calls.append(packet)
        return await generate_report(Model(), 'test', packet, trace)

    monkeypatch.setattr('app.reliability_report_api.create_report', create)
    settings = Settings(database=tmp_path / 'test.db', reliability_function=function)
    return create_app(settings), analysis, response, calls


def test_uploaded_result_generates_draft_download_then_explicit_review_with_version_guard(tmp_path, monkeypatch):
    app, analysis, response, calls = setup(tmp_path, monkeypatch)
    with TestClient(app) as client:
        base = '/api/collections/abc/analysis'
        digest = client.get(base + '/report-input').json()['verification_input_sha256']
        assert digest == input_digest(analysis)
        downloaded = client.get(base + '/download?format=verification')
        assert downloaded.headers['x-verification-input-sha256'] == digest
        report = client.post(base + '/report', json={'reliability_result': response,
            'verification_input_sha256': digest})
        assert report.status_code == 200, report.text
        assert report.json()['status'] == 'draft'
        assert len(calls) == 1
        assert client.get(base + '/report/download').status_code == 200
        assert client.get(base + '/report/download?format=json').json()['evidence'][0]['reliability'] == 0.53
        body = {'action': 'approve', 'reviewer': '검토자', 'note': '원문과 번역 확인', 'version': 1}
        approved = client.post(base + '/report/review', json=body)
        assert approved.status_code == 200 and approved.json()['status'] == 'approved'
        assert approved.json()['version'] == 2 and len(approved.json()['audit']) == 1
        assert client.post(base + '/report/review', json=body).status_code == 409
        # 재생성하면 이전 승인 상태를 물려받지 않는다.
        regenerated = client.post(base + '/report', json={'reliability_result': response})
        assert regenerated.json()['status'] == 'draft' and regenerated.json()['version'] == 3
        analysis['docs'][0]['weight'] = 0.9
        (tmp_path / 'source-analyses' / 'abc.json').write_text(json.dumps(analysis), encoding='utf-8')
        assert client.get(base + '/report').status_code == 409
        assert client.post(base + '/report/review', json={**body, 'version': 3}).status_code == 409


@pytest.mark.parametrize('change', ['old_id', 'wrong_quote', 'unknown_field', 'nan_score', 'stale_hash'])
def test_invalid_results_are_rejected_before_any_model_call(tmp_path, monkeypatch, change):
    app, _, response, calls = setup(tmp_path, monkeypatch)
    body = {'reliability_result': copy.deepcopy(response)}
    if change == 'old_id':
        body['reliability_result']['claims'][0]['claim_id'] = 'old-c1'
    elif change == 'wrong_quote':
        body['reliability_result']['claims'][0]['translated_quote'] = '다른 내용'
    elif change == 'unknown_field':
        body['reliability_result']['claims'][0]['code'] = 'exec'
    elif change == 'nan_score':
        body['reliability_result']['claims'][0]['reliability'] = 'NaN'
    else:
        body['verification_input_sha256'] = '0' * 64
    with TestClient(app) as client:
        result = client.post('/api/collections/abc/analysis/report', json=body)
        assert result.status_code == 422, result.text
    assert calls == [] and not (tmp_path / 'reliability-reports' / 'abc.json').is_file()


def test_local_function_not_configured_does_not_make_up_scores(tmp_path, monkeypatch):
    app, _, _, calls = setup(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.post('/api/collections/abc/analysis/verify-report').status_code == 503
    assert not calls


def test_local_verification_receives_current_input_then_generates_report(tmp_path, monkeypatch):
    app, analysis, response, calls = setup(tmp_path, monkeypatch, 'module:verify')

    async def verify(settings, rid, received):
        assert settings.reliability_function == 'module:verify' and rid == 'abc'
        assert received == analysis
        return ReliabilityResponse.model_validate({**response, 'input_sha256': input_digest(received)})

    monkeypatch.setattr('app.reliability_report_api.verify_locally', verify)
    with TestClient(app) as client:
        result = client.post('/api/collections/abc/analysis/verify-report')
        assert result.status_code == 200, result.text
        assert result.json()['confidence_input_binding'] == 'input_sha256'
        assert result.json()['status'] == 'draft' and len(calls) == 1


def test_analysis_and_report_model_requests_are_serialized(tmp_path, monkeypatch):
    import httpx
    app, _, response, _ = setup(tmp_path, monkeypatch)

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def create(settings, packet, trace):
            started.set()
            await release.wait()
            return await generate_report(Model(), 'test', packet, trace)

        monkeypatch.setattr('app.reliability_report_api.create_report', create)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            pending = asyncio.create_task(client.post('/api/collections/abc/analysis/report',
                json={'reliability_result': response}))
            await asyncio.wait_for(started.wait(), 5)
            try:
                assert (await client.post('/api/collections/abc/analysis')).status_code == 409
                assert (await client.post('/api/collections/abc/analysis/verify-report')).status_code == 409
            finally:
                release.set()
                await pending

    asyncio.run(scenario())


def test_comparison_proposals_require_explicit_human_decision_before_approval(tmp_path, monkeypatch):
    from test_reliability_report import draft
    app, _, response, _ = setup(tmp_path, monkeypatch)

    async def create(settings, packet, trace):
        value = draft()
        value['common_facts'] = [{'text': '두 자료는 당사자의 발표를 전한다.', 'claim_ids': ['a-c1', 'b-c1']}]
        return await generate_report(Model(value), 'test', packet, trace)

    monkeypatch.setattr('app.reliability_report_api.create_report', create)
    with TestClient(app) as client:
        base = '/api/collections/abc/analysis/report'
        result = client.post(base, json={'reliability_result': response}).json()
        assert result['sections']['common_facts'] == []
        assert len(result['proposed_comparisons']) == 1
        body = {'action': 'approve', 'reviewer': '검토자', 'note': '인용 쌍 검토', 'version': 1}
        assert client.post(base + '/review', json=body).status_code == 422
        approved = client.post(base + '/review', json={**body, 'comparison_decisions': {'common_facts:0': False}})
        assert approved.status_code == 200, approved.text
        assert approved.json()['sections']['common_facts'] == []
        assert approved.json()['proposed_comparisons'] == []
        assert approved.json()['excluded_statements'][0]['verdict'] == 'human_excluded'
