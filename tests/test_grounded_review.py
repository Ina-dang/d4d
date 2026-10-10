import asyncio
import json

import pytest
from test_snippet_analysis import SnippetModels, collection

from app.analysis_cache import AnalysisCache
from app.claim_validation import (
    MeaningChecks,
    VerifiedBlock,
    batches,
    exact_indices,
    verified_cache_key,
)
from app.errors import AnalysisError
from app.snippet_analysis import analyze_snippets
from app.snippet_batch import extraction_request
from app.snippet_quotes import SnippetExtraction, grounded_extraction
from app.source_analysis import request
from app.source_analysis_input import analysis_input


@pytest.mark.parametrize('indices', [[2], [2, 11, 1], [2, 2]])
def test_review_rejects_missing_extra_and_duplicate_indices(indices):
    checked = MeaningChecks(checks=[{'claim_index': i, 'verdict': 'pass', 'issues': []}
                                    for i in indices])
    with pytest.raises(AnalysisError):
        exact_indices(checked.checks, [2, 11])


def test_uncertain_result_still_fails_analysis(tmp_path):
    class Uncertain(SnippetModels):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'checks': [{'claim_index': c['claim_index'], 'verdict': 'uncertain',
                                'issues': ['uncertain']} for c in data['claims']]})}}
            if data.get('operation') == 'repair_claims':
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'corrections': [{'claim_index': c['claim_index'], **{
                        key: c['draft'][key] for key in ('translated_quote', 'expression', 'event_date')}}
                                    for c in data['failed_claims']]})}}
            return await super().chat(payload)

    question, docs = analysis_input(collection())
    llm = Uncertain()
    llm.cache = AnalysisCache(tmp_path, 'digest')
    with pytest.raises(AnalysisError, match='2회 재추출'):
        asyncio.run(analyze_snippets(llm, question, docs, 'llm', 'embed'))
    assert llm.embeds == []


def test_repair_batches_keep_all_claims_and_full_original_context():
    base = {'paragraphs': [{'paragraph_id': 'p1', 'raw_text': '원문 전체 문맥'}]}
    failed = [{'claim_index': i} for i in range(1, 10)]
    groups = list(batches(base, 'failed_claims', failed, max_items=3))
    assert len(groups) == 3
    assert [c for group in groups for c in group['failed_claims']] == failed
    assert all(group['paragraphs'] == base['paragraphs'] for group in groups)


def test_pre_optimization_verified_cache_is_reused_with_exact_current_grounding(tmp_path):
    question, docs = analysis_input(collection())
    models = SnippetModels()
    models.cache = AnalysisCache(tmp_path, 'digest')
    block = [{'paragraph_id': docs[0]['doc_id']+'-snippet-p1', 'raw_text': docs[0]['text_snippet']}]
    current, quotes = extraction_request(models, 'llm', question, docs[0], block)
    old = request('llm', SnippetExtraction, 'source_snippet_extract.txt', {
        'document_id': docs[0]['doc_id'], 'question': question,
        'language': docs[0]['language'], 'quotes': quotes})
    old['options'] = current['options']
    old['format'] = current['format']
    extraction = grounded_extraction(SnippetExtraction.model_validate({'claims': [{
        'quote_id': 1, 'translated_quote': '통제는 종료될 예정이다.', 'expression': '예정',
        'event_date': None}]}), quotes)
    models.cache.write(verified_cache_key(old, block, legacy=True), VerifiedBlock(
        extraction=extraction, repair_count=0, validation_trace=[{'phase': 'meaning_check'}]
    ).model_dump(mode='json'))
    result = asyncio.run(analyze_snippets(models, question, docs[:1], 'llm', 'embed'))
    assert models.requests == []
    assert result['timings']['llm_calls'] == 0


def test_grounded_repair_changes_translation_and_preserves_exact_source():
    class Repair(SnippetModels):
        async def chat(self, payload):
            data = json.loads(payload['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                self.requests.append(payload)
                claim = data['claims'][0]['claim']
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'checks': [{'claim_index': 1,
                                'verdict': 'fail' if '시행' in claim['translated_quote'] else 'pass',
                                'issues': ['modality'] if '시행' in claim['translated_quote'] else []}]})}}
            if data.get('operation') == 'repair_claims':
                self.requests.append(payload)
                fields = payload['format']['$defs']['GroundedCorrection']['properties']
                assert set(fields) == {'claim_index', 'translated_quote', 'expression', 'event_date'}
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
                    'corrections': [{'claim_index': 1, 'translated_quote': '통제는 종료될 예정이다.',
                                     'expression': '예정', 'event_date': None}]})}}
            raw = await super().chat(payload)
            parsed = json.loads(raw['message']['content'])
            parsed['claims'][0]['translated_quote'] = '통제가 시행되었다.'
            raw['message']['content'] = json.dumps(parsed)
            return raw

    question, docs = analysis_input(collection())
    result = asyncio.run(analyze_snippets(Repair(), question, docs[:1], 'llm', 'embed'))
    assert result['claims'][0]['original_quote'] == docs[0]['text_snippet']
    assert result['claims'][0]['paragraph_id'] == docs[0]['doc_id']+'-snippet-p1'
    assert result['claims'][0]['translated_quote'] == '통제는 종료될 예정이다.'
    assert result['timings']['phases']['reextraction']['llm_calls'] == 1
