"""Synthetic API upload -> preview -> import -> draft -> review -> export demo."""
import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from app.main import app, store
from .sample_workbooks import template


def main():
    original_env = {k: os.environ.get(k) for k in ('EVIDENCEDESK_DB', 'EVIDENCEDESK_API_KEY', 'EVIDENCEDESK_TENANT')}
    with tempfile.TemporaryDirectory() as directory:
        os.environ.update(EVIDENCEDESK_DB=str(Path(directory) / 'demo.db'),
                          EVIDENCEDESK_API_KEY='synthetic-local-demo', EVIDENCEDESK_TENANT='demo')
        store.cache_clear()
        try:
            client = TestClient(app)
            headers = {'X-API-Key': 'synthetic-local-demo', 'Idempotency-Key': 'workbook-demo-v1'}
            source, mapping = template()
            def upload(path):
                response = client.post(path, headers=headers, files={'file': ('security.xlsx', source)},
                                       data={'mapping': json.dumps(mapping)})
                response.raise_for_status()
                return response.json()
            preview = upload('/questionnaires/preview')
            assert preview['total'] == 5
            questionnaire = upload('/questionnaires')
            identifier = questionnaire['id']
            assert upload('/questionnaires')['id'] == identifier
            response = client.post('/documents', headers=headers, json={'title': 'Synthetic policy',
                'content': 'Customer data is encrypted at rest using AES-256. Transport encryption uses TLS 1.2 or higher.',
                'version': '1', 'valid_until': '2099-01-01'})
            response.raise_for_status()
            response = client.post(f'/questionnaires/{identifier}/draft', headers=headers, json={'limit': 100})
            response.raise_for_status()
            items = client.get(f'/questionnaires/{identifier}/items', headers=headers).json()['items']
            approved = 0
            for item in items:
                if item['status'] == 'needs_review' and item['provenance']['writable']:
                    response = client.post(f"/questionnaire-items/{item['id']}/approve", headers=headers,
                                           json={'expected_revision': 1, 'reviewer': 'synthetic local reviewer'})
                    response.raise_for_status()
                    approved += 1
            response = client.post(f'/questionnaires/{identifier}/export', headers=headers)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                output = bundle.read('completed.xlsx')
                manifest = json.loads(bundle.read('manifest.json'))
                assert manifest['source_sha256'] == hashlib.sha256(source).hexdigest()
                assert len(manifest['selected_revisions']) == approved == 3
                assert len(manifest['unresolved_item_ids']) == 2
                wb = load_workbook(io.BytesIO(output))
                assert wb['Security']['C5'].value == 'Existing response'
                assert wb['Security']['F2'].value == '=1+2'
                assert wb['Security']['C6'].value is None
                wb.close()
                destination = Path('output/milestone1')
                destination.mkdir(parents=True, exist_ok=True)
                for name in ('completed.xlsx', 'manifest.json', 'unresolved-items.csv'):
                    (destination / name).write_bytes(bundle.read(name))
            print(json.dumps({'mode': 'extractive-baseline', 'imported': 5, 'approved_exported': approved,
                              'unresolved': 2, 'source_unchanged': True, 'artifacts': str(destination)}, indent=2))
        finally:
            store.cache_clear()
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    main()
