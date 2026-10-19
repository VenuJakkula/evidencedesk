"""Authenticated evidence lifecycle routes; only bounded UTF-8 text uploads are parsed."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile
from .evidence import Evidence
from .workbooks import Problem, safe_filename

class TextVersion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str=Field(min_length=1,max_length=300)
    content: str=Field(min_length=1,max_length=100000)
    version: str=Field(min_length=1,max_length=100)
    valid_until: str
    metadata: dict[str,str]=Field(default_factory=dict)
class NextVersion(TextVersion):
    title: str=''
    expected_version: str
class VersionReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version_id: str
class Grant(BaseModel):
    model_config=ConfigDict(extra='forbid')
    subject: str=Field(min_length=1,max_length=200)
    can_write: bool=False
class Member(BaseModel):
    model_config=ConfigDict(extra='forbid')
    roles: list[Literal['author','reviewer','admin']]=Field(min_length=1,max_length=3)
    active: bool=True


class NamedMember(Member):
    subject:str=Field(min_length=1,max_length=200)


def router(scope,store):
    routes=APIRouter()
    def service():
        return Evidence(store())
    @routes.get('/evidence')
    def listing(offset:int=0,limit:int=20,tenant=Depends(scope)):
        return service().list(tenant,offset,limit)
    @routes.post('/evidence',status_code=201)
    def create(body:TextVersion,tenant=Depends(scope)):
        return service().create(tenant,**body.model_dump())
    @routes.post('/evidence/upload',status_code=201)
    async def upload(request:Request,tenant=Depends(scope)):
        maximum=200000
        data=bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>maximum:
                raise Problem('upload_too_large','Text evidence upload exceeds 200000 request bytes.',413)
            data.extend(chunk)
        request._body=bytes(data)
        try:
            async with request.form(max_files=1,max_fields=1,max_part_size=16384) as form:
                file=form.get('file')
                if not isinstance(file,UploadFile) or set(form)!={'file','metadata'} or not file.filename.lower().endswith('.txt'):
                    raise ValueError('UTF-8 .txt required')
                raw=await file.read(100001)
                if len(raw)>100000:
                    raise Problem('upload_too_large','Text evidence exceeds 100000 UTF-8 bytes.',413)
                content=raw.decode('utf-8-sig')
                fields=json.loads(form['metadata'])
                filename=(file.filename or '').replace('\\','/').split('/')[-1][:150]
                fields['content']=content
                fields.setdefault('metadata',{})['filename']=filename
                body=TextVersion.model_validate(fields)
                return service().create(tenant,**body.model_dump())
        except Problem:
            raise
        except Exception as exc:
            raise Problem('invalid_upload','Send a UTF-8 .txt file and metadata JSON (title, version, valid_until, metadata).') from exc
    @routes.post('/evidence/expire')
    def expire(tenant=Depends(scope)):
        return service().expire(tenant)
    @routes.get('/evidence/{identifier}')
    def get(identifier:str,tenant=Depends(scope)):
        return service().get(tenant,identifier)
    @routes.post('/evidence/{identifier}/versions',status_code=201)
    def version(identifier:str,body:NextVersion,tenant=Depends(scope)):
        fields=body.model_dump(); fields.pop('title')
        return service().version(tenant,identifier,**fields)
    @routes.post('/evidence/{identifier}/approve')
    def approve(identifier:str,body:VersionReview,tenant=Depends(scope)):
        return service().approve(tenant,identifier,body.version_id)
    @routes.post('/evidence/{identifier}/revoke')
    def revoke(identifier:str,tenant=Depends(scope)):
        return service().revoke(tenant,identifier)
    @routes.delete('/evidence/{identifier}')
    def delete(identifier:str,tenant=Depends(scope)):
        return service().revoke(tenant,identifier,True)
    @routes.put('/evidence/{identifier}/acl')
    def grant(identifier:str,body:Grant,tenant=Depends(scope)):
        return service().acl(tenant,identifier,body.subject,body.can_write)
    @routes.delete('/evidence/{identifier}/acl')
    def revoke_acl_body(identifier:str,body:Grant,tenant=Depends(scope)):
        return service().acl(tenant,identifier,body.subject,remove=True)
    @routes.put('/memberships')
    def member_body(body:NamedMember,tenant=Depends(scope)):
        return service().membership(tenant,body.subject,body.roles,body.active)
    @routes.delete('/evidence/{identifier}/acl/{subject}')
    def revoke_acl(identifier:str,subject:str,tenant=Depends(scope)):
        return service().acl(tenant,identifier,subject,remove=True)
    @routes.put('/memberships/{subject}')
    def member(subject:str,body:Member,tenant=Depends(scope)):
        return service().membership(tenant,subject,body.roles,body.active)
    @routes.get('/audit')
    def audit(offset:int=0,limit:int=20,tenant=Depends(scope)):
        from .access import require
        if offset<0 or not 1<=limit<=100:
            raise Problem('invalid_pagination','Use nonnegative offset and limit 1-100.')
        with store().connect() as db:
            require(db,tenant,'admin')
            rows=db.execute('SELECT * FROM audit_events WHERE tenant=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(str(tenant),limit,offset)).fetchall()
            total=db.execute('SELECT COUNT(*) FROM audit_events WHERE tenant=?',(str(tenant),)).fetchone()[0]
            return {'items':[{**dict(row),'details':json.loads(row['details'])} for row in rows],'total':total,'offset':offset,'limit':limit,'next_offset':offset+len(rows) if offset+len(rows)<total else None}
    return routes
