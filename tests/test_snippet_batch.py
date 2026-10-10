import asyncio
import json

import pytest
from test_snippet_analysis import SnippetModels, collection

from app.claims.snippet_analysis import analyze_snippets
from app.claims.source_analysis_input import analysis_input, verification_input
from app.core.analysis_cache import AnalysisCache
from app.core.errors import AnalysisError


class BatchModels(SnippetModels):
    batch_snippets = True

    async def chat(self, payload):
        data = json.loads(payload['messages'][1]['content'])
        if 'documents' not in data:
            return await super().chat(payload)
        self.requests.append(payload)
        output = {'documents': {doc['document_id']: {'claims': [{
            'quote_id': doc['quotes'][0]['quote_id'], 'translated_quote': '통제는 종료될 예정이다.',
            'expression': '예정', 'event_date': None}]} for doc in data['documents']}}
        return {'done': True, 'done_reason': 'stop',
                'message': {'content': json.dumps(output, ensure_ascii=False)}}


def test_two_documents_use_one_extraction_and_one_meaning_check(tmp_path):
    question, documents = analysis_input(collection())
    models = BatchModels()
    models.cache = AnalysisCache(tmp_path / 'claims', 'model-digest')
    models.embedding_cache = AnalysisCache(tmp_path / 'embedding', 'embed-digest')
    first = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert first['timings']['llm_calls'] == 2
    assert len(models.requests) == 2
    assert len(first['docs']) == len(first['claims']) == 2
    assert first['claims'][0]['original_quote'] == documents[0]['text_snippet']
    assert first['claims'][1]['original_quote'] == documents[1]['text_snippet']
    assert first['claims'][0]['document_id'] != first['claims'][1]['document_id']
    models.batch_snippets = False
    second = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert second['timings']['llm_calls'] == 0
    assert verification_input(first) == verification_input(second)


def test_batch_does_not_reprocess_a_document_already_verified(tmp_path):
    question, documents = analysis_input(collection())
    models = BatchModels()
    models.cache = AnalysisCache(tmp_path, 'model-digest')
    asyncio.run(analyze_snippets(models, question, documents[:1], 'llm', 'embed'))
    models.requests.clear()
    result = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert len(result['docs']) == 2
    assert len(models.requests) == 2
    data = json.loads(models.requests[0]['messages'][1]['content'])
    assert data['document_id'] == documents[1]['doc_id']
    assert 'paragraphs' not in data


@pytest.mark.parametrize('invalid', ['missing', 'unknown'])
def test_invalid_batch_document_ids_are_rejected(invalid):
    class Bad(BatchModels):
        async def chat(self, payload):
            response = await super().chat(payload)
            output = json.loads(response['message']['content'])
            if 'documents' in output:
                key = next(iter(output['documents']))
                removed = output['documents'].pop(key)
                if invalid == 'unknown':
                    output['documents']['unknown'] = removed
                response['message']['content'] = json.dumps(output)
            return response

    question, documents = analysis_input(collection())
    with pytest.raises(AnalysisError, match='문서 ID'):
        asyncio.run(analyze_snippets(Bad(), question, documents, 'llm', 'embed'))


def test_long_documents_remain_separate_without_truncation():
    question, documents = analysis_input(collection())
    for doc in documents:
        doc['text_snippet'] = '문서가 발표했다. ' * 120
    models = BatchModels()
    result = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert len(result['docs']) == 2
    assert len(models.requests) == 4
    assert all('documents' not in json.loads(request['messages'][1]['content'])
               for request in models.requests)


def test_batch_prompt_change_invalidates_individual_verified_cache(tmp_path, monkeypatch):
    from app.claims import claim_validation

    question, documents = analysis_input(collection())
    models = BatchModels()
    models.cache = AnalysisCache(tmp_path / 'cache', 'model-digest')
    asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    for path in claim_validation.PROMPTS.glob('*.txt'):
        (prompts / path.name).write_text(path.read_text(encoding='utf8'), encoding='utf8')
    (prompts / 'source_snippet_batch.txt').write_text('changed prompt', encoding='utf8')
    monkeypatch.setattr(claim_validation, 'PROMPTS', prompts)
    models.batch_snippets = False
    models.requests.clear()
    result = asyncio.run(analyze_snippets(models, question, documents, 'llm', 'embed'))
    assert result['timings']['llm_calls'] == 4


def test_batch_repair_cannot_move_a_claim_to_another_document():
    class CrossDocumentRepair(BatchModels):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                self.requests.append(payload)
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'checks': [{'claim_index': c['claim_index'], 'verdict': 'fail',
                                'issues': ['subject']} for c in data['claims']]})}}
            if data.get('operation') == 'repair_claims':
                self.requests.append(payload)
                other = data['paragraphs'][1]
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'corrections': [{'claim_index': c['claim_index'], 'claim': {
                        **c['draft'], 'paragraph_id': other['paragraph_id'],
                        'original_quote': other['raw_text']}} for c in data['failed_claims']]})}}
            if data.get('operation') == 'select_source_quote':
                self.requests.append(payload)
                assert all(candidate['paragraph_id'] == item['original_target']['paragraph_id']
                           for item in data['failed_claims'] for candidate in item['candidates'])
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'selections': [{'claim_index': c['claim_index'],
                        'quote_id': c['candidates'][0]['quote_id'],
                        'translated_quote': '통제는 종료될 예정이다.', 'expression': '예정',
                        'event_date': None} for c in data['failed_claims']]})}}
            return await super().chat(payload)

    question, documents = analysis_input(collection())
    trace = []
    with pytest.raises(AnalysisError):
        asyncio.run(analyze_snippets(CrossDocumentRepair(), question, documents, 'llm', 'embed', trace))
    repair = next(record['request'] for record in trace if record['phase'] == 'reextraction')
    properties = repair['format']['$defs']['GroundedCorrection']['properties']
    assert 'paragraph_id' not in properties and 'original_quote' not in properties
