"""Independent questionnaire-agent HTTP service; uses primary durable workflow/review policy."""
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from .a2a_expert import authenticate
from .a2a_client import RemoteFoundation, trusted_peer
from .workflow_api import Start
from .workflows import Workflows
from .workbooks import Problem


def build_app(store, expert_url):
    expert_url = trusted_peer(expert_url)
    app = FastAPI(title='EvidenceDesk A2A questionnaire agent')

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse({'error': {'code': error.code, 'message': error.message}}, status_code=error.status)

    def service(request):
        authorization = request.headers.get('authorization', '')
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        tenant = request.headers.get('x-tenant-id', '')
        scope = authenticate(store, token, tenant)
        return scope, Workflows(store, RemoteFoundation(store, expert_url, token, tenant))

    @app.post('/workflow-jobs')
    def create(body: Start, request: Request):
        scope, workflow = service(request)
        return workflow.create(scope, body.item_id, body.expected_revision, body.request_key, body.options.model_dump())

    @app.get('/workflow-jobs/{identifier}')
    def get(identifier: str, request: Request):
        scope, workflow = service(request)
        return workflow.get(scope, identifier)

    @app.post('/workflow-jobs/{identifier}/advance')
    def advance(identifier: str, request: Request):
        scope, workflow = service(request)
        return workflow.advance(scope, identifier)

    @app.post('/workflow-jobs/{identifier}/cancel')
    def cancel(identifier: str, request: Request):
        scope, workflow = service(request)
        return workflow.cancel(scope, identifier)

    return app


def main():
    import logging
    import uvicorn
    from .core import Store
    logging.disable(logging.CRITICAL)
    url = os.getenv('EVIDENCEDESK_A2A_EXPERT_URL', 'http://127.0.0.1:8011')
    port = int(os.getenv('EVIDENCEDESK_A2A_QUESTIONNAIRE_PORT', '8012'))
    uvicorn.run(build_app(Store(os.getenv('EVIDENCEDESK_DB', 'evidencedesk.db')), url), host='127.0.0.1', port=port, access_log=False)


if __name__ == '__main__':
    main()
