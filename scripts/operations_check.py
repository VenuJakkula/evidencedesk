"""Synthetic restore, migration idempotency and bounded local API load rehearsal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import tempfile
import time
from fastapi.testclient import TestClient
from app.core import Store
from app.main import app, store as api_store
from scripts.access_admin import copy_database


def run():
    import os
    with tempfile.TemporaryDirectory(prefix='evidencedesk-restore-') as directory:
        root=Path(directory)
        before=Store(root/'before.sqlite')
        identifier=before.add_document('synthetic','Restore marker','Synthetic backup recovery marker','1','2099-01-01')
        backup=Path(copy_database(before.path,root/'backup.sqlite'))
        # Candidate writes occur after backup and must disappear after restore rollback.
        before.add_document('synthetic','Candidate marker','Synthetic candidate change','1','2099-01-01')
        start=time.monotonic()
        restored=Store(copy_database(backup,root/'restored.sqlite'))
        Store(restored.path)  # Reapply all additive migrations idempotently.
        with restored.connect() as db:
            healthy=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            count=db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
            original=db.execute('SELECT id FROM documents').fetchone()[0]==identifier
        elapsed=round((time.monotonic()-start)*1000,3)
        if not healthy or count!=1 or not original: raise RuntimeError('Restore failed')
        # This exercises ASGI concurrency, not network/proxy/container load.
        with TestClient(app) as client:
            def request(_):
                started=time.monotonic(); response=client.get('/health')
                return response.status_code, (time.monotonic()-started)*1000
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(request,range(80)))
        latencies=sorted(value for _,value in results)
        failures=sum(status!=200 for status,_ in results)
        return {'version':'local-operations-v1', 'restore_integrity':healthy,
            'restored_documents':count, 'candidate_change_rolled_back':count==1,
            'migration_reapply':'passed', 'restore_ms':elapsed,
            'recovery_objectives':{'target_rpo_minutes':60,'target_rto_minutes':30,
                'status':'proposed operator objectives, not established production guarantees'},
            'load':{'transport':'in-process ASGI','requests':80,'concurrency':4,'failures':failures,
                'p50_ms':round(latencies[40],3),'p95_ms':round(latencies[math.ceil(.95*80)-1],3)},
            'staging_rollback':'not executed', 'container_smoke':'not executed',
            'limitations':'Tiny synthetic SQLite restore and health-route load only; no full-service RTO, production backup freshness, network load or image rollback claim.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='evals/operations_results.json');args=parser.parse_args()
    report=run();Path(args.output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if report['load']['failures']: raise SystemExit(1)

if __name__=='__main__':main()
