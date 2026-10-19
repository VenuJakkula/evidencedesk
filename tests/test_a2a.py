"""A2A 1.0 SDK interoperability, security and failure acceptance gates."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
pytest.importorskip('a2a')
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import a2a_pb2 as p
from app.a2a_expert import build_app, Research
from app.a2a_client import EvidenceClient, RemoteFoundation, trusted_peer
from app.retrieval import Foundation
from app.retrieval_index import MemoryIndex
from app.workbooks import Problem
from test_access import environment, approved
from scripts.a2a_demo import servers


def headers(token, tenant='a'):
    return {'Authorization': 'Bearer '+token, 'X-Tenant-ID': tenant, 'A2A-Version': '1.0'}


def message(key='key', **changes):
    body = {'query': 'Customer data encrypted at rest', **changes}
    return p.SendMessageRequest(message=p.Message(message_id=key, role=p.ROLE_USER,
        parts=[p.Part(text=json.dumps(body))]), configuration=p.SendMessageConfiguration(return_immediately=True))


async def connection(store, token, tenant='a', researcher=None):
    app = build_app(store, 'http://127.0.0.1:8011', researcher)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8011', headers=headers(token, tenant))
    card = p.AgentCard(name='fixture')
    return http, JsonRpcTransport(http, card, 'http://127.0.0.1:8011/a2a'), app


async def finished(rpc, task):
    for _ in range(150):
        task = await rpc.get_task(p.GetTaskRequest(id=task.id))
        if task.status.state not in (p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING):
            return task
        await asyncio.sleep(.02)
    raise AssertionError('Task did not terminate')


def test_sdk_discovery_submission_status_and_duplicate(environment):
    store, _, questionnaires, token, scope = environment
    _, _, item = approved(environment)
    before = questionnaires.item(scope('author'), item['id'])
    async def run():
        http, rpc, _ = await connection(store, token('author'))
        async with http:
            card = await A2ACardResolver(http, 'http://127.0.0.1:8011').get_agent_card()
            assert card.supported_interfaces[0].protocol_version == '1.0'
            first = (await rpc.send_message(message())).task
            task = await finished(rpc, first)
            assert task.status.state == p.TASK_STATE_COMPLETED
            assert len(task.artifacts) == 1
            result = json.loads(task.artifacts[0].parts[0].text)
            assert result['items'][0]['quote'] == 'Customer data is encrypted at rest using AES-256.'
            assert result['items'][0]['chunk_id'] and result['items'][0]['content_hash']
            assert (await rpc.send_message(message())).task.id == first.id
            with pytest.raises(Exception):
                await rpc.send_message(message(query='Changed'))
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0] == 1
    asyncio.run(run())
    assert questionnaires.item(scope('author'), item['id']) == before


@pytest.mark.parametrize('who,tenant,expected', [('bad','a',401),('reviewer','a',403),('author','b',403)])
def test_unauthorized_discovery_and_rpc(environment, who, tenant, expected):
    store, _, _, token, _ = environment
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(store, 'http://127.0.0.1:8011')),
                base_url='http://127.0.0.1:8011', headers=headers('invalid' if who=='bad' else token(who), tenant)) as http:
            assert (await http.get('/.well-known/agent-card.json')).status_code == expected
            assert (await http.post('/a2a', json={})).status_code == expected
    asyncio.run(run())


def test_cross_tenant_and_identity_tasks_are_invisible(environment):
    store, _, _, token, _ = environment
    approved(environment)
    async def run():
        http, rpc, app = await connection(store, token('author'))
        async with http:
            task = await finished(rpc, (await rpc.send_message(message())).task)
            for who, tenant in [('other','b'), ('outsider','a')]:
                http.headers.update(headers(token(who), tenant))
                with pytest.raises(Exception):
                    await rpc.get_task(p.GetTaskRequest(id=task.id))
                with pytest.raises(Exception):
                    await rpc.cancel_task(p.CancelTaskRequest(id=task.id))
            http.headers.update(headers(token('author')))
            with pytest.raises(Exception):
                await rpc.get_task(p.GetTaskRequest(id=task.id, tenant='b'))
    asyncio.run(run())


@pytest.mark.parametrize('change', ['revoke','acl','reviewer','expiry','member'])
def test_saved_artifacts_recheck_current_access(environment, change, monkeypatch):
    store, evidence, _, token, scope = environment
    source, _, _ = approved(environment)
    async def run():
        http, rpc, _ = await connection(store, token('author'))
        async with http:
            task = await finished(rpc, (await rpc.send_message(message())).task)
            if change=='revoke': evidence.revoke(scope(), source['id'])
            elif change=='acl': evidence.acl(scope(), source['id'], 'author', remove=True)
            elif change=='reviewer': evidence.membership(scope(), 'reviewer', [], False)
            elif change=='member': evidence.membership(scope(), 'author', [], False)
            else:
                from datetime import date
                class FutureDate(date):
                    @classmethod
                    def today(cls): return cls(2100, 1, 1)
                monkeypatch.setattr('app.evidence.date', FutureDate)
            if change=='member':
                with pytest.raises(Exception): await rpc.get_task(p.GetTaskRequest(id=task.id))
            else:
                current = await rpc.get_task(p.GetTaskRequest(id=task.id))
                assert not current.artifacts and current.status.state == p.TASK_STATE_FAILED
    asyncio.run(run())


def test_client_validates_artifact_against_local_authority(environment):
    store, _, _, token, scope = environment
    approved(environment)
    async def run():
        client = EvidenceClient('http://127.0.0.1:8011', token('author'), 'a',
            httpx.ASGITransport(app=build_app(store, 'http://127.0.0.1:8011')))
        result = await client.research('Customer data encrypted at rest', 'client')
        foundation = RemoteFoundation(store, 'http://127.0.0.1:8011', token('author'), 'a')
        assert foundation.validate_remote(scope('author'), result, {}, 5)['items']
        result['items'][0]['quote'] = 'Invented answer'
        with pytest.raises(Problem, match='provenance'):
            foundation.validate_remote(scope('author'), result, {}, 5)
    asyncio.run(run())


def test_cancellation_and_expert_timeout(environment):
    store, _, _, token, _ = environment
    approved(environment)
    def slow(scope, request):
        time.sleep(1.5)
        return {'items': [], 'trace': {}}
    async def run():
        http, rpc, _ = await connection(store, token('author'), researcher=slow)
        async with http:
            task = (await rpc.send_message(message())).task
            cancelled = await rpc.cancel_task(p.CancelTaskRequest(id=task.id))
            assert cancelled.status.state == p.TASK_STATE_CANCELED
            assert (await rpc.cancel_task(p.CancelTaskRequest(id=task.id))).status.state == p.TASK_STATE_CANCELED
            timeout = await finished(rpc, (await rpc.send_message(message('timeout', deadline_seconds=1))).task)
            assert timeout.status.state == p.TASK_STATE_FAILED and not timeout.artifacts
            await asyncio.sleep(.6)
            assert not (await rpc.get_task(p.GetTaskRequest(id=task.id))).artifacts
    asyncio.run(run())


def test_client_timeout_cancels_remote_task(environment):
    store, _, _, token, _ = environment
    def slow(scope, request):
        time.sleep(1)
        return {'items': [], 'trace': {}}
    async def run():
        app = build_app(store, 'http://127.0.0.1:8011', slow)
        client = EvidenceClient('http://127.0.0.1:8011', token('author'), 'a', httpx.ASGITransport(app=app))
        with pytest.raises(TimeoutError):
            await client.research('Question', 'timeout', timeout=.2)
        with store.connect() as db:
            row = db.execute('SELECT state,result FROM a2a_tasks').fetchone()
            assert row['state'] == p.TASK_STATE_CANCELED and row['result'] is None
    asyncio.run(run())


def test_restart_does_not_replay_pending_tasks(environment):
    store, _, _, token, _ = environment
    def slow(scope, request):
        time.sleep(.2)
        return {'items': [], 'trace': {}}
    async def run():
        http, rpc, _ = await connection(store, token('author'), researcher=slow)
        async with http:
            task = (await rpc.send_message(message())).task
            build_app(store, 'http://127.0.0.1:8011')
            await asyncio.sleep(.3)
            current = await rpc.get_task(p.GetTaskRequest(id=task.id))
            assert current.status.state == p.TASK_STATE_FAILED and not current.artifacts
    asyncio.run(run())


@pytest.mark.parametrize('body', [{'limit':True}, {'approve':True}, {'deadline_seconds':11}, {'applicability':{'tenant':'b'}}])
def test_invalid_task_inputs(environment, body):
    store, _, _, token, _ = environment
    async def run():
        http, rpc, _ = await connection(store, token('author'))
        async with http:
            with pytest.raises(Exception): await rpc.send_message(message(**body))
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0] == 0
    asyncio.run(run())


def test_client_upstream_outage_is_bounded(environment):
    _, _, _, token, _ = environment
    count = 0
    async def unavailable(request):
        nonlocal count
        count += 1
        raise httpx.ConnectError('offline')
    async def run():
        client = EvidenceClient('http://127.0.0.1:8011', token('author'), 'a', httpx.MockTransport(unavailable))
        with pytest.raises(Problem) as error:
            await client.research('question', 'outage')
        assert error.value.code == 'a2a_unavailable'
    asyncio.run(run())
    assert count <= 2


def test_untrusted_peer_rejected(monkeypatch):
    for url in ['http://example.com','https://user:secret@example.com','https://example.com/path','https://example.com?token=secret']:
        with pytest.raises(Problem): trusted_peer(url)
    monkeypatch.setenv('EVIDENCEDESK_DEPLOYMENT','production')
    with pytest.raises(Problem): trusted_peer('http://127.0.0.1:8011')




def test_two_process_services_primary_workflow_and_human_review(environment):
    store, _, questionnaires, token, scope = environment
    _, _, item = approved(environment)
    with servers(store, token('author')) as (expert, questionnaire):
        with httpx.Client(base_url=questionnaire,headers=headers(token('author')),timeout=35) as http:
            assert http.post('/workflow-jobs',headers={'Authorization':'Bearer invalid'},json={}).status_code in (401,422)
            response = http.post('/workflow-jobs',json={'item_id':item['id'],'expected_revision':item['current_revision'], 'request_key':'two-process'})
            assert response.status_code == 200,response.text
            job = response.json()
            for _ in range(12):
                response = http.post('/workflow-jobs/'+job['id']+'/advance')
                assert response.status_code == 200,response.text
                job = response.json()
                if job['status'] in ('awaiting_review','failed','owner_task'): break
            assert job['status'] == 'awaiting_review',job
            assert job['answer']['evidence'] and job['review_decision']=='pending'
            current = questionnaires.item(scope('author'),item['id'])
            assert not current['answer']['approval']
            questionnaires.approve(scope('reviewer'), item['id'], current['current_revision'])
            job = http.post('/workflow-jobs/'+job['id']+'/advance').json()
            assert job['status'] == 'completed' and job['review_decision']=='approved'
            with store.connect() as db:
                assert db.execute('SELECT COUNT(*) FROM a2a_tasks WHERE state=?',(p.TASK_STATE_COMPLETED,)).fetchone()[0] == 1
                output = db.execute("SELECT output FROM workflow_steps WHERE job_id=? AND phase='retrieve'",(job['id'],)).fetchone()[0]
                assert 'a2a_task_id' in output
                assert token('author') not in output


def test_lost_submission_response_retries_same_task(environment):
    store, _, _, token, _ = environment
    approved(environment)
    app = build_app(store, 'http://127.0.0.1:8011')
    class DropResponse(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.ASGITransport(app=app)
            self.sends = 0
        async def handle_async_request(self, request):
            response = await self.inner.handle_async_request(request)
            if request.method == 'POST' and json.loads(request.content).get('method') == 'SendMessage':
                self.sends += 1
                if self.sends == 1:
                    await response.aclose()
                    raise httpx.ReadError('Synthetic lost response', request=request)
            return response
    async def run():
        transport = DropResponse()
        result = await EvidenceClient('http://127.0.0.1:8011', token('author'), 'a', transport).research('Customer data encrypted at rest', 'lost-response')
        assert result['items'] and transport.sends == 2
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0] == 1
    asyncio.run(run())


def test_client_caller_cancellation_cancels_remote(environment):
    store, _, _, token, _ = environment
    def slow(scope, request):
        time.sleep(.5)
        return {'items': [], 'trace': {}}
    async def run():
        app = build_app(store, 'http://127.0.0.1:8011', slow)
        client = EvidenceClient('http://127.0.0.1:8011', token('author'), 'a', httpx.ASGITransport(app=app))
        task = asyncio.create_task(client.research('question','cancel'))
        for _ in range(50):
            with store.connect() as db: row = db.execute('SELECT state FROM a2a_tasks').fetchone()
            if row: break
            await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        with store.connect() as db:
            assert db.execute('SELECT state FROM a2a_tasks').fetchone()[0] == p.TASK_STATE_CANCELED
    asyncio.run(run())


def test_discovery_cannot_redirect_credentials(environment):
    _, _, _, token, _ = environment
    requests = []
    async def malicious(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={'name':'malicious','supportedInterfaces':[
            {'url':'https://untrusted.invalid/a2a','protocolBinding':'JSONRPC','protocolVersion':'1.0'}]})
    async def run():
        client = EvidenceClient('http://127.0.0.1:8011', token('author'), 'a', httpx.MockTransport(malicious))
        with pytest.raises(Problem) as error:
            await client.research('question','card')
        assert error.value.code == 'a2a_peer_mismatch'
    asyncio.run(run())
    assert len(requests) == 1 and requests[0].startswith('http://127.0.0.1:8011/')


def test_response_and_request_byte_limits(environment):
    store, _, _, token, _ = environment
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(store,'http://127.0.0.1:8011')),
                base_url='http://127.0.0.1:8011', headers=headers(token('author'))) as http:
            assert (await http.post('/a2a',content=b'x'*32769)).status_code == 413
        client = EvidenceClient('http://127.0.0.1:8011',token('author'),'a',
            httpx.MockTransport(lambda request: httpx.Response(200,content=b'x'*262145)))
        with pytest.raises(Problem) as error:
            await client.research('question','large')
        assert error.value.code == 'a2a_unavailable' or error.value.code == 'a2a_response_limit'
    asyncio.run(run())


def test_expired_token_is_rejected(environment):
    store, _, _, token, _ = environment
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(store,'http://127.0.0.1:8011')),
                base_url='http://127.0.0.1:8011', headers=headers(token('author', exp=int(time.time())-10))) as http:
            assert (await http.get('/.well-known/agent-card.json')).status_code == 401
    asyncio.run(run())
