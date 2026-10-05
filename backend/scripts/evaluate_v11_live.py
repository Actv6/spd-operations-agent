"""One explicitly selected live case at a time; persistent bounded round ledger."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from langsmith import tracing_context
from app.config import Settings,ROOT
from app.main import create_app
from app.models import Base,Run,RunEvent,PersonalTask,Document,Snapshot,Evidence
from app.agent import work_once
from app.providers import DeepSeekProvider
from app.errors import AppError
from langsmith_records import trace_records

CASES=[
 ('target-project','请扫描当前项目全部物资异常，给出高关注与中关注的数量和清单，说明扫描范围、不能估算覆盖的数量及原因。只按本轮工具事实说明。',[],None),
 ('target-restricted','反应杯具体缺哪两天？只回答日期、缺失状态和为何不能补零，不给处理建议，不追加其他物资或效期信息。',[], 'target-project'),
 ('target-no-evidence','请检索量子宇宙星际飞船技术制度。本次未检索到适用资料就明确说明依据不足，不编造，也不要断言知识库不存在资料。',['SIM-P001'],None),
 ('target-colloquial','反应杯有几天的用量没填咋办？请核查具体缺失日期和本项目适用依据，说明为何不能直接补零。',['SIM-P006'],None),
 ('project','请扫描当前项目全部物资的库存覆盖、批次效期和数据质量异常，说明扫描范围与跳过估算数量，并按关注级别汇总下一步核查建议。',[],None),
 ('missing','反应杯近14日消耗缺了哪两天？能否按零补齐或用12天平均估算覆盖？请查事实和制度，简洁回答。',['SIM-P006'],None),
 ('zero','低频检测耗材消耗记录是否完整？零消耗是否意味着数据缺失？为什么不能给出覆盖天数？',['SIM-P005'],None),
 ('no-evidence','请检索量子宇宙星际飞船的技术制度，没有适用资料就明确不能回答，不要编造。',['SIM-P001'],None),
 ('follow-up','它具体缺哪两天？只回答日期、缺失状态和为何不能补零。',['SIM-P006'],'missing'),
 ('draft','请重新核实依据，生成一份本人核查待办草稿，用3至5个清楚的步骤说明要核实什么，不执行采购或改库存。',['SIM-P006'],'missing'),
]


def save(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)


def frozen_hashes():
    root=ROOT.parent
    previous=json.loads((root/'docs/verification/v11-quality-close-20261004/manifest.json').read_text())
    return {f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in previous['source_sha256'] if f.startswith(('backend/app/','data/','frontend/src/')) or f in ['backend/uv.lock','frontend/pnpm-lock.yaml']}


def allowed(state,index):
    if state.get('stop_reason'):raise ValueError('Round halted: '+state['stop_reason'])
    if index!=len(state['results']):raise ValueError('Only the next case can run; completed cases cannot repeat')
    if index>=10:raise ValueError('Ten-run limit reached')
    if any(r['status']!='succeeded' or not r['usage_complete'] for r in state['results']):raise ValueError('Prior failure or unknown usage blocks further calls')
    if sum(r['tokens_recorded'] for r in state['results'])>=120000:raise ValueError('Round recorded token threshold reached')
    if index>=4 and not state.get('targeted_review',{}).get('passed'):raise ValueError('Four targeted cases require recorded semantic review before regression')


class RecordedProvider:
    def __init__(self,inner,directory,case):self.inner=inner;self.directory=directory;self.case=case;self.calls=[]
    async def complete(self,messages,final=False):
        call={'id':str(uuid.uuid4()),'started_at':time.time(),'messages':copy.deepcopy(messages),'final':final,'status':'started'}
        self.calls.append(call);save(self.directory/('provider-'+self.case+'.json'),self.calls)
        try:
            message,metadata=await self.inner.complete(messages,final)
            call.update(message=message,metadata=metadata,status='returned')
            return message,metadata
        except Exception as exc:
            call.update(status='failed',error=exc.body if isinstance(exc,AppError) else {'code':type(exc).__name__})
            raise
        finally:
            call['ended_at']=time.time();save(self.directory/('provider-'+self.case+'.json'),self.calls)


def initialize(directory):
    directory.mkdir(parents=True,exist_ok=True)
    if (directory/'round.json').exists():raise ValueError('Round already exists; refusing to replace')
    identity=str(uuid.uuid4());db_path=(directory/'evaluation.db').resolve()
    if db_path.exists():raise ValueError('Evaluation DB exists; refusing to replace')
    settings=Settings(database_url='sqlite:///'+str(db_path),llm_provider='deepseek',max_run_tokens=20000,rate_limit=100)
    if not settings.deepseek_api_key:raise ValueError('DeepSeek not configured')
    app=create_app(settings);Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        client.headers.update({'Origin':'http://127.0.0.1:4180','X-CSRF-Token':client.get('/api/v1/csrf').json()['token']})
        response=client.post('/api/v1/registrations',json={'email':'v11-'+identity+'@example.test','password':secrets.token_urlsafe(32),'display_name':'V1.1 独立质量评测'})
        response.raise_for_status();me=response.json()
    with app.state.factory() as db:
        snapshot=db.scalar(select(Snapshot).where(Snapshot.project_id==me['projects'][0]['id']))
        docs=db.scalars(select(Document).where(Document.project_id==me['projects'][0]['id']).order_by(Document.external_id)).all()
        state={'round_id':identity,'database':str(db_path),'actor_id':me['user']['id'] if 'user' in me else me['id'],
            'project_id':me['projects'][0]['id'],'snapshot_id':snapshot.id,'snapshot_hash':snapshot.source_hash,
            'knowledge':[{k:getattr(d,k) for k in ['external_id','version','source_hash']} for d in docs],
            'created_at':time.time(),'max_runs':10,'max_run_tokens':20000,'max_round_recorded_tokens':120000,
            'frozen_source_sha256':frozen_hashes(),'results':[],'targeted_review':None,'note':'Generated data; no task confirmation; engineering success is not semantic approval'}
    app.state.engine.dispose();save(directory/'round.json',state)
    # This file contains only generated evaluation identifiers, not the random password.
    (directory/'round.json').chmod(0o600)
    return state


def run_case(directory,index):
    path=directory/'round.json';state=json.loads(path.read_text());allowed(state,index)
    if frozen_hashes()!=state['frozen_source_sha256']:raise ValueError('Frozen product/data changed; no call made')
    name,question,items,parent_name=CASES[index]
    case_path=directory/(name+'.json')
    if case_path.exists() or (directory/('provider-'+name+'.json')).exists():raise ValueError('Existing evidence blocks repeat; reconcile unknown outcome manually')
    settings=Settings(database_url='sqlite:///'+state['database'],llm_provider='deepseek',max_run_tokens=20000,rate_limit=100)
    app=create_app(settings)
    parent=next((r for r in state['results'] if r['case']==parent_name),None)
    body={'schema_version':'1','mode':'draft_action' if name=='draft' else 'follow_up' if parent else 'analyze',
        'question':question,'parent_run_id':parent['run_id'] if parent else None,'session_id':parent['session_id'] if parent else None,
        'context':copy.deepcopy(parent['context']) if parent else {'snapshot_set_id':state['snapshot_id'],'item_ids':items,'department_ids':[],'analysis_id':None},
        'options':{'window_days':14,'focus':'risk_scan' if name in ['project','target-project'] else 'general'}}
    if parent:body['context']['analysis_id']=parent['analysis_id']
    provider=RecordedProvider(DeepSeekProvider(settings),directory,name)
    with TestClient(app) as client:
        # Local trusted evaluation session, no login credentials or ambient worker.
        from app.models import LoginSession
        from app.auth import digest
        token=secrets.token_urlsafe(32)
        with app.state.factory() as db:
            db.add(LoginSession(token_hash=digest(token),user_id=state['actor_id'],expires_at=time.time()+3600));db.commit()
        client.cookies.set('spd_session',token)
        client.headers.update({'Origin':'http://127.0.0.1:4180','X-CSRF-Token':client.get('/api/v1/csrf').json()['token']})
        response=client.post('/api/v1/projects/'+state['project_id']+'/runs',json=body,headers={'Idempotency-Key':'v11-'+name+'-'+state['round_id']})
        response.raise_for_status();run=response.json();started=time.time()
        with tracing_context(enabled=False):work_once(app.state.factory,settings,provider)
        ended=time.time();run=client.get('/api/v1/runs/'+run['run_id']).json()
        analysis=client.get('/api/v1/analyses/'+run['analysis_id']).json() if run['analysis_id'] else None
        draft=client.get('/api/v1/drafts/'+run['draft_id']).json() if run['draft_id'] else None
        with app.state.factory() as db:
            checkpoint=db.get(Run,run['run_id']).checkpoint or {}
            events=[dict(cursor=e.cursor,step=e.step,type=e.type,occurred_at=e.occurred_at,payload=e.payload) for e in db.scalars(select(RunEvent).where(RunEvent.run_id==run['run_id']).order_by(RunEvent.cursor))]
            evidence=[e.body for e in db.scalars(select(Evidence).where(Evidence.run_id==run['run_id']))]
            tasks=db.scalar(select(func.count()).select_from(PersonalTask))
        calls=provider.calls
        total=sum((c.get('metadata',{}).get('usage') or {}).get('total_tokens') or 0 for c in calls)
        complete=bool(calls) and all(c['status']=='returned' and (c.get('metadata',{}).get('usage') or {}).get('total_tokens') is not None for c in calls)
        record=dict(case=name,trace_id=str(uuid.uuid4()),run_id=run['run_id'],analysis_id=run['analysis_id'],session_id=run['session_id'],
            snapshot_set_id=run['snapshot_set_id'],context=run['context'],mode=run['mode'],question=question,status=run['status'],error=run['error'],
            started_at=started,ended_at=ended,elapsed_seconds=round(ended-started,3),tokens_recorded=total,usage_complete=complete,
            provider_calls=calls,analysis=analysis,draft=draft,checkpoint=checkpoint,events=events,evidence=evidence,personal_tasks=tasks)
        if tasks:raise ValueError('Unexpected task creation; halt and retain database')
        save(case_path,record)
        values=dotenv_values(ROOT/'.env');secret_values=[v for k,v in values.items() if v and any(w in k.upper() for w in ['KEY','SECRET','TOKEN','PASSWORD'])]
        save(directory/('trace-'+name+'.json'),trace_records(record,secret_values))
        state['results'].append(record);save(path,state)
    app.state.engine.dispose()
    print(json.dumps({'case':name,'status':record['status'],'tokens_recorded':total,'usage_complete':complete,'round_tokens_recorded':sum(r['tokens_recorded'] for r in state['results']),'elapsed_seconds':record['elapsed_seconds'],'error':record['error']},ensure_ascii=False))
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--init',action='store_true');parser.add_argument('--case',type=int,choices=range(10));parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if args.init:
        with tracing_context(enabled=False):state=initialize(args.directory)
        print(json.dumps({'initialized':True,'round_id':state['round_id'],'provider_calls':0}))
    elif args.live and args.case is not None:
        run_case(args.directory,args.case)
    else:parser.error('Use --init or explicit --live --case; no model calls made')
