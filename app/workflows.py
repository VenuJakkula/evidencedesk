"""Durable scoped LangGraph workflow. Graph state contains references, never credentials or source text."""
import json
import multiprocessing
import os
import queue as queue_module
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager, closing
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, Literal
from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langsmith import tracing_context
from .access import Principal, require, actor
from .evidence import audit, valid, global_valid
from .questionnaires import Questionnaires
from .retrieval import configured, fingerprint, CHUNKING, PROMPT
from .providers import HTTPProvider, ModelDraft
from .workbooks import Problem
from .workflow_worker import phase_worker
from .observability import traced, current_id

VERSION='langgraph-extractive-workflow-v1'
TERMINAL={'completed','owner_task','cancelled','failed','superseded'}
INSTRUCTIONS=re.compile(r'ignore.{0,40}(?:instructions|rules)|system\s*(?:prompt|message)|(?:assistant|developer)\s*:|<\|[^>]+\|>|reveal.{0,30}(?:secret|token)|exfiltrat',re.I)

class Options(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,validate_default=True)
    max_attempts:int=Field(default=4,ge=1,le=6)
    max_refinements:int=Field(default=1,ge=0,le=1)
    deadline_seconds:int=Field(default=120,ge=5,le=300)
    max_input_tokens:int=Field(default=100000,ge=100,le=1000000)
    max_output_tokens:int=Field(default=16000,ge=100,le=64000)
    max_cost_usd:float=Field(default=0,ge=0,le=100)
    method:Literal['lexical','embedding','hybrid']='hybrid'
    applicability:dict[str,str]=Field(default_factory=dict)

class State(TypedDict):
    job_id:str
    sequence:int
    route:str


def units(value):
    # Conservative serialized UTF-8 byte units, with fixed protocol overhead.
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())+512


class Workflows:
    def __init__(self,store,foundation=None):
        self.store=store;self.questionnaires=Questionnaires(store);self.injected=foundation
        self.checkpoint_path=str(Path(store.path).resolve())+'.workflow.sqlite'
        with self.control() as db:
            db.execute('CREATE TABLE IF NOT EXISTS workflow_controls(job_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,cancelled INTEGER NOT NULL DEFAULT 0)')
    @contextmanager
    def control(self):
        db=sqlite3.connect(self.checkpoint_path,timeout=5)
        try:
            with db: yield db
        finally: db.close()
    def foundation(self): return self.injected or configured(self.store)
    def profile(self,foundation):
        if getattr(foundation.provider,'experimental_only',False):
            raise Problem('experimental_provider','Experimental routing is not integrated with durable workflow cost accounting.',503)
        live=isinstance(foundation.embedding,HTTPProvider) or isinstance(foundation.provider,HTTPProvider)
        prices={name:os.getenv('EVIDENCEDESK_WORKFLOW_'+name+'_USD_PER_1K','0') for name in ('EMBED_INPUT','DRAFT_INPUT','DRAFT_OUTPUT')}
        if live:
            try:
                if os.getenv('EVIDENCEDESK_ALLOW_LIVE_WORKFLOWS')!='1' or any(not Decimal(value).is_finite() or Decimal(value)<=0 for value in prices.values()): raise ValueError()
            except Exception: raise Problem('live_budget_configuration','Live workflows require explicit opt-in and positive contracted price caps.',503) from None
        if not live: prices={name:'0' for name in prices}
        return {'version':VERSION,'embedding':foundation.embedding.model,'model':foundation.provider.model,'profile':foundation.profile,'chunking':CHUNKING,'prompt':PROMPT,'backend':type(foundation.index).__name__,'transport':fingerprint([getattr(foundation.index,'dsn',None),getattr(foundation.embedding,'url',None),getattr(foundation.provider,'url',None)]+([foundation.a2a_url] if hasattr(foundation,'a2a_url') else [])),'live':live,'prices':prices}
    def owner(self,job): return Principal(job['tenant'],job['issuer'],job['subject'])
    def row(self,db,scope,identifier,write=False):
        require(db,scope,'author' if write else 'read')
        if not isinstance(scope,Principal): raise Problem('verified_identity_required','Workflows require OIDC identity.',403)
        job=db.execute('SELECT * FROM workflow_jobs WHERE tenant=? AND id=?',(str(scope),identifier)).fetchone()
        if not job: raise Problem('not_found','Workflow job not found.',404)
        if write and (job['issuer'],job['subject'])!=(scope.issuer,scope.subject) and 'admin' not in require(db,scope):
            raise Problem('job_owner','Only the originating author or tenant admin can advance this job.',403)
        return dict(job)
    def cancelled(self,identifier):
        with self.control() as db:
            row=db.execute('SELECT cancelled FROM workflow_controls WHERE job_id=?',(identifier,)).fetchone()
            return bool(row and row[0])
    def guard(self,db,job,lease=None,deadline=True):
        require(db,self.owner(job),'author')
        if lease and job['lease_owner']!=lease: raise Problem('job_lease','Another runner owns this job.',409)
        if self.cancelled(job['id']): raise Problem('workflow_cancelled','Workflow cancelled.',409)
        if deadline and time.time()>=job['deadline']: raise Problem('workflow_deadline','Workflow deadline exhausted.',504)
    @traced('workflow')
    def create(self,scope,item_id,expected_revision,key,options=None):
        options=Options.model_validate({} if options is None else options).model_dump()
        if set(options['applicability'])-{'product','edition','deployment'} or any(not value or len(value)>300 for value in options['applicability'].values()):
            raise Problem('invalid_applicability','Use bounded exact applicability filters.')
        if type(expected_revision)!=int or expected_revision<0 or not isinstance(key,str) or not 1<=len(key)<=100:
            raise Problem('invalid_workflow','Provide a current revision and bounded request key.')
        with self.store.connect() as db:
            require(db,scope,'author')
            if not isinstance(scope,Principal): raise Problem('verified_identity_required','Workflows require OIDC identity.',403)
        foundation=self.foundation();profile=self.profile(foundation)
        if profile['live'] and options['max_cost_usd']<=0: raise Problem('live_budget_required','Specify a positive authorized live-call cost budget.')
        payload=fingerprint([item_id,expected_revision,options,profile])
        identifier=str(uuid.uuid4());created=time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');require(db,scope,'author')
            if not isinstance(scope,Principal): raise Problem('verified_identity_required','Workflows require OIDC identity.',403)
            previous=db.execute('SELECT * FROM workflow_jobs WHERE tenant=? AND issuer=? AND subject=? AND request_key=?',(str(scope),scope.issuer,scope.subject,key)).fetchone()
            if previous:
                if previous['payload_hash']!=payload: raise Problem('idempotency_conflict','Request key already belongs to different workflow inputs.',409)
                identifier=previous['id']
            else:
                item=self.questionnaires._item(db,scope,item_id)
                if item['current_revision']!=expected_revision: raise Problem('revision_conflict','Reload the item before starting a workflow.',409)
                if db.execute("SELECT 1 FROM workflow_jobs WHERE tenant=? AND item_id=? AND status IN ('queued','running','retryable','awaiting_review')",(str(scope),item_id)).fetchone():
                    raise Problem('active_workflow','An active workflow already exists for this item.',409)
                db.execute('''INSERT INTO workflow_jobs(id,tenant,issuer,subject,item_id,question,expected_revision,request_key,payload_hash,options,profile,created_at,deadline,status,phase)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'queued','classify')''',(identifier,str(scope),scope.issuer,scope.subject,item_id,item['question'],expected_revision,key,payload,json.dumps(options),json.dumps(profile),created,created+options['deadline_seconds']))
                audit(db,scope,'workflow.created',identifier,{'item_id':item_id,'version':VERSION})
        with self.control() as db: db.execute('INSERT OR IGNORE INTO workflow_controls(job_id,tenant) VALUES(?,?)',(identifier,str(scope)))
        return self.get(scope,identifier)
    def get(self,scope,identifier):
        with self.store.connect() as db:
            job=self.row(db,scope,identifier)
            permissions=require(db,scope)
            can_advance=('admin' in permissions or ('author' in permissions and (job['issuer'],job['subject'])==(scope.issuer,scope.subject)))
            steps=[{'sequence':r['sequence'],'phase':r['phase'],'status':r['status']} for r in db.execute('SELECT sequence,phase,status FROM workflow_steps WHERE tenant=? AND job_id=? ORDER BY sequence',(str(scope),identifier))]
        item=self.questionnaires.item(scope,job['item_id'])
        answer=self.store.get(scope,job['published_answer_id']) if job['published_answer_id'] else None
        decision=None
        if job['published_revision']:
            if item['current_revision']!=job['published_revision']: decision='superseded'
            elif item['answer'] and item['answer'].get('approval'): decision='approved'
            elif item['answer'] and (item['answer'].get('stale_evidence') or item['answer'].get('invalidation_reason') or item['answer'].get('access_blocked')): decision='evidence_changed'
            else: decision='pending'
        return {'id':job['id'],'item_id':job['item_id'],'can_advance':can_advance,'status':'cancelled' if self.cancelled(identifier) else job['status'],'phase':job['phase'],'steps':steps,
            'attempts':job['attempts'],'retrievals':job['retrievals'],'input_tokens_reserved':job['input_units'],'output_tokens_reserved':job['output_units'],
            'cost_usd_reserved':job['reserved_cost'],'budget':json.loads(job['options']),'failure_code':job['failure_code'],'published_revision':job['published_revision'],
            'review_decision':decision,'answer':answer,'owner_task':{'owner':item['owner'] or 'unassigned','reason':job['failure_code']} if job['status']=='owner_task' else None}
    def list(self,scope,item_id,limit=5):
        if type(limit)!=int or not 1<=limit<=20: raise Problem('invalid_pagination','Limit is 1 to 20.')
        with self.store.connect() as db:
            require(db,scope)
            if not isinstance(scope,Principal): raise Problem('verified_identity_required','Workflows require OIDC identity.',403)
            self.questionnaires._item(db,scope,item_id)
            ids=[row[0] for row in db.execute('SELECT id FROM workflow_jobs WHERE tenant=? AND item_id=? ORDER BY created_at DESC,id LIMIT ?',(str(scope),item_id,limit))]
        return {'items':[self.get(scope,identifier) for identifier in ids]}
    def cancel(self,scope,identifier):
        with self.store.connect() as db: job=self.row(db,scope,identifier,True)
        if job['status'] in TERMINAL: return self.get(scope,identifier)
        with self.control() as db: db.execute('INSERT INTO workflow_controls VALUES(?,?,1) ON CONFLICT(job_id) DO UPDATE SET cancelled=1',(identifier,str(scope)))
        # The independent control flag lets a runner kill a child holding the workflow-store writer lock.
        with self.store.connect() as db:
            db.execute("UPDATE workflow_jobs SET status='cancelled',failure_code='workflow_cancelled' WHERE tenant=? AND id=?",(str(scope),identifier))
            audit(db,scope,'workflow.cancelled',identifier)
        return self.get(scope,identifier)
    def latest(self,db,job,phase):
        row=db.execute("SELECT output FROM workflow_steps WHERE tenant=? AND job_id=? AND phase=? AND status='done' ORDER BY sequence DESC LIMIT 1",(job['tenant'],job['id'],phase)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}
    def reserve(self,db,job,kind,payload):
        options=json.loads(job['options']);profile=json.loads(job['profile'])
        count=units(payload);remaining=options['max_output_tokens']-job['output_units']
        output=min(8000,remaining) if kind=='draft' else 0
        if job['attempts']>=options['max_attempts'] or job['input_units']+count>options['max_input_tokens'] or (kind=='draft' and output<100):
            raise Problem('workflow_budget','Workflow attempt/token budget exhausted.',413)
        prices=profile['prices'];price=Decimal(prices['EMBED_INPUT' if kind=='retrieve' else 'DRAFT_INPUT'])
        cost=Decimal(count)*price/1000+(Decimal(output)*Decimal(prices['DRAFT_OUTPUT'])/1000 if kind=='draft' else 0)
        total=Decimal(job['reserved_cost'])+cost
        if total>Decimal(str(options['max_cost_usd'])): raise Problem('workflow_cost_budget','Authorized cost budget exhausted.',413)
        attempt=job['attempts']+1;hashed=fingerprint(payload)
        db.execute('INSERT INTO workflow_calls VALUES(?,?,?,?,?,?,?,?,?)',(job['tenant'],job['id'],attempt,kind,hashed,count,output,str(cost),'started'))
        db.execute('UPDATE workflow_jobs SET attempts=?,retrievals=retrievals+?,input_units=input_units+?,output_units=output_units+?,reserved_cost=? WHERE id=?',(attempt,int(kind=='retrieve'),count,output,str(total),job['id']))
        return {'call_key':job['id']+':'+str(attempt),'input_hash':hashed,'max_output_tokens':output,'attempt':attempt}
    def isolated(self,job,phase,payload,foundation):
        timeout=min(20,max(0,job['deadline']-time.time()))
        if timeout<=0: raise Problem('workflow_deadline','Workflow deadline exhausted.',504)
        context=multiprocessing.get_context('spawn');channel=context.Queue(maxsize=1)
        process=context.Process(target=phase_worker,args=(channel,foundation,(job['tenant'],job['issuer'],job['subject']),phase,payload,timeout,current_id(),job['id']),daemon=True)
        process.start();end=time.monotonic()+timeout
        try:
            while True:
                if self.cancelled(job['id']): raise Problem('workflow_cancelled','Workflow cancelled.',409)
                if time.monotonic()>=end: raise Problem('workflow_deadline','Isolated workflow phase exceeded its deadline.',504)
                try:
                    result=channel.get(timeout=0.1)
                    process.join(timeout=1)
                    return result
                except queue_module.Empty:
                    if not process.is_alive(): raise Problem('uncertain_step','Worker exited without a durable result; not replaying its call.',503)
        finally:
            if process.is_alive(): process.terminate();process.join(timeout=2)
            if process.is_alive(): process.kill();process.join(timeout=2)
            channel.close();channel.join_thread()
    def step(self,scope,identifier,sequence,phase,lease):
        foundation=self.foundation()
        if phase=='human_review': return self.publish(scope,identifier,sequence,lease)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');job=self.row(db,scope,identifier,True);self.guard(db,job,lease)
            if sequence>16: raise Problem('workflow_budget','Workflow step bound exhausted.',413)
            previous=db.execute('SELECT * FROM workflow_steps WHERE tenant=? AND job_id=? AND sequence=?',(str(scope),identifier,sequence)).fetchone()
            if previous and previous['phase']!=phase: raise Problem('checkpoint_mismatch','Checkpoint and phase ledger disagree.',409)
            if previous and previous['status']=='done':
                db.execute("UPDATE workflow_jobs SET status='running',failure_code=NULL WHERE id=?",(identifier,))
                return json.loads(previous['output'])
            if previous and phase in {'retrieve','draft'}: raise Problem('uncertain_step','A started external call has no durable result; not replaying it.',503)
            if not previous: db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?,?,?,?)',(str(scope),identifier,sequence,phase,'started',None,time.time(),None))
            options=json.loads(job['options']);payload=None
            if phase=='retrieve':
                query=job['question']
                if job['retrievals']:
                    from .core import terms
                    query=' '.join(sorted(terms(query))) or query
                chunks=foundation.authorized(db,self.owner(job),options['applicability'])
                texts=[chunk['quote'] for chunk in chunks]+[query]
                reservation=self.reserve(db,job,phase,texts) if chunks else None
                payload={'query':query,'method':options['method'],'limit':5,'applicability':options['applicability'],**(reservation or {})}
                if not chunks:
                    data={'items':[],'trace':{'provider_calls':0},'_route':'assess'}
            elif phase=='draft':
                hits=self.latest(db,job,'retrieve')['items']
                if hits and not valid(db,self.owner(job),hits): raise Problem('evidence_changed','Evidence access changed before drafting.',409)
                request={'question':job['question'],'evidence':hits,'prompt_version':PROMPT,'model':foundation.provider.model}
                reservation=self.reserve(db,job,phase,request)
                payload={'query':job['question'],'hits':hits,'applicability':options['applicability'],**reservation}
            elif phase=='classify':
                reasons=['suspicious_question_instructions'] if INSTRUCTIONS.search(job['question']) else []
                data={'classification':'security' if re.search('encrypt|security|TLS',job['question'],re.I) else 'general','uncertainty':reasons,'_route':'human_review' if reasons else 'retrieve'}
            elif phase=='assess':
                hits=self.latest(db,job,'retrieve').get('items',[])
                if hits and not valid(db,self.owner(job),hits): raise Problem('evidence_changed','Retrieved evidence became invalid.',409)
                reasons=self.assess(job['question'],hits,options['applicability'],foundation)
                if reasons==['missing_evidence'] and job['retrievals']<1+options['max_refinements']:
                    # Empty corpora still consume a retrieval attempt, even without a provider call.
                    data={'uncertainty':reasons,'_route':'retrieve'}
                else: data={'uncertainty':reasons,'_route':'verify' if reasons else 'draft'}
            else:
                assessed=self.latest(db,job,'assess')
                if assessed.get('uncertainty'):
                    data=self.abstain(assessed['uncertainty'])
                else:
                    data=self.latest(db,job,'draft');hits=self.latest(db,job,'retrieve')['items']
                    if data.get('status')=='needs_review': self.verify(db,job,data,hits)
                data={**data,'_route':'human_review'}
            db.execute("UPDATE workflow_jobs SET status='running',phase=? WHERE id=?",(phase,identifier))
        if payload and (phase=='draft' or payload.get('call_key')):
            result=self.isolated(job,phase,payload,foundation)
            terminal_error=None
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');current=self.row(db,scope,identifier,True);self.guard(db,current,lease)
                db.execute('UPDATE workflow_calls SET status=? WHERE tenant=? AND job_id=? AND attempt=?',('failed' if 'error' in result else 'done',str(scope),identifier,payload['attempt']))
                if 'error' in result:
                    if result['retryable'] and current['attempts']<options['max_attempts']:
                        data={'error':result['error'],'_route':phase,'retryable':True}
                    else: terminal_error=Problem(result['error'],'Workflow phase failed.',503)
                else: data={**result['ok'],'_route':'assess' if phase=='retrieve' else 'verify'}
            if terminal_error: raise terminal_error
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self.row(db,scope,identifier,True);self.guard(db,current,lease)
            if phase=='retrieve' and not payload.get('call_key'):
                db.execute('UPDATE workflow_jobs SET retrievals=retrievals+1 WHERE id=?',(identifier,))
            db.execute("UPDATE workflow_steps SET status='done',output=?,finished_at=? WHERE tenant=? AND job_id=? AND sequence=?",(json.dumps(data),time.time(),str(scope),identifier,sequence))
            db.execute('UPDATE workflow_jobs SET sequence=?,status=?,phase=?,failure_code=? WHERE id=?',(sequence,'retryable' if data.get('retryable') else 'running',phase,data.get('error'),identifier))
        return data

    @staticmethod
    def abstain(reasons):
        return {'draft':'Insufficient approved evidence. Assign to a subject-matter expert.','evidence':[],'claims':[],'uncertainty':reasons,'status':'needs_evidence'}

    def assess(self,question,hits,applicability,foundation):
        if not hits: return ['missing_evidence']
        if any(INSTRUCTIONS.search(hit['quote']) for hit in hits): return ['suspicious_source_instructions']
        if any(len({hit['metadata'].get(key) for hit in hits if hit['metadata'].get(key)})>1 for key in ('product','edition','deployment') if key not in applicability): return ['applicability_unspecified']
        positive=any('encrypted' in hit['quote'].lower() and not re.search(r'not encrypted|unencrypted',hit['quote'],re.I) for hit in hits)
        negative=any(re.search(r'not encrypted|unencrypted',hit['quote'],re.I) for hit in hits)
        if positive and negative: return ['conflicting_evidence']
        from .core import terms
        from .providers import FixtureEmbedding
        synonyms=FixtureEmbedding.synonyms if isinstance(foundation.embedding,FixtureEmbedding) else {}
        wanted={synonyms.get(word,word) for word in terms(question)}
        overlap=max((len(wanted & {synonyms.get(word,word) for word in terms(hit['quote'])}) for hit in hits),default=0)
        return [] if overlap/max(len(wanted),1)>=0.34 else ['missing_evidence']

    def verify(self,db,job,result,hits):
        output=ModelDraft.model_validate({'applicability':'selected evidence','answer':result['draft'],'claims':result['claims'],'uncertainty':result['uncertainty']})
        allowed={hit['chunk_id']:hit for hit in hits}
        if not result['evidence'] or not valid(db,self.owner(job),result['evidence']): raise Problem('evidence_changed','Draft evidence became invalid.',409)
        if result['draft']!='\n'.join(claim.text for claim in output.claims): raise Problem('unsupported_claim','Answer contains unsupported prose.',502)
        for claim in output.claims:
            if claim.chunk_id not in allowed or claim.text!=claim.quote or claim.quote not in allowed[claim.chunk_id]['quote']:
                raise Problem('unsupported_claim','Claim is not supported by retrieved material.',502)

    def publish(self,scope,identifier,sequence,lease):
        with self.store.connect() as db:
            db.execute('ATTACH DATABASE ? AS workflow_control',(self.checkpoint_path,))
            db.execute('BEGIN IMMEDIATE');job=self.row(db,scope,identifier,True)
            self.guard(db,job,lease,deadline=not bool(job['published_answer_id']))
            if db.execute('SELECT cancelled FROM workflow_control.workflow_controls WHERE job_id=?',(identifier,)).fetchone()[0]:
                raise Problem('workflow_cancelled','Workflow cancelled.',409)
            previous=db.execute("SELECT output FROM workflow_steps WHERE tenant=? AND job_id=? AND sequence=? AND status='done'",(str(scope),identifier,sequence)).fetchone()
            if previous: return json.loads(previous[0])
            item=self.questionnaires._item(db,self.owner(job),job['item_id'])
            if item['current_revision']!=job['expected_revision']: raise Problem('revision_conflict','Item changed during workflow; no revision published.',409)
            result=self.latest(db,job,'verify')
            if not result:
                result=self.abstain(self.latest(db,job,'classify').get('uncertainty') or ['missing_evidence'])
            hits=self.latest(db,job,'retrieve').get('items',[])
            if result['status']=='needs_review': self.verify(db,job,result,hits)
            answer_id=str(uuid.uuid5(uuid.UUID(identifier),'workflow-answer'))
            draft_calls=db.execute("SELECT COUNT(*) FROM workflow_calls WHERE job_id=? AND status='done' AND kind='draft'",(identifier,)).fetchone()[0]
            trace={'workflow_version':VERSION,'workflow_job_id':identifier,'provider':json.loads(job['profile'])['model'],
                'workflow':['classify','retrieve','assess','draft','verify','human_review'],'draft_provider_calls':draft_calls,'llm_calls':None if json.loads(job['profile'])['live'] else 0,
                'cost_usd':None if json.loads(job['profile'])['live'] else 0,'budget_cost_usd_reserved':job['reserved_cost'],'uncertainty':result['uncertainty']}
            db.execute('INSERT INTO answers VALUES(?,?,?,?,?,?,?,?,?)',(answer_id,str(scope),job['question'],result['draft'],json.dumps(result['evidence']),result['status'],None,None,json.dumps(trace)))
            self.questionnaires._revision(db,self.owner(job),item,result['draft'],result['evidence'],actor(self.owner(job)),answer_id,json.loads(job['profile'])['model'],PROMPT)
            revision=item['current_revision']+1
            db.execute("UPDATE questionnaires SET status='in_review' WHERE tenant=? AND id=?",(str(scope),item['questionnaire_id']))
            status='awaiting_review' if result['evidence'] else 'owner_task'
            code=result['uncertainty'][0] if result['uncertainty'] else None
            db.execute('UPDATE workflow_jobs SET published_revision=?,published_answer_id=?,status=?,phase=?,sequence=?,failure_code=? WHERE id=?',(revision,answer_id,status,'human_review',sequence,code,identifier))
            output={'published_revision':revision,'status':status,'_route':'review'}
            db.execute("INSERT INTO workflow_steps VALUES(?,?,?,?,?,?,?,?)",(str(scope),identifier,sequence,'human_review','done',json.dumps(output),time.time(),time.time()))
            audit(db,scope,'workflow.published',identifier,{'item_id':job['item_id'],'revision':revision,'status':status})
            return output

    def graph(self,scope,identifier,lease,saver):
        builder=StateGraph(State)
        phases=['classify','retrieve','assess','draft','verify','human_review']
        for phase in phases:
            def node(state,phase=phase):
                sequence=state['sequence']+1
                output=self.step(scope,identifier,sequence,phase,lease)
                if phase=='human_review':
                    if output['status']=='awaiting_review':
                        interrupt({'job_id':identifier,'revision':output['published_revision'],'phase':'human_review'})
                        view=self.get(scope,identifier)
                        if view['review_decision']!='approved': raise Problem('human_review_required','A current verified human approval is required.',409)
                        with self.store.connect() as db:
                            db.execute('BEGIN IMMEDIATE')
                            current=self.row(db,scope,identifier,True);self.guard(db,current,lease,deadline=False)
                            item=self.questionnaires._scoped_view(db,scope,self.questionnaires._item(db,scope,current['item_id']))
                            if item['current_revision']!=current['published_revision'] or not item['answer'] or not item['answer'].get('approval'):
                                raise Problem('human_review_required','Current verified human approval changed.',409)
                            db.execute("UPDATE workflow_jobs SET status='completed',failure_code=NULL WHERE id=?",(identifier,))
                    return {'job_id':identifier,'sequence':sequence,'route':'end'}
                return {'job_id':identifier,'sequence':sequence,'route':output['_route']}
            builder.add_node(phase,node)
        builder.add_edge(START,'classify')
        for phase in phases[:-1]: builder.add_conditional_edges(phase,lambda state:state['route'],{name:name for name in phases})
        builder.add_edge('human_review',END)
        return builder.compile(checkpointer=saver,interrupt_after=phases[:-1])

    @traced('workflow')
    def advance(self,scope,identifier):
        lease=str(uuid.uuid4())
        with self.store.connect() as db:
            job=self.row(db,scope,identifier,True)
            if job['status'] in TERMINAL: return self.get(scope,identifier)
            if job['lease_owner'] and job['lease_until']>time.time(): raise Problem('job_busy','Another runner is advancing this job.',409)
            db.execute('BEGIN IMMEDIATE')
            job=self.row(db,scope,identifier,True)
            if job['lease_owner'] and job['lease_until']>time.time(): raise Problem('job_busy','Another runner is advancing this job.',409)
            if self.profile(self.foundation())!=json.loads(job['profile']): raise Problem('workflow_configuration_changed','Resume requires the original model/index profile.',409)
            db.execute('UPDATE workflow_jobs SET lease_owner=?,lease_until=? WHERE id=?',(lease,time.time()+35,identifier))
        try:
            if job['status']=='awaiting_review' and self.get(scope,identifier)['review_decision']!='approved': return self.get(scope,identifier)
            with closing(sqlite3.connect(self.checkpoint_path,check_same_thread=False,timeout=5)) as connection:
                serde=JsonPlusSerializer(pickle_fallback=False,allowed_json_modules=[('langgraph.types','Interrupt')],allowed_msgpack_modules=[('langgraph.types','Interrupt')])
                saver=SqliteSaver(connection,serde=serde)
                graph=self.graph(scope,identifier,lease,saver)
                config={'configurable':{'thread_id':fingerprint([str(scope),identifier])},'recursion_limit':24}
                snapshot=graph.get_state(config)
                initial={'job_id':identifier,'sequence':0,'route':'classify'} if not snapshot.values else None
                if job['status']=='awaiting_review' and any(task.interrupts for task in snapshot.tasks): initial=Command(resume={'decision':'approved'})
                with tracing_context(enabled=False):
                    graph.invoke(initial,config,durability='sync')
                    # Recover publication committed before the human-review interrupt was checkpointed.
                    if job['status']=='awaiting_review' and initial is None and self.get(scope,identifier)['review_decision']=='approved':
                        graph.invoke(Command(resume={'decision':'approved'}),config,durability='sync')
        except Problem as error:
            with self.store.connect() as db:
                db.execute("UPDATE workflow_jobs SET status=?,failure_code=? WHERE id=? AND lease_owner=?",('cancelled' if error.code=='workflow_cancelled' else 'failed',error.code,identifier,lease))
                audit(db,scope,'workflow.stopped',identifier,{'code':error.code})
        except Exception:
            # Checkpoint failures can replay only ledger-completed steps; unfinished external calls fail closed.
            with self.store.connect() as db:
                db.execute("UPDATE workflow_jobs SET status=CASE WHEN published_answer_id IS NULL THEN 'retryable' ELSE status END,failure_code='checkpoint_unavailable' WHERE id=? AND lease_owner=?",(identifier,lease))
        finally:
            with self.store.connect() as db: db.execute('UPDATE workflow_jobs SET lease_owner=NULL,lease_until=NULL WHERE id=? AND lease_owner=?',(identifier,lease))
        return self.get(scope,identifier)
