"""Ordinary scoped API adapter for retrieval ablations and draft previews."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .retrieval import configured

class Search(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    query:str=Field(min_length=1,max_length=5000)
    method:Literal['lexical','embedding','hybrid']='hybrid'
    limit:int=Field(ge=1,le=20,default=5)
    applicability:dict[str,str]=Field(default_factory=dict)
    rerank:bool=False

def router(tenant,store):
    api=APIRouter(prefix='/retrieval',tags=['Retrieval foundation'])
    @api.post('/search')
    def search(body:Search,scope=Depends(tenant)):
        return configured(store()).run(scope,body.query,body.method,body.limit,body.applicability,body.rerank)
    @api.post('/preview')
    def preview(body:Search,scope=Depends(tenant)):
        """Unpersisted author draft preview; no approval side effects."""
        return configured(store()).run(scope,body.query,body.method,body.limit,body.applicability,body.rerank,draft=True)
    return api
