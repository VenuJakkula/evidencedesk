"""Real HTTP T01 smoke check with isolated backend/Vite processes, not a browser test."""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def request(url, headers=None, method='GET', data=None):
    try:
        with urlopen(Request(url, headers=headers or {}, method=method, data=data), timeout=2) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def ready(url, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Smoke-test server exited before becoming ready.')
        try:
            if request(url)[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(.1)
    raise RuntimeError('Smoke-test server did not become ready within 15 seconds.')


def main():
    root = Path(__file__).resolve().parents[1]
    frontend = root / 'frontend'
    vite = frontend / 'node_modules/vite/bin/vite.js'
    node = shutil.which('node')
    if not node or not vite.exists():
        raise SystemExit('Install Node and run npm.cmd ci in frontend/ before running this check.')
    processes = []
    with tempfile.TemporaryDirectory() as directory:
        backend_port, frontend_port = port(), port()
        while frontend_port == backend_port:
            frontend_port = port()
        key = secrets.token_urlsafe(32)
        backend_env = {**os.environ, 'EVIDENCEDESK_DB': str(Path(directory) / 'smoke.db'),
                       'EVIDENCEDESK_API_KEY': key, 'EVIDENCEDESK_TENANT': 'frontend-smoke',
                       'EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY': '1'}
        backend_env['EVIDENCEDESK_ALLOW_LOCAL_FRONTEND'] = '1'
        frontend_env = {**os.environ, 'EVIDENCEDESK_API_TARGET': f'http://127.0.0.1:{backend_port}'}
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(backend_port)], cwd=root, env=backend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            processes.append(backend)
            ready(f'http://127.0.0.1:{backend_port}/health', backend)
            dev = subprocess.Popen([node, str(vite), '--port', str(frontend_port)], cwd=frontend, env=frontend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            processes.append(dev)
            base = f'http://127.0.0.1:{frontend_port}'
            ready(base, dev)
            assert b'EvidenceDesk' in request(base)[1]
            assert json.loads(request(base + '/api/health')[1])['status'] == 'ok'
            assert request(base + '/api/session')[0] == 401
            status, body = request(base + '/api/session', {'X-API-Key': key})
            assert status == 200 and json.loads(body)['tenant'] == 'frontend-smoke'
            assert request(base + '/api/session', {'X-API-Key': 'wrong'})[0] == 401
            assert request(base + '/api/local/api-key', {'X-Local-Key-Recovery': 'true'}, 'POST')[0] == 404
            assert request(base + '/api/%2e%2e/local/api-key', {'X-Local-Key-Recovery': 'true'}, 'POST')[0] == 404
            assert request(base + '/api/session', {'X-API-Key': key})[0] == 200
            bootstrap_headers = {'X-Local-Session': 'true', 'Origin': base}
            status, payload = request(base + '/dev/session-key', bootstrap_headers, 'POST')
            assert status == 200
            automatic_key = json.loads(payload)['api_key']
            assert automatic_key == key
            assert json.loads(request(base + '/dev/session-key', bootstrap_headers, 'POST')[1])['api_key'] == automatic_key
            assert request(base + '/api/session', {'X-API-Key': automatic_key})[0] == 200
            assert request(base + '/dev/session-key', {'X-Local-Session': 'true', 'Origin': 'http://evil.example'}, 'POST')[0] == 403
            assert request(base + '/dev/session-key', {'Origin': base}, 'POST')[0] == 403
            assert request(base + '/dev/session-key', {**bootstrap_headers, 'X-Forwarded-For': '127.0.0.1'}, 'POST')[0] == 403
            assert request(base + '/dev/session-key', bootstrap_headers)[0] == 405
            assert request(base + '/api/local/session-key', bootstrap_headers, 'POST')[0] == 404
            assert not (Path(directory) / 'smoke.db').exists(), 'Read-only connection checks must not create a database.'
            from app.core import Store
            from app.questionnaires import Questionnaires
            from app.workbooks import Mapping
            from scripts.sample_workbooks import template
            service = Questionnaires(Store(Path(directory) / 'smoke.db'))
            data, mapping = template('security')
            saved = service.create('frontend-smoke', data, 'security.xlsx', Mapping.model_validate(mapping), 'smoke-import')
            service.create('other-tenant', data, 'private.xlsx', Mapping.model_validate(mapping), 'private-import')
            headers = {'X-API-Key': key}
            status, payload = request(base + '/api/questionnaires?limit=1', headers)
            listing = json.loads(payload)
            assert status == 200 and listing['total'] == 1 and listing['items'][0]['id'] == saved['id']
            assert listing['items'][0]['filename'] == 'security.xlsx' and listing['items'][0]['total'] == 5
            assert json.loads(request(base + '/api/questionnaires/' + saved['id'], headers)[1])['total'] == 5
            assert json.loads(request(base + '/api/questionnaires?offset=1', headers)[1])['items'] == []
            assert request(base + '/api/questionnaires?limit=101', headers)[0] == 422
            assert request(base + '/api/questionnaires')[0] == 401
            evidence = {'title': 'Synthetic policy', 'content': 'Data is encrypted at rest.', 'version': '1', 'valid_until': '2099-01-01'}
            status, payload = request(base + '/api/documents', {**headers, 'Content-Type': 'application/json'}, 'POST', json.dumps(evidence).encode())
            assert status == 201 and json.loads(payload)['id']
            with service.store.connect() as db:
                assert db.execute('SELECT COUNT(*) FROM documents WHERE tenant=?', ('frontend-smoke',)).fetchone()[0] == 1
            print(json.dumps({'checks': 26, 'failures': 0, 'scope': 'real HTTP frontend/proxy/backend; no browser',
                              'isolated_database': True, 'key_recovery_proxied': False, 'automatic_connection': True,
                              'dashboard_and_evidence': True}))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    main()
