"""Read-only audit of this fixed live run. No provider calls, credentials, or mutations."""
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = HERE / 'live-20260928-200737.json'
DB = ROOT / 'backend/var/evals/m21-20260928-200737.db'
connection = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
connection.row_factory = sqlite3.Row
cases = json.loads(RAW.read_text())['cases']
checks = []
def check(label, result):
    checks.append({'check': label, 'passed': bool(result)})
def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

parents = {}
for case in cases:
    name = case['case']
    run = connection.execute('select * from agent_runs where id=?', (case['run_id'],)).fetchone()
    request = json.loads(run['request'])
    parents[name] = (run, request)
    analysis = case['analysis']
    check(f'{name}: real model success', run['provider'] == 'deepseek' and run['status'] == 'succeeded' and analysis['generation_mode'] == 'model')
    check(f'{name}: complete usage', case['usage_complete'])
    for citation in analysis['citations']:
        saved = connection.execute('select * from evidence where id=?', (citation['evidence_id'],)).fetchone()
        body = json.loads(saved['body'])
        check(f'{name}: citation {citation["evidence_id"]} belongs to run/project', saved['run_id'] == run['id'] and saved['project_id'] == run['project_id'])
        check(f'{name}: saved citation unchanged', all(citation[k] == v for k, v in body.items()))
        if body['source_kind'] == 'tool':
            key = next(k for k in body['facts'] if k != 'source_hash')
            check(f'{name}: tool hash {key}', canonical(body['facts'][key]) == body['hash'])
            check(f'{name}: tool snapshot {key}', body['source_version'] == run['snapshot_id'])
        else:
            doc = connection.execute('select * from documents where id=?', (body['location']['document_id'],)).fetchone()
            chunk = connection.execute('select * from chunks where id=?', (body['location']['chunk_id'],)).fetchone()
            check(f'{name}: document hash/location', hashlib.sha256(doc['content'].encode()).hexdigest() == body['hash'] and doc['content'][chunk['start_offset']:chunk['end_offset']] == body['excerpt'] and chunk['text'] == body['excerpt'])
    if name in ['follow-up', 'draft']:
        parent, parent_request = parents['missing']
        check(f'{name}: inherited snapshot/session/scope', run['snapshot_id'] == parent['snapshot_id'] and run['session_id'] == parent['session_id'] and request['parent_run_id'] == parent['id'] and all(request['context'][k] == parent_request['context'][k] for k in ['item_ids', 'department_ids']))

project_run = parents['project'][0]
snapshot = connection.execute('select * from snapshots where id=?', (project_run['snapshot_id'],)).fetchone()
facts = json.loads(snapshot['facts'])
asof = datetime.fromisoformat(snapshot['as_of'])
window = [(asof.date() - timedelta(days=n)).isoformat() for n in range(14, 0, -1)]
missing_dates = [date for date in window if not any(r['product_id']=='SIM-P006' and r['date']==date for r in facts['consumption_daily'])]
check('fixture: missing dates', missing_dates == ['2026-09-22', '2026-09-24'])
zeros = [r for r in facts['consumption_daily'] if r['product_id']=='SIM-P005' and r['date'] in window]
check('fixture: 14 confirmed zero days', len(zeros)==14 and all(r['record_type']=='confirmed_consumption' and Decimal(str(r['quantity_base']))==0 for r in zeros))
fluid = next(r for r in facts['inventory_snapshots'] if r['product_id']=='SIM-P001')
uses = [r for r in facts['consumption_daily'] if r['product_id']=='SIM-P001' and r['date'] in window]
average = sum(Decimal(str(r['quantity_base'])) for r in uses)/Decimal(14)
check('fixture: fluid 120/20=6', Decimal(str(fluid['available_base']))==120 and average==20 and Decimal(str(fluid['available_base']))/average==6)
stale = next(r for r in facts['inventory_snapshots'] if r['product_id']=='SIM-P007')
check('fixture: stale inventory exceeds 24h', (asof-datetime.fromisoformat(stale['snapshot_at'])).total_seconds()>86400)
expiry = [r for r in facts['inventory_batches'] if Decimal(str(r['on_hand_base']))>0 and (datetime.fromisoformat(r['expiry_date']).date()-asof.date()).days<=30]
check('fixture: two expiry hits, one expired', len(expiry)==2 and sum(datetime.fromisoformat(r['expiry_date']).date()<asof.date() for r in expiry)==1)
report = next(c['facts']['risks'] for c in cases[0]['analysis']['citations'] if c.get('facts',{}).get('risks'))
priorities = dict(Counter(r['priority'] for r in report['findings']))
check('risk evidence: high3 medium5', priorities == {'high':3,'medium':5})
check('pending draft has no created tasks', connection.execute('select count(*) from personal_tasks').fetchone()[0]==0 and cases[-1]['draft']['status']=='pending' and cases[-1]['draft']['task_id'] is None)
check('production source unchanged during evaluation', all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in json.loads((HERE/'manifest.json').read_text())['source_sha256'].items()))
calls=[call for case in cases for call in case['calls']]
summary={'raw_sha256':hashlib.sha256(RAW.read_bytes()).hexdigest(),'checks':checks,'all_evidence_checks_pass':all(c['passed'] for c in checks),'tokens_recorded':sum(c['tokens_recorded'] for c in cases),'model_requests':len(calls),'input_tokens':sum(c['usage']['prompt_tokens'] for c in calls),'output_tokens':sum(c['usage']['completion_tokens'] for c in calls),'max_input_chars':max(c['input_chars'] for c in calls),'models':sorted(set(c['response_model'] for c in calls)),'prompt_releases':sorted(set(c['prompt_release'] for c in calls)),'priority_counts_in_evidence':priorities,'priority_counts_claimed_in_answer':{'high':2,'medium':6},'critical_semantic_defect':'project answer priority counts contradict saved tool findings','personal_tasks':0,'note':'Evidence checks do not prove sentence-level entailment or independent business approval.'}
(HERE/'evidence-checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=False,indent=2))
assert summary['all_evidence_checks_pass'], [c for c in checks if not c['passed']]
