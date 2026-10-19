"""Content-free spans. Remote LangSmith export requires explicit operator opt-in."""
import contextvars
import json
import os
import threading
import time
import uuid
import math
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

_current = contextvars.ContextVar('evidencedesk_span', default=None)
_lock = threading.Lock()
_sink = None
FIELDS = {'status', 'failure', 'phase', 'attempts', 'input_units', 'output_units',
          'cost_usd', 'cache_hit', 'provider_calls', 'candidates', 'job_id'}
FAILURES = {'access', 'validation', 'conflict', 'deadline', 'provider', 'internal', 'none'}


def current_id(): return _current.get()


@contextmanager
def linked_parent(identifier):
    try: identifier=str(uuid.UUID(identifier)) if identifier else None
    except (TypeError,ValueError,AttributeError): identifier=None
    token=_current.set(identifier)
    try: yield
    finally: _current.reset(token)


def category(status):
    if status in (401, 403): return 'access'
    if status == 409: return 'conflict'
    if status in (408, 504): return 'deadline'
    if status in (400, 404, 413, 422): return 'validation'
    if status in (502, 503): return 'provider'
    return 'internal' if status >= 500 else 'none'


def langsmith_sink():
    global _sink
    if os.getenv('EVIDENCEDESK_TRACE_EXPORT') != 'langsmith': return None
    if _sink is None:
        from langsmith import Client
        from urllib.parse import urlsplit
        endpoint=os.environ['EVIDENCEDESK_TRACE_ENDPOINT']
        parsed=urlsplit(endpoint)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an operator-approved HTTPS trace endpoint')
        # Nothing from implicit graph/framework inputs is sent by this module.
        _sink = Client(api_url=endpoint,
                       api_key=os.environ['EVIDENCEDESK_TRACE_KEY'],
                       auto_batch_tracing=False, hide_inputs=True, hide_outputs=True,
                       omit_traced_runtime_info=True, timeout_ms=1000)
    return _sink


def emit(event):
    path = os.getenv('EVIDENCEDESK_TRACE_FILE')
    if path:
        # Operators choose a protected local path and its retention policy.
        with _lock:
            with Path(path).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, sort_keys=True)+'\n')
    client = langsmith_sink()
    if client:
        start = datetime.fromtimestamp(event['started'], timezone.utc)
        client.create_run(event['name'], {}, 'chain', id=event['id'],
                          parent_run_id=event['parent_id'], start_time=start,
                          project_name='evidencedesk-operations',
                          extra={'metadata': event['metrics']})
        client.update_run(event['id'], end_time=datetime.now(timezone.utc),
                          outputs={}, error=event['metrics'].get('failure') if event['metrics'].get('failure') != 'none' else None)


@contextmanager
def span(name, **metrics):
    # Names are fixed instrumentation constants, never URL/query/source text.
    if name not in {'http', 'ingestion', 'retrieval', 'model', 'tool', 'workflow', 'cache', 'provider'}:
        raise ValueError('Use a fixed span name')
    parent = _current.get()
    event = {'id': str(uuid.uuid4()), 'parent_id': parent, 'name': name,
             'started': time.time(), 'metrics': {}}
    def update(**values):
        for key, value in values.items():
            if key not in FIELDS: continue
            if key == 'job_id':
                try: value = str(uuid.UUID(value))
                except (ValueError, TypeError, AttributeError): continue
            elif key == 'failure':
                if value not in FAILURES: continue
            elif key == 'phase':
                if value not in {'classify','retrieve','assess','draft','verify','human_review','publish'}: continue
            elif type(value) not in (int, float, bool) or not math.isfinite(value): continue
            event['metrics'][key] = value
    update(**metrics)
    token = _current.set(event['id'])
    started = time.monotonic()
    try:
        yield update
        event['metrics'].setdefault('failure', 'none')
    except BaseException as error:
        update(failure=category(getattr(error, 'status', getattr(error, 'status_code', 500))))
        raise
    finally:
        event['duration_ms'] = round((time.monotonic()-started)*1000, 3)
        _current.reset(token)
        try: emit(event)
        except Exception: pass  # Observability cannot change approval or request outcomes.


class TraceMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        with span('http') as update:
            identifier = _current.get()
            async def response(message):
                if message['type'] == 'http.response.start':
                    update(status=message['status'], failure=category(message['status']))
                    message = {**message, 'headers': list(message['headers'])+[(b'x-request-id', identifier.encode())]}
                await send(message)
            await self.app(scope, receive, response)


def traced(name):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            with span(name) as update:
                result = function(*args, **kwargs)
                if isinstance(result, dict):
                    trace = result.get('trace', {})
                    update(**{key: value for key, value in trace.items() if key in FIELDS})
                    if name == 'workflow' and 'id' in result:
                        update(job_id=result['id'], attempts=result.get('attempts', 0),
                               phase=result.get('phase'),
                               input_units=result.get('input_tokens_reserved', 0),
                               output_units=result.get('output_tokens_reserved', 0),
                               cost_usd=float(result.get('cost_usd_reserved', 0)))
                return result
        return invoke
    return decorate
