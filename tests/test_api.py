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
