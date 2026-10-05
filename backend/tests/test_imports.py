import csv
import io
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.models import Snapshot, Membership, DataImport
from app.imports import csv_text, HEADERS
from conftest import register, create_run


def setup(client):
    me = register(client)
    project = me['projects'][0]['id']
    return me, project, client.get(f'/api/v1/projects/{project}/import-template').json()


def edit(body, kind, fn):
    rows = list(csv.DictReader(io.StringIO(body['files'][kind].lstrip('\ufeff'))))
    fn(rows)
    body['files'][kind] = csv_text(HEADERS[kind], [[r[h] for h in HEADERS[kind]] for r in rows])


def upload(client, project, body, key='import-test-key'):
    return client.post(f'/api/v1/projects/{project}/imports', json=body, headers={'Idempotency-Key': key})


def publish(client, project, job, ack=True):
    return client.post(f'/api/v1/projects/{project}/imports/{job["id"]}/publish', json={'acknowledge_warnings': ack})


def test_preview_publish_idempotency_and_history(client, app):
    _, project, body = setup(client)
    run = create_run(client, project)
    old = client.get(f'/api/v1/projects/{project}/inventory').json()
    response = upload(client, project, body)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job['status'] == 'ready', job['issues']
    assert upload(client, project, body).json()['id'] == job['id']
    assert client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id'] == old['snapshot_set_id']
    result = publish(client, project, job)
    assert result.status_code == 200, result.text
    new_id = result.json()['snapshot_id']
    assert new_id != old['snapshot_set_id']
    assert publish(client, project, job).json()['snapshot_id'] == new_id
    assert client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id'] == new_id
    assert client.get(f'/api/v1/projects/{project}/risks').json()['snapshot_set_id'] == new_id
    assert client.get(f'/api/v1/runs/{run["run_id"]}').json()['snapshot_set_id'] == old['snapshot_set_id']
    assert client.get(f'/api/v1/projects/{project}/inventory?snapshot_set_id={old["snapshot_set_id"]}').json() == old
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project)) == 2
        assert db.get(DataImport, job['id']).published_by


def test_missing_days_warn_not_zero_and_require_confirmation(client):
    _, project, body = setup(client)
    edit(body, 'consumption', lambda rows: rows.clear())
    job = upload(client, project, body).json()
    assert job['status'] == 'ready' and job['warning_count']
    assert all(r['daily_average'] is None and r['coverage_days'] is None for r in job['inventory'])
    assert publish(client, project, job, False).json()['code'] == 'WARNINGS_UNCONFIRMED'
    assert publish(client, project, job).status_code == 200


@pytest.mark.parametrize('kind,mutate,expected', [
    ('inventory', lambda rows: rows.append(rows[0]), '重复记录'),
    ('inventory', lambda rows: rows[0].update(单位='箱'), '基础单位'),
    ('inventory', lambda rows: rows[0].update(物资编码='OTHER'), '不存在'),
    ('inventory', lambda rows: rows[0].update(科室='其他医院科室'), '不存在'),
    ('inventory', lambda rows: rows[0].update(在库数量='NaN'), '非负数'),
    ('inventory', lambda rows: rows[0].update(在库数量='-1'), '非负数'),
    ('inventory', lambda rows: rows[0].update(冻结数量='99999999'), '超过在库'),
    ('inventory', lambda rows: rows[0].update(在库数量='99999999'), '汇总不一致'),
    ('inventory', lambda rows: rows[0].update(记录时间='2026-09-29T09:00:00+08:00'), '晚于业务'),
    ('inventory', lambda rows: rows[0].update(记录时间='2026-09-27T09:00:00'), '包含时区'),
    ('batches', lambda rows: rows.append(rows[0]), '重复记录'),
    ('batches', lambda rows: rows[0].update(有效期='2026-02-30'), '日期不存在'),
    ('batches', lambda rows: rows[0].update(状态='待审核'), '仅支持'),
    ('consumption', lambda rows: rows.append(rows[0]), '重复记录'),
    ('consumption', lambda rows: rows[0].update(日期='2026-09-27'), '14个完整'),
])
def test_invalid_csv_blocks_publish(client, kind, mutate, expected):
    _, project, body = setup(client)
    edit(body, kind, mutate)
    job = upload(client, project, body).json()
    assert job['status'] == 'invalid', job
    assert any(expected in i['message'] for i in job['issues']), job['issues']
    assert publish(client, project, job).json()['code'] == 'IMPORT_INVALID'


def test_wrong_header_and_empty_file(client):
    _, project, body = setup(client)
    body['files']['inventory'] = ''
    body['files']['batches'] = 'bad,header\n1,2'
    job = upload(client, project, body).json()
    assert job['status'] == 'invalid'
    assert any(i['row'] == 1 for i in job['issues'])


def test_old_records_warn_and_removed_positions_explicit(client):
    _, project, body = setup(client)
    edit(body, 'inventory', lambda rows: rows[0].update(记录时间='2026-09-25T09:00:00+08:00'))
    job = upload(client, project, body).json()
    assert any('24小时' in i['message'] for i in job['issues'])
    assert any('STALE_SNAPSHOT' in r['quality_issues'] for r in job['inventory'])
    for kind in HEADERS:
        edit(body, kind, lambda rows: rows.__setitem__(slice(None), [r for r in rows if r['物资编码'] == 'SIM-P001']))
    job = upload(client, project, body, 'removed-test-key').json()
    assert job['status'] == 'ready', job['issues']
    assert any(r['kind'] == 'removed' for r in job['changes'])
    assert any('移除' in i['message'] for i in job['issues'])


def test_stale_base_and_conflicting_key(client):
    _, project, body = setup(client)
    first = upload(client, project, body).json()
    second = upload(client, project, body, 'second-import-key').json()
    changed = deepcopy(body); changed['as_of'] = '2026-09-28T09:00:00+08:00'
    assert upload(client, project, changed).json()['code'] == 'IDEMPOTENCY_CONFLICT'
    assert publish(client, project, first).status_code == 200
    assert publish(client, project, second).json()['code'] == 'SNAPSHOT_CHANGED'
    assert client.get(f'/api/v1/projects/{project}/imports/{second["id"]}').json()['stale']
    assert upload(client, project, body, 'third-import-key').json()['code'] == 'SNAPSHOT_CHANGED'


def test_permissions_and_cross_project(client, app):
    me, project, body = setup(client)
    job = upload(client, project, body).json()
    with app.state.factory() as db:
        db.get(Membership, (me['user']['id'], project)).role = 'reader'; db.commit()
    assert not client.get(f'/api/v1/projects/{project}/imports').json()['can_publish']
    assert upload(client, project, body).status_code == 403
    assert publish(client, project, job).status_code == 403
    other = register(client, 'second@example.test')['projects'][0]['id']
    assert client.get(f'/api/v1/projects/{project}/imports').status_code == 404
    assert client.get(f'/api/v1/projects/{other}/imports/{job["id"]}').status_code == 404
    assert publish(client, other, job).status_code == 404
    assert upload(client, other, body).status_code == 404


def test_timezone_normalization_and_backdating(client):
    _, project, body = setup(client)
    body['as_of'] = '2026-09-27T01:00:00+00:00'
    assert upload(client, project, body).json()['as_of'] == '2026-09-27T09:00:00+08:00'
    body['as_of'] = '2026-09-26T09:00:00+08:00'
    assert upload(client, project, body, 'backdate-test-key').json()['code'] == 'INVALID_AS_OF'


def test_concurrent_publish_only_one_winner(client, app):
    _, project, body = setup(client)
    jobs = [upload(client, project, body, f'concurrent-key-{i}').json() for i in range(2)]
    cookies, headers = dict(client.cookies), dict(client.headers)
    def submit(job):
        with TestClient(app) as c:
            c.cookies.update(cookies); c.headers.update(headers)
            return publish(c, project, job)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, jobs))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project)) == 2


def test_batch_expiry_change_is_visible_even_with_same_available_stock(client):
    _, project, body = setup(client)
    edit(body, 'batches', lambda rows: rows[0].update(有效期='2027-01-01'))
    job = upload(client, project, body).json()
    assert job['status'] == 'ready'
    assert any(r['kind'] == 'changed' and '批次数量、状态或效期变化' in r['details'] for r in job['changes'])


def test_zero_stock_publication_updates_inventory_and_risk(client):
    _, project, body = setup(client)
    for kind in ['inventory', 'batches']:
        edit(body, kind, lambda rows: [r.update(在库数量='0', 冻结数量='0', 预留数量='0') for r in rows if r['物资编码'] == 'SIM-P001'])
    job = upload(client, project, body).json()
    assert job['status'] == 'ready', job['issues']
    result = publish(client, project, job).json()
    dashboard = client.get(f'/api/v1/projects/{project}/dashboard').json()
    row = next(r for r in dashboard['inventory'] if r['item_id'] == 'SIM-P001')
    assert row['available'] == '0' and row['coverage_days'] == '0.0000'
    assert dashboard['snapshot_set_id'] == result['snapshot_id']
    report = client.get(f'/api/v1/projects/{project}/risks').json()
    assert any(r['item_id'] == 'SIM-P001' and r['kind'] == 'low_coverage' for r in report['findings'])


def test_completed_analysis_and_evidence_unchanged(client, app):
    from app.agent import work_once
    _, project, body = setup(client)
    run = create_run(client, project)
    work_once(app.state.factory, app.state.settings)
    result = client.get(f'/api/v1/runs/{run["run_id"]}').json()
    analysis_url = f'/api/v1/analyses/{result["analysis_id"]}'
    before = client.get(analysis_url).json()
    evidence_before = {c['evidence_id']: client.get(f'/api/v1/evidence/{c["evidence_id"]}').json() for c in before['citations']}
    job = upload(client, project, body).json()
    assert publish(client, project, job).status_code == 200
    assert client.get(analysis_url).json() == before
    assert evidence_before
    for eid, evidence in evidence_before.items():
        assert client.get(f'/api/v1/evidence/{eid}').json() == evidence


def test_utf8_byte_limit_and_line_limit(client):
    _, project, body = setup(client)
    body['files']['inventory'] = '中' * 3600000
    job = upload(client, project, body).json()
    assert any('10MB' in i['message'] for i in job['issues'])
    body['files']['inventory'] = ','.join(HEADERS['inventory']) + '\n' + 'x,x,x,0,0,0,x\n' * 10001
    job = upload(client, project, body, 'line-limit-test').json()
    assert any('10000' in i['message'] for i in job['issues'])


def test_more_than_one_mb_valid_csv_preview(client):
    _, project, body = setup(client)
    # Large UTF-8 CSV without expanding business row count: whitespace is trimmed by the validator.
    rows = list(csv.DictReader(io.StringIO(body['files']['inventory'].lstrip('\ufeff'))))
    for row in rows:
        for field in ['物资编码', '科室', '单位']:
            row[field] += ' ' * 120000
    body['files']['inventory'] = csv_text(HEADERS['inventory'], [[r[h] for h in HEADERS['inventory']] for r in rows])
    assert 1048576 < len(body['files']['inventory'].encode('utf-8')) < 10 * 1048576
    before = client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id']
    response = upload(client, project, body, 'large-valid-preview-key')
    assert response.status_code == 201
    assert response.json()['status'] == 'ready', response.json()['issues']
    assert client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id'] == before
