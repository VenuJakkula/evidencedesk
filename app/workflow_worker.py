"""Isolated provider work. Inputs originate only from the authorized service ledger."""
import json
import os
import threading
import time
from .access import Principal, require
from .evidence import valid
from .providers import HTTPProvider
from .retrieval import fingerprint
from .workbooks import Problem
from .observability import linked_parent, span, category

class ReservedEmbedding:
    def __init__(self,provider,expected,timeout):
        self.provider,self.expected,self.timeout=provider,expected,timeout
        self.model,self.dimensions=provider.model,provider.dimensions
    def embed(self,texts,timeout):
        if fingerprint(texts)!=self.expected:
            raise Problem('evidence_changed','Authorized corpus changed before provider exposure.',409)
        return self.provider.embed(texts,min(timeout,self.timeout))


def phase_worker(queue,foundation,identity,phase,payload,timeout,parent_id=None,job_id=None):
    with linked_parent(parent_id), span('workflow',phase=phase,job_id=job_id) as update:
        update(attempts=payload.get('attempt',0),output_units=payload.get('max_output_tokens',0))
        return _phase_worker(queue,foundation,identity,phase,payload,timeout,update)


def _phase_worker(queue,foundation,identity,phase,payload,timeout,update):
    # Protect even an orphaned worker after a parent crash.
    timer=threading.Timer(timeout,lambda:os._exit(124));timer.daemon=True;timer.start()
    # Workflow data must never be sent to implicit framework tracing services.
    os.environ['LANGCHAIN_TRACING_V2']='false';os.environ['LANGSMITH_TRACING']='false'
    try:
        scope=Principal(*identity)
        call_key=payload['call_key']
        for adapter in [foundation.embedding,foundation.provider]:
            if isinstance(adapter,HTTPProvider):
                adapter.idempotency_key=call_key
                adapter.max_output_tokens=payload['max_output_tokens']
        if hasattr(foundation,'call_key'):
            foundation.call_key=call_key
        if phase=='retrieve':
            foundation.embedding=ReservedEmbedding(foundation.embedding,payload['input_hash'],timeout)
            result=foundation.run(scope,payload['query'],payload['method'],payload['limit'],payload['applicability'])
        else:
            with foundation.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');require(db,scope,'author')
                hits=payload['hits']
                if hits and not valid(db,scope,hits):
                    raise Problem('evidence_changed','Retrieved material no longer authorized.',409)
                trace={'provider_calls':0}
                result=foundation.generate(payload['query'],hits,payload['applicability'],foundation.clock()+timeout,trace)
                result['trace']=trace
                if hits and not valid(db,scope,hits):
                    raise Problem('evidence_changed','Evidence changed during provider call.',409)
        serialized=json.dumps(result,ensure_ascii=False).encode()
        if phase=='draft' and len(serialized)>payload['max_output_tokens']:
            raise Problem('output_budget','Structured draft exceeds its reserved conservative output units.',413)
        queue.put({'ok':result})
    except Problem as error:
        update(failure=category(error.status))
        queue.put({'error':error.code,'retryable':error.code in {'provider_unavailable','retrieval_unavailable'}})
    except BaseException:
        update(failure='internal')
        queue.put({'error':'worker_failed','retryable':False})
    finally:
        timer.cancel()
