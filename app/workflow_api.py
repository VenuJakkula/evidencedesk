"""Verified-author workflow controls. No approval mutation is exposed here."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from .workflows import Workflows, Options

class Start(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    item_id:str=Field(min_length=1,max_length=100)
    expected_revision:int=Field(ge=0)
    request_key:str=Field(min_length=1,max_length=100)
    options:Options=Field(default_factory=Options)

def router(tenant,store):
    api=APIRouter(prefix='/workflow-jobs',tags=['Bounded drafting workflow'])
    @api.post('')
    def create(body:Start,scope=Depends(tenant)):
        return Workflows(store()).create(scope,body.item_id,body.expected_revision,body.request_key,body.options.model_dump())
    @api.get('')
    def listing(item_id:str=Query(min_length=1,max_length=100),limit:int=Query(default=5,ge=1,le=20),scope=Depends(tenant)):
        return Workflows(store()).list(scope,item_id,limit)
    @api.get('/{identifier}')
    def get(identifier:str,scope=Depends(tenant)):
        return Workflows(store()).get(scope,identifier)
    @api.post('/{identifier}/advance')
    def advance(identifier:str,scope=Depends(tenant)):
        return Workflows(store()).advance(scope,identifier)
    @api.post('/{identifier}/cancel')
    def cancel(identifier:str,scope=Depends(tenant)):
        return Workflows(store()).cancel(scope,identifier)
    return api
