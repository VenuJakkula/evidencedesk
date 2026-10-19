import json
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from .questionnaires import Questionnaires
from .workbooks import Limits, Mapping, Problem, inspect


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=10000)
    expected_revision: int = Field(ge=1, strict=True)
    owner: str | None = Field(default=None, max_length=200)


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1, strict=True)
    reviewer: str = Field(default="", max_length=200)
    reason: str = Field(default='', max_length=1000)


class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=1,strict=True)


class Batch(BaseModel):
    limit: int = Field(default=100, ge=1, le=200, strict=True)


async def upload(request, required_mapping):
    """Cap the full HTTP body before multipart decoding or spooling."""
    limits = Limits.configured()
    maximum = limits.upload + 64 * 1024
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) > maximum:
                raise Problem('upload_too_large', 'Upload exceeds the configured request limit.', 413)
        except ValueError as exc:
            raise Problem('invalid_request', 'Invalid Content-Length.') from exc
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise Problem('upload_too_large', 'Upload exceeds the configured request limit.', 413)
        body.extend(chunk)
    request._body = bytes(body)
    try:
        async with request.form(max_files=1, max_fields=1, max_part_size=64 * 1024) as form:
            file = form.get('file')
            if not isinstance(file, UploadFile) or set(form) - {'file', 'mapping'}:
                raise Problem('invalid_upload', 'Send multipart file and optional mapping JSON fields.')
            value = form.get('mapping')
            mapping = Mapping.model_validate_json(value) if isinstance(value, str) else None
            if required_mapping and mapping is None:
                raise Problem('mapping_required', 'Confirm an explicit mapping before import.')
            data = await file.read(limits.upload + 1)
            return data, file.filename, mapping
    except (ValueError, ValidationError, HTTPException) as exc:
        raise Problem('invalid_upload', 'Invalid multipart upload or mapping; use the documented mapping schema.') from exc


def router(scope, store):
    routes = APIRouter()

    def service():
        return Questionnaires(store())

    @routes.get('/questionnaires/limits')
    def workbook_limits(tenant=Depends(scope)):
        return {'max_upload_bytes': Limits.configured().upload}

    @routes.post('/questionnaires/preview')
    async def preview(request: Request, tenant=Depends(scope)):
        data, filename, mapping = await upload(request, False)
        result = inspect(data, filename, mapping)
        result['rows'] = result['rows'][:100]
        result['preview_limit'] = 100
        return result

    @routes.post('/questionnaires', status_code=201)
    async def create(request: Request, idempotency_key: str = Header(default=''), tenant=Depends(scope)):
        data, filename, mapping = await upload(request, True)
        return service().create(tenant, data, filename, mapping, idempotency_key)

    @routes.get('/questionnaires')
    def listing(offset: int = 0, limit: int = 20, tenant=Depends(scope)):
        return service().list(tenant, offset, limit)

    @routes.get('/questionnaires/{identifier}')
    def get(identifier: str, tenant=Depends(scope)):
        return service().get(tenant, identifier)

    @routes.get('/questionnaires/{identifier}/items')
    def items(identifier: str, offset: int = 0, limit: int = 100, tenant=Depends(scope)):
        return service().items(tenant, identifier, offset, limit)

    @routes.post('/questionnaires/{identifier}/draft')
    def draft(identifier: str, body: Batch, tenant=Depends(scope)):
        return service().draft(tenant, identifier, body.limit)

    @routes.post('/questionnaire-items/{identifier}/redraft')
    def redraft(identifier: str, body: Revision, tenant=Depends(scope)):
        return service().redraft(tenant,identifier,body.expected_revision)

    @routes.get('/questionnaire-items/{identifier}')
    def item(identifier: str, tenant=Depends(scope)):
        return service().item(tenant, identifier)

    @routes.patch('/questionnaire-items/{identifier}/answer')
    def edit(identifier: str, body: Edit, tenant=Depends(scope)):
        return service().edit(tenant, identifier, **body.model_dump())

    @routes.post('/questionnaire-items/{identifier}/approve')
    def approve(identifier: str, body: Review, tenant=Depends(scope)):
        return service().approve(tenant, identifier, **body.model_dump())

    @routes.get('/questionnaires/{identifier}/exports/{export_id}')
    def export_summary(identifier: str, export_id: str, offset: int = 0, limit: int = 20, tenant=Depends(scope)):
        return service().export_summary(tenant, identifier, export_id, offset, limit)

    @routes.post('/questionnaires/{identifier}/export')
    def export(identifier: str, tenant=Depends(scope)):
        bundle, manifest = service().export_result(tenant, identifier)
        return Response(bundle, media_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename="questionnaire-export.zip"',
                                 'X-Export-ID': manifest['export_id'], 'Cache-Control': 'no-store'})

    return routes
