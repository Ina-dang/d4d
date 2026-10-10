import asyncio
import copy

import pytest
from test_reliability_report import Model, draft, inputs

from app.core.analysis_cache import AnalysisCache
from app.reporting.reliability_report import ReliabilityResponse, generate_report, report_evidence


def packet():
    collection, analysis, response = inputs()
    return report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))


def test_report_reuses_draft_with_new_ids_and_current_input_binding(tmp_path):
    model = Model()
    model.cache = AnalysisCache(tmp_path, 'model-digest')
    original = packet()
    first = asyncio.run(generate_report(model, 'test', original, []))
    current = copy.deepcopy(original)
    current['input_sha256'] = '1' * 64
    current['docs'] = [{'id': 'new-a', 'country': 'CN', 'weight': 0.5, 'sim': {'new-b': 0.67}},
                       {'id': 'new-b', 'country': 'TW', 'weight': 0.8, 'sim': {'new-a': 0.67}}]
    for item in current['evidence']:
        for field in ('claim_id', 'document_id', 'paragraph_id'):
            item[field] = 'new-' + item[field]
    model.calls.clear()
    trace = []
    second = asyncio.run(generate_report(model, 'test', current, trace))
    assert model.calls == []
    assert second['timings']['llm_calls'] == 0
    assert second['input_sha256'] == current['input_sha256']
    assert second['evidence'] == current['evidence']
    assert second['sections']['key_judgment'][0]['claim_ids'] == ['new-a-c1', 'new-b-c1']
    assert second['sections']['key_judgment'][0]['text'] == first['sections']['key_judgment'][0]['text']
    assert second['status'] == 'draft' and second['audit'] == []
    assert trace[0]['validation_history']


@pytest.mark.parametrize('change', ['score', 'quote', 'weight', 'sim', 'question', 'model', 'prompt'])
def test_report_invalidates_changed_evidence_or_policy(tmp_path, monkeypatch, change):
    from app.reporting import report_cache

    model = Model()
    model.cache = AnalysisCache(tmp_path / 'cache', 'digest')
    current = packet()
    asyncio.run(generate_report(model, 'test', current, []))
    if change == 'score':
        current['evidence'][0]['reliability'] = 0.22
    elif change == 'quote':
        current['evidence'][0]['translated_quote'] += ' 추가 번역'
    elif change == 'weight':
        current['docs'][0]['weight'] = 0.4
    elif change == 'sim':
        current['docs'][0]['sim']['b'] = 0.5
    elif change == 'question':
        current['question'] += ' 새 질문'
    elif change == 'model':
        model.cache = AnalysisCache(tmp_path / 'cache', 'new-digest')
    else:
        prompts = tmp_path / 'prompts'
        prompts.mkdir()
        for name in ('source_reliability_report.txt', 'source_report_review.txt'):
            (prompts / name).write_text('new prompt', encoding='utf-8')
        monkeypatch.setattr(report_cache, 'PROMPTS', prompts)
    trace = []
    asyncio.run(generate_report(model, 'test', current, trace))
    assert not any(item.get('cache_kind') == 'verified_report' for item in trace)


def test_report_cache_keeps_comparisons_pending_human_approval(tmp_path):
    response = draft()
    response['common_facts'] = [{'text': '두 발표의 공통 내용 후보.', 'claim_ids': ['a-c1', 'b-c1']}]
    model = Model(response)
    model.cache = AnalysisCache(tmp_path, 'digest')
    first = asyncio.run(generate_report(model, 'test', packet(), []))
    model.calls.clear()
    second = asyncio.run(generate_report(model, 'test', packet(), []))
    assert model.calls == []
    assert second['sections']['common_facts'] == []
    assert second['proposed_comparisons'] == first['proposed_comparisons']
    assert second['audit'] == []
