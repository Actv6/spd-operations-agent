"""Explicit evaluation-only trace export. Never enables ambient app tracing."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
from dotenv import dotenv_values


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def scrub(value, secrets=()):
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k, v in value.items()
                if not re.search(r'api.?key|password|authorization|cookie|csrf|secret|access.?token|email|actor_id', k, re.I)}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[EMAIL]', value)
        value = re.sub(r'(?i)(?:Bearer\s+|sk-)[A-Za-z0-9_-]+', '[REDACTED]', value)
        return value
    return value


def trace_records(case, secrets=()):
    """Allowlisted root output; provider messages are generated evaluation data."""
    root_id = case['trace_id']
    analysis = case.get('analysis') or {}
    outputs = {k: analysis.get(k) for k in ['answer', 'insufficient_evidence', 'risk_summary', 'risk_priority_summary']}
    outputs.update(status=case['status'], tokens_recorded=case['tokens_recorded'], usage_complete=case['usage_complete'])
    if case.get('semantic_review'):outputs['semantic_review']=case['semantic_review']
    if case.get('draft'):
        outputs['draft'] = {k:case['draft'].get(k) for k in ['title','steps','status','task_id']}
    root_order = datetime.fromtimestamp(case['started_at'],timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + root_id
    common = dict(trace_id=root_id, tags=['spd-v11-eval','generated-data','not-business-approval'])
    records = [dict(id=root_id, name=case['case'], run_type='chain', start_time=iso(case['started_at']),
        end_time=iso(case['ended_at']), inputs={'question':case['question'],'mode':case['mode']},
        outputs=outputs, error=(case.get('error') or {}).get('code'), dotted_order=root_order,
        extra={'metadata':{'app_run_id':case['run_id'],'prompt_release':'v11-quality-2','retrieval_release':'lexical-quality-3',
            'snapshot_id':case['snapshot_set_id'],'semantic_review':'separate_local_review','data_origin':'generated_evaluation'}}, **common)]
    for call in case['provider_calls']:
        meta = call.get('metadata') or {}
        usage = meta.get('usage') or {}
        child_order = datetime.fromtimestamp(call['started_at'],timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+call['id']
        record = dict(id=call['id'],name='DeepSeek final' if call['final'] else 'DeepSeek tool planning',run_type='llm',
            parent_run_id=root_id,start_time=iso(call['started_at']),end_time=iso(call['ended_at']),
            inputs={'messages':call['messages']},outputs={'message':call.get('message'),'usage':usage},
            error=(call.get('error') or {}).get('code'),dotted_order=root_order+'.'+child_order,
            extra={'metadata':{k:meta.get(k) for k in ['requested_model','response_model','prompt_release','provider_version']},
                   'runtime':{'library':'spd-explicit-evaluation'}},**common)
        record['extra']['metadata'].update(ls_provider='deepseek',ls_model_name=meta.get('response_model') or meta.get('requested_model'))
        for dest, source in [('prompt_tokens','prompt_tokens'),('completion_tokens','completion_tokens'),('total_tokens','total_tokens')]:
            if usage.get(source) is not None: record[dest]=usage[source]
        records.append(record)
    for event in case['events']:
        if not event['payload'].get('tool_call_id'): continue
        tool_messages = [m for m in case['checkpoint'].get('messages',[]) if m.get('role')=='tool' and m.get('tool_call_id')==event['payload']['tool_call_id']]
        tool_id = str(uuid.uuid5(uuid.UUID(root_id),'tool:'+str(event['cursor'])))
        observed=event['occurred_at']
        records.append(dict(id=tool_id,name=event['step'],run_type='tool',parent_run_id=root_id,
            start_time=iso(observed),end_time=iso(observed),inputs={'arguments':event['payload'].get('arguments')},
            outputs={'result':json.loads(tool_messages[-1]['content']) if tool_messages else None},
            dotted_order=root_order+'.'+datetime.fromtimestamp(observed,timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+tool_id,
            extra={'metadata':{'timing':'completion_event_only_not_measured_tool_duration'}},**common))
    return scrub(records,secrets)


def upload(directory, client=None):
    """Upload already-generated records; no model/import/worker access."""
    directory=Path(directory)
    values={**dotenv_values(Path(__file__).resolve().parents[1]/'.env'),**os.environ}
    key=values.get('LANGSMITH_API_KEY') or values.get('LANGCHAIN_API_KEY')
    path=directory/'langsmith-upload.json'
    if client is None and not key:
        result={'status':'pending_configuration','model_calls':0,'reason':'LANGSMITH_API_KEY missing'}
        path.write_text(json.dumps(result,indent=2)+'\n'); return result
    if client is None:
        from langsmith import Client
        client=Client(api_key=key,api_url=values.get('LANGSMITH_ENDPOINT') or 'https://api.smith.langchain.com',
            workspace_id=values.get('LANGSMITH_WORKSPACE_ID'),auto_batch_tracing=False,omit_traced_runtime_info=True,timeout_ms=15000)
    state=json.loads((directory/'round.json').read_text())
    project='spd-v11-live-'+state['round_id'][:8]
    receipts=json.loads(path.read_text()).get('receipts',{}) if path.exists() else {}
    failures=[]
    for case in state['results']:
        records=json.loads((directory/('trace-'+case['case']+'.json')).read_text())
        for record in records:
            if receipts.get(record['id'],{}).get('verified'): continue
            payload={**record,'project_name':project}
            # Parse ISO dates for the SDK; never pass any app config/runtime object.
            for field in ['start_time','end_time']: payload[field]=datetime.fromisoformat(payload[field])
            try:
                client.create_run(**payload)
                saved=client.read_run(record['id'])
                if str(saved.id)!=record['id']: raise ValueError('trace id mismatch')
                receipts[record['id']]={'verified':True,'trace_id':record['trace_id'],'url':getattr(saved,'url',None)}
            except Exception as exc:
                failures.append({'id':record['id'],'error_class':type(exc).__name__})
            path.write_text(json.dumps({'status':'partial' if failures else 'uploading','project':project,'receipts':receipts,'failures':failures,'model_calls':0},indent=2)+'\n')
    result={'status':'verified' if not failures else 'partial','project':project,'receipts':receipts,'failures':failures,'model_calls':0}
    path.write_text(json.dumps(result,indent=2)+'\n'); return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(); result=upload(args.directory)
    print(json.dumps({'status':result['status'],'verified':len(result.get('receipts',{})),'model_calls':0}))
