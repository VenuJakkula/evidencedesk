import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from app import observability as traces
from app.main import app, store as api_store
from app.providers import ExtractiveProvider, ScriptedProvider
from app.provider_router import Peer, RoutedDraft
from app.retrieval import Foundation
from app.retrieval_index import MemoryIndex
from app.scoped_cache import ScopedCache
from app.workbooks import Problem
from test_access import environment, approved


def test_nested_traces_redact_content_and_seeded_failure(tmp_path, monkeypatch):
    path=tmp_path/'traces.jsonl'
    monkeypatch.setenv('EVIDENCEDESK_TRACE_FILE',str(path))
    with traces.span('http',question='secret',job_id='Bearer SECRET') as update:
        update(status=503,failure='provider',phase='retrieve',cost_usd=0)
        with pytest.raises(Problem):
            with traces.span('provider'):
                raise Problem('provider_unavailable','SECRET SOURCE AND TOKEN',503)
    raw=path.read_text()
    rows=[json.loads(line) for line in raw.splitlines()]
    assert 'SECRET' not in raw and 'question' not in raw
    assert rows[0]['parent_id']==rows[1]['id']
    assert rows[0]['metrics']['failure']=='provider'


def test_langsmith_export_uses_only_approved_metadata(tmp_path, monkeypatch):
    calls=[]
    class Client:
        def create_run(self,*args,**kwargs): calls.append((args,kwargs))
        def update_run(self,*args,**kwargs): calls.append((args,kwargs))
    monkeypatch.setenv('EVIDENCEDESK_TRACE_EXPORT','langsmith')
    monkeypatch.setattr(traces,'_sink',Client())
    with traces.span('tool',input='PRIVATE',status=200): pass
    assert len(calls)==2 and calls[0][0][1]=={} and calls[1][1]['outputs']=={}
    assert 'PRIVATE' not in repr(calls)


def test_real_langsmith_sdk_serialization_is_content_free(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from langsmith import Client
    payloads=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payloads.append(self.rfile.read(int(self.headers.get('Content-Length','0'))).decode())
            self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        do_PATCH=do_POST
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"version":"0.14.8"}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=Client(api_url=f'http://127.0.0.1:{server.server_port}',api_key='synthetic-key',
        auto_batch_tracing=False,hide_inputs=True,hide_outputs=True,omit_traced_runtime_info=True,timeout_ms=1000)
    monkeypatch.setenv('EVIDENCEDESK_TRACE_EXPORT','langsmith')
    monkeypatch.setattr(traces,'_sink',client)
    try:
        with traces.span('model',question='PRIVATE',status=200):pass
        assert len(payloads)==2
        assert 'PRIVATE' not in ''.join(payloads) and 'synthetic-key' not in ''.join(payloads)
        assert json.loads(payloads[0])['inputs']=={}
    finally:
        client.close();server.shutdown();server.server_close();thread.join(timeout=2)


def test_trace_sink_outage_does_not_change_results(monkeypatch):
    def failure(event): raise OSError('disk full')
    monkeypatch.setattr(traces,'emit',failure)
    with traces.span('retrieval'): result=3
    assert result==3


def test_readiness_and_request_ids(environment, monkeypatch):
    store,_,_,_,_=environment
    app.dependency_overrides.clear()
    monkeypatch.setattr('app.main.store',lambda:store)
    with TestClient(app) as http:
        ready=http.get('/ready')
        assert ready.status_code==200 and ready.json()=={'status':'ready'}
        assert ready.headers['x-request-id']
        monkeypatch.setenv('EVIDENCEDESK_OIDC_JWKS_FILE','missing-jwks-file')
        bad=http.get('/ready')
        assert bad.status_code==503 and 'missing-jwks' not in bad.text


@pytest.mark.parametrize('change',['revoke','acl','version','membership'])
def test_scoped_cache_current_authority(environment,change):
    store,evidence,_,_,scope=environment
    source,_,_=approved(environment)
    service=Foundation(store,MemoryIndex(),cache=ScopedCache())
    query='Customer data encrypted at rest'
    first=service.run(scope('author'),query)
    second=service.run(scope('author'),query)
    assert first['items'] and second['trace']['cache_hit']
    assert not service.run(scope('outsider'),query)['items']
    if change=='revoke': evidence.revoke(scope(),source['id'])
    elif change=='acl': evidence.acl(scope(),source['id'],'author',remove=True)
    elif change=='version': evidence.version(scope('author'),source['id'],source['current_version'],'Replacement policy','2','2099-01-01')
    else: evidence.membership(scope(),'author',[],False)
    if change=='membership':
        with pytest.raises(Problem): service.run(scope('author'),query)
    else: assert not service.run(scope('author'),query)['items']


def test_cache_expiry_capacity_and_copy():
    now=[0]
    cache=ScopedCache(capacity=1,ttl=2,clock=lambda:now[0])
    cache.put('a',[1]); value=cache.get('a');value.append(2)
    assert cache.get('a')==[1]
    cache.put('b',[2]);assert cache.get('a') is None
    now[0]=3; assert cache.get('b') is None
    import pickle
    worker=pickle.loads(pickle.dumps(cache))
    assert worker.capacity==1 and worker.entries=={}


def test_provider_outage_fallback_and_cooldown():
    now=[0]
    primary=ScriptedProvider(Problem('provider_unavailable','offline',503))
    secondary=ExtractiveProvider()
    router=RoutedDraft([Peer('one',primary,'local','fixture',0),Peer('two',secondary,'local','fixture',0)],
        'one',region='local',privacy='fixture',max_price=0,clock=lambda:now[0])
    assert router.draft('q',[],1)['claims']==[]
    router.draft('q',[],1)
    assert len(primary.calls)==1
    now[0]=11;router.draft('q',[],1)
    assert len(primary.calls)==2


@pytest.mark.parametrize('field,value',[('region','elsewhere'),('privacy','retained'),('price_cap',1)])
def test_provider_fallback_cannot_relax_policy(field,value):
    values=dict(name='two',provider=ExtractiveProvider(),region='local',privacy='private',price_cap=0)
    values[field]=value
    with pytest.raises(Problem):
        RoutedDraft([Peer('one',ExtractiveProvider(),'local','private',0),Peer(**values)],'one',region='local',privacy='private',max_price=0)


def test_invalid_provider_response_does_not_fallback():
    bad=ScriptedProvider(Problem('unsupported_claim','bad claim',502))
    fallback=ScriptedProvider({})
    router=RoutedDraft([Peer('one',bad,'local','private',0),Peer('two',fallback,'local','private',0)],'one',region='local',privacy='private',max_price=0)
    with pytest.raises(Problem,match='bad claim'): router.draft('q',[],1)
    assert fallback.calls==[]


def test_experimental_router_cannot_bypass_live_workflow_budget(environment):
    from app.workflows import Workflows
    store,_,_,_,_=environment
    router=RoutedDraft([Peer('one',ExtractiveProvider(),'local','private',0),Peer('two',ExtractiveProvider(),'local','private',0)],'one',region='local',privacy='private',max_price=0)
    with pytest.raises(Problem,match='cost accounting'):
        Workflows(store).profile(Foundation(store,MemoryIndex(),provider=router))


def test_release_gate_detects_invalid_citations(monkeypatch):
    from scripts import release_evaluate as evaluation
    monkeypatch.setattr(evaluation,'valid',lambda *args:False)
    result=evaluation.evaluate('validation')
    assert 'citation_integrity' in result['failures']


def test_dataset_splits_disjoint_and_honestly_labeled():
    from scripts.release_evaluate import load_cases
    splits=[load_cases(name) for name in ['development','validation','heldout']]
    identifiers=[{case['id'] for case in cases} for cases in splits]
    assert len(set.union(*identifiers))==50
    assert not identifiers[0]&identifiers[2] and not identifiers[1]&identifiers[2]
    assert all(case['review_status']=='synthetic_unreviewed' for cases in splits for case in cases)
