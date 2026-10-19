"""A2A 1.0 evidence expert: scoped, read-only, bounded offline retrieval tasks."""
import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import RequestHandler
from a2a.server.routes.common import ServerCallContextBuilder
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.types import a2a_pb2 as p
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, TaskNotCancelableError, UnsupportedOperationError
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from .access import mode, verify, require
from .evidence import valid
from .retrieval import Foundation
from .retrieval_index import MemoryIndex
from .workbooks import Problem
from .observability import traced, TraceMiddleware


class Research(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=5000)
    method: str = Field(default='hybrid', pattern='^(lexical|embedding|hybrid)$')
    limit: int = Field(default=5, ge=1, le=20)
    applicability: dict[str, str] = Field(default_factory=dict)
    deadline_seconds: int = Field(default=10, ge=1, le=10)


def authenticate(store, token, tenant):
    if mode() != 'oidc':
        raise HTTPException(503, 'A2A requires OIDC')
    principal = verify(token, tenant)
    with store.connect() as db:
        require(db, principal, 'author')
    return principal


class Auth:
    def __init__(self, app, store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        authorization = headers.get(b'authorization', b'').decode('latin1')
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        tenant = headers.get(b'x-tenant-id', b'').decode('latin1')
        try:
            principal = authenticate(self.store, token, tenant)
        except (HTTPException, Problem) as error:
            status = error.status_code if isinstance(error, HTTPException) else error.status
            return await JSONResponse({'error': 'authentication_or_access_denied'}, status_code=status)(scope, receive, send)
        # Bound the entire HTTP body, including chunked requests, before SDK parsing.
        body = bytearray()
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            body.extend(event.get('body', b''))
            if len(body) > 32768:
                return await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
            if not event.get('more_body'):
                break
        scope.setdefault('state', {})['a2a_identity'] = (principal, token, tenant)
        sent = False
        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, send)


class Context(ServerCallContextBuilder):
    def build(self, request):
        principal, token, tenant = request.state.a2a_identity
        return ServerCallContext(tenant=tenant, state={'principal': principal, 'token': token, 'headers': {'a2a-version': request.headers.get('a2a-version', '')}})


class EvidenceHandler(RequestHandler):
    def __init__(self, store, researcher=None):
        self.store = store
        self.researcher = researcher or self.research
        self.running = {}
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS a2a_tasks (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                request_key TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL, deadline REAL NOT NULL,
                state INTEGER NOT NULL, result TEXT, failure TEXT,
                UNIQUE(tenant,issuer,subject,request_key))''')
            # A separate expert process owns this table. Never replay uncertain work.
            db.execute('UPDATE a2a_tasks SET state=?,failure=? WHERE state IN (?,?)',
                (p.TASK_STATE_FAILED, 'restart_interrupted', p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING))

    def identity(self, context, params=None):
        scope = context.state['principal']
        if params is not None and getattr(params, 'tenant', '') not in ('', str(scope)):
            raise InvalidParamsError('tenant_mismatch')
        # Fresh token verification and live membership on every operation.
        return authenticate(self.store, context.state['token'], str(scope))

    def row(self, scope, identifier):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM a2a_tasks WHERE id=? AND tenant=? AND issuer=? AND subject=?',
                (identifier, str(scope), scope.issuer, scope.subject)).fetchone()
        if not row:
            raise TaskNotFoundError()
        return dict(row)

    def task(self, scope, row):
        result = json.loads(row['result']) if row['result'] else None
        state, failure = row['state'], row['failure']
        with self.store.connect() as db:
            require(db, scope, 'author')
            if result and result['items'] and not valid(db, scope, result['items']):
                result, state, failure = None, p.TASK_STATE_FAILED, 'evidence_changed'
        task = p.Task(id=row['id'], context_id=row['id'], status=p.TaskStatus(state=state))
        if failure:
            task.status.message.CopyFrom(p.Message(message_id=uuid.uuid4().hex, role=p.ROLE_AGENT,
                parts=[p.Part(text=failure)]))
        if result:
            task.artifacts.append(p.Artifact(artifact_id=row['id'], name='authorized-evidence-v1',
                parts=[p.Part(text=json.dumps(result, separators=(',', ':')), media_type='application/json')]))
        return task

    @traced('tool')
    def research(self, scope, request):
        # Finite offline adapters only. No paid calls, remote embedding or arbitrary tools.
        return Foundation(self.store, MemoryIndex()).run(scope, request.query, request.method,
            request.limit, request.applicability)

    async def execute(self, identifier, token, tenant, request):
        try:
            scope = authenticate(self.store, token, tenant)
            with self.store.connect() as db:
                db.execute('UPDATE a2a_tasks SET state=? WHERE id=? AND state=?',
                    (p.TASK_STATE_WORKING, identifier, p.TASK_STATE_SUBMITTED))
            result = await asyncio.wait_for(asyncio.to_thread(self.researcher, scope, request), request.deadline_seconds)
            # Immutable results are snapshots; recheck current access before storing/exposing.
            authenticate(self.store, token, tenant)
            with self.store.connect() as db:
                if result['items'] and not valid(db, scope, result['items']):
                    raise Problem('evidence_changed', 'Evidence changed.', 409)
                db.execute('UPDATE a2a_tasks SET state=?,result=? WHERE id=? AND state=? AND deadline>?',
                    (p.TASK_STATE_COMPLETED, json.dumps(result), identifier, p.TASK_STATE_WORKING, time.time()))
                db.execute('UPDATE a2a_tasks SET state=?,failure=? WHERE id=? AND state=?',
                    (p.TASK_STATE_FAILED, 'expert_deadline', identifier, p.TASK_STATE_WORKING))
        except asyncio.CancelledError:
            self.fail(identifier, 'cancelled', p.TASK_STATE_CANCELED)
            raise
        except (TimeoutError, Problem, HTTPException) as error:
            self.fail(identifier, error.code if isinstance(error, Problem) else 'expert_deadline' if isinstance(error, TimeoutError) else 'access_changed')
        except Exception:
            self.fail(identifier, 'expert_unavailable')
        finally:
            self.running.pop(identifier, None)

    def fail(self, identifier, reason, state=p.TASK_STATE_FAILED):
        with self.store.connect() as db:
            db.execute('UPDATE a2a_tasks SET state=?,result=NULL,failure=? WHERE id=? AND state IN (?,?)',
                (state, reason, identifier, p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING))

    async def on_message_send(self, params, context):
        scope = self.identity(context, params)
        message = params.message
        if (message.task_id or message.context_id or len(message.parts) != 1 or
                message.role != p.ROLE_USER or message.parts[0].WhichOneof('content') != 'text' or
                not 1 <= len(message.message_id) <= 100 or params.HasField('metadata') or
                params.configuration.HasField('task_push_notification_config')):
            raise InvalidParamsError('bounded_new_research_required')
        try:
            request = Research.model_validate_json(message.parts[0].text)
            if set(request.applicability) - {'product', 'edition', 'deployment'} or any(not v or len(v)>300 for v in request.applicability.values()):
                raise ValueError()
        except Exception:
            raise InvalidParamsError('invalid_research') from None
        payload = request.model_dump_json()
        identifier = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM a2a_tasks WHERE tenant=? AND issuer=? AND subject=? AND request_key=?',
                (str(scope), scope.issuer, scope.subject, message.message_id)).fetchone()
            if previous:
                if previous['payload'] != payload:
                    raise InvalidParamsError('request_key_conflict')
                identifier = previous['id']
            else:
                count = db.execute('SELECT COUNT(*) FROM a2a_tasks').fetchone()[0]
                active = db.execute('SELECT COUNT(*) FROM a2a_tasks WHERE state IN (?,?)', (p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING)).fetchone()[0]
                if count >= 1000 or active >= 8:
                    raise InvalidParamsError('expert_capacity')
                db.execute('INSERT INTO a2a_tasks VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)',
                    (identifier, str(scope), scope.issuer, scope.subject, message.message_id, payload,
                        time.time(), time.time()+request.deadline_seconds, p.TASK_STATE_SUBMITTED))
        if not previous:
            self.running[identifier] = asyncio.create_task(self.execute(identifier, context.state['token'], str(scope), request))
        if not params.configuration.return_immediately and identifier in self.running:
            await asyncio.shield(self.running[identifier])
        return self.task(scope, self.row(scope, identifier))

    async def on_get_task(self, params, context):
        scope = self.identity(context, params)
        return self.task(scope, self.row(scope, params.id))

    async def on_cancel_task(self, params, context):
        scope = self.identity(context, params)
        row = self.row(scope, params.id)
        if row['state'] == p.TASK_STATE_CANCELED:
            return self.task(scope, row)
        if row['state'] not in (p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING):
            raise TaskNotCancelableError()
        self.fail(params.id, 'cancelled', p.TASK_STATE_CANCELED)
        if params.id in self.running:
            self.running[params.id].cancel()
        return self.task(scope, self.row(scope, params.id))

    async def unsupported(self, *args, **kwargs):
        raise UnsupportedOperationError()

    on_list_tasks = unsupported
    on_message_send_stream = unsupported
    on_create_task_push_notification_config = unsupported
    on_get_task_push_notification_config = unsupported
    on_subscribe_to_task = unsupported
    on_list_task_push_notification_configs = unsupported
    on_delete_task_push_notification_config = unsupported
    on_get_extended_agent_card = unsupported


def build_app(store, public_url, researcher=None):
    handler = EvidenceHandler(store, researcher)
    card = p.AgentCard(name='EvidenceDesk evidence expert', version='1.0.0',
        description='Read-only scoped evidence research. No approval or export.',
        supported_interfaces=[p.AgentInterface(url=public_url.rstrip('/')+'/a2a', protocol_binding='JSONRPC', protocol_version='1.0')],
        capabilities=p.AgentCapabilities(), default_input_modes=['application/json'], default_output_modes=['application/json'],
        skills=[p.AgentSkill(id='evidence-research', name='Evidence research', description='Return authorized current evidence with exact provenance.', tags=['evidence'])],
        security_schemes={'oidc': p.SecurityScheme(http_auth_security_scheme=p.HTTPAuthSecurityScheme(scheme='Bearer', bearer_format='JWT'))},
        security_requirements=[p.SecurityRequirement(schemes={'oidc': p.StringList()})])
    @asynccontextmanager
    async def lifespan(app):
        yield
        active = list(handler.running.values())
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
    app = Starlette(routes=create_agent_card_routes(card)+create_jsonrpc_routes(handler, '/a2a', Context()), lifespan=lifespan)
    app.state.expert = handler
    return TraceMiddleware(Auth(app, store))


def main():
    import logging
    import os
    import uvicorn
    from .core import Store
    # Never log request payloads, tokens or SDK trace exceptions in the standalone service.
    logging.disable(logging.CRITICAL)
    port = int(os.getenv('EVIDENCEDESK_A2A_PORT', '8011'))
    url = os.getenv('EVIDENCEDESK_A2A_PUBLIC_URL', f'http://127.0.0.1:{port}')
    uvicorn.run(build_app(Store(os.getenv('EVIDENCEDESK_DB', 'evidencedesk.db')), url), host='127.0.0.1', port=port, access_log=False)


if __name__ == '__main__':
    main()
