import asyncio
import json

import httpx
import pytest

from app.claims.ollama_source_analysis import OllamaSourceAnalysis
from app.config import Settings
from app.core.errors import AnalysisError


def test_snippet_provider_switches_models_and_closes_transport(tmp_path):
    async def scenario():
        provider = OllamaSourceAnalysis(Settings(database=tmp_path / 'test.db'))
        await provider.http.aclose()
        requests = []

        def reply(request):
            body = json.loads(request.content) if request.content else {}
            requests.append((request.url.path, body))
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [
                    {'name': 'gemma4:e2b', 'digest': 'llm'},
                    {'name': 'bge-m3:latest', 'digest': 'embedding'}]})
            if request.url.path == '/api/embed':
                return httpx.Response(200, json={'embeddings': [[1, 0], [0.6, 0.8], [0, 1]]})
            if request.url.path == '/api/generate':
                return httpx.Response(200, json={'done': True})
            data = json.loads(body['messages'][1]['content'])
            if data.get('operation') == 'verify_translation':
                result = {'checks': [{'claim_index': claim['claim_index'], 'verdict': 'pass',
                                     'issues': []} for claim in data['claims']]}
            elif 'documents' in data:
                result = {'documents': {doc['document_id']: {'claims': [{
                    'quote_id': doc['quotes'][0]['quote_id'], 'translated_quote': '발표된 주장.',
                    'expression': '발표', 'event_date': None}]} for doc in data['documents']}}
            else:
                result = {'claims': [{'quote_id': data['quotes'][0]['quote_id'],
                    'translated_quote': '발표된 주장.',
                    'expression': '발표', 'event_date': None}]}
            return httpx.Response(200, json={'done': True, 'done_reason': 'stop',
                'message': {'content': json.dumps(result)}})

        provider.http = httpx.AsyncClient(base_url='http://test',
            transport=httpx.MockTransport(reply))
        result = await provider.analyze('질문', [
            {'doc_id': 'd0', 'text_snippet': '甲方发布了声明。'},
            {'doc_id': 'd1', 'text_snippet': '乙方发布了声明。'}], [])
        assert result['docs'][0]['sim'] == {'d1': 0.8}
        assert result['docs'][1]['sim'] == {'d0': 0.8}
        assert result['question_relevance'] == {'d0': 0.6, 'd1': 0.0}
        embedding_index = next(i for i, (path, _) in enumerate(requests) if path == '/api/embed')
        assert requests[embedding_index - 1] == (
            '/api/generate', {'model': 'gemma4:e2b', 'keep_alive': 0})
        assert requests[-1] == ('/api/generate', {'model': 'bge-m3', 'keep_alive': 0})
        assert provider.http.is_closed
        assert result['timings']['embedding_calls'] == 1

    asyncio.run(scenario())


def test_missing_embedding_model_fails_before_claim_calls(tmp_path):
    async def scenario():
        provider = OllamaSourceAnalysis(Settings(database=tmp_path / 'test.db'))
        await provider.http.aclose()
        paths = []

        def reply(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={'models': [{'name': 'gemma4:e2b'}]})

        provider.http = httpx.AsyncClient(base_url='http://test',
            transport=httpx.MockTransport(reply))
        with pytest.raises(AnalysisError, match='ollama pull bge-m3'):
            await provider.analyze('질문', [{'doc_id': 'd0', 'text_snippet': '原文。'}], [])
        assert '/api/chat' not in paths
        assert '/api/embed' not in paths
        assert provider.http.is_closed

    asyncio.run(scenario())
