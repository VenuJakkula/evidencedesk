"""T06 browser acceptance gate against isolated loopback FastAPI/Vite processes."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from .frontend_smoke import port, ready


def main():
    workflow = '--workflow' in sys.argv
    if workflow: sys.argv.remove('--workflow')
    enterprise = '--oidc' in sys.argv
    if workflow and not enterprise: raise SystemExit('--workflow requires --oidc')
    if enterprise: sys.argv.remove('--oidc')
    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    frontend = root / 'frontend'
    node = shutil.which('node')
    cli = frontend / 'node_modules/@playwright/test/cli.js'
    if not node or not cli.exists():
        raise SystemExit('Run npm.cmd ci in frontend/ before browser verification.')
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with tempfile.TemporaryDirectory(prefix='evidencedesk-browser-') as directory:
        (Path(directory) / '.browser-fixture.json').write_text('{"database": "browser.db", "purpose": "synthetic-browser-tests"}')
        backend_port, frontend_port = port(), port()
        while frontend_port == backend_port:
            frontend_port = port()
        # Bootstrap generates a process-local key. No key is placed in browser storage or test files.
        backend_env = {**os.environ, 'EVIDENCEDESK_DB': str(Path(directory) / 'browser.db'),
                       'EVIDENCEDESK_API_KEY': '', 'EVIDENCEDESK_TENANT': 'browser-synthetic',
                       'EVIDENCEDESK_ALLOW_LOCAL_FRONTEND': '1', 'EVIDENCEDESK_MAX_UPLOAD': '10485760'}
        backend_env['EVIDENCEDESK_AUTH_MODE']='oidc' if enterprise else 'local'
        backend_env['EVIDENCEDESK_DEPLOYMENT']='production' if enterprise and not workflow else 'local'
        backend_env.update(EVIDENCEDESK_DRAFT_ENGINE='baseline',EVIDENCEDESK_MODEL_PROVIDER='fixture',EVIDENCEDESK_ALLOW_LIVE_WORKFLOWS='0')
        if workflow: backend_env['EVIDENCEDESK_RETRIEVAL_BACKEND']='memory'
        if enterprise:
            from .oidc_fixture import initialize, ISSUER, AUDIENCE
            initialize(directory)
            backend_env.update(EVIDENCEDESK_OIDC_ISSUER=ISSUER,EVIDENCEDESK_OIDC_AUDIENCE=AUDIENCE,EVIDENCEDESK_OIDC_JWKS_FILE=str(Path(directory)/'jwks.json'),EVIDENCEDESK_TENANT='enterprise')
        frontend_env = {**os.environ, 'EVIDENCEDESK_API_TARGET': f'http://127.0.0.1:{backend_port}', 'VITE_AUTH_MODE': 'oidc' if enterprise else 'local', 'VITE_DEFAULT_TENANT': 'enterprise' if enterprise else ''}
        try:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(backend_port)], cwd=root, env=backend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            processes.append(backend)
            ready(f'http://127.0.0.1:{backend_port}/health', backend)
            vite = subprocess.Popen([node, str(frontend / 'node_modules/vite/bin/vite.js'), '--port', str(frontend_port)], cwd=frontend, env=frontend_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            processes.append(vite)
            base = f'http://127.0.0.1:{frontend_port}'
            ready(base, vite)
            from openpyxl import Workbook
            large_path = Path(directory) / 'large.xlsx'
            large = Workbook()
            large.active.title = 'Questions'
            large.active.append(['Question', 'Answer'])
            for _ in range(45):
                large.active.append(['Is customer data encrypted at rest?', None])
            large.save(large_path)
            large.close()
            env = {**os.environ, 'EVIDENCEDESK_BROWSER_BASE_URL': base, 'EVIDENCEDESK_BROWSER_LARGE_WORKBOOK': str(large_path), 'EVIDENCEDESK_BROWSER_PYTHON': sys.executable, 'EVIDENCEDESK_BROWSER_FIXTURE_DIR': directory, 'EVIDENCEDESK_BROWSER_OIDC': '1' if enterprise else '0', 'EVIDENCEDESK_BROWSER_WORKFLOW': '1' if workflow else '0'}
            result = subprocess.run([node, str(cli), 'test', '--config', 'playwright.config.ts', *sys.argv[1:]], cwd=frontend, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', timeout=240, creationflags=flags)
            print(result.stdout, flush=True)
            if result.returncode:
                raise SystemExit(result.returncode)
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
