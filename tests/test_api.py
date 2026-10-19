from fastapi.testclient import TestClient
from app.main import app, store

def test_authenticated_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'test-secret')
    monkeypatch.setenv('EVIDENCEDESK_DB', str(tmp_path/'api.db'))
    store.cache_clear()
    client = TestClient(app)
    assert client.post('/answers', json={'question':'test'}).status_code == 401
    headers = {'X-API-Key':'test-secret'}
    assert client.post('/documents', headers=headers, json={'title':'Policy','content':'Data encryption uses AES-256.','version':'1','valid_until':'2099-01-01'}).status_code == 201
    answer = client.post('/answers', headers=headers, json={'question':'What data encryption is used?'}).json()
    assert answer['status'] == 'needs_review'
    assert client.post(f"/answers/{answer['id']}/approve", headers=headers, json={'reviewer':'reviewer','final':answer['draft']}).status_code == 200
    assert 'AES-256' in client.get('/export', headers=headers).text
    assert client.get('/answers/missing', headers=headers).status_code == 404
    store.cache_clear()

def test_unconfigured_auth_fails_closed(monkeypatch):
    monkeypatch.delenv('EVIDENCEDESK_API_KEY', raising=False)
    assert TestClient(app).get('/export').status_code == 503


def test_session_check_requires_key_and_does_not_open_database(monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'session-test-key')
    monkeypatch.setenv('EVIDENCEDESK_TENANT', 'session-tenant')
    def unexpected_store():
        raise AssertionError('Connection checking must not open a database')
    monkeypatch.setattr('app.main.store', unexpected_store)
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/session').status_code == 401
    assert client.get('/session', headers={'X-API-Key': 'wrong'}).status_code == 401
    response = client.get('/session', headers={'X-API-Key': 'session-test-key'})
    assert response.json() == {'tenant': 'session-tenant', 'mode': 'extractive-baseline', 'authentication': 'local-api-key'}
    monkeypatch.delenv('EVIDENCEDESK_API_KEY')
    assert client.get('/session').status_code == 503


def test_local_key_recovery_rotates_and_authenticates(monkeypatch, tmp_path):
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'previous-key')
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY', '1')
    monkeypatch.setenv('EVIDENCEDESK_DB', str(tmp_path / 'recovery.db'))
    store.cache_clear()
    try:
        client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12345))
        response = client.post('/local/api-key', headers={'X-Local-Key-Recovery': 'true', 'Origin': 'http://127.0.0.1:8000'})
        assert response.status_code == 200
        key = response.json()['api_key']
        assert len(key) >= 43 and key != 'previous-key'
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/export', headers={'X-API-Key': key}).status_code == 200
        assert client.get('/export', headers={'X-API-Key': 'previous-key'}).status_code == 401
        second = client.post('/local/api-key', headers={'X-Local-Key-Recovery': 'true'}).json()['api_key']
        assert second != key
        assert client.get('/export', headers={'X-API-Key': key}).status_code == 401
    finally:
        store.cache_clear()


def test_local_key_recovery_access_controls(monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'unchanged')
    monkeypatch.delenv('EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY', raising=False)
    client = TestClient(app, base_url='http://localhost:8000', client=('127.0.0.1', 12345))
    headers = {'X-Local-Key-Recovery': 'true'}
    assert client.post('/local/api-key', headers=headers).status_code == 404
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY', '1')
    assert client.post('/local/api-key').status_code == 403
    assert client.post('/local/api-key', headers={**headers, 'Origin': 'http://evil.example'}).status_code == 403
    assert client.post('/local/api-key', headers={**headers, 'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    remote = TestClient(app, base_url='http://localhost:8000', client=('192.0.2.1', 12345))
    assert remote.post('/local/api-key', headers=headers).status_code == 403
    bad_host = TestClient(app, base_url='http://evil.example', client=('127.0.0.1', 12345))
    assert bad_host.post('/local/api-key', headers=headers).status_code == 403
    assert __import__('os').environ['EVIDENCEDESK_API_KEY'] == 'unchanged'


def test_local_frontend_bootstrap_reuses_key_and_authenticates(monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND', '1')
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'existing-local-key')
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12345))
    headers = {'X-Local-Session': 'true'}
    first = client.post('/local/session-key', headers=headers)
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-store'
    assert first.json()['api_key'] == 'existing-local-key'
    assert client.post('/local/session-key', headers=headers).json() == first.json()
    assert client.get('/session', headers={'X-API-Key': first.json()['api_key']}).status_code == 200
    monkeypatch.delenv('EVIDENCEDESK_API_KEY')
    generated = client.post('/local/session-key', headers=headers).json()['api_key']
    assert len(generated) >= 43
    assert client.post('/local/session-key', headers=headers).json()['api_key'] == generated


def test_local_frontend_bootstrap_rejects_disabled_remote_and_cross_origin(monkeypatch):
    monkeypatch.setenv('EVIDENCEDESK_API_KEY', 'unchanged')
    monkeypatch.delenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND', raising=False)
    headers = {'X-Local-Session': 'true'}
    client = TestClient(app, base_url='http://localhost:8000', client=('127.0.0.1', 12345))
    assert client.post('/local/session-key', headers=headers).status_code == 404
    monkeypatch.setenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND', '1')
    assert client.post('/local/session-key').status_code == 403
    assert client.post('/local/session-key', headers={**headers, 'Origin': 'http://evil.example'}).status_code == 403
    assert client.post('/local/session-key', headers={**headers, 'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    remote = TestClient(app, base_url='http://localhost:8000', client=('192.0.2.1', 12345))
    assert remote.post('/local/session-key', headers=headers).status_code == 403
    bad_host = TestClient(app, base_url='http://evil.example', client=('127.0.0.1', 12345))
    assert bad_host.post('/local/session-key', headers=headers).status_code == 403
    assert __import__('os').environ['EVIDENCEDESK_API_KEY'] == 'unchanged'
