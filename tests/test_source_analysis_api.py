import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AnalysisError
from app.main import create_app


def test_saved_collection_analysis_and_download(tmp_path, monkeypatch):
    from app.ollama_source_analysis import OllamaSourceAnalysis

    async def analyze(self, question, documents, trace):
        assert question == '시험에 대해 알려줘'
        assert documents[0]['doc_id'] == 'd0'
        return {'docs': [{'id': 'd0', 'country': 'JP', 'weight': 0.5,
                          'score': 0.8, 'sim': {}}], 'claims': [], 'warnings': []}

    monkeypatch.setattr(OllamaSourceAnalysis, 'analyze', analyze)
    directory = tmp_path / 'collections'
    directory.mkdir()
    (directory / 'abc.json').write_text(json.dumps({
        'status': 'completed', 'input': {'question': '시험에 대해 알려줘'},
        'output': {'documents': [{'doc_id': 'd0'}]}}, ensure_ascii=False), encoding='utf-8')
    with TestClient(create_app(Settings(database=tmp_path / 'test.db'))) as client:
        response = client.post('/api/collections/abc/analysis')
        assert response.status_code == 200, response.text
        assert response.json()['docs'][0]['score'] == 0.8
        downloaded = client.get('/api/collections/abc/analysis/download')
        assert downloaded.status_code == 200
        assert downloaded.json() == response.json()
        progress = client.get('/api/collections/abc/analysis/status').json()
        assert progress['status'] == 'completed'
        assert progress['percent'] == 100
        assert client.post('/api/collections/missing/analysis').status_code == 404


def test_analysis_failure_preserves_collected_originals(tmp_path, monkeypatch):
    from app.ollama_source_analysis import OllamaSourceAnalysis

    async def fail(self, *args):
        raise AnalysisError('인용 검사 실패')

    monkeypatch.setattr(OllamaSourceAnalysis, 'analyze', fail)
    directory = tmp_path / 'collections'
    directory.mkdir()
    source = directory / 'abc.json'
    original = json.dumps({'status': 'completed', 'input': {'question': '질문'},
                           'output': {'documents': [{'doc_id': 'd0'}]}})
    source.write_text(original, encoding='utf-8')
    with TestClient(create_app(Settings(database=tmp_path / 'test.db'))) as client:
        assert client.post('/api/collections/abc/analysis').status_code == 422
        assert client.get('/api/collections/abc/analysis/download').status_code == 404
        progress = client.get('/api/collections/abc/analysis/status').json()
        assert progress['status'] == 'failed'
        assert progress['percent'] is None or progress['percent'] < 100
        assert progress['error'] == '인용 검사 실패'
    assert source.read_text(encoding='utf-8') == original


def test_running_progress_can_be_read_while_analysis_request_is_pending(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from app.ollama_source_analysis import OllamaSourceAnalysis

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def analyze(self, question, documents, trace):
            self.progress({'stage': 'comparing', 'completed': 2, 'total': 4,
                           'detail': '문서 2쌍 비교 중'})
            started.set()
            await release.wait()
            return {'docs': [], 'claims': [], 'warnings': []}

        monkeypatch.setattr(OllamaSourceAnalysis, 'analyze', analyze)
        directory = tmp_path / 'collections'
        directory.mkdir()
        (directory / 'abc.json').write_text(json.dumps({
            'status': 'completed', 'input': {'question': '질문'},
            'output': {'documents': [{'doc_id': 'd0'}]}}), encoding='utf-8')
        app = create_app(Settings(database=tmp_path / 'test.db'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                     base_url='http://testserver') as client:
            pending = asyncio.create_task(client.post('/api/collections/abc/analysis'))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                response = await client.get('/api/collections/abc/analysis/status')
                assert response.status_code == 200
                assert response.json()['status'] == 'running'
                assert response.json()['percent'] == 50
                assert response.json()['detail'] == '문서 2쌍 비교 중'
                assert not pending.done()
            finally:
                release.set()
                await pending

    asyncio.run(scenario())


def test_by_country_collection_and_exact_verification_download(tmp_path, monkeypatch):
    from app.ollama_source_analysis import OllamaSourceAnalysis

    async def analyze(self, question, documents, trace):
        assert question == '대만해협의 발표 비교'
        assert [doc['doc_id'] for doc in documents] == ['doc_cn', 'doc_tw']
        assert all('paragraphs' not in doc for doc in documents)
        assert documents[0]['country'] == 'CN'
        return {
            'docs': [{'id': 'doc_cn', 'country': 'CN', 'weight': 0.5,
                      'sim': {'doc_tw': 0.61}},
                     {'id': 'doc_tw', 'country': 'TW', 'weight': 0.8,
                      'sim': {'doc_cn': 0.61}}],
            'claims': [{'claim_id': 'doc_cn-c1', 'document_id': 'doc_cn', 'tier': 2,
                        'event_date': None, 'paragraph_id': 'doc_cn-snippet-p1',
                        'translated_quote': '원문에 명시된 발표.', 'original_quote': '原文。',
                        'expression': '발표'}],
            'warnings': ['snippet 범위만 분석'],
            'analysis_paragraphs': [{'paragraph_id': 'doc_cn-snippet-p1', 'raw_text': '原文。'}],
            'timings': {},
        }

    monkeypatch.setattr(OllamaSourceAnalysis, 'analyze', analyze)
    directory = tmp_path / 'collections'
    directory.mkdir()
    source = directory / 'new.json'
    original = json.dumps({
        'status': 'completed', 'output': {'korean_question': '대만해협의 발표 비교',
            'by_country': {'CN': [{'doc_id': 'doc_cn', 'text_snippet': '原文。'}],
                           'TW': [{'doc_id': 'doc_tw', 'text_snippet': '原文。'}]}}})
    source.write_text(original, encoding='utf-8')
    with TestClient(create_app(Settings(database=tmp_path / 'test.db'))) as client:
        response = client.post('/api/collections/new/analysis')
        assert response.status_code == 200, response.text
        downloaded = client.get('/api/collections/new/analysis/download?format=verification')
        assert downloaded.status_code == 200
        result = downloaded.json()
        assert set(result) == {'docs', 'claims'}
        assert set(result['docs'][0]) == {'id', 'country', 'weight', 'sim'}
        assert set(result['claims'][0]) == {
            'claim_id', 'document_id', 'tier', 'event_date', 'paragraph_id', 'translated_quote'}
        assert result['claims'][0]['event_date'] is None
        assert 'attachment' in downloaded.headers['content-disposition']
        details = client.get('/api/collections/new/analysis/download').json()
        assert details['claims'][0]['original_quote'] == '原文。'
        assert details['analysis_paragraphs']
    assert source.read_text(encoding='utf-8') == original
