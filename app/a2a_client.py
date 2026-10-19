"""Official A2A SDK client with fixed peer, bounded retries and provenance validation."""
import asyncio
import ipaddress
import json
import os
import time
from urllib.parse import urlsplit

import httpx
from a2a.client.errors import A2AClientError
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import a2a_pb2 as p
from .access import verify, require
from .evidence import valid
from .retrieval import Foundation, fingerprint
from .retrieval_index import MemoryIndex
from .workbooks import Problem


def trusted_peer(url):
    parsed = urlsplit(url)
    local = False
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or (parsed.scheme != 'https' and not
            (parsed.scheme == 'http' and local and os.getenv('EVIDENCEDESK_DEPLOYMENT', 'local') == 'local'))):
        raise Problem('a2a_peer_configuration', 'Configure one trusted HTTPS peer origin, or local loopback HTTP.', 503)
    return url.rstrip('/')


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner=None):
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        body = bytearray()
        try:
            if response.headers.get('content-encoding', 'identity') != 'identity':
                raise Problem('a2a_encoding', 'Compressed expert responses are not accepted.', 502)
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 262144:
                    raise Problem('a2a_response_limit', 'Expert response exceeded the artifact budget.', 502)
            return httpx.Response(response.status_code, headers=response.headers, content=bytes(body), request=request)
        finally:
            await response.aclose()

    async def aclose(self):
        await self.inner.aclose()


class EvidenceClient:
    def __init__(self, url, token, tenant, transport=None):
        self.url, self.token, self.tenant = trusted_peer(url), token, tenant
        self.transport = transport

    async def research(self, query, key, *, method='hybrid', limit=5, applicability=None, timeout=12, cancel_event=None):
        if not 0 < timeout <= 15:
            raise Problem('a2a_deadline', 'Use a bounded client deadline.')
        request = p.SendMessageRequest(tenant=self.tenant,
            message=p.Message(message_id=key, role=p.ROLE_USER, parts=[p.Part(text=json.dumps({
                'query': query, 'method': method, 'limit': limit, 'applicability': applicability or {}, 'deadline_seconds': min(10, max(1, int(timeout)-1))}))]),
            configuration=p.SendMessageConfiguration(return_immediately=True, accepted_output_modes=['application/json']))
        deadline = time.monotonic()+timeout
        task_id = None
        async with httpx.AsyncClient(transport=BoundedTransport(self.transport), follow_redirects=False,
                timeout=min(3, timeout), headers={'Authorization': 'Bearer '+self.token,
                    'X-Tenant-ID': self.tenant, 'A2A-Version': '1.0', 'Accept-Encoding': 'identity'}) as http:
            rpc = None
            async def call(operation):
                # At most two transport attempts; identical message ID makes submission safe to retry.
                for attempt in range(2):
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    try:
                        return await asyncio.wait_for(operation(), max(.001, deadline-time.monotonic()))
                    except (httpx.TransportError, httpx.HTTPStatusError, A2AClientError) as error:
                        causes = []
                        cause = error
                        while cause is not None and cause not in causes:
                            causes.append(cause)
                            cause = cause.__cause__ or cause.__context__
                        retryable = any(isinstance(c, httpx.TransportError) or
                            (isinstance(c, httpx.HTTPStatusError) and c.response.status_code >= 500) for c in causes)
                        if attempt or not retryable:
                            raise
            try:
                card = await call(lambda: A2ACardResolver(http, self.url).get_agent_card())
                # Discovery cannot redirect credentials or change the operator's configured peer.
                if not any(i.url == self.url+'/a2a' and i.protocol_binding == 'JSONRPC' and i.protocol_version == '1.0' for i in card.supported_interfaces):
                    raise Problem('a2a_peer_mismatch', 'Expert card does not match the configured A2A 1.0 endpoint.', 502)
                rpc = JsonRpcTransport(http, card, self.url+'/a2a')
                response = await call(lambda: rpc.send_message(request))
                if not response.HasField('task') or not response.task.id:
                    raise Problem('a2a_invalid_task', 'Expert did not return a task.', 502)
                task = response.task
                task_id = task.id
                while task.status.state in (p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING):
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError
                    await asyncio.sleep(.05)
                    task = await call(lambda: rpc.get_task(p.GetTaskRequest(id=task_id, tenant=self.tenant)))
                    if task.id != task_id:
                        raise Problem('a2a_invalid_task', 'Expert returned a different task.', 502)
                if task.status.state != p.TASK_STATE_COMPLETED:
                    raise Problem('a2a_task_failed', 'Expert task did not complete successfully.', 503)
                if len(task.artifacts) != 1 or len(task.artifacts[0].parts) != 1 or task.artifacts[0].name != 'authorized-evidence-v1':
                    raise Problem('a2a_invalid_artifact', 'Expert artifact schema is invalid.', 502)
                result = json.loads(task.artifacts[0].parts[0].text)
                return {**result, 'a2a_task_id': task_id}
            except (TimeoutError, asyncio.CancelledError):
                if rpc and task_id:
                    try:
                        await asyncio.wait_for(rpc.cancel_task(p.CancelTaskRequest(id=task_id, tenant=self.tenant)), 1)
                    except Exception:
                        pass
                raise
            except Problem:
                raise
            except Exception:
                raise Problem('a2a_unavailable', 'Expert unavailable or returned an invalid protocol response.', 503) from None


class RemoteFoundation(Foundation):
    """Inject into the primary LangGraph workflow; credentials stay in process memory."""
    def __init__(self, store, url, token, tenant):
        super().__init__(store, MemoryIndex())
        self.a2a_url, self.token, self.tenant = trusted_peer(url), token, tenant
        self.call_key = None

    def run(self, scope, question, method='hybrid', limit=5, applicability=None, rerank=False, draft=False):
        if draft or rerank:
            raise Problem('a2a_retrieval_only', 'Remote adapter supports evidence retrieval only.')
        identity = verify(self.token, self.tenant)
        if (str(scope), scope.issuer, scope.subject) != (str(identity), identity.issuer, identity.subject):
            raise Problem('a2a_identity_mismatch', 'Workflow requires the originating author token.', 403)
        applicability = applicability or {}
        with self.store.connect() as db:
            chunks = self.authorized(db, scope, applicability)
        expected = getattr(self.embedding, 'expected', None)
        if expected and fingerprint([c['quote'] for c in chunks]+[question]) != expected:
            raise Problem('evidence_changed', 'Authorized corpus changed before remote research.', 409)
        key = self.call_key or fingerprint([question, method, limit, applicability, [c['chunk_id'] for c in chunks]])
        try:
            result = asyncio.run(EvidenceClient(self.a2a_url, self.token, self.tenant).research(
                question, key, method=method, limit=limit, applicability=applicability))
        except TimeoutError:
            raise Problem('a2a_deadline', 'Evidence expert deadline exhausted.', 504) from None
        return self.validate_remote(scope, result, applicability, limit)

    def validate_remote(self, scope, result, applicability, limit):
        try:
            hits = result['items']
            if not isinstance(hits, list) or len(hits)>limit or len({h['chunk_id'] for h in hits}) != len(hits):
                raise ValueError()
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                require(db, scope, 'author')
                allowed = {c['chunk_id']:c for c in self.authorized(db, scope, applicability)}
                if any(allowed.get(h['chunk_id']) != h for h in hits) or (hits and not valid(db, scope, hits)):
                    raise ValueError()
            return {'items': hits, 'trace': {'retrieval': 'a2a', 'a2a_task_id': result['a2a_task_id'],
                'candidates': len(allowed), 'provider_calls': 0, 'profile': self.profile}}
        except (KeyError, TypeError, ValueError):
            raise Problem('a2a_invalid_provenance', 'Expert evidence failed authoritative provenance verification.', 502) from None
