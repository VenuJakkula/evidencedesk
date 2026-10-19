import hmac
import os
import secrets
import ipaddress
import threading
from functools import lru_cache
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .core import Store
from .workbooks import Problem
from .questionnaire_api import router
from .evidence_api import router as evidence_router
from .access import Principal, actor, mode, require, roles, verify
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler

app = FastAPI(title="EvidenceDesk", version="0.1.0", description="Local extractive prototype; live GenAI integration pending")
from .observability import TraceMiddleware
app.add_middleware(TraceMiddleware)
local_key_lock = threading.Lock()
@lru_cache
def store():
    return Store(os.getenv("EVIDENCEDESK_DB", "evidencedesk.db"))
def tenant(x_api_key: str = Header(default=""), authorization: str = Header(default=""), x_tenant_id: str = Header(default="")):
    if mode()=='oidc':
        if not authorization.startswith('Bearer '):
            raise HTTPException(401,'Use a verified bearer access token')
        scope=verify(authorization[7:],x_tenant_id or os.getenv('EVIDENCEDESK_TENANT','demo'))
        with store().connect() as db:
            require(db,scope)
        return scope
    secret = os.getenv("EVIDENCEDESK_API_KEY", "")
    if not secret:
        raise HTTPException(503, "Configure EVIDENCEDESK_API_KEY before use")
    if not hmac.compare_digest(x_api_key.encode(), secret.encode()):
        raise HTTPException(401, "Invalid API key")
    return os.getenv("EVIDENCEDESK_TENANT", "demo")
class Document(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100000)
    version: str = Field(min_length=1, max_length=100)
    valid_until: str
class Question(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
class Approval(BaseModel):
    reviewer: str = Field(default="", max_length=200)
    final: str = Field(min_length=1, max_length=10000)
@app.get("/health")
def health():
    return {"status": "ok", "mode": "extractive-baseline"}

@app.get('/ready')
def ready():
    """Generic readiness; never disclose database paths, identities or key material."""
    try:
        mode()
        if mode() == 'local' and not os.getenv('EVIDENCEDESK_API_KEY'):
            raise ValueError('unconfigured')
        if mode() == 'oidc':
            from .access import public_keys
            if not os.getenv('EVIDENCEDESK_OIDC_ISSUER') or not os.getenv('EVIDENCEDESK_OIDC_AUDIENCE'):
                raise ValueError('unconfigured')
            public_keys()
        with store().connect() as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise ValueError('database')
        return {'status': 'ready'}
    except Exception:
        return JSONResponse({'status': 'not_ready'}, status_code=503)

@app.get('/session', tags=['Connection'])
def session(scope=Depends(tenant)):
    """Authenticated, read-only connection check; does not access the database."""
    if isinstance(scope,Principal):
        with store().connect() as db:
            current=roles(db,scope)
        return {'tenant':str(scope),'mode':'extractive-baseline','authentication':'oidc','subject':scope.subject,'issuer':scope.issuer,'roles':sorted(current),'identity_verified':True}
    return {'tenant': scope, 'mode': 'extractive-baseline', 'authentication': 'local-api-key'}

@app.post('/local/api-key', tags=['Local development'])
def recover_local_key(request: Request, x_local_key_recovery: str = Header(default='')):
    """Rotate the process-local API key. Explicitly opt in on a loopback-only server."""
    if mode() != 'local' or os.getenv('EVIDENCEDESK_ALLOW_LOCAL_KEY_RECOVERY') != '1':
        raise HTTPException(404, 'Local key recovery is disabled')
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local or request.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise HTTPException(403, 'Local key recovery requires a direct loopback connection')
    if any(header in request.headers for header in ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto')):
        raise HTTPException(403, 'Local key recovery cannot be used through a proxy')
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
        raise HTTPException(403, 'Cross-origin key recovery is forbidden')
    if x_local_key_recovery != 'true':
        raise HTTPException(403, 'Set X-Local-Key-Recovery: true to rotate the local key')
    key = secrets.token_urlsafe(32)
    os.environ['EVIDENCEDESK_API_KEY'] = key
    return JSONResponse({'api_key': key, 'header': 'X-API-Key', 'tenant': os.getenv('EVIDENCEDESK_TENANT', 'demo'),
                         'previous_key_revoked': True, 'scope': 'current server process; resets on restart'},
                        headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})

@app.post('/local/session-key', tags=['Local development'])
def local_session_key(request: Request, x_local_session: str = Header(default='')):
    """Opt-in direct-loopback bootstrap for the development frontend; never rotates a key."""
    if mode() != 'local' or os.getenv('EVIDENCEDESK_ALLOW_LOCAL_FRONTEND') != '1':
        raise HTTPException(404, 'Automatic local frontend connection is disabled')
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local or request.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise HTTPException(403, 'Automatic connection requires a direct loopback connection')
    if any(header in request.headers for header in ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto')):
        raise HTTPException(403, 'Automatic connection cannot use the ordinary API proxy')
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
        raise HTTPException(403, 'Cross-origin bootstrap is forbidden')
    if x_local_session != 'true':
        raise HTTPException(403, 'Explicit local session header is required')
    with local_key_lock:
        key = os.getenv('EVIDENCEDESK_API_KEY')
        if not key:
            key = secrets.token_urlsafe(32)
            os.environ['EVIDENCEDESK_API_KEY'] = key
    return JSONResponse({'api_key': key}, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
@app.post("/documents", status_code=201)
def add_document(body: Document, scope=Depends(tenant)):
    try:
        return {"id": store().add_document(scope, **body.model_dump())}
    except ValueError as exc:
        raise HTTPException(422, "valid_until must be a valid ISO date") from exc
@app.post("/answers", status_code=201)
def draft(body: Question, scope=Depends(tenant)):
    return store().draft(scope, body.question)
@app.get("/answers/{identifier}")
def get(identifier: str, scope=Depends(tenant)):
    try:
        return store().get(scope, identifier)
    except KeyError as exc:
        raise HTTPException(404, "Answer not found") from exc
@app.post("/answers/{identifier}/approve")
def approve(identifier: str, body: Approval, scope=Depends(tenant)):
    try:
        return store().approve(scope, identifier, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
@app.get("/export")
def export(scope=Depends(tenant)):
    return Response(store().export(scope), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="approved-answers.csv"'})

@app.exception_handler(Problem)
async def workbook_problem(request, exc):
    return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})

@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={'error': {'code': 'invalid_request', 'message': 'Request fields do not match the documented schema.'}})

app.include_router(router(tenant, store))
app.include_router(evidence_router(tenant,store))

@app.exception_handler(StarletteHTTPException)
async def http_problem(request, exc):
    if request.url.path.startswith(('/questionnaires', '/questionnaire-items')):
        code = {401: 'unauthorized', 404: 'not_found', 503: 'auth_unconfigured'}.get(exc.status_code, 'http_error')
        return JSONResponse(status_code=exc.status_code, content={'error': {'code': code, 'message': str(exc.detail)}})
    return await http_exception_handler(request, exc)

from .retrieval_api import router as retrieval_router
app.include_router(retrieval_router(tenant,store))

from .workflow_api import router as workflow_router
app.include_router(workflow_router(tenant,store))
