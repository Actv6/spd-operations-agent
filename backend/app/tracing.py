"""Explicit live-worker tracing; durable scrubbed outbox, isolated from business writes."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

_current = ContextVar('spd_trace', default=None)
_child = ContextVar('spd_span', default=None)


def scrub(value, secrets=()):
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k,v in value.items()
                if not re.search(r'api.?key|password|authorization|cookie|csrf|secret|email|actor_id|access.?token',k,re.I)}
    if isinstance(value,list): return [scrub(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret: value=value.replace(secret,'[REDACTED]')
        value=re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b','[EMAIL]',value)
        return re.sub(r'(?i)(?:Bearer\s+|sk-)[A-Za-z0-9_-]+','[REDACTED]',value)
    return value


def now(): return datetime.now(timezone.utc).isoformat()
def order(at, identity): return datetime.fromisoformat(at).strftime('%Y%m%dT%H%M%S%fZ')+identity


class LiveTrace:
    def __init__(self,settings,run_id,fence,request,snapshot,provider):
        self.settings=settings
        # Explicit off switch; mock and injected test adapters never upload by default.
        self.enabled=settings.langsmith_tracing and bool(settings.langsmith_api_key) and provider=='deepseek'
        self.records=[]; self.token=None
        if self.enabled:
            identity=str(uuid.uuid5(uuid.NAMESPACE_URL,'spd:'+run_id+':'+fence)); at=now()
            self.root=dict(id=identity,trace_id=identity,name='AI核查',run_type='chain',start_time=at,
                dotted_order=order(at,identity),inputs={k:request.get(k) for k in ['question','mode','context','parent_run_id']},
                tags=['spd-live','generated-scenario'],extra={'metadata':{'app_run_id':run_id,'snapshot_id':snapshot,
                'attempt_fence':fence,'generation_mode':'model','quality_review':'not_automatically_passed'}})
            self.records.append(self.root)

    def __enter__(self):
        self.token=_current.set(self if self.enabled else None); return self
    def __exit__(self,*args):
        _current.reset(self.token)
    def finish(self,status,error,analysis):
        if not self.enabled:return
        try:
            self.root.update(end_time=now(),outputs={'status':status,**{k:(analysis or {}).get(k) for k in ['answer','risk_summary','risk_priority_summary','insufficient_evidence']}})
            if error:self.root['error']=error.get('code','RUN_FAILED')
            path=Path(self.settings.langsmith_spool_dir);path.mkdir(parents=True,exist_ok=True)
            payload=scrub({'project':self.settings.langsmith_project,'records':self.records,'verified':[]},
                [self.settings.langsmith_api_key,self.settings.deepseek_api_key,self.settings.csrf_secret])
            target=path/(self.root['id']+'.json');temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps(payload,ensure_ascii=False));os.chmod(temp,0o600);temp.replace(target)
        except Exception as exc:
            print('LangSmith outbox failure: '+type(exc).__name__,flush=True)


@contextmanager
def span(name,kind,inputs):
    trace=_current.get()
    if trace is None:
        yield None;return
    identity=str(uuid.uuid4());at=now()
    record=dict(id=identity,trace_id=trace.root['id'],parent_run_id=trace.root['id'],name=name,run_type=kind,
        start_time=at,dotted_order=trace.root['dotted_order']+'.'+order(at,identity),inputs=inputs)
    trace.records.append(record); token=_child.set(record)
    try:yield record
    except BaseException as exc:
        record['error']=getattr(exc,'body',{}).get('code',type(exc).__name__);raise
    finally:
        record['end_time']=now();_child.reset(token)


def model_input(payload):
    record=_child.get()
    if record is not None:record['inputs']=payload


class TracedProvider:
    def __init__(self,provider):self.provider=provider
    async def complete(self,messages,final=False):
        with span('DeepSeek final' if final else 'DeepSeek planning','llm',{'messages':messages,'final':final}) as record:
            message,metadata=await self.provider.complete(messages,final=final)
            if record is not None:
                usage=metadata.get('usage') or {}
                record['outputs']={'message':message,'usage':usage}
                record['extra']={'metadata':{**{k:metadata.get(k) for k in ['prompt_release','requested_model','response_model']},
                    'ls_provider':'deepseek','ls_model_name':metadata.get('response_model') or metadata.get('requested_model')}}
                for key in ['prompt_tokens','completion_tokens','total_tokens']:
                    if usage.get(key) is not None:record[key]=usage[key]
            return message,metadata


def upload_pending(settings,client=None):
    """Called only by background uploader; SDK/network failure never reaches Agent."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:return
    if client is None:
        from langsmith import Client
        client=Client(api_key=settings.langsmith_api_key,api_url=settings.langsmith_endpoint,
            workspace_id=settings.langsmith_workspace_id or None,auto_batch_tracing=False,
            omit_traced_runtime_info=True,timeout_ms=5000)
    for path in sorted(Path(settings.langsmith_spool_dir).glob('*.json')):
        import fcntl
        with path.with_suffix('.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:continue
            payload=json.loads(path.read_text());verified=set(payload.get('verified',[]))
            for record in payload['records']:
                if record['id'] in verified:continue
                try:
                    # An accepted POST may not be indexed immediately. Retry fixed IDs safely.
                    try: saved=client.read_run(record['id'])
                    except Exception:
                        wire={**record,'project_name':payload['project']}
                        for key in ['start_time','end_time']:wire[key]=datetime.fromisoformat(wire[key])
                        client.create_run(**wire);saved=client.read_run(record['id'])
                    if str(saved.id)!=record['id']:raise ValueError('trace id mismatch')
                    verified.add(record['id']);payload.pop('last_error_class',None)
                    if not record.get('parent_run_id'):payload['trace_url']=getattr(saved,'url',None)
                except Exception as exc:
                    payload['last_error_class']=type(exc).__name__
                    # Retry on the next sweep, not in the business call.
                    continue
                finally:
                    payload['verified']=sorted(verified);payload['status']='verified' if len(verified)==len(payload['records']) else 'pending'
                    temp=path.with_suffix('.upload.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False));os.chmod(temp,0o600);temp.replace(path)


def start_uploader(settings):
    if not settings.langsmith_tracing or not settings.langsmith_api_key:return
    def loop():
        while True:
            try:upload_pending(settings)
            except Exception as exc:print('LangSmith uploader failure: '+type(exc).__name__,flush=True)
            time.sleep(15)
    threading.Thread(target=loop,name='langsmith-outbox',daemon=True).start()
