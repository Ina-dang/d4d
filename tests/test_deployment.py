import pytest
from fastapi.testclient import TestClient

from app.cli.check_deployment import inspect
from app.config import Settings
from app.main import create_app


def deployed(tmp_path, **changes):
    return Settings(**{
        'database': tmp_path / 'state' / 'db.sqlite3', 'deployment': True,
        'access_user': 'team', 'access_password': 'test-only-password-123',
        'allowed_hosts': ('backend.example.com',),
        'public_origins': ('https://project.vercel.app',),
        'tavily_key': '', 'openai_key': '', **changes,
    })


def test_deployment_requires_credentials_and_exact_https_origins(tmp_path):
    for changes in [
        {'access_password': ''}, {'access_password': 'short'}, {'public_origins': ()},
        {'public_origins': ('https://*.vercel.app',)},
        {'public_origins': ('https://user:secret@example.com',)},
        {'public_origins': ('https://example.com/path',)},
        {'allowed_hosts': ('*',)},
    ]:
        with pytest.raises(ValueError):
            deployed(tmp_path, **changes)


def test_deployment_protects_ui_data_and_accepts_only_configured_frontend(tmp_path):
    settings = deployed(tmp_path)
    with TestClient(create_app(settings), base_url='https://backend.example.com') as client:
        for path in ['/', '/api/config', '/api/scenarios/active', '/healthz']:
            response = client.get(path)
            assert response.status_code == 401
            assert response.headers['cache-control'] == 'no-store'
        for credential in ['Basic broken', 'Bearer arbitrary']:
            assert client.get('/api/config', headers={'Authorization': credential}).status_code == 401
        client.auth = (settings.access_user, settings.access_password)
        assert client.get('/').status_code == 200
        assert client.get('/healthz').json() == {'status': 'ok'}
        assert 'access_password' not in client.get('/api/config').text
        response = client.post('/api/scenarios', json={}, headers={'origin': 'https://project.vercel.app'})
        assert response.status_code == 422  # Reaches request validation, not a CSRF rejection.
        assert client.post('/api/scenarios', json={}, headers={
            'origin': 'https://attacker.vercel.app',
            'x-forwarded-host': 'attacker.vercel.app',
        }).status_code == 403
        assert client.get('/api/config', headers={'host': 'untrusted.example.com'}).status_code == 400


def test_data_directory_can_be_a_persistent_volume(monkeypatch, tmp_path):
    monkeypatch.setenv('SKYTRACE_DATA_DIR', str(tmp_path / 'volume'))
    assert Settings().database == tmp_path / 'volume' / 'skytrace.sqlite3'


def test_vercel_python_readiness_does_not_misreport_current_app_as_deployable(tmp_path):
    result = inspect(Settings(database=tmp_path / 'db', tavily_key='fixture'), 'vercel-functions')
    assert not result['checks_passed']
    failed = {c['name'] for c in result['checks'] if not c['passed']}
    assert failed == {'hosted_llm', 'durable_storage', 'durable_jobs'}
    assert 'fixture' not in str(result)
