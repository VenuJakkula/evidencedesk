"""Reproducible two-process A2A / primary LangGraph demonstration; synthetic only."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
import httpx

@contextmanager
def servers(store, token, tenant="a"):
    ports = []
    for _ in range(2):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); ports.append(sock.getsockname()[1])
    expert, questionnaire = [f'http://127.0.0.1:{port}' for port in ports]
    env = dict(os.environ, EVIDENCEDESK_DB=store.path, EVIDENCEDESK_A2A_PORT=str(ports[0]),
        EVIDENCEDESK_A2A_QUESTIONNAIRE_PORT=str(ports[1]), EVIDENCEDESK_A2A_PUBLIC_URL=expert,
        EVIDENCEDESK_A2A_EXPERT_URL=expert, LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
    processes = []
    try:
        for module in ['app.a2a_expert', 'app.a2a_questionnaire']:
            processes.append(subprocess.Popen([sys.executable,'-m',module],env=env, stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for _ in range(150):
            try:
                if httpx.get(expert+'/.well-known/agent-card.json',headers={'Authorization':'Bearer '+token,'X-Tenant-ID':tenant},timeout=.3).status_code == 200 and httpx.get(questionnaire+'/openapi.json',timeout=.3).status_code == 200:
                    break
            except httpx.HTTPError: pass
            if any(poll.poll() is not None for poll in processes):
                raise AssertionError('A2A process exited')
            time.sleep(.1)
        else: raise AssertionError('A2A services did not start')
        yield expert, questionnaire
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)



def main():
    from app.access import verify
    from app.core import Store
    from app.evidence import Evidence
    from app.questionnaires import Questionnaires
    from app.workbooks import Mapping
    from scripts.oidc_fixture import initialize, ISSUER, AUDIENCE
    from scripts.sample_workbooks import template
    with tempfile.TemporaryDirectory(prefix='evidencedesk-a2a-demo-') as directory:
        root = Path(directory)
        initialize(root)
        tokens = json.loads((root/'oidc-fixture.json').read_text())['tokens']
        settings = {'EVIDENCEDESK_AUTH_MODE':'oidc', 'EVIDENCEDESK_DEPLOYMENT':'local',
            'EVIDENCEDESK_OIDC_ISSUER':ISSUER, 'EVIDENCEDESK_OIDC_AUDIENCE':AUDIENCE,
            'EVIDENCEDESK_OIDC_JWKS_FILE':str(root/'jwks.json')}
        previous = {key:os.environ.get(key) for key in settings}
        os.environ.update(settings)
        try:
            store = Store(root/'browser.db')
            author, reviewer, admin = [verify(tokens[who], 'enterprise') for who in ('author','reviewer','admin')]
            evidence = Evidence(store)
            source = evidence.create(author, 'Synthetic encryption policy',
                'Customer data is encrypted at rest using AES-256.', '1', '2099-01-01', {'product':'Synthetic'})
            evidence.acl(admin, source['id'], 'reviewer')
            evidence.approve(reviewer, source['id'], source['current_version'])
            questionnaires = Questionnaires(store)
            data, mapping = template()
            questionnaire = questionnaires.create(author, data, 'synthetic.xlsx', Mapping.model_validate(mapping), 'a2a-demo')
            item = questionnaires.items(author, questionnaire['id'])['items'][0]
            with servers(store, tokens['author'], 'enterprise') as (_, url):
                with httpx.Client(base_url=url, headers={'Authorization':'Bearer '+tokens['author'], 'X-Tenant-ID':'enterprise'}, timeout=35) as http:
                    response = http.post('/workflow-jobs', json={'item_id':item['id'], 'expected_revision':0, 'request_key':'demo'})
                    response.raise_for_status(); job=response.json()
                    for _ in range(12):
                        response = http.post('/workflow-jobs/'+job['id']+'/advance')
                        response.raise_for_status(); job=response.json()
                        if job['status'] in ('awaiting_review','failed','owner_task'): break
                    if job['status'] != 'awaiting_review':
                        raise RuntimeError('Synthetic workflow did not reach human review')
                    current = questionnaires.item(author,item['id'])
                    if current['answer']['approval'] or not current['answer']['evidence']:
                        raise RuntimeError('Synthetic evidence/review gate failed')
                    questionnaires.approve(reviewer, item['id'], current['current_revision'])
                    response = http.post('/workflow-jobs/'+job['id']+'/advance')
                    response.raise_for_status(); job=response.json()
                    if job['status'] != 'completed': raise RuntimeError('Human review did not complete')
                    with store.connect() as db:
                        research = json.loads(db.execute("SELECT output FROM workflow_steps WHERE job_id=? AND phase='retrieve'", (job['id'],)).fetchone()[0])
                    print(json.dumps({'services':2, 'transport':'A2A 1.0 JSON-RPC', 'status':job['status'],
                        'citation_count':len(current['answer']['evidence']), 'remote_task_recorded':bool(research['trace']['a2a_task_id']),
                        'automatically_approved':False, 'review_decision':job['review_decision'], 'paid_calls':0}))
        finally:
            for key,value in previous.items():
                if value is None: os.environ.pop(key,None)
                else: os.environ[key]=value


if __name__ == '__main__':
    main()
