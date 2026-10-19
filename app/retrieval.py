"""Bounded, authorized retrieval and extractive structured draft foundation (T09)."""
import hashlib
import json
import os
import re
import time
from datetime import date
from .access import Principal, require
from .evidence import global_valid, synchronize_expiry
from .providers import FixtureEmbedding, ExtractiveProvider, ModelDraft, checked_vectors
from .retrieval_index import MemoryIndex, PostgresIndex
from .workbooks import Problem
from .observability import traced

CHUNKING='lines-exact-1000-v1'
PROMPT='extractive-claims-v1'
from .scoped_cache import ScopedCache
_cache=ScopedCache()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def chunk_version(row,profile):
    chunks=[]; section=None
    content=row['content']
    metadata=json.loads(row['metadata'])
    for line in re.finditer(r'[^\n]+',content):
        if line.group().lstrip().startswith('#'):
            section=line.group().strip('# \t\r')[:300]
        for start in range(line.start(),line.end(),1000):
            end=min(start+1000,line.end())
            while start<end and content[start].isspace(): start+=1
            while end>start and content[end-1].isspace(): end-=1
            if start==end: continue
            chunk={'document_id':row['id'],'version_id':row['id'],'source_id':row['source_id'],
                'content_hash':row['content_hash'],'version':row['label'],'title':row['title'],
                'quote':content[start:end], 'start':start,'end':end,
                'line':content.count('\n',0,start)+1,'page':None,'section':section,'metadata':metadata}
            chunk['chunk_id']=fingerprint([row['tenant'],row['id'],row['content_hash'],start,end,profile])
            chunks.append(chunk)
    return chunks


class Foundation:
    def __init__(self,store,index,embedding=None,provider=None,clock=time.monotonic,cache=None):
        self.store,self.index=store,index
        self.embedding=embedding or FixtureEmbedding()
        self.provider=provider or ExtractiveProvider()
        self.clock=clock
        self.cache=cache
        if self.embedding.dimensions!=64: raise Problem('embedding_space','This schema requires 64-dimensional embeddings.',503)
        self.profile=fingerprint([self.embedding.model,self.embedding.dimensions,CHUNKING])

    def remaining(self,deadline):
        value=deadline-self.clock()
        if value<=0: raise Problem('retrieval_deadline','Retrieval/model deadline exceeded.',504)
        return value

    def authorized(self,db,scope,applicability):
        current=require(db,scope)
        if not isinstance(scope,Principal): raise Problem('verified_identity_required','Foundation retrieval requires OIDC identity.',403)
        synchronize_expiry(db,scope)
        clause='' if 'admin' in current else ' AND EXISTS(SELECT 1 FROM document_acl a WHERE a.tenant=v.tenant AND a.source_id=v.source_id AND a.issuer=? AND a.subject=?)'
        params=[str(scope),date.today().isoformat()]+([] if 'admin' in current else [scope.issuer,scope.subject])
        rows=db.execute('''SELECT v.*,s.title FROM evidence_versions v
            JOIN evidence_sources s ON s.tenant=v.tenant AND s.id=v.source_id
            JOIN evidence_states st ON st.tenant=v.tenant AND st.version_id=v.id
            WHERE v.tenant=? AND v.valid_until>=? AND s.deleted=0 AND s.current_version=v.id AND st.state='approved' '''+clause+' ORDER BY v.id',params)
        chunks=[]; versions=0; size=0
        for row in rows:
            metadata=json.loads(row['metadata'])
            if any(metadata.get(key)!=value for key,value in applicability.items()): continue
            # Validate reviewer authority and actual hash before exposing any content.
            probe={'document_id':row['id'],'version_id':row['id'],'source_id':row['source_id'],'version':row['label'],'content_hash':row['content_hash'],'quote':row['content'][:1]}
            if not global_valid(db,scope,probe): continue
            versions+=1; size+=len(row['content'])
            if versions>100 or size>200000:
                raise Problem('corpus_budget','Narrow applicability; authorized corpus exceeds this foundation budget.',413)
            chunks.extend(chunk_version(row,self.profile))
            if len(chunks)>500: raise Problem('corpus_budget','Authorized corpus exceeds 500 chunks.',413)
        return chunks

    @traced('retrieval')
    def run(self,scope,question,method='hybrid',limit=5,applicability=None,rerank=False,draft=False):
        if not isinstance(question,str) or not question.strip() or len(question)>5000 or method not in {'lexical','embedding','hybrid'} or type(limit)!=int or not 1<=limit<=20 or type(rerank)!=bool:
            raise Problem('invalid_retrieval','Use a bounded query, method and limit.')
        if applicability is None: applicability={}
        if not isinstance(applicability,dict) or set(applicability)-{'product','edition','deployment'} or any(not isinstance(value,str) or not value or len(value)>300 for value in applicability.values()):
            raise Problem('invalid_applicability','Use bounded exact product, edition and deployment filters.')
        if any(not (c in '\t\n\r' or 0x20<=ord(c)<=0xD7FF or 0xE000<=ord(c)<=0xFFFD or 0x10000<=ord(c)<=0x10FFFF) for c in question):
            raise Problem('invalid_retrieval','Use valid Unicode text without control characters.')
        deadline=self.clock()+20
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if draft: require(db,scope,'author')
                chunks=self.authorized(db,scope,applicability)
                corpus=fingerprint([chunk['chunk_id'] for chunk in chunks])
                cache_key=fingerprint([str(self.store.path),str(scope),scope.issuer,scope.subject,corpus,self.profile,
                    PROMPT,self.provider.model,question,method,limit,applicability,rerank])
                cached=self.cache.get(cache_key) if self.cache is not None else None
                hits=[]
                if cached is not None:
                    allowed={chunk['chunk_id']:chunk for chunk in chunks}
                    if any(identifier not in allowed for identifier in cached):
                        raise Problem('invalid_cache','Cached evidence failed authorization.',502)
                    hits=[allowed[identifier] for identifier in cached]
                elif chunks:
                    vectors=checked_vectors(self.embedding.embed([chunk['quote'] for chunk in chunks]+[question],self.remaining(deadline)),len(chunks)+1)
                    self.remaining(deadline)
                    self.index.replace(str(scope),corpus,self.profile,chunks,vectors[:-1])
                    self.remaining(deadline)
                    ids=self.index.search(str(scope),corpus,self.profile,question,vectors[-1],min(limit*2,20) if rerank else limit,method)
                    allowed={chunk['chunk_id']:chunk for chunk in chunks}
                    if len(ids)!=len(set(ids)) or len(ids)>20 or any(identifier not in allowed for identifier in ids):
                        raise Problem('invalid_index_result','Index returned unauthorized or malformed identifiers.',502)
                    hits=[allowed[identifier] for identifier in ids]
                    if rerank:
                        from .core import terms
                        hits.sort(key=lambda chunk:(-len(terms(question)&terms(chunk['quote'])),chunk['chunk_id']))
                    hits=hits[:limit]
                if self.cache is not None and cached is None:
                    self.cache.put(cache_key,[chunk['chunk_id'] for chunk in hits])
                self.remaining(deadline)
                trace={'retrieval':method,'embedding_model':self.embedding.model,'chunking':CHUNKING,'corpus':corpus,'profile':self.profile,'prompt':PROMPT,'model':self.provider.model,'rerank':'lexical-overlap-v1' if rerank else None,'candidates':len(chunks),'provider_calls':0}
                trace['cache_hit']=cached is not None
                result={'items':hits,'trace':trace}
                if draft:
                    result.update(self.generate(question,hits,applicability,deadline,trace))
                # Recheck before returning; authoritative writer transaction spans exposure to adapters.
                require(db,scope)
                if any(not global_valid(db,scope,chunk) for chunk in hits):
                    raise Problem('evidence_changed','Evidence changed during retrieval.',409)
                self.remaining(deadline)
                return result
        except Problem: raise
        except Exception:
            raise Problem('retrieval_unavailable','Retrieval or provider failed; no fallback was used.',503) from None

    @traced('model')
    def generate(self,question,hits,applicability,deadline,trace):
        reasons=[]
        if not hits: reasons=['missing_evidence']
        elif any(re.search(r'ignore (?:all |previous |the )?(?:instructions|rules)|system prompt|reveal (?:the )?(?:secret|token)',chunk['quote'],re.I) for chunk in hits): reasons=['suspicious_source_instructions']
        elif any(len({chunk['metadata'].get(key) for chunk in hits if chunk['metadata'].get(key)})>1 for key in ('product','edition','deployment') if key not in applicability): reasons=['applicability_unspecified']
        else:
            text=' '.join(chunk['quote'].lower() for chunk in hits)
            if re.search(r'\bnot encrypted\b|\bunencrypted\b',text) and any('encrypted' in chunk['quote'].lower() and not re.search(r'not encrypted|unencrypted',chunk['quote'].lower()) for chunk in hits): reasons=['conflicting_evidence']
        if reasons:
            return {'draft':'Insufficient approved evidence. Assign to a subject-matter expert.','evidence':[],'status':'needs_evidence','claims':[],'uncertainty':reasons}
        raw=self.provider.draft(question,hits,self.remaining(deadline));trace['provider_calls']=1
        self.remaining(deadline)
        try: output=ModelDraft.model_validate(raw)
        except Exception: raise Problem('invalid_model_output','Provider output does not match the draft schema.',502) from None
        authorized={chunk['chunk_id']:chunk for chunk in hits}
        evidence=[]
        for claim in output.claims:
            chunk=authorized.get(claim.chunk_id)
            if not chunk or claim.quote not in chunk['quote'] or claim.text!=claim.quote:
                raise Problem('unsupported_claim','Claims must be exact quotes from authorized retrieved chunks.',502)
            start=chunk['start']+chunk['quote'].index(claim.quote)
            evidence.append({**chunk,'quote':claim.quote,'start':start,'end':start+len(claim.quote)})
        if output.uncertainty or not evidence:
            return {'draft':'Insufficient approved evidence. Assign to a subject-matter expert.','evidence':[],'status':'needs_evidence','claims':[],'uncertainty':output.uncertainty or ['missing_evidence']}
        if output.answer!='\n'.join(claim.text for claim in output.claims):
            raise Problem('unsupported_claim','Answer contains text outside validated claims.',502)
        return {'draft':output.answer,'evidence':evidence,'status':'needs_review','claims':[claim.model_dump() for claim in output.claims],'uncertainty':[]}


def configured(store):
    backend=os.getenv('EVIDENCEDESK_RETRIEVAL_BACKEND','postgres')
    if backend=='memory':
        if os.getenv('EVIDENCEDESK_DEPLOYMENT','local')!='local': raise Problem('fixture_backend','Memory index is restricted to local fixtures.',503)
        index=MemoryIndex()
    elif backend=='postgres':
        dsn=os.getenv('EVIDENCEDESK_RETRIEVAL_DSN','')
        if not dsn: raise Problem('retrieval_unconfigured','Configure PostgreSQL retrieval DSN and migrate its schema.',503)
        index=PostgresIndex(dsn)
    else: raise Problem('retrieval_unconfigured','Unsupported retrieval backend.',503)
    from .providers import HTTPProvider
    kind=os.getenv('EVIDENCEDESK_MODEL_PROVIDER','fixture')
    if kind=='fixture':
        embedding,provider=FixtureEmbedding(),ExtractiveProvider()
    elif kind=='gateway':
        url=os.getenv('EVIDENCEDESK_PROVIDER_URL','')
        key=os.getenv('EVIDENCEDESK_PROVIDER_KEY','')
        embedding=HTTPProvider(url,os.getenv('EVIDENCEDESK_EMBEDDING_MODEL',''),key)
        provider=HTTPProvider(url,os.getenv('EVIDENCEDESK_DRAFT_MODEL',''),key)
    else: raise Problem('provider_configuration','Unsupported provider adapter.',503)
    return Foundation(store,index,embedding,provider,cache=_cache if os.getenv('EVIDENCEDESK_CACHE')=='1' else None)
