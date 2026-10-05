"""Acceptance expectations for human decisions, independent of model quality."""
import copy
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.agent import work_once
from app.models import (Run, Analysis, Evidence, HumanReviewRecord, Membership, Snapshot, Document, TaskDraft, PersonalTask)
from conftest import register, create_run, request_body, ORIGIN
from test_m2 import child_body, DraftProvider, confirm_body


def setup(client, app, fail=False):
    me = register(client)
    project = me['projects'][0]['id']
    run = create_run(client, project)
    if fail:
        with app.state.factory() as db:
            r = db.get(Run, run['run_id']); r.status = 'failed'
            r.error = {'code': 'MODEL_UNAVAILABLE', 'message': '模型不可用', 'trace_id': r.id, 'retryable': True}
            db.commit()
    else:
        work_once(app.state.factory, app.state.settings)
    return me, project, client.get('/api/v1/runs/' + run['run_id']).json()


def review_body(view, status='confirmed', **overrides):
    return {'revision': view['revision'], 'source_token': view['source_token'], 'status': status,
        'conclusion': '已人工核对本次范围，建议按核实后的信息处理。',
        'basis': '已逐项查看绑定快照和原始资料，并核对记录的业务时点。',
        'next_step': '核实缺失信息后重新核查。' if status in {'error', 'insufficient'} else '',
        'evidence_ids': [v['evidence_id'] for v in view['available_evidence']],
        'handled_feedback_ids': [f['id'] for f in view['pending_feedback']], **overrides}


def confirm_review(client, run_id, key='review-confirm-key'):
    url = '/api/v1/runs/' + run_id + '/human-review'
    v = client.get(url).json()
    response = client.post(url, json=review_body(v), headers={'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json()


def test_append_only_and_idempotency(client, app):
    _, _, run = setup(client, app)
    url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    with app.state.factory() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.run_id == run['run_id']))
        saved = copy.deepcopy(analysis.body)
        evidence = [copy.deepcopy(e.body) for e in db.scalars(select(Evidence).where(Evidence.run_id == run['run_id']))]
    v = client.get(url).json(); assert v['status'] == 'pending'
    body = review_body(v)
    r = client.post(url, json=body, headers={'Idempotency-Key': 'same-request-key'})
    assert r.status_code == 200, r.text
    assert r.json()['items'][0]['self_review'] and r.json()['status'] == 'confirmed'
    assert client.post(url, json=body, headers={'Idempotency-Key': 'same-request-key'}).json()['revision'] == 1
    assert client.post(url, json={**body, 'conclusion': '不同'}, headers={'Idempotency-Key': 'same-request-key'}).status_code == 409
    assert client.post(url, json=body, headers={'Idempotency-Key': 'new-request-key'}).status_code == 409
    new = client.post(url, json=review_body(r.json(), 'error'), headers={'Idempotency-Key': 'error-request-key'}).json()
    assert new['revision'] == 2 and new['blocked'] and len(new['items']) == 2
    with app.state.factory() as db:
        assert db.get(Analysis, analysis.id).body == saved
        assert [e.body for e in db.scalars(select(Evidence).where(Evidence.run_id == run['run_id']))] == evidence


def test_failure_can_be_handled_without_model_success(client, app):
    _, _, run = setup(client, app, True)
    v = confirm_review(client, run['run_id'])
    assert v['manual_only'] and v['inventory'] and v['items'][0]['analysis_hash'] is None
    assert client.get('/api/v1/runs/' + run['run_id']).json()['status'] == 'failed'
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Analysis)) == 0


def test_active_run_cannot_be_reviewed(client, app):
    project = register(client)['projects'][0]['id']; run = create_run(client, project)
    url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    v = client.get(url).json(); assert not v['can_submit']
    assert client.post(url, json=review_body(v), headers={'Idempotency-Key': 'active-run-key'}).status_code == 409


import pytest
@pytest.mark.parametrize('fields', [{'conclusion': ' '}, {'basis': ' '}, {'status': 'error', 'next_step': ''}, {'status': 'insufficient', 'next_step': ''}])
def test_required_content(client, app, fields):
    _, _, run = setup(client, app); url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    assert client.post(url, json=review_body(client.get(url).json(), **fields), headers={'Idempotency-Key': 'blank-content-key'}).status_code == 422


def test_feedback_reopens_review_and_requires_acknowledgement(client, app):
    _, _, run = setup(client, app); v = confirm_review(client, run['run_id'])
    assert client.post('/api/v1/analyses/' + run['analysis_id'] + '/feedback', json={'rating': 'needs_correction', 'comment': '实际交期尚未核实'}, headers={'Idempotency-Key': 'new-feedback-key'}).status_code == 200
    url = '/api/v1/runs/' + run['run_id'] + '/human-review'; new = client.get(url).json()
    assert new['status'] == 'error' and new['blocked'] and len(new['pending_feedback']) == 1
    assert client.post(url, json=review_body(v), headers={'Idempotency-Key': 'old-source-key'}).json()['code'] == 'REVIEW_SOURCE_CHANGED'
    r = client.post(url, json=review_body(new, handled_feedback_ids=[]), headers={'Idempotency-Key': 'no-acknowledge-key'})
    assert r.json()['code'] == 'REVIEW_FEEDBACK_REQUIRED'
    assert confirm_review(client, run['run_id'], 'acknowledge-key')['status'] == 'confirmed'


def test_evidence_scope_and_permission_boundaries(client, app):
    me, project, run = setup(client, app)
    second = create_run(client, project, 'other-run-key'); work_once(app.state.factory, app.state.settings)
    other_view = client.get('/api/v1/runs/' + second['run_id'] + '/human-review').json()
    url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    r = client.post(url, json=review_body(client.get(url).json(), evidence_ids=[other_view['available_evidence'][0]['evidence_id']]), headers={'Idempotency-Key': 'foreign-evidence-key'})
    assert r.json()['code'] == 'REVIEW_EVIDENCE_SCOPE'
    with TestClient(app) as other:
        other.headers.update({'Origin': ORIGIN, 'X-CSRF-Token': other.get('/api/v1/csrf').json()['token']})
        person = register(other, 'reviewer@example.test')
        assert other.get(url).status_code == 404
        with app.state.factory() as db:
            db.add(Membership(user_id=person['user']['id'], project_id=project, role='viewer')); db.commit()
        assert not other.get(url).json()['can_submit']
        assert other.post(url, json=review_body(other.get(url).json()), headers={'Idempotency-Key': 'viewer-write-key'}).status_code == 403
        with app.state.factory() as db:
            db.get(Membership, (person['user']['id'], project)).role = 'owner'; db.commit()
        v = confirm_review(other, run['run_id'])
        assert not v['items'][0]['self_review'] and v['items'][0]['actor_id'] == person['user']['id']
        with app.state.factory() as db:
            db.delete(db.get(Membership, (person['user']['id'], project))); db.commit()
        assert other.get(url).status_code == 404
        assert other.post(url, json=review_body(v), headers={'Idempotency-Key': 'revoked-write-key'}).status_code == 404


@pytest.mark.parametrize('change', ['snapshot', 'document'])
def test_stale_sources_and_read_token(client, app, change):
    _, project, run = setup(client, app); url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    v = client.get(url).json()
    with app.state.factory() as db:
        if change == 'snapshot':
            old = db.get(Snapshot, run['snapshot_set_id'])
            db.add(Snapshot(project_id=project, as_of=old.as_of, source_hash='b'*64, facts=old.facts, created_at=old.created_at+20))
        else:
            doc = db.scalar(select(Document).where(Document.project_id == project, Document.status == 'approved_demo'))
            doc.status = 'retired_demo'
        db.commit()
    assert client.post(url, json=review_body(v), headers={'Idempotency-Key': 'stale-token-key'}).status_code == 409
    now = client.get(url).json(); assert now['stale_reasons']
    assert client.post(url, json=review_body(now), headers={'Idempotency-Key': 'stale-confirm-key'}).json()['code'] == 'REVIEW_SOURCE_STALE'
    assert client.post(url, json=review_body(now, 'insufficient'), headers={'Idempotency-Key': 'stale-note-key'}).status_code == 200


def test_concurrent_revision_only_one_appends(client, app):
    _, _, run = setup(client, app); url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    body = review_body(client.get(url).json())
    def submit(i):
        with TestClient(app) as c:
            c.cookies.update(client.cookies); c.headers.update(client.headers)
            return c.post(url, json=body, headers={'Idempotency-Key': f'concurrent-key-{i}'})
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(submit, range(2)))
    assert sorted(r.status_code for r in result) == [200, 409]
    assert client.get(url).json()['revision'] == 1


def test_draft_and_ancestor_gate_then_feedback_reblocks(client, app):
    _, project, parent = setup(client, app)
    child = create_run(client, project, 'review-draft-key', child_body(parent, 'draft_action'))
    work_once(app.state.factory, app.state.settings, DraftProvider())
    child = client.get('/api/v1/runs/' + child['run_id']).json()
    draft = client.get('/api/v1/drafts/' + child['draft_id']).json(); url = '/api/v1/drafts/' + draft['id'] + '/confirm'
    assert len(draft['review_blockers']) == 2
    assert client.post(url, json=confirm_body(draft)).json()['code'] == 'HUMAN_REVIEW_REQUIRED'
    assert client.get('/api/v1/drafts/' + draft['id']).json()['status'] == 'pending'
    confirm_review(client, child['run_id'])
    assert client.post(url, json=confirm_body(draft)).status_code == 409
    confirm_review(client, parent['run_id'])
    client.post('/api/v1/analyses/' + parent['analysis_id'] + '/feedback', json={'rating':'needs_correction','comment':'需要补查'}, headers={'Idempotency-Key':'gate-feedback-key'})
    assert client.post(url, json=confirm_body(draft)).status_code == 409
    confirm_review(client, parent['run_id'], 'review-after-feedback')
    response = client.post(url, json=confirm_body(draft)); assert response.status_code == 200, response.text
    task = response.json()
    client.post('/api/v1/analyses/' + parent['analysis_id'] + '/feedback', json={'rating':'needs_correction','comment':'后续发现问题'}, headers={'Idempotency-Key':'after-task-feedback-key'})
    # Existing task is retained; repeating the original request cannot create another.
    assert client.post(url, json=confirm_body(draft)).json()['id'] == task['id']
    assert client.get('/api/v1/drafts/' + draft['id']).json()['review_blockers']
    assert len(client.get(f'/api/v1/projects/{project}/tasks').json()) == 1


def test_duplicate_concurrent_retry_appends_once(client, app):
    _, _, run = setup(client, app); url = '/api/v1/runs/' + run['run_id'] + '/human-review'
    body = review_body(client.get(url).json())
    def submit(_):
        with TestClient(app) as c:
            c.cookies.update(client.cookies); c.headers.update(client.headers)
            return c.post(url, json=body, headers={'Idempotency-Key': 'same-concurrent-review'})
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert all(len(r.json()['items']) == 1 for r in responses)


def test_ordinary_no_high_risk_remains_available_for_sampling(client, app):
    from test_m21 import ScanProvider
    from app.operations import risks
    from app.data import snapshot_for, inventory
    project = register(client)['projects'][0]['id']
    with app.state.factory() as db:
        snapshot = snapshot_for(db, project)
        affected = {f['item_id'] for f in risks(snapshot)['findings'] if f['priority'] == 'high' or f['kind'] == 'quality'}
        item = next(row['item_id'] for row in inventory(snapshot) if row['item_id'] not in affected)
    app.state.settings.llm_provider = 'deepseek'
    run = create_run(client, project, body=request_body('请扫描该物资风险', item_ids=[item]))
    import json
    class FactOnlyProvider(ScanProvider):
        async def complete(self, messages, final=False):
            msg, meta = await super().complete(messages, final)
            if final:
                payload = json.loads(msg['content']); payload['insufficient_evidence'] = False
                msg['content'] = json.dumps(payload, ensure_ascii=False)
            return msg, meta
    work_once(app.state.factory, app.state.settings, FactOnlyProvider())
    result = client.get('/api/v1/runs/' + run['run_id']).json(); assert result['status'] == 'succeeded', result
    v = client.get('/api/v1/runs/' + run['run_id'] + '/human-review').json()
    assert v['status'] == 'pending' and not v['required'] and not v['blocked'] and v['can_submit']
    assert confirm_review(client, run['run_id'])['status'] == 'confirmed'


def test_missing_key_manual_result_does_not_call_provider(client, app):
    project = register(client)['projects'][0]['id']
    app.state.settings.llm_provider = 'deepseek'
    app.state.settings.deepseek_api_key = ''
    run = create_run(client, project)
    work_once(app.state.factory, app.state.settings)
    current = client.get('/api/v1/runs/' + run['run_id']).json()
    assert current['status'] == 'failed' and current['error']['code'] == 'PROVIDER_NOT_CONFIGURED'
    assert confirm_review(client, run['run_id'])['manual_only']


def test_review_change_and_confirmation_are_serialized(client, app):
    from conftest import complete_human_reviews
    _, project, parent = setup(client, app)
    child = create_run(client, project, 'serialize-draft-key', child_body(parent, 'draft_action'))
    work_once(app.state.factory, app.state.settings, DraftProvider())
    child = client.get('/api/v1/runs/' + child['run_id']).json()
    complete_human_reviews(client, parent['run_id'], child['run_id'])
    url = '/api/v1/runs/' + parent['run_id'] + '/human-review'
    body = review_body(client.get(url).json(), 'error')
    assert client.post(url, json=body, headers={'Idempotency-Key':'serialize-error-key'}).status_code == 200
    draft = client.get('/api/v1/drafts/' + child['draft_id']).json()
    assert client.post('/api/v1/drafts/' + child['draft_id'] + '/confirm', json=confirm_body(draft)).status_code == 409
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(PersonalTask)) == 0


def test_upgrade_existing_database_preserves_legacy_records(tmp_path):
    import os, subprocess, sys, json
    from pathlib import Path
    from app.config import Settings
    from app.main import create_app
    root = Path(__file__).resolve().parents[1]
    url = 'sqlite:///' + str(tmp_path / 'legacy-review.db')
    env = {**os.environ, 'DATABASE_URL': url, 'CSRF_SECRET': 'legacy-review-migration-secret-32-characters'}
    first = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'v1101'], cwd=root, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    old = create_app(Settings(_env_file=None, database_url=url, csrf_secret=env['CSRF_SECRET'], llm_provider='mock'))
    with TestClient(old) as c:
        c.headers.update({'Origin':ORIGIN,'X-CSRF-Token':c.get('/api/v1/csrf').json()['token']})
        me = register(c, 'legacy-review@example.test'); project=me['projects'][0]['id']
    raw = {'answer':'历史原始答案，不应补造人工通过','citations':[],'generation_mode':'mock'}
    from app.data import snapshot_for
    with old.state.factory() as db:
        snapshot = snapshot_for(db, project)
        run=Run(project_id=project,actor_id=me['user']['id'],snapshot_id=snapshot.id,
            idempotency_key='legacy-run-key',request_hash='a'*64,request=request_body(),provider='mock',status='failed')
        db.add(run);db.flush();analysis=Analysis(run_id=run.id,project_id=project,body=raw);db.add(analysis);db.commit()
        rid, aid = run.id, analysis.id
    upgrade = subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,capture_output=True,text=True)
    assert upgrade.returncode == 0, upgrade.stderr
    with old.state.factory() as db:
        assert db.get(Analysis, aid).body == raw and db.get(Run,rid).status == 'failed'
        assert db.scalar(select(func.count()).select_from(HumanReviewRecord)) == 0
    with TestClient(old) as c:
        c.headers.update({'Origin':ORIGIN,'X-CSRF-Token':c.get('/api/v1/csrf').json()['token']})
        assert c.post('/api/v1/sessions',json={'email':'legacy-review@example.test','password':'safe-demo-password'}).status_code == 200
        v=c.get('/api/v1/runs/'+rid+'/human-review').json()
        assert v['status']=='pending' and v['items']==[] and v['manual_only']
    old.state.engine.dispose()


def test_new_snapshot_reopens_effective_review_without_erasing_confirmation(client, app):
    _, project, run = setup(client, app)
    old = confirm_review(client, run['run_id'])
    with app.state.factory() as db:
        snapshot=db.get(Snapshot,run['snapshot_set_id'])
        db.add(Snapshot(project_id=project,as_of=snapshot.as_of,source_hash='c'*64,facts=snapshot.facts,created_at=snapshot.created_at+30))
        db.commit()
    v=client.get('/api/v1/runs/'+run['run_id']+'/human-review').json()
    assert v['status']=='pending' and v['blocked'] and v['stale_reasons']
    assert v['items']==old['items'] and v['items'][0]['status']=='confirmed'


def test_accumulated_correction_feedback_can_all_be_resolved(client, app):
    from app.models import AnalysisFeedback
    _, _, run = setup(client, app)
    with app.state.factory() as db:
        for i in range(101):
            db.add(AnalysisFeedback(analysis_id=run['analysis_id'],actor_id=db.get(Run,run['run_id']).actor_id,
                idempotency_key=f'accumulated-feedback-{i}',request_hash='d'*64,rating='needs_correction',comment=f'待核实记录{i}',context={}))
        db.commit()
    v=confirm_review(client,run['run_id'])
    assert v['status']=='confirmed' and not v['pending_feedback']
    assert len(v['items'][0]['handled_feedback_ids'])==101
