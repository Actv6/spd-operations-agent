import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from app.tracing import LiveTrace,TracedProvider,span,upload_pending,model_input
from app.agent import work_once
from conftest import register,create_run


def settings(tmp_path):
    return SimpleNamespace(langsmith_tracing=True,langsmith_api_key='secret-cloud-key',deepseek_api_key='secret-model-key',csrf_secret='secret-csrf',langsmith_spool_dir=str(tmp_path),langsmith_project='controlled-test')


def test_trace_actual_calls_usage_errors_and_scrubbing(tmp_path):
    s=settings(tmp_path)
    class Provider:
        async def complete(self,messages,final=False):
            model_input({'messages':messages,'model':'controlled'})
            return {'content':'secret-cloud-key person@example.test'},{'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'requested_model':'controlled'}
    trace=LiveTrace(s,'run-a','fence-a',{'question':'secret-model-key','mode':'analyze'},'snapshot','deepseek')
    with trace:
        asyncio.run(TracedProvider(Provider()).complete([{'role':'user','content':'question'}]))
        with pytest.raises(ValueError):
            with span('blocked-tool','tool',{'password':'bad','args':{}}):raise ValueError('secret-model-key')
    trace.finish('failed',{'code':'TOOL_REJECTED'},None)
    body=json.loads(next(tmp_path.glob('*.json')).read_text());text=json.dumps(body)
    assert all(x not in text for x in ['secret-model-key','secret-cloud-key','person@example.test','bad'])
    root,llm,tool=body['records'];assert root['extra']['metadata']['app_run_id']=='run-a'
    assert llm['total_tokens']==5 and llm['inputs']['model']=='controlled'
    assert tool['error']=='ValueError' and tool['end_time']>=tool['start_time']
    assert root['error']=='TOOL_REJECTED'


def test_off_and_mock_create_no_outbox(tmp_path):
    s=settings(tmp_path)
    for provider,enabled in [('mock',True),('deepseek',False)]:
        s.langsmith_tracing=enabled
        t=LiveTrace(s,'r','f',{},'s',provider)
        with t:
            with span('x','tool',{}) as record:assert record is None
        t.finish('succeeded',None,None)
    assert not list(tmp_path.iterdir())


def test_disk_failure_does_not_fail_business(tmp_path):
    s=settings(tmp_path);p=tmp_path/'file';p.write_text('x');s.langsmith_spool_dir=str(p)
    t=LiveTrace(s,'r','f',{},'s','deepseek')
    with t:pass
    t.finish('succeeded',None,None)


def test_upload_retry_and_no_duplicate_verified_records(tmp_path):
    s=settings(tmp_path);t=LiveTrace(s,'r','f',{},'s','deepseek')
    with t:pass
    t.finish('succeeded',None,None)
    class Client:
        def __init__(self):self.saved={};self.calls=0;self.offline=True
        def read_run(self,id):
            if self.offline:raise ConnectionError()
            return self.saved[id]
        def create_run(self,**wire):
            if self.offline:raise ConnectionError()
            self.calls+=1;self.saved[wire['id']]=SimpleNamespace(id=wire['id'],url='https://example.test/trace')
    c=Client();upload_pending(s,c);p=next(tmp_path.glob('*.json'));assert json.loads(p.read_text())['status']=='pending'
    c.offline=False;upload_pending(s,c);assert json.loads(p.read_text())['status']=='verified'
    upload_pending(s,c);assert c.calls==1


def test_web_run_worker_failure_has_linked_trace(client,app,tmp_path):
    s=app.state.settings;s.llm_provider='deepseek';s.deepseek_api_key='';s.langsmith_tracing=True;s.langsmith_api_key='controlled-key';s.langsmith_spool_dir=str(tmp_path)
    project=register(client)['projects'][0]['id'];run=create_run(client,project)
    assert work_once(app.state.factory,s)
    result=client.get('/api/v1/runs/'+run['run_id']).json();assert result['status']=='failed'
    body=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert body['records'][0]['extra']['metadata']['app_run_id']==run['run_id']
    assert body['records'][1]['error']=='PROVIDER_NOT_CONFIGURED'
    assert body['records'][0]['outputs']['status']=='failed'


def test_one_unindexed_child_does_not_block_other_records(tmp_path):
    s=settings(tmp_path);t=LiveTrace(s,'r','f',{},'s','deepseek')
    with t:
        with span('tool','tool',{}) as item:item['outputs']={'ok':True}
    t.finish('succeeded',None,None)
    class Client:
        def read_run(self,id):
            if id==t.root['id']:raise KeyError('not indexed yet')
            return SimpleNamespace(id=id,url=None)
        def create_run(self,**wire):pass
    upload_pending(s,Client())
    p=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert p['status']=='pending' and p['verified']==[t.records[1]['id']]
