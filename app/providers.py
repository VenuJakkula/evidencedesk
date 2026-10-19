"""Versioned provider contracts. Default implementations are offline fixtures, not neural models."""
import hashlib
import math
import re
from typing import Protocol, Literal
from pydantic import BaseModel, ConfigDict, Field
from .workbooks import Problem

class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=1000)
    chunk_id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=1000)

class ModelDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    applicability: str = Field(max_length=300)
    answer: str = Field(max_length=10000)
    claims: list[Claim] = Field(max_length=10)
    uncertainty: list[Literal['missing_evidence','conflicting_evidence','applicability_unspecified','provider_uncertainty']] = Field(max_length=10)

class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    def embed(self, texts: list[str], timeout: float) -> list[list[float]]: ...

class DraftProvider(Protocol):
    model: str
    def draft(self, question: str, chunks: list[dict], timeout: float) -> dict: ...


def checked_vectors(vectors, count, dimensions=64):
    if not isinstance(vectors,list) or len(vectors)!=count:
        raise Problem('invalid_embedding','Provider returned invalid embeddings.',502)
    for row in vectors:
        if not isinstance(row,list) or len(row)!=dimensions or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>1e30 for x in row) or not any(row):
            raise Problem('invalid_embedding','Provider returned invalid embeddings.',502)
    return vectors


class FixtureEmbedding:
    model = 'fixture-hash64-synonyms-v1'
    dimensions = 64
    # Tiny fixed synthetic dictionary supports reproducible ablation cases only.
    synonyms = {'ciphered':'encrypted','encryption':'encrypted','ciphering':'encrypted','transit':'transport','transport':'transport','storage':'rest'}
    def embed(self, texts, timeout):
        output=[]
        for text in texts:
            vector=[0.0]*64
            for word in re.findall(r'[a-z0-9]+',text.lower()):
                word=self.synonyms.get(word,word)
                slot=int.from_bytes(hashlib.sha256(word.encode()).digest()[:2],'big')%64
                vector[slot]+=1
            if not any(vector): vector[0]=1
            norm=math.sqrt(sum(value*value for value in vector))
            output.append([value/norm for value in vector])
        return output


class ExtractiveProvider:
    model='extractive-claims-v1'
    def draft(self, question, chunks, timeout):
        selected=chunks[:3]
        return {'applicability':'selected evidence','answer':'\n'.join(chunk['quote'] for chunk in selected),
                'claims':[{'text':chunk['quote'],'quote':chunk['quote'],'chunk_id':chunk['chunk_id']} for chunk in selected],
                'uncertainty':[] if selected else ['missing_evidence']}


class ScriptedProvider:
    """Deterministic adapter for malformed output, hallucination and failure tests."""
    model='scripted-fixture-v1'
    def __init__(self,response): self.response=response; self.calls=[]
    def draft(self,question,chunks,timeout):
        self.calls.append((question,chunks,timeout))
        if isinstance(self.response,Exception): raise self.response
        return self.response

class HTTPProvider:
    """Adapter for a trusted deployment-owned embedding/draft gateway, not an SDK-specific API."""
    dimensions=64
    def __init__(self,url,model,key='',allow_loopback=False):
        from urllib.parse import urlsplit
        parsed=urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or (parsed.scheme!='https' and not (allow_loopback and parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost','::1'})):
            raise Problem('provider_configuration','Use a trusted HTTPS gateway.',503)
        if not model or len(model)>200: raise Problem('provider_configuration','Configure a bounded model identity.',503)
        self.url,self.model,self.key=url.rstrip('/'),model,key
    def request(self,path,payload,timeout):
        import json
        from urllib.request import Request, build_opener
        from .access import NoRedirect
        headers={'Content-Type':'application/json'}
        if getattr(self,'idempotency_key',None): headers['Idempotency-Key']=self.idempotency_key
        if getattr(self,'max_output_tokens',None): payload={**payload,'budget':{'max_output_tokens':self.max_output_tokens}}
        if self.key: headers['Authorization']='Bearer '+self.key
        request=Request(self.url+path,data=json.dumps({'model':self.model,**payload}).encode(),headers=headers,method='POST')
        try:
            with build_opener(NoRedirect).open(request,timeout=min(timeout,10)) as response:
                data=response.read(1048577)
            if len(data)>1048576: raise ValueError('size')
            return json.loads(data)
        except Exception:
            raise Problem('provider_unavailable','Provider gateway failed; no retries or fallback.',503) from None
    def embed(self,texts,timeout):
        response=self.request('/embed',{'texts':texts},timeout)
        if not isinstance(response,dict) or set(response)!={'vectors'}:
            raise Problem('invalid_embedding','Provider returned invalid embeddings.',502)
        return response['vectors']
    def draft(self,question,chunks,timeout):
        return self.request('/draft',{'question':question,'evidence':chunks,'prompt_version':'extractive-claims-v1'},timeout)
