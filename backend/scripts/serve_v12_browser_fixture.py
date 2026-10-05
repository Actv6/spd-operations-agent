"""Isolated generated fixture; controlled provider, no .env/cloud/model requests."""
import argparse
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tests')]
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Base
from app.config import Settings
from app.agent import work_once
from app.providers import MockProvider
from app.claim_support import render_claims
from app.schemas import AnswerClaim
from test_m21 import ScanProvider
import uvicorn


class BrowserProvider(ScanProvider):
    async def complete(self,messages,final=False):
        msg,meta=await super().complete(messages,final)
        if msg.get('tool_calls'):
            msg['tool_calls'].append({'id':'knowledge','function':{'name':'search_knowledge','arguments':'{"query":"14日消耗缺日缺失记录"}'}})
        if final:
            payload=json.loads(msg['content'])
            outputs=[json.loads(m['content']) for m in messages if m['role']=='tool']
            source=next(o for o in outputs if o['kind']=='knowledge' and o['data'])['data'][0]
            quote=next(line for line in source['excerpt'].splitlines() if line.strip() and not line.startswith('#'))
            claims=[AnswerClaim.model_validate(c) for c in payload['claims']]
            claims.append(AnswerClaim(kind='policy',text=quote,evidence_ids=[source['evidence_id']]))
            claims.append(AnswerClaim(kind='suggestion',text='核对反应杯的缺日记录',evidence_ids=claims[0].evidence_ids))
            claims.append(AnswerClaim(kind='unknown',text='是否存在尚未同步记录仍待确认。'))
            payload.update(claims=[c.model_dump() for c in claims],answer=render_claims(claims),
                           evidence_ids=list(dict.fromkeys(e for c in claims for e in c.evidence_ids)))
            msg['content']=json.dumps(payload,ensure_ascii=False)
        return msg,meta


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args()
    if args.database.exists(): raise SystemExit('Refuse to replace an existing fixture database')
    app=create_app(Settings(_env_file=None,database_url='sqlite:///'+str(args.database.resolve()),
        csrf_secret='v12-browser-fixture-secret-32-characters',llm_provider='mock',deepseek_api_key='',
        langsmith_tracing=False,allowed_origins=['http://127.0.0.1:4182'],rate_limit=100))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        client.headers.update({'Origin':'http://127.0.0.1:4182','X-CSRF-Token':client.get('/api/v1/csrf').json()['token']})
        me=client.post('/api/v1/registrations',json={'email':'v12-browser@example.test','password':'local-test-password','display_name':'本地验收'}).json()
        project=me['projects'][0]['id']
        request={'schema_version':'1','mode':'analyze','question':'历史流程兼容核查','session_id':None,'parent_run_id':None,
                 'context':{'snapshot_set_id':None,'item_ids':[],'department_ids':[],'analysis_id':None},'options':{'window_days':14}}
        client.post(f'/api/v1/projects/{project}/runs',json=request,headers={'Idempotency-Key':'v12-old-fixture'})
        work_once(app.state.factory,app.state.settings,MockProvider())
        app.state.settings.llm_provider='deepseek'
        request.update(question='V1.2本地受控验收：事实归因与逐条依据',options={'window_days':14,'focus':'risk_scan'})
        run=client.post(f'/api/v1/projects/{project}/runs',json=request,headers={'Idempotency-Key':'v12-new-fixture'}).json()
        work_once(app.state.factory,app.state.settings,BrowserProvider())
        result=client.get('/api/v1/runs/'+run['run_id']).json()
        assert result['status']=='succeeded',result
    print('Controlled fixture http://127.0.0.1:8012; zero real model calls',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8012)
