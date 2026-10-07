import hmac
import os
from functools import lru_cache
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .core import Store

app = FastAPI(title="EvidenceDesk", version="0.1.0", description="Local extractive prototype; live GenAI integration pending")
@lru_cache
def store():
    return Store(os.getenv("EVIDENCEDESK_DB", "evidencedesk.db"))
def tenant(x_api_key: str = Header(default="")):
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
    reviewer: str = Field(min_length=1, max_length=200)
    final: str = Field(min_length=1, max_length=10000)
@app.get("/health")
def health():
    return {"status": "ok", "mode": "extractive-baseline"}
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
