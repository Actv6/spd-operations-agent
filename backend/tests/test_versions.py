from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.models import Snapshot, SnapshotActivation, Membership, DataImport
from app.versions import compare
from conftest import create_run, register
from test_imports import setup, edit, upload, publish


def versions(client, project):
    return client.get(f'/api/v1/projects/{project}/versions')


def restore(client, project, target, revision, key='restore-test-key', reason='误导入后恢复已核实的原版本'):
    return client.post(f'/api/v1/projects/{project}/versions/restore', json={'target_snapshot_id': target, 'expected_revision': revision, 'reason': reason}, headers={'Idempotency-Key': key})


def published(client):
    me, project, body = setup(client)
    old_id = body['base_snapshot_id']
    # A later business time must not override the explicit restored version.
    body['as_of'] = '2026-09-27T10:00:00+08:00'
    job = upload(client, project, body).json()
    response = publish(client, project, job)
    assert response.status_code == 200, response.text
    return me, project, old_id, response.json()['snapshot_id']


def test_initial_history_permissions_and_compare_self(client):
    _, project, body = setup(client)
    result = versions(client, project).json()
    assert result['revision'] == 0 and result['history'] == [] and result['can_restore']
    assert len(result['items']) == 1 and result['items'][0]['current']
    response = client.get(f'/api/v1/projects/{project}/versions/compare', params={'from_id': body['base_snapshot_id'], 'to_id': body['base_snapshot_id']})
    assert response.status_code == 200
    assert all(c['kind'] == 'unchanged' for c in response.json()['changes'])


def test_restore_older_business_time_preserves_facts_and_run(client, app):
    _, project, old_id, new_id = published(client)
    run = create_run(client, project)
    with app.state.factory() as db:
        before = {s.id: (s.as_of, s.source_hash, deepcopy(s.facts)) for s in db.scalars(select(Snapshot))}
    listing = versions(client, project).json()
    assert listing['current_snapshot_id'] == new_id and listing['revision'] == 1
    assert listing['history'][0]['action'] == 'publish'
    response = restore(client, project, old_id, 1)
    assert response.status_code == 200, response.text
    assert response.json()['previous_snapshot_id'] == new_id
    assert client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id'] == old_id
    assert client.get(f'/api/v1/projects/{project}/inventory').json()['snapshot_set_id'] == old_id
    assert client.get(f'/api/v1/projects/{project}/risks').json()['snapshot_set_id'] == old_id
    assert client.get(f'/api/v1/runs/{run["run_id"]}').json()['snapshot_set_id'] == new_id
    with app.state.factory() as db:
        assert before == {s.id: (s.as_of, s.source_hash, s.facts) for s in db.scalars(select(Snapshot))}
    assert versions(client, project).json()['revision'] == 2
    fresh = client.get(f'/api/v1/projects/{project}/import-template').json()
    assert fresh['base_snapshot_id'] == old_id and fresh['publication_revision'] == 2
    next_job = upload(client, project, fresh, 'after-restore-import').json()
    assert publish(client, project, next_job).status_code == 200
    assert versions(client, project).json()['revision'] == 3


def test_idempotent_replay_after_another_switch_and_conflict(client, app):
    _, project, old_id, new_id = published(client)
    first = restore(client, project, old_id, 1)
    assert restore(client, project, new_id, 2, 'restore-next-key').status_code == 200
    assert restore(client, project, old_id, 1).json() == first.json()
    assert restore(client, project, old_id, 1, reason='不同的回退原因说明').json()['code'] == 'IDEMPOTENCY_CONFLICT'
    assert versions(client, project).json()['current_snapshot_id'] == new_id
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(SnapshotActivation)) == 3


@pytest.mark.parametrize('reason', ['', '    ', 'abcd', '     a', 'x'*501])
def test_reason_validation(client, reason):
    _, project, old_id, _ = published(client)
    assert restore(client, project, old_id, 1, reason=reason).status_code == 422


def test_current_and_revision_conflicts(client):
    _, project, old_id, new_id = published(client)
    assert restore(client, project, new_id, 1).json()['code'] == 'ALREADY_CURRENT'
    assert restore(client, project, old_id, 0).json()['code'] == 'SNAPSHOT_CHANGED'


def test_roles_and_cross_project(client, app):
    me, project, old_id, _ = published(client)
    with app.state.factory() as db:
        db.get(Membership, (me['user']['id'], project)).role = 'reader'; db.commit()
    assert not versions(client, project).json()['can_restore']
    assert restore(client, project, old_id, 1).status_code == 403
    other = register(client, 'version-other@example.test')['projects'][0]['id']
    assert versions(client, project).status_code == 404
    assert restore(client, other, old_id, 0).status_code == 404
    current = versions(client, other).json()['current_snapshot_id']
    assert client.get(f'/api/v1/projects/{other}/versions/compare', params={'from_id': current, 'to_id': old_id}).status_code == 404


def test_aba_invalidates_old_candidate_and_old_template(client):
    _, project, body = setup(client)
    candidate = upload(client, project, body, 'candidate-before-aba').json()
    other = upload(client, project, body, 'published-before-aba').json()
    assert publish(client, project, other).status_code == 200
    assert restore(client, project, body['base_snapshot_id'], 1).status_code == 200
    assert client.get(f'/api/v1/projects/{project}/imports/{candidate["id"]}').json()['stale']
    assert publish(client, project, candidate).json()['code'] == 'SNAPSHOT_CHANGED'
    assert upload(client, project, body, 'upload-after-aba').json()['code'] == 'SNAPSHOT_CHANGED'
    assert publish(client, project, other).status_code == 200  # Replaying does not re-activate.
    assert versions(client, project).json()['current_snapshot_id'] == body['base_snapshot_id']


def test_old_candidate_missing_revision_requires_revalidation(client, app):
    _, project, body = setup(client)
    job = upload(client, project, body).json()
    with app.state.factory() as db:
        row = db.get(DataImport, job['id']); facts = deepcopy(row.facts)
        del facts['import_provenance']['publication_revision']; row.facts = facts; db.commit()
    assert publish(client, project, job).json()['code'] == 'SNAPSHOT_CHANGED'


def test_concurrent_restore_has_one_winner(client, app):
    _, project, old_id, _ = published(client)
    cookies, headers = dict(client.cookies), dict(client.headers)
    def action(key):
        with TestClient(app) as c:
            c.cookies.update(cookies); c.headers.update(headers)
            return restore(c, project, old_id, 1, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(action, ['parallel-restore-a', 'parallel-restore-b']))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    assert versions(client, project).json()['revision'] == 2


def test_concurrent_publish_and_restore_one_winner(client, app):
    _, project, old_id, _ = published(client)
    body = client.get(f'/api/v1/projects/{project}/import-template').json()
    job = upload(client, project, body, 'parallel-import-key').json()
    cookies, headers = dict(client.cookies), dict(client.headers)
    def action(kind):
        with TestClient(app) as c:
            c.cookies.update(cookies); c.headers.update(headers)
            return restore(c, project, old_id, 1) if kind == 'restore' else publish(c, project, job)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(action, ['restore', 'publish']))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]


def test_comparison_catches_raw_frozen_expiry_and_daily_changes(client, app):
    _, project, body = setup(client)
    with app.state.factory() as db:
        before = db.get(Snapshot, body['base_snapshot_id'])
        facts = deepcopy(before.facts)
        facts['inventory_snapshots'][0]['frozen_base'] = '1'
        facts['inventory_batches'][0]['expiry_date'] = '2028-01-01'
        next(r for r in facts['consumption_daily'] if '2026-09-13' <= r['date'] < '2026-09-27')['quantity_base'] = '99999'
        after = Snapshot(as_of=before.as_of, facts=facts)
        result = compare(before, after)
        details = [d for c in result for d in c['details']]
        assert any('冻结' in d for d in details)
        assert any('效期' in d for d in details)
        assert any('消耗' in d for d in details)
        assert any(c['kind'] == 'changed' for c in result)
        same = compare(before, Snapshot(as_of=before.as_of, facts=deepcopy(before.facts)))
        assert all(c['kind'] == 'unchanged' for c in same)


def test_comparison_added_removed_and_own_time_window(client, app):
    _, project, body = setup(client)
    with app.state.factory() as db:
        before = db.get(Snapshot, body['base_snapshot_id'])
        facts = deepcopy(before.facts)
        facts['inventory_snapshots'].pop()
        after = Snapshot(as_of='2026-10-15T09:00:00+08:00', facts=facts)
        changes = compare(before, after)
        assert sum(c['kind'] == 'removed' for c in changes) == 1
        assert all(c['after_average'] is None for c in changes)
        assert sum(c['kind'] == 'added' for c in compare(after, before)) == 1


def test_restore_initializes_catalog_from_current_before_switch(client, app):
    from app.models import CatalogEntry
    from app.data import canonical_hash
    me = register(client)
    project = me['projects'][0]['id']
    old = client.get(f'/api/v1/projects/{project}/inventory').json()['snapshot_set_id']
    with app.state.factory() as db:
        previous = db.get(Snapshot, old)
        facts = deepcopy(previous.facts)
        facts['products'][0]['name'] = '回退前当前目录名称'
        newer = Snapshot(project_id=project, as_of='2026-09-27T10:00:00+08:00', source_hash=canonical_hash(facts), facts=facts)
        db.add(newer); db.commit()
    assert restore(client, project, old, 0).status_code == 200
    names = client.get(f'/api/v1/projects/{project}/catalog/products').json()['items']
    assert any(r['name'] == '回退前当前目录名称' for r in names)


def test_concurrent_same_key_replays_one_activation(client, app):
    _, project, old_id, _ = published(client)
    cookies, headers = dict(client.cookies), dict(client.headers)
    def action(_):
        with TestClient(app) as c:
            c.cookies.update(cookies); c.headers.update(headers)
            return restore(c, project, old_id, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(action, range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert versions(client, project).json()['revision'] == 2
