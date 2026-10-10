import asyncio
import json

import pytest
from test_source_analysis import FakeLLM, documents

from app.errors import AnalysisError
from app.source_analysis import analyze_sources


def response(data):
    return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(data)}}


def test_changed_modality_is_repaired_before_similarity():
    class DriftLLM(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                self.requests.append(payload)
                return response({'checks': [
                    {'claim_index': c['claim_index'],
                     'verdict': 'fail' if '시행' in c['claim']['translated_quote'] else 'pass',
                     'issues': ['modality'] if '시행' in c['claim']['translated_quote'] else []}
                    for c in data['claims']]})
            if data.get('operation') == 'repair_claims':
                self.requests.append(payload)
                assert data['failed_claims'][0]['issues'] == ['modality']
                return response({'corrections': [{'claim_index': c['claim_index'], 'claim': {
                    **c['draft'], 'translated_quote': '통제는 예정되어 있다.'}}
                    for c in data['failed_claims']]})
            raw = await super().chat(payload)
            if 'paragraphs' in data and data['paragraphs'][0]['paragraph_id'] == 'd0-p1':
                parsed = json.loads(raw['message']['content'])
                parsed['claims'][0]['translated_quote'] = '통제가 시행되었다.'
                return response(parsed)
            if 'pairs' in data:
                assert data['documents'][0]['claims'][0]['text'] == '통제는 예정되어 있다.'
            return raw

    llm = DriftLLM()
    result = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert result['claims'][0]['translated_quote'] == '통제는 예정되어 있다.'
    assert result['docs'][0]['sim']['d1'] == 0.93
    assert result['timings']['phases']['reextraction']['llm_calls'] == 1
    assert result['timings']['phases']['meaning_check']['llm_calls'] == 3


@pytest.mark.parametrize('mode', ['missing', 'wrong_id', 'null'])
def test_failed_repair_never_produces_partial_similarity(mode):
    class BrokenRepair(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'repair_claims':
                self.requests.append(payload)
                if mode == 'missing':
                    corrections = []
                else:
                    corrections = [{'claim_index': 2 if mode == 'wrong_id' else 1, 'claim': None}]
                return response({'corrections': corrections})
            return await super().chat(payload)
    llm = BrokenRepair(invalid_quote=True)
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert not any('pairs' in json.loads(r['messages'][1]['content']) for r in llm.requests)
    assert len(llm.requests) <= 3


def test_uncertain_translation_never_reaches_similarity():
    class UncertainLLM(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                self.requests.append(payload)
                return response({'checks': [{'claim_index': c['claim_index'],
                    'verdict': 'uncertain', 'issues': ['uncertain']} for c in data['claims']]})
            return await super().chat(payload)
    llm = UncertainLLM()
    with pytest.raises(AnalysisError, match='2회 재추출'):
        asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert len(llm.requests) == 6
    assert not any('pairs' in json.loads(r['messages'][1]['content']) for r in llm.requests)


def test_missing_meaning_check_is_rejected():
    class MissingCheck(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                return response({'checks': [{'claim_index': 2, 'verdict': 'pass', 'issues': []}]})
            return await super().chat(payload)
    with pytest.raises(AnalysisError, match='주장 번호'):
        asyncio.run(analyze_sources(MissingCheck(), '질문', documents(), 'test-model'))


def test_repair_cannot_substitute_a_different_valid_source_claim():
    docs = documents()
    docs[0]['paragraphs'][0]['raw_text'] += ' 別の事案は60分間の予定です。'

    class WrongTarget(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'repair_claims':
                self.requests.append(payload)
                return response({'corrections': [{'claim_index': 1, 'claim': {
                    **data['failed_claims'][0]['draft'], 'original_quote': '60分間の予定です。',
                    'translated_quote': '다른 사건은 60분간 예정되어 있다.'}}]})
            if data.get('operation') == 'verify_translation':
                self.requests.append(payload)
                assert data['claims'][0]['repair_target']['original_quote'] == 'made up'
                return response({'checks': [{'claim_index': 1, 'verdict': 'fail',
                                              'issues': ['same_claim']}]})
            return await super().chat(payload)
    llm = WrongTarget(invalid_quote=True)
    trace = []
    with pytest.raises(AnalysisError, match='2회 재추출'):
        asyncio.run(analyze_sources(llm, '질문', docs, 'test-model', trace))
    assert any('same_claim' in e.get('issues', [])
               for r in trace for e in r.get('validation_errors', []))
    assert not any('pairs' in json.loads(r['messages'][1]['content']) for r in llm.requests)


def test_cached_call_timing_does_not_count_old_model_duration(tmp_path):
    from app.analysis_cache import AnalysisCache

    class SlowMetadataLLM(FakeLLM):
        async def chat(self, payload):
            raw = await super().chat(payload)
            raw['total_duration'] = 99_000_000_000
            return raw
    llm = SlowMetadataLLM()
    llm.cache = AnalysisCache(tmp_path, 'digest')
    first = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    second = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert first['timings']['llm_calls'] == 5
    assert second['timings']['llm_calls'] == 0
    assert second['timings']['cache_hits'] == 5
    assert sum(p['seconds'] for p in second['timings']['phases'].values()) < 99
