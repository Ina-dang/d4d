import asyncio
import json

import pytest
from test_source_analysis import FakeLLM, documents

from app.errors import AnalysisError
from app.source_analysis import analyze_sources


def response(data):
    return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(data)}}


@pytest.mark.parametrize('bad_id', [False, True])
def test_repeated_paraphrase_uses_selected_raw_source_before_meaning_review(bad_id, tmp_path):
    source = "8일 언론에 따르면 차이 전 총통은 7일 콘퍼런스에서 이같이 말했다."
    invented = "차이잉원 전 대만 총통은 7일 콘퍼런스에서 이같이 말했다."
    doc = documents()[0]
    doc['paragraphs'][0]['raw_text'] = source

    class RepeatedParaphrase(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'select_source_quote':
                self.requests.append(payload)
                item = data['failed_claims'][0]
                candidate = next(c for c in item['candidates'] if c['original_quote'] == source)
                return response({'selections': [{'claim_index': 1,
                    'quote_id': 999 if bad_id else candidate['quote_id'],
                    'translated_quote': source, 'expression': '발표', 'event_date': None}]})
            if data.get('operation') == 'verify_translation':
                assert data['claims'][0]['claim']['original_quote'] == source
                assert data['claims'][0]['repair_target']['original_quote'] == invented
                return await super().chat(payload)
            self.requests.append(payload)
            claim = {'paragraph_id': 'd0-p1', 'original_quote': invented,
                     'translated_quote': invented, 'expression': '발표', 'event_date': None}
            if data.get('operation') == 'repair_claims':
                return response({'corrections': [{'claim_index': 1, 'claim': claim}]})
            return response({'claims': [claim]})

    llm = RepeatedParaphrase()
    from app.analysis_cache import AnalysisCache
    llm.cache = AnalysisCache(tmp_path, 'test-digest')
    if bad_id:
        with pytest.raises(AnalysisError, match='인용 후보'):
            asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model'))
    else:
        result = asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model'))
        assert result['claims'][0]['original_quote'] == source
        assert result['claims'][0]['translated_quote'] == source
        assert result['timings']['phases']['reextraction']['llm_calls'] == 1
        previous_calls = len(llm.requests)
        reused_trace = []
        second = asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model', reused_trace))
        assert len(llm.requests) == previous_calls
        assert second['claims'] == result['claims']
        assert second['timings']['llm_calls'] == 0
        assert second['timings']['cache_hits'] == 1
        history = reused_trace[0]['validation_history']
        assert [r['phase'] for r in history] == ['extraction', 'reextraction', 'meaning_check']
        assert json.loads(history[0]['response']['message']['content'])['claims'][0]['original_quote'] == invented
        assert history[0]['validation_errors'][0]['reason'] == 'quote_not_in_paragraph'


def test_hallucinated_event_date_is_cleared_before_model_review():
    class InventedDate(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            raw = await super().chat(payload)
            if 'paragraphs' in data and not data.get('operation'):
                parsed = json.loads(raw['message']['content'])
                parsed['claims'][0]['event_date'] = '2024-01-01'
                return response(parsed)
            return raw

    llm, trace = InventedDate(), []
    result = asyncio.run(analyze_sources(llm, '질문', documents()[:1], 'test-model', trace))
    assert result['claims'][0]['event_date'] is None
    checked = json.loads(llm.requests[-1]['messages'][1]['content'])
    assert checked['claims'][0]['claim']['event_date'] is None
    assert trace[0]['date_normalizations'][0]['model_date'] == '2024-01-01'


def test_verified_block_cache_rejects_quote_outside_the_current_source(tmp_path):
    from app.analysis_cache import AnalysisCache
    from app.claim_validation import verified_cache_key

    llm = FakeLLM()
    llm.cache = AnalysisCache(tmp_path, 'digest')
    doc = documents()[0]
    asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model'))
    key = verified_cache_key(llm.requests[0], doc['paragraphs'])
    saved = llm.cache.read(key)
    saved['extraction']['claims'][0]['original_quote'] = 'not in source'
    llm.cache.write(key, saved)
    trace = []
    result = asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model', trace))
    assert result['claims'][0]['original_quote'] == doc['paragraphs'][0]['raw_text']
    assert not any(row.get('cache_kind') == 'verified_block' for row in trace)


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


def test_translation_repair_keeps_the_already_verified_source_fixed():
    class EnglishTranslation(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'translate_claims':
                self.requests.append(payload)
                assert data['quotes'] == [{'claim_index': 1, 'source_quote': '40分間の予定です。'}]
                return response({'translations': [{'claim_index': 1, 'korean_text': '40분간 예정되어 있다.'}]})
            raw = await super().chat(payload)
            if not data.get('operation'):
                output = json.loads(raw['message']['content'])
                output['claims'][0]['translated_quote'] = 'Planned for 40 minutes.'
                return response(output)
            return raw
    result = asyncio.run(analyze_sources(EnglishTranslation(), '질문', documents()[:1], 'test-model'))
    assert result['claims'][0]['original_quote'] == '40分間の予定です。'
    assert result['claims'][0]['translated_quote'] == '40분간 예정되어 있다.'


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
    assert second['timings']['cache_hits'] == 3  # Two verified blocks and one comparison.
    assert sum(p['seconds'] for p in second['timings']['phases'].values()) < 99
