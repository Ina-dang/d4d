import asyncio
import json

import pytest

from app.errors import AnalysisError
from app.source_analysis import analyze_sources, paragraph_blocks


def documents():
    return [
        {'doc_id': 'd0', 'country': 'JP', 'tier': 2, 'credibility_weight': 0.5,
         'score': 0.81, 'language': 'ja', 'query': '試験', 'event_date': None,
         'paragraphs': [{'paragraph_id': 'd0-p1', 'raw_text': '40分間の予定です。'}]},
        {'doc_id': 'd1', 'country': 'US', 'tier': 3, 'credibility_weight': 0.8,
         'score': 0.72, 'language': 'en', 'query': 'test', 'event_date': None,
         'paragraphs': [{'paragraph_id': 'd1-p1', 'raw_text': 'Planned for 60 minutes.'}]},
    ]


class FakeLLM:
    def __init__(self, invalid_quote=False, incomplete=False):
        self.requests = []
        self.invalid_quote = invalid_quote
        self.incomplete = incomplete

    async def chat(self, payload):
        self.requests.append(payload)
        data = json.loads(payload['messages'][1]['content'])
        if data.get('operation') == 'verify_translation':
            output = {'checks': [{'claim_index': item['claim_index'], 'verdict': 'pass', 'issues': []}
                                 for item in data['claims']]}
        elif data.get('operation') == 'select_source_quote':
            output = {'selections': [{'claim_index': item['claim_index'],
                'quote_id': None if self.invalid_quote else item['candidates'][0]['quote_id'],
                'translated_quote': item['draft']['translated_quote'],
                'expression': item['draft']['expression'], 'event_date': None}
                for item in data['failed_claims']]}
        elif data.get('operation') == 'repair_claims':
            paragraph = data['paragraphs'][0]
            output = {'corrections': [{'claim_index': item['claim_index'], 'claim': {
                **item['draft'], 'paragraph_id': paragraph['paragraph_id'],
                'original_quote': 'made up' if self.invalid_quote else paragraph['raw_text']}}
                for item in data['failed_claims']]}
        elif 'paragraphs' in data:
            paragraph = data['paragraphs'][0]
            output = {'claims': [{'paragraph_id': paragraph['paragraph_id'],
                'original_quote': 'made up' if self.invalid_quote else paragraph['raw_text'],
                'translated_quote': '통제는 예정되어 있다.', 'expression': '예정',
                'event_date': None}]}
        else:
            output = {'comparisons': [{'document_ids': pair, 'similarity': 0.93}
                                       for pair in data['pairs']]}
        return {'done': True, 'done_reason': 'length' if self.incomplete else 'stop',
                'message': {'content': json.dumps(output)}}


def test_analysis_preserves_metadata_and_symmetric_similarity():
    llm = FakeLLM()
    result = asyncio.run(analyze_sources(llm, '시험에 대해 알려줘', documents(), 'test-model'))
    assert result['docs'][0] == {'id': 'd0', 'country': 'JP', 'weight': 0.5,
                                'score': 0.81, 'sim': {'d1': 0.93}}
    assert result['docs'][1]['sim'] == {'d0': 0.93}
    assert 'query_sim' not in result['docs'][0]
    assert result['claims'][0]['claim_id'] == 'd0-c1'
    assert result['claims'][0]['tier'] == 2
    assert result['claims'][0]['original_quote'] == '40分間の予定です。'
    assert result['claims'][0]['event_date'] is None
    assert len(llm.requests) == 5  # 추출 2회 + 의미 검증 2회 + 비교 1회


def test_incomplete_analysis_is_not_success():
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_sources(FakeLLM(incomplete=True), '질문', documents(), 'test-model'))


def test_paraphrased_quote_is_reextracted_before_similarity():
    # 실제 실패 응답: 대상을 대명사 대신 Taiwan으로 바꾸고 had를 has로 변경했다.
    source = ('Washington’s policy towards the self-ruled island had seen a “discontinuity”, '
              'becoming “less independent” from its China policy in the current administration.')
    paraphrase = ('Washington’s policy towards [Taiwan](https://www.scmp.com/topics/taiwan'
                  '?module=inline&pgtype=article) has seen a “discontinuity”, becoming '
                  '“less independent” from its China policy in the current administration.')
    doc = documents()[0]
    doc['paragraphs'] = [{'paragraph_id': 'd0-p1', 'raw_text': source}]

    class ParaphrasingLLM(FakeLLM):
        async def chat(self, payload):
            if json.loads(payload['messages'][1]['content']).get('operation'):
                return await super().chat(payload)
            result = {'claims': [{'paragraph_id': 'd0-p1', 'original_quote': quote,
                      'translated_quote': '미국의 대만 정책에 변화가 있었다는 발표.',
                      'expression': '발표', 'event_date': None} for quote in [paraphrase, source]]}
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': json.dumps(result)}}

    trace = []
    result = asyncio.run(analyze_sources(ParaphrasingLLM(), '질문', [doc], 'test-model', trace))
    assert [c['original_quote'] for c in result['claims']] == [source]
    assert result['claims'][0]['claim_id'] == 'd0-c1'
    assert any('재추출' in w for w in result['warnings'])
    assert trace[0]['validation_errors'][0]['reason'] == 'quote_not_in_paragraph'


def test_omitted_markdown_link_is_restored_from_source_before_meaning_check():
    source = '[Taiwan](https://example.com/taiwan) is set to receive 29 systems.'
    quote = 'Taiwan is set to receive 29 systems.'
    doc = documents()[0]
    doc['paragraphs'] = [{'paragraph_id': 'd0-p1', 'raw_text': source}]

    class LinkOmittingLLM(FakeLLM):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation'):
                return await super().chat(payload)
            self.requests.append(payload)
            return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                'claims': [{'paragraph_id': 'd0-p1', 'original_quote': quote,
                            'translated_quote': '대만은 시스템 29대를 받을 예정이다.',
                            'expression': '예정', 'event_date': None}]})}}

    llm, trace = LinkOmittingLLM(), []
    result = asyncio.run(analyze_sources(llm, '질문', [doc], 'test-model', trace))
    assert result['claims'][0]['original_quote'] == source
    assert [row['phase'] for row in trace] == ['extraction', 'meaning_check']
    check = json.loads(llm.requests[-1]['messages'][1]['content'])
    assert check['claims'][0]['claim']['original_quote'] == source
    assert trace[0]['quote_restorations'][0]['method'] == 'exact_markdown_label_match'


def test_no_claims_does_not_invent_similarity():
    class EmptyLLM(FakeLLM):
        async def chat(self, payload):
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': '{"claims": []}'}}
    updates = []
    result = asyncio.run(analyze_sources(EmptyLLM(), '질문', documents(), 'test-model',
                                        progress=updates.append))
    assert result['docs'][0]['sim'] == {'d1': None}
    assert result['claims'] == []
    assert updates[-1]['completed'] == updates[-1]['total'] == 3


def test_duplicate_ids_are_rejected():
    docs = documents()
    docs[1]['doc_id'] = 'd0'
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_sources(FakeLLM(), '질문', docs, 'test-model'))


@pytest.mark.parametrize('body_length', [4100, 14000])
def test_full_article_tail_is_analyzed_with_traceable_supplemental_paragraph(body_length):
    doc = documents()[0]
    doc['article_text'] = doc['paragraphs'][0]['raw_text'] + '\n' + 'x' * body_length + '\n末尾の主張。'

    class TailLLM(FakeLLM):
        async def chat(self, payload):
            if json.loads(payload['messages'][1]['content']).get('operation'):
                return await super().chat(payload)
            self.requests.append(payload)
            data = json.loads(payload['messages'][1]['content'])
            p = next((p for p in data['paragraphs'] if '末尾の主張。' in p['raw_text']),
                     data['paragraphs'][0])
            quote = '末尾の主張。' if '末尾の主張。' in p['raw_text'] else p['raw_text'][:20]
            result = {'claims': [{'paragraph_id': p['paragraph_id'], 'original_quote': quote,
                       'translated_quote': '원문에 명시된 주장.', 'expression': '발표', 'event_date': None}]}
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': json.dumps(result)}}

    result = asyncio.run(analyze_sources(TailLLM(), '질문', [doc], 'test-model'))
    tail = next(c for c in result['claims'] if c['original_quote'] == '末尾の主張。')
    assert tail['paragraph_id'] != 'd0-p1'
    assert any(p['paragraph_id'] == tail['paragraph_id'] and tail['original_quote'] in p['raw_text']
               for p in result['analysis_paragraphs'])


def test_chunk_overlap_preserves_max_length_quote_across_boundary():
    quote = '条件付きの主張' + 'z' * 1592
    text = 'x' * 5700 + quote + 'y' * 3000
    blocks = paragraph_blocks({'paragraphs': [{'paragraph_id': 'p1', 'raw_text': text}]})
    assert any(quote in p['raw_text'] for block in blocks for p in block)


class BatchLLM(FakeLLM):
    async def chat(self, payload):
        data = json.loads(payload['messages'][1]['content'])
        if 'pairs' not in data:
            return await super().chat(payload)
        self.requests.append(payload)
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
            'comparisons': [{'document_ids': pair, 'similarity': 0.93} for pair in data['pairs']]
        })}}


def test_similarity_pairs_are_batched_without_missing_or_asymmetric_scores():
    docs = []
    for i in range(5):
        doc = {**documents()[0], 'doc_id': f'd{i}', 'paragraphs': [
            {'paragraph_id': f'd{i}-p1', 'raw_text': '40分間の予定です。'}]}
        docs.append(doc)
    llm = BatchLLM()
    result = asyncio.run(analyze_sources(llm, '질문', docs, 'test-model'))
    pair_calls = [r for r in llm.requests if 'paragraphs' not in json.loads(r['messages'][1]['content'])]
    assert len(pair_calls) == 2  # 10쌍을 최대 8쌍씩, 기존에는 10회
    assert len(llm.requests) == 12
    for doc in result['docs']:
        assert len(doc['sim']) == 4
        for other in result['docs']:
            if other['id'] != doc['id']:
                assert doc['sim'][other['id']] == other['sim'][doc['id']] == 0.93


def test_supplemental_full_body_is_not_analyzed_again_with_original_prefix():
    from app.source_analysis import complete_paragraphs
    doc = documents()[0]
    doc['article_text'] = doc['paragraphs'][0]['raw_text'] + '\n' + 'x' * 4100
    complete, _ = complete_paragraphs(doc)
    blocks = paragraph_blocks(complete)
    sent_text = ''.join(p['raw_text'] for block in blocks for p in block)
    assert sent_text.count('40分間の予定です。') == 1


def test_original_paragraph_id_is_preserved_when_quote_repeats():
    doc = documents()[0]
    doc['paragraphs'].append({'paragraph_id': 'd0-p2', 'raw_text': '別の事案。40分間の予定です。'})

    class SecondParagraphLLM(FakeLLM):
        async def chat(self, payload):
            if json.loads(payload['messages'][1]['content']).get('operation'):
                return await super().chat(payload)
            result = {'claims': [{'paragraph_id': 'd0-p2',
                      'original_quote': '40分間の予定です。', 'translated_quote': '다른 사건의 예정 시간.',
                      'expression': '예정', 'event_date': None}]}
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': json.dumps(result)}}

    result = asyncio.run(analyze_sources(SecondParagraphLLM(), '질문', [doc], 'test-model'))
    assert result['claims'][0]['paragraph_id'] == 'd0-p2'


def test_successful_calls_are_reused_but_changed_question_is_reanalyzed(tmp_path):
    from app.analysis_cache import AnalysisCache
    llm = FakeLLM()
    llm.cache = AnalysisCache(tmp_path, 'model-digest')
    first = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    second = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert {k: v for k, v in first.items() if k != 'timings'} == {
        k: v for k, v in second.items() if k != 'timings'}
    assert len(llm.requests) == 5
    asyncio.run(analyze_sources(llm, '새 질문', documents(), 'test-model'))
    assert len(llm.requests) == 7  # 새 질문 추출만 재호출, 의미 검증·비교 캐시는 재사용


def test_batch_missing_pair_is_rejected():
    class MissingLLM(FakeLLM):
        async def chat(self, payload):
            if 'pairs' not in json.loads(payload['messages'][1]['content']):
                return await super().chat(payload)
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': '{"comparisons": []}'}}
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_sources(MissingLLM(), '질문', documents(), 'test-model'))


def test_invalid_quote_does_not_poison_cache(tmp_path):
    from app.analysis_cache import AnalysisCache
    llm = FakeLLM(invalid_quote=True)
    llm.cache = AnalysisCache(tmp_path, 'model-digest')
    with pytest.raises(AnalysisError, match='재추출'):
        asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert not list(tmp_path.glob('*.json'))
    llm.invalid_quote = False
    result = asyncio.run(analyze_sources(llm, '질문', documents(), 'test-model'))
    assert result['claims'][0]['original_quote'] == '40分間の予定です。'
    assert len(llm.requests) == 8


def test_progress_reports_verified_work_including_skipped_pairs():
    updates = []
    result = asyncio.run(analyze_sources(FakeLLM(), '질문', documents(), 'test-model',
                                        progress=updates.append))
    assert result['docs'][0]['sim']['d1'] == 0.93
    assert updates[0]['stage'] == 'extracting'
    assert updates[0]['completed'] == 0
    assert updates[0]['total'] == 3
    assert updates[0]['stage_total'] == 2
    assert any(u['stage_completed'] == 1 and u['stage_total'] == 2
               for u in updates if u['stage'] == 'extracting')
    assert updates[-1]['stage'] == 'comparing'
    assert updates[-1]['completed'] == 3
    assert all(a['completed'] <= b['completed']
               for a, b in zip(updates, updates[1:], strict=False))
