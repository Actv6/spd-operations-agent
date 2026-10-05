"""Cross-milestone local acceptance; provider is explicitly mock, never a paid model."""
from app.agent import work_once
from conftest import create_run, complete_human_reviews
from test_imports import setup, upload, publish
from test_m2 import DraftProvider, child_body, confirm_body
from test_versions import restore


def test_v1_import_risk_agent_citations_task_and_restore(client, app):
    _, project, template = setup(client)
    old_id = template['base_snapshot_id']
    preview = upload(client, project, template).json()
    assert preview['status'] == 'ready'
    assert client.get(f'/api/v1/projects/{project}/inventory').json()['snapshot_set_id'] == old_id
    released = publish(client, project, preview).json()
    new_id = released['snapshot_id']
    risks = client.get(f'/api/v1/projects/{project}/risks').json()
    assert risks['snapshot_set_id'] == new_id and risks['findings']
    run = create_run(client, project)
    work_once(app.state.factory, app.state.settings)
    run = client.get('/api/v1/runs/'+run['run_id']).json()
    assert run['status'] == 'succeeded' and run['generation_mode'] == 'mock'
    analysis = client.get('/api/v1/analyses/'+run['analysis_id']).json()
    assert analysis['snapshot_set_id'] == new_id and analysis['citations']
    evidence = {c['evidence_id']: client.get('/api/v1/evidence/'+c['evidence_id']).json() for c in analysis['citations']}
    assert all('hash' in e for e in evidence.values())
    child = create_run(client, project, 'v1-draft-request', child_body(run, 'draft_action'))
    work_once(app.state.factory, app.state.settings, DraftProvider())
    child = client.get('/api/v1/runs/'+child['run_id']).json()
    draft = client.get('/api/v1/drafts/'+child['draft_id']).json()
    assert not client.get(f'/api/v1/projects/{project}/tasks').json()
    complete_human_reviews(client, run['run_id'], child['run_id'])
    task = client.post('/api/v1/drafts/'+draft['id']+'/confirm', json=confirm_body(draft)).json()
    path = '/api/v1/tasks/'+task['id']
    task = client.patch(path, json={'revision': task['revision'], 'status':'in_progress'}).json()
    task = client.patch(path, json={'revision': task['revision'], 'status':'completed', 'result':'核查已记录，库存异常需数据复核'}).json()
    assert task['status'] == 'completed'
    assert client.get(f'/api/v1/projects/{project}/risks').json() == risks
    assert restore(client, project, old_id, 1).status_code == 200
    assert client.get(f'/api/v1/projects/{project}/inventory').json()['snapshot_set_id'] == old_id
    assert client.get('/api/v1/analyses/'+run['analysis_id']).json() == analysis
    assert {key:client.get('/api/v1/evidence/'+key).json() for key in evidence} == evidence
