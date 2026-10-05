"""Live-round ledger/export safety. No provider or cloud calls."""
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_v11_live import allowed,RecordedProvider
from langsmith_records import scrub,trace_records,upload


def test_ledger_budget_order_unknown_usage_and_review_gate():
    state={'results':[]}
    allowed(state,0)
    with pytest.raises(ValueError):allowed({'results':[],'stop_reason':'P1 semantic error'},0)
    with pytest.raises(ValueError):allowed(state,1)
    for result in [{'status':'failed','usage_complete':True,'tokens_recorded':10},
                   {'status':'succeeded','usage_complete':False,'tokens_recorded':0},
                   {'status':'succeeded','usage_complete':True,'tokens_recorded':120000}]:
        with pytest.raises(ValueError):allowed({'results':[result]},1)
    results=[{'status':'succeeded','usage_complete':True,'tokens_recorded':100} for _ in range(4)]
    with pytest.raises(ValueError):allowed({'results':results},4)
    allowed({'results':results,'targeted_review':{'passed':True}},4)


def test_scrub_nested_secrets_and_email_without_changing_source():
    original={'api_key':'secret','inputs':{'text':'Bearer abc123 user@example.test configured-secret','password':'unsafe'},'total_tokens':15}
    clean=scrub(original,['configured-secret'])
    assert clean=={'inputs':{'text':'[REDACTED] [EMAIL] [REDACTED]'},'total_tokens':15}
    assert original['api_key']=='secret'


def sample():
    return dict(trace_id='a7b31aa0-1111-4111-8111-000000000001',case='test',question='生成问题',mode='analyze',run_id='generated-run',
        started_at=1000,ended_at=1002,status='succeeded',tokens_recorded=15,usage_complete=True,snapshot_set_id='generated-snapshot',
        analysis={'answer':'本次未检索到','insufficient_evidence':True,'actor_id':'DO_NOT_EXPORT','email':'DO_NOT_EXPORT'},
        provider_calls=[{'id':'a7b31aa0-1111-4111-8111-000000000002','started_at':1000,'ended_at':1001,'messages':[{'role':'user','content':'generated'}],
            'final':True,'message':{'content':'{}'},'metadata':{'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}}],
        events=[{'cursor':1,'step':'search_knowledge','occurred_at':1001,'payload':{'tool_call_id':'t','arguments':{'query':'generated'}}}],
        checkpoint={'messages':[{'role':'tool','tool_call_id':'t','content':'{"data":[]}'}]})


def test_allowlist_trace_tree_usage_and_unknown_tool_timing():
    records=trace_records(sample())
    assert len(records)==3
    assert 'DO_NOT_EXPORT' not in json.dumps(records)
    assert records[1]['total_tokens']==15
    assert records[1]['parent_run_id']==records[0]['id']
    assert records[2]['start_time']==records[2]['end_time']
    assert records[2]['extra']['metadata']['timing'].startswith('completion_event_only')


def test_upload_uses_recorded_trace_and_readback_without_model_calls(tmp_path):
    case=sample(); (tmp_path/'round.json').write_text(json.dumps({'round_id':'test-round','results':[{'case':'test'}]}))
    (tmp_path/'trace-test.json').write_text(json.dumps(trace_records(case)))
    class Client:
        def __init__(self):self.items={};self.sent=0
        def create_run(self,**payload):
            assert isinstance(payload['start_time'],datetime)
            self.items[payload['id']]=payload;self.sent+=1
        def read_run(self,id):return SimpleNamespace(id=id,url=None)
    client=Client();result=upload(tmp_path,client)
    assert result['status']=='verified' and len(result['receipts'])==3 and result['model_calls']==0
    upload(tmp_path,client);assert client.sent==3


def test_provider_failure_keeps_request_and_unknown_usage(tmp_path):
    import asyncio
    from app.errors import AppError
    class Provider:
        async def complete(self,messages,final=False):raise AppError('PROVIDER_TIMEOUT','超时',503)
    provider=RecordedProvider(Provider(),tmp_path,'failure')
    with pytest.raises(AppError):asyncio.run(provider.complete([{'role':'user','content':'generated'}]))
    saved=json.loads((tmp_path/'provider-failure.json').read_text())
    assert saved[0]['messages'][0]['content']=='generated'
    assert saved[0]['status']=='failed' and saved[0]['ended_at']>=saved[0]['started_at']
    assert 'metadata' not in saved[0]


def test_init_and_single_case_flow_with_controlled_provider(tmp_path,monkeypatch):
    import evaluate_v11_live as module
    from app.config import Settings
    from test_m21 import ScanProvider
    monkeypatch.setattr(module,'Settings',lambda **kwargs:Settings(_env_file=None,csrf_secret='test-secret-with-at-least-32-characters',deepseek_api_key='controlled-test-key',**kwargs))
    monkeypatch.setattr(module,'DeepSeekProvider',lambda settings:ScanProvider())
    monkeypatch.setattr(module,'frozen_hashes',lambda:{'test':'frozen'})
    directory=tmp_path/'round'
    state=module.initialize(directory)
    assert state['results']==[]
    result=module.run_case(directory,0)
    assert result['status']=='succeeded' and result['usage_complete']
    assert result['personal_tasks']==0 and result['tokens_recorded']==300
    with pytest.raises(ValueError):module.run_case(directory,0)
    assert (directory/'trace-target-project.json').exists()
