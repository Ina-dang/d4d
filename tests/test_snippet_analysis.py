import asyncio
import json

import pytest

from app.claims.snippet_analysis import analyze_snippets
from app.claims.source_analysis_input import analysis_input, verification_input
from app.claims.source_embeddings import question_relevance
from app.core.analysis_cache import AnalysisCache
from app.core.errors import AnalysisError


def collection():
    return {
        'reference_date': '2026-10-01', 'korean_question': '통제 종료 시각을 비교해줘',
        'total_count': 2, 'by_country': {
            'CN': [{'doc_id': 'doc_cn', 'country': 'CN', 'tier': 2,
                    'credibility_weight': 0.5, 'language': 'zh', 'title': '통제 공지',
                    'text_snippet': '管制将于22:40结束。',
                    'article_text': '管制将于22:40结束。\n\nFULL_BODY_ONLY',
                    'published_date': '2026-10-01'}],
            'TW': [{'doc_id': 'doc_tw', 'country': 'TW', 'tier': 3,
                    'credibility_weight': 0.8, 'language': 'zh', 'title': '통제 발표',
                    'text_snippet': '管制将于22:20结束。',
                    'article_text': '管制将于22:20结束。\n\nFULL_BODY_ONLY'}],
            'JP': [],
        },
    }


class SnippetModels:
    def __init__(self):
        self.similarity_target = 'user_question'
        self.requests = []
        self.embeds = []
        self.unloads = []

    async def chat(self, payload):
        self.requests.append(payload)
        data = json.loads(payload['messages'][1]['content'])
        if data.get('operation') == 'verify_translation':
            output = {'checks': [{'claim_index': item['claim_index'], 'verdict': 'pass', 'issues': []}
                                 for item in data['claims']]}
        else:
            output = {'claims': [{'quote_id': data['quotes'][0]['quote_id'],
                'translated_quote': '통제는 종료될 예정이다.', 'expression': '예정',
                'event_date': None}]}
        return {'done': True, 'done_reason': 'stop',
                'message': {'content': json.dumps(output, ensure_ascii=False)}}

    async def embed(self, payload):
        self.embeds.append(payload)
        return {'embeddings': [[1.0, 0.0] if '22:40' in text else [0.6, 0.8]
                               for text in payload['input']]}

    async def unload(self, model):
        self.unloads.append(model)


def test_new_by_country_and_saved_job_are_read_without_paragraphs():
    payload = collection()
    for source in (payload, {'status': 'completed', 'input': {'question': '질문'},
                             'output': payload}):
        question, documents = analysis_input(source)
        assert question == ('질문' if 'output' in source else payload['korean_question'])
        assert [doc['doc_id'] for doc in documents] == ['doc_cn', 'doc_tw']
        assert all('paragraphs' not in doc for doc in documents)
    assert payload == collection()


def test_source_country_is_preserved_when_search_group_differs():
    payload = collection()
    payload['by_country']['US'] = payload['by_country'].pop('TW')
    payload['by_country']['US'][0]['country'] = 'GLOBAL'
    _, documents = analysis_input(payload)
    assert documents[1]['country'] == 'GLOBAL'


def test_snippets_produce_exact_contract_and_question_relevance():
    question, documents = analysis_input(collection())
    models, updates = SnippetModels(), []
    result = asyncio.run(analyze_snippets(models, question, documents, 'test-llm',
                                         'test-embedding', progress=updates.append))
    output = verification_input(result)
    assert set(output) == {'docs', 'claims'}
    assert output['docs'] == [
        {'id': 'doc_cn', 'country': 'CN', 'weight': 0.5, 'sim': 0.6},
        {'id': 'doc_tw', 'country': 'TW', 'weight': 0.8, 'sim': 1.0},
    ]
    assert set(output['claims'][0]) == {
        'claim_id', 'document_id', 'tier', 'event_date', 'paragraph_id', 'translated_quote'}
    assert output['claims'][0]['claim_id'] == 'doc_cn-c1'
    assert output['claims'][0]['event_date'] is None
    assert all('FULL_BODY_ONLY' not in json.dumps(request) for request in models.requests)
    assert all(request['options']['num_ctx'] == 4096 for request in models.requests)
    assert models.unloads == ['test-llm']
    assert models.embeds[0]['truncate'] is False
    assert len(models.requests) == 4  # 추출 및 의미 확인, 문서별 한 번씩
    assert result['timings']['llm_calls'] == 4
    assert result['timings']['embedding_calls'] == 1
    assert result['analysis_scope'] == 'text_snippet'
    assert result['similarity_target'] == 'user_question'
    assert result['analysis_question'] == question
    assert models.embeds[0]['input'][0] == question
    assert models.embeds[0]['input'][1:] == [d['text_snippet'] for d in documents]
    assert updates[-1]['completed'] == updates[-1]['total']
    for claim in result['claims']:
        assert any(p['paragraph_id'] == claim['paragraph_id']
                   and claim['original_quote'] in p['raw_text']
                   for p in result['analysis_paragraphs'])


def test_empty_snippet_and_missing_body_do_not_use_title_as_evidence():
    question, documents = analysis_input(collection())
    documents[0]['text_snippet'] = ''
    documents[0].pop('article_text')
    models = SnippetModels()
    result = asyncio.run(analyze_snippets(models, question, documents, 'test-llm', 'embed'))
    assert result['docs'][0]['sim'] is None
    assert all(c['document_id'] == 'doc_tw' for c in result['claims'])
    assert len(models.requests) == 2
    assert len(models.embeds[0]['input']) == 2
    assert any('doc_cn' in warning for warning in result['warnings'])


def test_link_only_snippet_keeps_document_and_embedding_without_a_fake_claim():
    question, documents = analysis_input(collection())
    documents[0]['text_snippet'] = 'References: https://example.org.'
    documents[0]['article_text'] = 'References: https://example.org.'
    models = SnippetModels()
    result = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert len(result['docs']) == 2
    assert all(c['document_id'] != documents[0]['doc_id'] for c in result['claims'])
    assert len(models.requests) == 2
    assert len(models.embeds[0]['input']) == 3
    assert result['analysis_paragraphs'][0]['raw_text'] == documents[0]['text_snippet']
    assert any('링크·참고 목록' in warning for warning in result['warnings'])


def test_embeddings_are_reused_and_do_not_depend_on_question(tmp_path):
    question, documents = analysis_input(collection())
    models = SnippetModels()
    models.cache = AnalysisCache(tmp_path / 'claims', 'llm-digest')
    models.embedding_cache = AnalysisCache(tmp_path / 'vectors', 'embed-digest')
    first = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    second = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert verification_input(first) == verification_input(second)
    assert len(models.embeds) == 1
    assert len(models.requests) == 4
    assert second['timings']['llm_calls'] == second['timings']['embedding_calls'] == 0
    asyncio.run(analyze_snippets(models, '다른 질문', documents, 'llm', 'embed'))
    assert len(models.embeds) == 2
    assert models.embeds[-1]['input'] == ['다른 질문']
    assert len(models.requests) > 4


def test_verified_cpu_claims_can_be_reused_with_gpu_automatic_settings(tmp_path):
    question, documents = analysis_input(collection())
    models = SnippetModels()
    models.cache = AnalysisCache(tmp_path / 'claims', 'same-model-digest')
    models.embedding_cache = AnalysisCache(tmp_path / 'vectors', 'same-embedding-digest')
    models.force_cpu = True
    first = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    models.force_cpu = False
    trace = []
    second = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed', trace))
    assert verification_input(first) == verification_input(second)
    assert len(models.requests) == 4
    assert second['timings']['llm_calls'] == 0
    assert all(record['cpu_cache_reused'] for record in trace if record['phase'] == 'extraction')


@pytest.mark.parametrize('vectors', [[[0, 0], [1, 0]], [[1, 0]],
                                    [[float('nan'), 0], [1, 0]], [[1, 0], [1, 0, 0]]])
def test_invalid_embedding_response_is_rejected(vectors):
    class Invalid(SnippetModels):
        async def embed(self, payload):
            return {'embeddings': vectors}

    question, documents = analysis_input(collection())
    with pytest.raises(AnalysisError, match='임베딩'):
        asyncio.run(analyze_snippets(Invalid(), question, documents, 'llm', 'embed'))


def test_negative_cosine_is_zero_in_the_zero_to_one_contract():
    class Opposite(SnippetModels):
        async def embed(self, payload):
            return {'embeddings': [[1, 0], [-1, 0], [1, 0]]}

    question, documents = analysis_input(collection())
    result = asyncio.run(analyze_snippets(Opposite(), question, documents, 'llm', 'embed'))
    assert result['docs'][0]['sim'] == 0


def test_duplicate_document_ids_fail_before_model_calls():
    question, documents = analysis_input(collection())
    documents[1]['doc_id'] = documents[0]['doc_id']
    models = SnippetModels()
    with pytest.raises(AnalysisError, match='ID'):
        asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert models.requests == models.embeds == []


def test_missing_snippet_can_recover_from_article_with_explicit_provenance():
    question, documents = analysis_input(collection())
    documents[0].pop('text_snippet')
    result = asyncio.run(analyze_snippets(SnippetModels(), question, documents, 'llm', 'embed'))
    recovered = next(c for c in result['claims'] if c['document_id'] == 'doc_cn')
    assert recovered['evidence_origin'] == 'article_text'
    assert recovered['original_quote'] in documents[0]['article_text']
    assert 'text_snippet' not in documents[0]
    assert result['similarity_sources']['doc_cn'] == 'article_text'


def test_documents_without_relevant_claims_still_have_semantic_similarity():
    class NoClaims(SnippetModels):
        async def chat(self, payload):
            self.requests.append(payload)
            return {'done': True, 'done_reason': 'stop',
                    'message': {'content': '{"claims": []}'}}

    question, documents = analysis_input(collection())
    models = NoClaims()
    result = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert result['claims'] == []
    assert result['docs'][0]['sim'] == 0.6
    assert len(models.requests) == 4  # snippet 추출 2회 + 원문 후보 추출 2회
    assert all(item['status'] == 'no_relevant_claim' for item in result['article_fallback'])


def test_implicit_event_date_is_not_copied_from_published_date():
    class InventedDate(SnippetModels):
        async def chat(self, payload):
            response = await super().chat(payload)
            output = json.loads(response['message']['content'])
            if 'claims' in output:
                for claim in output['claims']:
                    claim['event_date'] = '2026-10-01'
                response['message']['content'] = json.dumps(output)
            return response

    question, documents = analysis_input(collection())
    trace = []
    result = asyncio.run(analyze_snippets(InventedDate(), question, documents,
                                         'llm', 'embed', trace))
    assert all(claim['event_date'] is None for claim in result['claims'])
    assert any(record.get('date_normalizations') for record in trace)


def test_new_question_changes_relevance_and_reuses_only_document_embeddings(tmp_path):
    class Directional(SnippetModels):
        async def embed(self, payload):
            self.embeds.append(payload)
            return {'embeddings': [[1, 0] if text in {'질문 A', '기사 A'} else [0, 1]
                                   for text in payload['input']]}

    models = Directional()
    models.embedding_cache = AnalysisCache(tmp_path / 'vectors', 'same-digest')
    docs = [{'doc_id': 'a', 'title': '임베딩에서 제외할 제목', 'text_snippet': '기사 A'},
            {'doc_id': 'b', 'title': '다른 제목', 'text_snippet': '기사 B'}]
    first = asyncio.run(question_relevance(models, '질문 A', docs, 'embed', []))
    second = asyncio.run(question_relevance(models, '질문 B', docs, 'embed', []))
    assert first == {'a': 1.0, 'b': 0.0}
    assert second == {'a': 0.0, 'b': 1.0}
    assert models.embeds[0]['input'] == ['질문 A', '기사 A', '기사 B']
    assert models.embeds[1]['input'] == ['질문 B']


def test_document_id_cannot_overwrite_the_question_vector():
    models = SnippetModels()
    docs = [{'doc_id': '__user_question__', 'title': '', 'text_snippet': '22:40 종료'},
            {'doc_id': '__user_question___', 'title': '', 'text_snippet': '다른 내용'}]
    result = asyncio.run(question_relevance(models, '질문', docs, 'embed', []))
    assert result == {'__user_question__': 0.6, '__user_question___': 1.0}


def test_document_dictionary_contract_keeps_all_pairs_and_separate_query_scores():
    question, docs = analysis_input(collection())
    models = SnippetModels()
    models.similarity_target = 'other_documents'
    updates = []
    result = asyncio.run(analyze_snippets(models, question, docs, 'llm', 'embed', progress=updates.append))
    assert result['docs'][0]['sim'] == {'doc_tw': 0.6}
    assert result['docs'][1]['sim'] == {'doc_cn': 0.6}
    assert result['question_relevance'] == {'doc_cn': 0.6, 'doc_tw': 1.0}
    assert result['similarity_target'] == 'other_documents'
    assert 'question_relevance' not in verification_input(result)
    assert len(models.embeds) == 1
    assert updates[-1]['stage_total'] == 1
    assert updates[-1]['completed'] == updates[-1]['total']


def test_empty_snippet_is_null_in_both_directions_and_all_articles_are_kept():
    question, docs = analysis_input(collection())
    docs[0]['text_snippet'] = ''
    docs[0].pop('article_text')
    models = SnippetModels()
    models.similarity_target = 'other_documents'
    result = asyncio.run(analyze_snippets(models, question, docs, 'llm', 'embed'))
    assert len(result['docs']) == 2
    assert result['docs'][0]['sim'] == {'doc_tw': None}
    assert result['docs'][1]['sim'] == {'doc_cn': None}
    assert result['question_relevance']['doc_cn'] is None


def test_one_document_has_no_self_similarity_entry():
    question, docs = analysis_input(collection())
    models = SnippetModels()
    models.similarity_target = 'other_documents'
    result = asyncio.run(analyze_snippets(models, question, docs[:1], 'llm', 'embed'))
    assert result['docs'][0]['sim'] == {}


@pytest.mark.parametrize('question', ['', '  ', None])
def test_missing_question_fails_before_extraction_or_embedding(question):
    _, docs = analysis_input(collection())
    models = SnippetModels()
    with pytest.raises(AnalysisError, match='사용자 질문'):
        asyncio.run(analyze_snippets(models, question, docs, 'llm', 'embed'))
    assert models.requests == models.embeds == []
