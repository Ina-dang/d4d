import asyncio
import json
from copy import deepcopy

from app.claims.article_fallback import MAX_EMBED_CANDIDATES, body_candidates
from app.claims.snippet_analysis import analyze_snippets
from app.claims.source_analysis_input import verification_input


class FallbackModels:
    force_cpu = True
    similarity_target = 'user_question'

    def __init__(self):
        self.requests, self.embeds, self.unloads = [], [], []

    async def chat(self, payload):
        self.requests.append(payload)
        data = json.loads(payload['messages'][1]['content'])
        if data.get('operation') == 'verify_translation':
            output = {'checks': [{'claim_index': c['claim_index'], 'verdict': 'pass', 'issues': []}
                                 for c in data['claims']]}
        elif 'context' in data:
            output = {'claims': [{'quote_id': data['quotes'][0]['quote_id'],
                'translated_quote': data['quotes'][0]['original_quote'],
                'expression': '가능', 'event_date': '2026-10-01'}]}
        else:
            output = {'claims': []}
        return {'done': True, 'done_reason': 'stop',
                'message': {'content': json.dumps(output, ensure_ascii=False)}}

    async def embed(self, payload):
        self.embeds.append(payload)
        return {'embeddings': [[1, 0] if text == '대만 충돌의 영향' else
                               [0.8, 0.6] if '충돌이 커지면' in text else [-1, 0]
                               for text in payload['input']]}

    async def unload(self, model):
        self.unloads.append(model)


def test_only_missing_claims_use_body_and_sim_tracks_recovered_evidence():
    documents = [{'doc_id': 'a', 'text_snippet': '구독 안내를 확인하세요.', 'country': 'KR',
                  'tier': 3, 'credibility_weight': 0.55,
                  'article_text': '일반적인 경제 상황을 설명합니다. '
                                  '대만 주변에서 충돌이 커지면 한국도 영향을 받을 수 있습니다.'},
                 {'doc_id': 'b', 'text_snippet': '', 'article_text': 'Account Settings',
                  'country': 'IN', 'tier': 3, 'credibility_weight': 0.75}]
    original = deepcopy(documents)
    models, updates, trace = FallbackModels(), [], []
    result = asyncio.run(analyze_snippets(models, '대만 충돌의 영향', documents, 'llm', 'embed',
                                         trace, progress=updates.append))
    output = verification_input(result)
    assert len(output['docs']) == 2 and len(output['claims']) == 1
    assert output['docs'][0]['sim'] == 0.8  # 구독 문구의 벡터는 음의 유사도
    assert output['docs'][1]['sim'] is None
    assert result['similarity_target'] == 'user_question'
    assert result['analysis_scope'] == 'text_snippet_with_article_text_fallback'
    claim = result['claims'][0]
    assert claim['original_quote'] == '대만 주변에서 충돌이 커지면 한국도 영향을 받을 수 있습니다.'
    assert claim['event_date'] is None  # 게시일이나 임의 날짜를 채우지 않음
    assert claim['expression'] == '가능'
    assert result['similarity_sources']['a'] == 'article_text'
    evidence = next(p for p in result['analysis_paragraphs'] if p['paragraph_id'] == claim['paragraph_id'])
    assert evidence['origin'] == 'article_text'
    assert evidence['raw_text'] == documents[0]['article_text'][evidence['source_start']:evidence['source_end']]
    assert claim['original_quote'] == documents[0]['article_text'][evidence['quote_start']:evidence['quote_end']]
    assert documents == original
    fallback_payload = next(p for p in models.requests if 'context' in json.loads(p['messages'][1]['content']))
    assert fallback_payload['format']['properties']['claims']['maxItems'] == 1
    assert all(p['options']['num_gpu'] == 0 for p in models.requests + models.embeds)
    assert models.unloads == ['llm', 'embed', 'llm']
    assert updates[-1]['completed'] == updates[-1]['total']
    assert result['verification_selection']['documents_without_claims'] == ['b']


def test_transcript_is_preferred_and_quotes_keep_source_offsets_and_conditions():
    body = ('# Video title\n\nSubscribed with another email?\n\n### Transcript\n\n'
            '[0:02] 중국이 대만을 공격한다고 가정합니다.\n\n'
            '[0:10] 그 경우 한국도 영향을 받을 수 있습니다.')
    candidates, diagnostics = body_candidates({'doc_id': 'video', 'article_text': body}, '대만')
    assert diagnostics['transcript_preferred'] is True
    assert len(candidates) == 2
    for candidate in candidates:
        p = candidate['evidence']
        assert candidate['original_quote'] == body[p['quote_start']:p['quote_end']]
        assert p['raw_text'] == body[p['source_start']:p['source_end']]
        assert '구독' not in candidate['original_quote']
    assert '가정합니다' in candidates[1]['evidence']['raw_text']


def test_no_body_or_boilerplate_does_not_call_fallback_model():
    models = FallbackModels()
    docs = [{'doc_id': 'empty', 'text_snippet': None},
            {'doc_id': 'paywall', 'article_text': 'Subscribed with another email? '
                         'Logout and Login with that one.\n\nAccount Settings'}]
    result = asyncio.run(analyze_snippets(models, '대만 충돌의 영향', docs, 'llm', 'embed'))
    assert len(result['docs']) == 2 and result['claims'] == []
    assert models.requests == []
    assert [d['status'] for d in result['article_fallback']] == ['no_article_text', 'no_body_candidates']
    assert all(d['sim'] is None for d in result['docs'])


def test_long_body_uses_bounded_candidate_pool_without_cutting_sentences():
    sentences = ['일반 경제 소식에 관한 내용입니다.'] * (MAX_EMBED_CANDIDATES + 10)
    sentences.append('중국과 대만의 충돌 가능성을 설명하는 문장입니다.')
    body = '\n\n'.join(sentences)
    candidates, diagnostics = body_candidates({'doc_id': 'long', 'article_text': body}, '대만 충돌')
    assert diagnostics['candidate_count'] == len(sentences)
    assert diagnostics['lexical_prefilter_applied'] is True
    assert len(candidates) == MAX_EMBED_CANDIDATES
    assert candidates[0]['original_quote'] == sentences[-1]
    assert all(c['original_quote'] in body for c in candidates)


def test_oversized_sentence_is_excluded_whole_with_diagnostic():
    body = '한' * 1601 + '。 정상적인 대만 관련 문장입니다.'
    candidates, diagnostics = body_candidates({'doc_id': 'long', 'article_text': body}, '대만')
    assert diagnostics['oversized_sentences_excluded'] == 1
    assert candidates[0]['original_quote'] == '정상적인 대만 관련 문장입니다.'


def test_chinese_search_query_can_retrieve_later_sentences_in_long_body():
    body = '\n\n'.join(['这是一般经济新闻的内容。'] * 55 + ['台湾海峡冲突风险正在上升。'])
    candidates, diagnostics = body_candidates(
        {'doc_id': 'zh', 'article_text': body, 'query': '台湾海峡 冲突'}, '대만해협 충돌')
    assert diagnostics['lexical_prefilter_applied'] is True
    assert candidates[0]['original_quote'] == '台湾海峡冲突风险正在上升。'


def test_document_similarities_use_recovered_vector_in_both_directions():
    models = FallbackModels()
    models.similarity_target = 'other_documents'
    docs = [{'doc_id': 'a', 'text_snippet': '구독 안내를 확인하세요.',
             'article_text': '대만 주변에서 충돌이 커지면 한국도 영향을 받을 수 있습니다.'},
            {'doc_id': 'b', 'text_snippet': '대만 충돌의 영향'}]
    result = asyncio.run(analyze_snippets(models, '대만 충돌의 영향', docs, 'llm', 'embed'))
    assert result['docs'][0]['sim'] == {'b': 0.8}
    assert result['docs'][1]['sim'] == {'a': 0.8}
    assert result['question_relevance'] == {'a': 0.8, 'b': 1.0}


def test_plain_timestamp_lines_are_joined_at_sentence_boundaries_with_exact_source_offsets():
    body = '[0:00] 台湾について何を持ち出すかというと\n\n[0:08] 中国側は対話を求めた。\n\n[0:16] 台湾側は拒否した。'
    candidates, info = body_candidates({'doc_id': 'video', 'article_text': body},
                                       '대만 양측 발표', require_focus=True)
    assert info['transcript_preferred']
    assert candidates[0]['original_quote'].endswith('中国側は対話を求めた。')
    assert '\n\n[0:08]' in candidates[0]['original_quote']
    for candidate in candidates:
        evidence = candidate['evidence']
        assert body[evidence['quote_start']:evidence['quote_end']] == candidate['original_quote']
