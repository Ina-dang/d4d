import asyncio
import json
from types import SimpleNamespace

import pytest

from app import analyze_collection
from app.errors import AnalysisError


def arguments(tmp_path):
    return SimpleNamespace(input=tmp_path / 'collection.json',
                           output=tmp_path / 'verification.json', details=None,
                           question=None, model=None, embedding_model=None, cpu=True)


def test_cli_exports_contract_and_keeps_evidence_separate(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    source = {'korean_question': '수집 질문', 'by_country': {'CN': [
        {'doc_id': 'real-doc', 'text_snippet': '原文。', 'article_text': 'FULL_BODY'}]}}
    args.input.write_text(json.dumps(source), encoding='utf-8-sig')
    original = args.input.read_bytes()
    calls = []

    class Provider:
        def __init__(self, settings):
            self.settings = settings

        async def analyze(self, question, documents, trace):
            calls.append((question, documents, self.input_scope, self.force_cpu))
            trace.append({'phase': 'extraction'})
            return {'docs': [{'id': 'real-doc', 'country': 'CN', 'weight': 0.8, 'sim': {}}],
                'claims': [{'claim_id': 'real-doc-c1', 'document_id': 'real-doc',
                    'tier': 2, 'event_date': None, 'paragraph_id': 'real-doc-snippet-p1',
                    'translated_quote': '한국어 번역', 'original_quote': '原文。'}],
                'warnings': ['snippet 범위'], 'timings': {'llm_calls': 2}}

    monkeypatch.setattr(analyze_collection, 'OllamaSourceAnalysis', Provider)
    args.question = '새 질문'
    asyncio.run(analyze_collection.run(args))
    output = json.loads(args.output.read_text(encoding='utf-8'))
    details = json.loads((tmp_path / 'verification-details.json').read_text(encoding='utf-8'))
    assert set(output) == {'docs', 'claims'}
    assert 'original_quote' not in output['claims'][0]
    assert details['result']['claims'][0]['original_quote'] == '原文。'
    assert details['trace'] == [{'phase': 'extraction'}]
    assert calls[0][0] == '새 질문'
    assert calls[0][2:] == ('snippet', True)
    assert args.input.read_bytes() == original


def test_cli_refuses_to_overwrite_source(tmp_path):
    args = arguments(tmp_path)
    args.input.write_text('{}', encoding='utf-8')
    args.output = args.input
    with pytest.raises(AnalysisError, match='서로 다른 파일'):
        asyncio.run(analyze_collection.run(args))
    assert args.input.read_text(encoding='utf-8') == '{}'


def test_failed_cli_keeps_review_trace_without_exporting_scores(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    args.input.write_text(json.dumps({'korean_question': '질문', 'by_country': {
        'CN': [{'doc_id': 'doc', 'text_snippet': '原文。'}]}}), encoding='utf-8')

    class Failure:
        def __init__(self, settings):
            pass

        async def analyze(self, question, documents, trace):
            trace.append({'phase': 'meaning_check', 'cache_hit': False,
                          'elapsed_seconds': 2, 'validation_errors': ['subject']})
            raise AnalysisError('번역 검토 실패')

    monkeypatch.setattr(analyze_collection, 'OllamaSourceAnalysis', Failure)
    with pytest.raises(AnalysisError, match='번역 검토 실패'):
        asyncio.run(analyze_collection.run(args))
    assert not args.output.exists()
    details = json.loads((tmp_path / 'verification-details.json').read_text(encoding='utf-8'))
    assert details['error'] == '번역 검토 실패'
    assert details['trace'][0]['validation_errors'] == ['subject']
    assert details['timings']['llm_calls'] == 1
