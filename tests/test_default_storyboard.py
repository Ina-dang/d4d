from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_default_entry_opens_existing_storyboard_and_its_assets(tmp_path):
    with TestClient(create_app(Settings(openai_key='', tavily_key='', database=tmp_path/'test.sqlite3'))) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert response.url.path == '/storyboard/storyboard.html'
        assert '겹눈 · 시나리오 스토리보드' in response.text
        assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in response.headers['content-security-policy']
        assert "frame-ancestors 'self'" in response.headers['content-security-policy']
        for asset in ('storyboard.css', 'storyboard.js', 'sidebar-icons.svg',
                      'logo-gyeopnun.png', 'favicon-gyeopnun.png'):
            assert client.get('/storyboard/'+asset).status_code == 200
        assert client.get('/storyboard/.env').status_code == 404
        assert client.get('/storyboard/data/skytrace.sqlite3').status_code == 404


def test_existing_analysis_app_remains_available_separately(tmp_path):
    with TestClient(create_app(Settings(openai_key='', tavily_key='', database=tmp_path/'test.sqlite3'))) as client:
        response = client.get('/app')
        assert response.status_code == 200
        assert 'LOCAL MVP' in response.text
        assert "frame-ancestors 'none'" in response.headers['content-security-policy']
        assert client.get('/static/app.js').status_code == 200
        assert client.get('/api/config').status_code == 200
