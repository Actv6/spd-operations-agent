"""Isolated human review preview; controlled providers, no keys, uploads or daily DB."""
import argparse
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'tests')]
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Base, Membership
from app.config import Settings
from app.agent import work_once
from app.data import inventory, snapshot_for
from app.operations import risks
from test_m21 import ScanProvider
from test_m2 import child_body
import uvicorn


class FactOnlyProvider(ScanProvider):
    async def complete(self, messages, final=False):
        msg, meta = await super().complete(messages, final)
        if final:
            data = json.loads(msg['content']); data['insufficient_evidence'] = False
            msg['content'] = json.dumps(data, ensure_ascii=False)
        return msg, meta


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    args = p.parse_args()
    if args.database.exists() or args.metadata.exists():
        raise SystemExit('Refuse to overwrite fixture database or metadata')
    app = create_app(Settings(_env_file=None, database_url='sqlite:///' + str(args.database.resolve()),
        csrf_secret='human-review-browser-fixture-secret-32-characters', llm_provider='deepseek', deepseek_api_key='',
        langsmith_tracing=False, allowed_origins=['http://127.0.0.1:4183'], rate_limit=100))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.headers.update({'Origin':'http://127.0.0.1:4183', 'X-CSRF-Token':c.get('/api/v1/csrf').json()['token']})
        def register(email, name):
            r = c.post('/api/v1/registrations', json={'email':email,'password':'local-test-password','display_name':name})
            assert r.status_code == 201, r.text
            return r.json()
        me = register('human-review@example.test', '核查人员')
        project = me['projects'][0]['id']
        from conftest import request_body
        def run(body, key, provider):
            r = c.post(f'/api/v1/projects/{project}/runs', json=body, headers={'Idempotency-Key':key})
            assert r.status_code == 202, r.text
            work_once(app.state.factory, app.state.settings, provider)
            return c.get('/api/v1/runs/'+r.json()['run_id']).json()
        main = run(request_body('人工复核验收：全范围核查', item_ids=[]), 'review-main-fixture', ScanProvider())
        assert main['status'] == 'succeeded', main
        draft = run(child_body(main, 'draft_action'), 'review-draft-fixture', ScanProvider())
        assert draft['status'] == 'succeeded', draft
        failed = run(request_body('人工接手验收：AI未完成'), 'review-failed-fixture', None)
        assert failed['status'] == 'failed', failed
        with app.state.factory() as db:
            snapshot = snapshot_for(db, project)
            high = {f['item_id'] for f in risks(snapshot)['findings'] if f['priority'] == 'high' or f['kind'] == 'quality'}
            item = next(r['item_id'] for r in inventory(snapshot) if r['item_id'] not in high)
        ordinary = run(request_body('人工抽查验收：普通结果', item_ids=[item]), 'review-ordinary-fixture', FactOnlyProvider())
        assert ordinary['status'] == 'succeeded' and not ordinary['human_review']['required'], ordinary
        second = register('human-reviewer@example.test', '复核人员')
        with app.state.factory() as db:
            db.add(Membership(user_id=second['user']['id'], project_id=project, role='owner')); db.commit()
    args.metadata.write_text(json.dumps({'project_id': project,'main':main,'draft':draft,'failed':failed,'ordinary':ordinary,
        'real_model_calls':0,'cloud_uploads':0}, ensure_ascii=False,indent=2)+'\n')
    print('Isolated human review fixture http://127.0.0.1:8013; zero real model calls', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8013)
