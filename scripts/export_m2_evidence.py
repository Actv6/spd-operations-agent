"""Read-only local M2 run evidence export. Excludes keys, sessions and raw prompts."""
import json
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNS=['addf6d09-22f0-426d-9185-189b706757d3','955f981a-42bb-4f21-9acb-1d2a13d3b87a','cd63cb8f-bef7-4849-8ae7-8a213d81e9b7','7a6995e4-c128-44fa-b918-335a34128ff8','a2876e4c-c26f-449b-97e2-c37693cbebd0','4c30beca-cd86-4762-ab47-310ce172c4c7']
with sqlite3.connect(f"file:{ROOT/'backend/var/spd.db'}?mode=ro",uri=True) as db:
    db.row_factory=sqlite3.Row
    results=[]
    for id in RUNS:
        run=db.execute('select * from agent_runs where id=?',(id,)).fetchone()
        if run is None: continue
        analysis=db.execute('select body from analyses where run_id=?',(id,)).fetchone()
        checkpoint=json.loads(run['checkpoint']);request=json.loads(run['request'])
        body=json.loads(analysis['body']) if analysis else {}
        calls=body.get('provider_metadata',{}).get('calls',checkpoint.get('metadata',[]))
        events=[dict(r) for r in db.execute('select step,payload from run_events where run_id=? order by cursor',(id,))]
        results.append({'run_id':id,'status':run['status'],'mode':request['mode'],'parent_run_id':request.get('parent_run_id'),
                        'snapshot_id':run['snapshot_id'],'provider':run['provider'],'duration_seconds':round(run['updated_at']-run['created_at'],2),
                        'error':json.loads(run['error']) if run['error'] else None,'citations':len(body.get('citations',[])),
                        'model_calls':calls,'total_tokens_recorded':sum((c.get('usage') or {}).get('total_tokens',0) for c in calls) if calls else None,
                        'tool_steps':[e['step'] for e in events if e['step'] in ['get_inventory','get_batches','get_consumption','compute_risks','search_knowledge']],
                        'final_validation_count':sum(e['step']=='final_validation' for e in events)})
    tasks=[dict(r) for r in db.execute('select id,draft_id,title,status,revision,due_date,history from personal_tasks')]
    for t in tasks:t['history']=json.loads(t['history'])
    output={'runs':results,'personal_tasks':tasks,'notes':['Generated scenario data, not company records.','The initial TOOL_BUDGET_EXCEEDED run predates usage checkpoint fix; missing usage is unknown, not zero.','Success denotes engineering completion, not full semantic accuracy.']}
    target=ROOT/'docs/verification/m2-20260928/runtime-evidence.json';target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    for r in results:print(r['run_id'],r['status'],r['mode'],r['duration_seconds'],r['total_tokens_recorded'],r['tool_steps'],r['final_validation_count'])
