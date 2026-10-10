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
        if 'paragraphs' in data:
            paragraph = data['paragraphs'][0]
            output = {'claims': [{'paragraph_id': paragraph['paragraph_id'],
                'original_quote': 'made up' if self.invalid_quote else paragraph['raw_text'],
                'translated_quote': '통제는 예정되어 있다.', 'expression': '예정',
                'event_date': None}]}
        else:
            output = {'similarity': 0.93}
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
    assert len(llm.requests) == 3


@pytest.mark.parametrize('kwargs', [{'invalid_quote': True}, {'incomplete': True}])
def test_invalid_analysis_is_not_success(kwargs):
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_sources(FakeLLM(**kwargs), '질문', documents(), 'test-model'))


def test_no_claims_does_not_invent_similarity():
    class EmptyLLM(FakeLLM):
        async def chat(self, payload):
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': '{"claims": []}'}}
    result = asyncio.run(analyze_sources(EmptyLLM(), '질문', documents(), 'test-model'))
    assert result['docs'][0]['sim'] == {'d1': None}
    assert result['claims'] == []


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
