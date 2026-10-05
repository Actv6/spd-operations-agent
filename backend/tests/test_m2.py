import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.agent import work_once, initial_state
from app.models import Run, Analysis, TaskDraft, PersonalTask, Snapshot, Document, Membership
from app.providers import MockProvider
from app.operations import details, risks
from conftest import register, create_run, request_body, ORIGIN, complete_human_reviews

class DraftProvider(MockProvider):
    async def complete(self, messages, final=False):
        answer, meta = await super().complete(messages, final)
        if final:
            value = json.loads(answer['content'])
            value['task_draft'] = {'title': '核实清洗液补货依据', 'steps': ['核对可用库存与批次', '补充交期及在途信息']}
            answer['content'] = json.dumps(value, ensure_ascii=False)
        return answer, meta

def setup_run(client, app):
    me = register(client); project = me['projects'][0]['id']
    run = create_run(client, project)
    work_once(app.state.factory, app.state.settings)
    return me, project, client.get('/api/v1/runs/' + run['run_id']).json()

def child_body(parent, mode='follow_up'):
    return {**request_body('请继续核查批次和缺日'), 'mode': mode, 'parent_run_id': parent['run_id'], 'session_id': parent['session_id'],
            'context': {**parent['context'], 'analysis_id': parent['analysis_id']}}

def make_draft(client, app):
    me, project, parent = setup_run(client, app)
    run = create_run(client, project, 'draft-key', child_body(parent, 'draft_action'))
    work_once(app.state.factory, app.state.settings, DraftProvider())
    run = client.get('/api/v1/runs/' + run['run_id']).json()
    assert run['status'] == 'succeeded', run
    complete_human_reviews(client, parent['run_id'], run['run_id'])
    draft = client.get('/api/v1/drafts/' + run['draft_id']).json()
    return me, project, draft

def confirm_body(draft):
    return {'revision': draft['revision'], 'title': '已编辑：核对清洗液', 'steps': ['先核对批次', '记录交期信息'], 'due_date': '2026-10-01'}

def test_risk_scan_and_real_details(client, app):
    project = register(client)['projects'][0]['id']
    report = client.get(f'/api/v1/projects/{project}/risks').json()
    assert report['scanned_positions'] == 24 and report['skipped_estimates'] == 3
    assert report['estimate_gap_counts'] == {'data_quality': 2, 'zero_consumption': 1}
    assert report == client.get(f'/api/v1/projects/{project}/risks').json()
    assert any(f['item_id'] == 'SIM-P001' and f['kind'] == 'low_coverage' for f in report['findings'])
    assert not any(f['item_id'] == 'SIM-P006' and f['kind'] == 'low_coverage' for f in report['findings'])
    d = client.get(f'/api/v1/projects/{project}/item-details?item_id=SIM-P006').json()
    assert len(d['consumption'][0]['days']) == 14
    missing = [r for r in d['consumption'][0]['days'] if r['status'] == 'missing']
    assert len(missing) == 2 and all(r['quantity'] is None for r in missing)
    assert d['consumption'][0]['daily_average'] is None
    assert client.get(f'/api/v1/projects/{project}/item-details?item_id=unowned').status_code == 422

def test_expiry_boundaries_and_frozen_stock(client, app):
    project = register(client)['projects'][0]['id']
    with app.state.factory() as db:
        snapshot = db.scalar(select(Snapshot).where(Snapshot.project_id == project))
        from copy import deepcopy
        from datetime import date, timedelta
        snapshot.facts = deepcopy(snapshot.facts)
        batches = [b for b in snapshot.facts['inventory_batches'] if b['product_id'] == 'SIM-P001']
        day = date.fromisoformat(snapshot.as_of[:10])
        for b, delta in zip(batches, [-1, 30, 31]):
            b['expiry_date'] = (day + timedelta(days=delta)).isoformat()
        batches[1]['frozen_base'] = batches[1]['on_hand_base']
        expiry = next(f for f in risks(snapshot, ['SIM-P001'])['findings'] if f['kind'] == 'expiry')
        assert len(expiry['source_rows']) == 2 and expiry['priority'] == 'high'
        actual = details(snapshot, ['SIM-P001'])['batches']
        assert actual[0]['available'] == '0' and actual[1]['available'] == '0'

def test_follow_up_inherits_scope_and_history(client, app):
    _, project, parent = setup_run(client, app)
    body = child_body(parent); child = create_run(client, project, 'follow-up-key', body)
    assert child['snapshot_set_id'] == parent['snapshot_set_id'] and child['session_id'] == parent['session_id']
    assert create_run(client, project, 'follow-up-key', body)['run_id'] == child['run_id']
    with app.state.factory() as db:
        state = initial_state(db, db.get(Run, child['run_id']))
        assert any(m['role'] == 'assistant' for m in state['messages']) and state['evidence_ids'] == []
    work_once(app.state.factory, app.state.settings)
    chain = client.get('/api/v1/runs/' + child['run_id'] + '/conversation').json()
    assert len(chain) == 2 and chain[1]['parent_run_id'] == parent['run_id']
    body['context']['item_ids'] = ['SIM-P002']
    assert client.post(f'/api/v1/projects/{project}/runs', json=body, headers={'Idempotency-Key': 'bad-scope-key'}).status_code == 409

@pytest.mark.parametrize('mode', ['follow_up', 'draft_action'])
def test_parent_required_and_must_be_ready(client, app, mode):
    project = register(client)['projects'][0]['id']
    assert client.post(f'/api/v1/projects/{project}/runs', json={**request_body(), 'mode': mode}, headers={'Idempotency-Key': 'no-parent-key'}).status_code == 422
    queued = create_run(client, project)
    assert client.post(f'/api/v1/projects/{project}/runs', json=child_body(queued, mode), headers={'Idempotency-Key': 'not-ready-key'}).status_code == 409

def test_draft_confirm_edit_idempotency_and_lifecycle(client, app):
    _, project, draft = make_draft(client, app)
    endpoint = '/api/v1/drafts/' + draft['id'] + '/confirm'
    assert client.get(f'/api/v1/projects/{project}/tasks').json() == []
    body = confirm_body(draft); r = client.post(endpoint, json=body)
    assert r.status_code == 200, r.text
    task = r.json(); assert task['title'] == body['title'] and task['steps'] == body['steps']
    assert client.post(endpoint, json=body).json()['id'] == task['id']
    assert client.post(endpoint, json={**body, 'title': 'changed'}).status_code == 409
    url = '/api/v1/tasks/' + task['id']
    assert client.patch(url, json={'revision': 1, 'status': 'completed', 'result': '直接完成'}).status_code == 409
    task = client.patch(url, json={'revision': 1, 'status': 'in_progress'}).json()
    assert client.patch(url, json={'revision': task['revision'], 'status': 'completed', 'result': '  '}).status_code == 422
    assert client.patch(url, json={'revision': 1, 'status': 'completed', 'result': '旧版本'}).status_code == 409
    before = client.get(f'/api/v1/projects/{project}/risks').json()
    task = client.patch(url, json={'revision': task['revision'], 'status': 'completed', 'result': '已核对，待补交期'}).json()
    assert client.get(f'/api/v1/projects/{project}/risks').json() == before
    task = client.patch(url, json={'revision': task['revision'], 'status': 'todo', 'result': '需再次核实'}).json()
    assert len(task['history']) == 4 and task['status'] == 'todo'

@pytest.mark.parametrize('change', ['snapshot', 'document'])
def test_stale_draft_rejected_without_partial_commit(client, app, change):
    _, project, draft = make_draft(client, app)
    with app.state.factory() as db:
        if change == 'snapshot':
            snapshot = db.get(Snapshot, draft['snapshot_set_id'])
            db.add(Snapshot(project_id=project, as_of=snapshot.as_of, source_hash='a'*64, facts=snapshot.facts, created_at=snapshot.created_at+10))
        else:
            analysis = db.get(Analysis, draft['analysis_id'])
            citation = next(c for c in analysis.body['citations'] if c['source_kind'] == 'document')
            db.get(Document, citation['location']['document_id']).status = 'retired_demo'
        db.commit()
    assert client.get('/api/v1/drafts/' + draft['id']).json()['stale_reason']
    assert client.post('/api/v1/drafts/' + draft['id'] + '/confirm', json=confirm_body(draft)).status_code == 409
    assert client.get('/api/v1/drafts/' + draft['id']).json()['status'] == 'pending'
    assert client.get(f'/api/v1/projects/{project}/tasks').json() == []

def test_owner_isolation_even_with_project_membership(client, app):
    _, project, draft = make_draft(client, app)
    task = client.post('/api/v1/drafts/' + draft['id'] + '/confirm', json=confirm_body(draft)).json()
    with TestClient(app) as other:
        other.headers.update({'Origin': ORIGIN, 'X-CSRF-Token': other.get('/api/v1/csrf').json()['token']})
        me = register(other, 'second@example.test')
        assert other.get(f'/api/v1/projects/{project}/risks').status_code == 404
        with app.state.factory() as db:
            db.add(Membership(user_id=me['user']['id'], project_id=project)); db.commit()
        for url in ['/api/v1/drafts/'+draft['id'], '/api/v1/tasks/'+task['id'], '/api/v1/runs/'+draft['run_id']+'/conversation']:
            assert other.get(url).status_code == 404
        assert other.get(f'/api/v1/projects/{project}/tasks').json() == []
        assert other.post('/api/v1/drafts/'+draft['id']+'/confirm', json=confirm_body(draft)).status_code == 404

class ToolProvider(MockProvider):
    def __init__(self, name, invalid=False):
        self.name, self.invalid = name, invalid
    async def complete(self, messages, final=False):
        if not final and not any(m['role'] == 'tool' for m in messages):
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'details-1', 'function': {'name': self.name, 'arguments': json.dumps({'item_ids': ['SIM-P002'] if self.invalid else [], 'department_ids': []})}}]}, {}
        return await super().complete(messages, final)

@pytest.mark.parametrize('name', ['get_batches', 'get_consumption', 'compute_risks'])
@pytest.mark.parametrize('invalid', [False, True])
def test_new_tools_scope_and_evidence(client, app, name, invalid):
    project = register(client)['projects'][0]['id']; run = create_run(client, project)
    work_once(app.state.factory, app.state.settings, ToolProvider(name, invalid))
    result = client.get('/api/v1/runs/'+run['run_id']).json()
    if invalid:
        assert result['status'] == 'failed' and result['error']['code'] == 'TOOL_SCOPE_REJECTED'
    else:
        assert result['status'] == 'succeeded', result
        analysis = client.get('/api/v1/analyses/'+result['analysis_id']).json()
        assert analysis['citations'][0]['source_version'] == run['snapshot_set_id']

def test_rejected_draft_cannot_confirm(client, app):
    _, _, draft = make_draft(client, app); url = '/api/v1/drafts/' + draft['id']
    assert client.post(url+'/reject', json={'revision': 1}).json()['status'] == 'rejected'
    assert client.post(url+'/confirm', json=confirm_body(draft)).status_code == 409

def test_draft_requires_structured_model_output(client, app):
    _, project, parent = setup_run(client, app)
    run = create_run(client, project, 'invalid-draft-key', child_body(parent, 'draft_action'))
    work_once(app.state.factory, app.state.settings)
    result = client.get('/api/v1/runs/'+run['run_id']).json()
    assert result['status'] == 'failed' and result['error']['code'] == 'DRAFT_INVALID'
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(TaskDraft)) == 0

def test_duplicate_concurrent_confirmation_creates_one_task(client, app):
    from concurrent.futures import ThreadPoolExecutor
    _, project, draft = make_draft(client, app)
    body = confirm_body(draft)
    def confirm_once(_):
        with TestClient(app) as c:
            c.cookies.update(client.cookies); c.headers.update(client.headers)
            return c.post('/api/v1/drafts/'+draft['id']+'/confirm', json=body)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(confirm_once, range(2)))
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json()['id'] == responses[1].json()['id']
    assert len(client.get(f'/api/v1/projects/{project}/tasks').json()) == 1


def test_follow_up_foreign_parent_and_revoked_membership(client, app):
    me, project, parent = setup_run(client, app)
    with TestClient(app) as other:
        other.headers.update({'Origin':ORIGIN,'X-CSRF-Token':other.get('/api/v1/csrf').json()['token']})
        second = register(other, 'parent-other@example.test')
        assert other.post(f"/api/v1/projects/{second['projects'][0]['id']}/runs",json=child_body(parent),headers={'Idempotency-Key':'foreign-parent-key'}).status_code == 404
    with app.state.factory() as db:
        db.delete(db.get(Membership,(me['user']['id'],project))); db.commit()
    assert client.post(f'/api/v1/projects/{project}/runs',json=child_body(parent),headers={'Idempotency-Key':'revoked-parent-key'}).status_code == 404


def test_seven_day_boundary_is_not_flagged(client, app):
    from copy import deepcopy
    project=register(client)['projects'][0]['id']
    with app.state.factory() as db:
        snapshot=db.scalar(select(Snapshot).where(Snapshot.project_id==project))
        snapshot.facts=deepcopy(snapshot.facts)
        batches=[b for b in snapshot.facts['inventory_batches'] if b['product_id']=='SIM-P001']
        for b,qty in zip(batches,[40,40,60]): b['on_hand_base']=qty
        assert not any(f['kind']=='low_coverage' for f in risks(snapshot,['SIM-P001'])['findings'])

def test_one_model_format_repair_keeps_usage(client, app):
    class RepairProvider(MockProvider):
        def __init__(self): self.finals=0
        async def complete(self,messages,final=False):
            if final:
                self.finals+=1
                if self.finals==1: return {'role':'assistant','content':'{"answer":"bad\njson"}'},{'usage':{'total_tokens':7}}
            answer,meta=await super().complete(messages,final)
            return answer,{'usage':{'total_tokens':11}}
    project=register(client)['projects'][0]['id'];run=create_run(client,project);provider=RepairProvider()
    work_once(app.state.factory,app.state.settings,provider)
    result=client.get('/api/v1/runs/'+run['run_id']).json()
    assert result['status']=='succeeded' and provider.finals==2
    analysis=client.get('/api/v1/analyses/'+result['analysis_id']).json()
    assert [m['usage']['total_tokens'] for m in analysis['provider_metadata']['calls']][-2:]==[7,11]
