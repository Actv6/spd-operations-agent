"""Opt-in live provider evaluation in an isolated local database. No business-task writes."""
import argparse
import json
import secrets
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.config import Settings, ROOT
from app.main import create_app
from app.models import Base, Run
from app.agent import work_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Actually call configured DeepSeek; consumes provider tokens')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=['project','missing','zero','no-evidence','follow-up','draft'], help='Subset in canonical order; parent cases must be included')
    parser.add_argument('--tokens-already-recorded', type=int, default=0, help='Carry forward recorded usage from earlier passes in this evaluation budget')
    args = parser.parse_args()
    if args.tokens_already_recorded < 0:
        parser.error('tokens-already-recorded must be nonnegative')
    if args.cases and any(c in args.cases for c in ['follow-up','draft']) and 'missing' not in args.cases:
        parser.error('follow-up/draft require missing in --cases')
    if not args.live:
        raise SystemExit('Explicit --live is required; no calls made.')
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    db_path = ROOT / 'var' / 'evals' / f'm21-{stamp}.db'
    db_path.parent.mkdir(parents=True, exist_ok=True)
    settings = Settings(database_url=f'sqlite:///{db_path}', llm_provider='deepseek', max_run_tokens=20000)
    if not settings.deepseek_api_key:
        raise SystemExit('DeepSeek key is not configured; no evaluation claimed.')
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    results = []
    cases = [
        ('project', '请扫描当前项目全部物资的库存覆盖、批次效期和数据质量异常，说明扫描范围与跳过估算数量，并按关注级别汇总下一步核查建议。', [], None),
        ('missing', '反应杯近14日消耗缺了哪两天？能否按零补齐或用12天平均估算覆盖？请查事实和制度，简洁回答。', ['SIM-P006'], None),
        ('zero', '低频检测耗材消耗记录是否完整？零消耗是否意味着数据缺失？为什么不能给出覆盖天数？', ['SIM-P005'], None),
        ('no-evidence', '请检索量子宇宙星际飞船的技术制度，没有适用资料就明确不能回答，不要编造。', ['SIM-P001'], None),
        ('follow-up', '它具体缺哪两天？只回答日期、缺失状态和为何不能补零。', ['SIM-P006'], 'missing'),
        ('draft', '请重新核实依据，生成一份本人核查待办草稿，用3至5个清楚的步骤说明要核实什么，不执行采购或改库存。', ['SIM-P006'], 'missing'),
    ]
    parents = {}
    if args.cases:
        cases = [c for c in cases if c[0] in args.cases]
    with TestClient(app) as client:
        client.headers.update({'Origin':'http://127.0.0.1:4180', 'X-CSRF-Token':client.get('/api/v1/csrf').json()['token']})
        account = client.post('/api/v1/registrations', json={'email':f'm21-{stamp}@example.test', 'password':secrets.token_urlsafe(24), 'display_name':'M2.1 质量评测'}).json()
        project = account['projects'][0]['id']
        for name, question, items, parent_name in cases:
            if args.tokens_already_recorded + sum(r['tokens_recorded'] for r in results) >= 90000:
                print('Evaluation cumulative budget reached; remaining cases not run.', flush=True)
                break
            parent = parents.get(parent_name)
            if parent_name and (not parent or parent['status'] != 'succeeded'):
                results.append({'case':name, 'status':'not_run', 'reason':'parent_failed', 'tokens_recorded':0})
                continue
            body = {'schema_version':'1', 'mode':'draft_action' if name=='draft' else 'follow_up' if parent else 'analyze',
                    'question':question, 'parent_run_id':parent['run_id'] if parent else None, 'session_id':parent['session_id'] if parent else None,
                    'context':dict(parent['context']) if parent else {'snapshot_set_id':None,'item_ids':items,'department_ids':[],'analysis_id':None},
                    'options':{'window_days':14, 'focus':'risk_scan' if name=='project' else 'general'}}
            if parent: body['context']['analysis_id'] = parent['analysis_id']
            response = client.post(f'/api/v1/projects/{project}/runs', json=body, headers={'Idempotency-Key':secrets.token_hex(12)})
            response.raise_for_status(); run = response.json(); started = time.monotonic()
            work_once(app.state.factory, settings)
            run = client.get('/api/v1/runs/'+run['run_id']).json(); parents[name] = run
            analysis = client.get('/api/v1/analyses/'+run['analysis_id']).json() if run['analysis_id'] else None
            with app.state.factory() as db:
                checkpoint = db.get(Run,run['run_id']).checkpoint or {}
            calls = analysis['provider_metadata']['calls'] if analysis else checkpoint.get('metadata',[])
            events = client.get('/api/v1/runs/'+run['run_id']+'/events?limit=200').json()['items']
            record = {'case':name,'run_id':run['run_id'],'question':question,'status':run['status'],'error':run['error'],
                      'elapsed_seconds':round(time.monotonic()-started,2),'tokens_recorded':sum((c.get('usage') or {}).get('total_tokens') or 0 for c in calls),
                      'usage_complete':bool(calls) and all((c.get('usage') or {}).get('total_tokens') is not None for c in calls),
                      'calls':calls,'tool_steps':[e['step'] for e in events if e['payload'].get('tool_call_id')],
                      'final_validations':sum(e['step']=='final_validation' for e in events), 'analysis':analysis,
                      'draft':client.get('/api/v1/drafts/'+run['draft_id']).json() if run['draft_id'] else None}
            results.append(record)
            (args.output / f'live-{stamp}.json').write_text(json.dumps({'tokens_already_recorded':args.tokens_already_recorded,'cases':results,'note':'Generated scenario; real DeepSeek calls; engineering success is not semantic approval; no tasks confirmed.'},ensure_ascii=False,indent=2)+'\n')
            print(name, run['status'], record['tokens_recorded'], record['elapsed_seconds'], (run['error'] or {}).get('code',''), flush=True)
    app.state.engine.dispose()
    print('Evidence:',args.output / f'live-{stamp}.json', flush=True)

if __name__ == '__main__': main()
