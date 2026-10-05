from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.models import CatalogEntry, Membership, DataImport, Snapshot
from app.imports import HEADERS, csv_text
from conftest import register
from test_imports import upload, publish


def setup(client):
    me = register(client)
    project = me['projects'][0]['id']
    return me, project, f'/api/v1/projects/{project}/catalog'


def payload(row, **changes):
    return {**{k: row[k] for k in ['code', 'name', 'base_unit', 'specification', 'active', 'revision']}, **changes}


def product(code='MAT-NEW', **changes):
    return {'code': code, 'name': '新增清洗液', 'specification': '500mL', 'base_unit': '瓶', 'active': True, **changes}


def test_initialize_once_from_current_snapshot_and_preserve_ids(client, app):
    _, project, url = setup(client)
    products = client.get(url+'/products').json()
    departments = client.get(url+'/departments').json()
    assert products['can_edit'] and len(products['items']) == 24
    assert departments['items'] and departments['items'][0]['code'].startswith('DEP-')
    assert client.get(url+'/products').json() == products
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(CatalogEntry).where(CatalogEntry.project_id == project)) == 27
        assert db.scalar(select(CatalogEntry).where(CatalogEntry.project_id == project, CatalogEntry.code == 'SIM-P001')).source_id == 'SIM-P001'


def test_create_edit_deactivate_restore_history(client):
    _, _, url = setup(client)
    created = client.post(url+'/products', json=product(code='  mat-new  '))
    assert created.status_code == 201, created.text
    row = created.json(); path = url+'/products/'+row['id']
    assert row['code'] == 'MAT-NEW' and not row['unit_locked']
    edited = client.put(path, json=payload(row, name='更名清洗液', base_unit='支')).json()
    assert edited['revision'] == 2 and edited['base_unit'] == '支'
    disabled = client.put(path, json=payload(edited, active=False)).json()
    assert not disabled['active']
    restored = client.put(path, json=payload(disabled, active=True)).json()
    assert restored['active'] and [h['action'] for h in restored['history']] == ['新增', '编辑', '停用', '启用']
    assert client.get(path).json() == restored


@pytest.mark.parametrize('change', [{'code': 'ＡＢＣ'}, {'code': ' abc '}, {'code': 'AbC'}])
def test_duplicate_code_normalization_including_disabled(client, change):
    _, _, url = setup(client)
    assert client.post(url+'/products', json=product('ABC', active=False)).status_code == 201
    response = client.post(url+'/products', json=product(**change))
    assert response.status_code == 409 and response.json()['code'] == 'CATALOG_DUPLICATE'


def test_department_unique_name_and_product_names_can_repeat(client):
    _, _, url = setup(client)
    assert client.post(url+'/departments', json={'code': 'D-A', 'name': ' 新科室 '}).status_code == 201
    assert client.post(url+'/departments', json={'code': 'D-B', 'name': '新科室', 'active': False}).status_code == 409
    assert client.post(url+'/products', json=product('A')).status_code == 201
    assert client.post(url+'/products', json=product('B')).status_code == 201


@pytest.mark.parametrize('changes', [{'name': '  '}, {'code': '=CMD'}, {'code': 'A B'}, {'name': '=危险公式'}, {'base_unit': ''}, {'name': '含\n换行'}, {'name': '\u200b'}, {'name': '㍿' * 30}])
def test_invalid_values(client, changes):
    _, _, url = setup(client)
    assert client.post(url+'/products', json=product(**changes)).status_code == 422


def test_unit_locked_and_history_unchanged(client):
    _, project, url = setup(client)
    old = client.get(f'/api/v1/projects/{project}/inventory').json()
    row = client.get(url+'/products').json()['items'][0]
    assert row['unit_locked']
    path = url+'/products/'+row['id']
    assert client.put(path, json=payload(row, base_unit='箱')).json()['code'] == 'UNIT_IN_USE'
    result = client.put(path, json=payload(row, name='新名称', specification='新规格')).json()
    assert result['name'] == '新名称'
    assert client.get(f'/api/v1/projects/{project}/inventory').json() == old


def test_conflict_and_permissions(client, app):
    me, project, url = setup(client)
    row = client.get(url+'/products').json()['items'][0]
    path = url+'/products/'+row['id']
    assert client.put(path, json=payload(row, name='更新名称')).status_code == 200
    assert client.put(path, json=payload(row, name='旧版本覆盖')).json()['code'] == 'CATALOG_CHANGED'
    with app.state.factory() as db:
        db.get(Membership, (me['user']['id'], project)).role = 'reader'; db.commit()
    assert not client.get(url+'/products').json()['can_edit']
    assert client.post(url+'/products', json=product()).status_code == 403
    assert client.put(path, json=payload(row)).status_code == 403
    other = register(client, 'other@example.test')['projects'][0]['id']
    assert client.get(path).status_code == 404
    assert client.get(f'/api/v1/projects/{other}/catalog/products/{row["id"]}').status_code == 404
    assert client.put(f'/api/v1/projects/{other}/catalog/products/{row["id"]}', json=payload(row)).status_code == 404


def test_catalog_edit_invalidates_previews_and_template_refresh(client):
    _, project, url = setup(client)
    body = client.get(f'/api/v1/projects/{project}/import-template').json()
    old = client.get(f'/api/v1/projects/{project}/inventory').json()
    job = upload(client, project, body).json()
    row = client.get(url+'/departments').json()['items'][0]
    path = url+'/departments/'+row['id']
    assert client.put(path, json=payload(row, name='更名科室')).status_code == 200
    assert publish(client, project, job).json()['code'] == 'CATALOG_CHANGED'
    assert client.get(f'/api/v1/projects/{project}/imports/{job["id"]}').json()['stale']
    assert upload(client, project, body, 'stale-catalog-key').json()['code'] == 'CATALOG_CHANGED'
    fresh = client.get(f'/api/v1/projects/{project}/import-template').json()
    assert '更名科室' in fresh['files']['inventory']
    assert fresh['catalog_hash'] != body['catalog_hash']
    new = upload(client, project, fresh, 'fresh-catalog-key').json()
    assert new['status'] == 'ready' and any('物资或科室档案变化' in c['details'] for c in new['changes'])
    assert publish(client, project, new).status_code == 200
    assert client.get(f'/api/v1/projects/{project}/inventory?snapshot_set_id={old["snapshot_set_id"]}').json() == old


def test_disabled_entry_blocks_new_import_but_keeps_stock(client):
    _, project, url = setup(client)
    old = client.get(f'/api/v1/projects/{project}/inventory').json()
    row = client.get(url+'/products').json()['items'][0]
    path = url+'/products/'+row['id']
    disabled = client.put(path, json=payload(row, active=False)).json()
    body = client.get(f'/api/v1/projects/{project}/import-template').json()
    job = upload(client, project, body).json()
    assert job['status'] == 'invalid' and any('已停用' in i['message'] for i in job['issues'])
    assert client.get(f'/api/v1/projects/{project}/inventory').json() == old
    assert client.put(path, json=payload(disabled, active=True)).status_code == 200
    fresh = client.get(f'/api/v1/projects/{project}/import-template').json()
    assert upload(client, project, fresh, 'reactivated-key').json()['status'] == 'ready'


def test_new_product_department_import_and_publish(client):
    _, project, url = setup(client)
    created = client.post(url+'/products', json=product()).json()
    assert client.post(url+'/departments', json={'code': 'DEP-NEW', 'name': '新检验科'}).status_code == 201
    body = client.get(f'/api/v1/projects/{project}/import-template').json()
    data = {'inventory': [['MAT-NEW', '新检验科', '瓶', '14', '0', '0', body['as_of']]], 'batches': [['LOT-NEW', 'MAT-NEW', '新检验科', '瓶', '14', '0', '0', '2027-01-01', '可用']], 'consumption': [['MAT-NEW', '新检验科', '瓶', f'2026-09-{day:02d}', '1'] for day in range(13, 27)]}
    body['files'] = {k: csv_text(HEADERS[k], rows) for k, rows in data.items()}
    job = upload(client, project, body).json()
    assert job['status'] == 'ready', job
    assert job['inventory'][0]['name'] == created['name'] and job['inventory'][0]['coverage_days'] == '14.0000'
    assert publish(client, project, job).status_code == 200
    assert client.get(url+'/products/'+created['id']).json()['unit_locked']
    assert client.get(f'/api/v1/projects/{project}/inventory').json()['items'][0]['department_name'] == '新检验科'


def test_legacy_candidate_requires_revalidation(client, app):
    _, project, url = setup(client)
    body = client.get(f'/api/v1/projects/{project}/import-template').json()
    job = upload(client, project, body).json()
    with app.state.factory() as db:
        row = db.get(DataImport, job['id']); facts = deepcopy(row.facts); del facts['import_provenance']['catalog_hash']; row.facts = facts; db.commit()
    assert publish(client, project, job).json()['code'] == 'CATALOG_CHANGED'


def test_concurrent_edits_have_one_winner(client, app):
    _, _, url = setup(client)
    row = client.get(url+'/products').json()['items'][0]
    path = url+'/products/'+row['id']
    cookies, headers = dict(client.cookies), dict(client.headers)
    def edit(name):
        with TestClient(app) as c:
            c.cookies.update(cookies); c.headers.update(headers)
            return c.put(path, json=payload(row, name=name))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ['并发名称一', '并发名称二']))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]


def test_duplicate_update_rolls_back_and_audit_keeps_actor_id(client):
    me, _, url = setup(client)
    row = client.post(url+'/products', json=product('NEW-A')).json()
    other = client.post(url+'/products', json=product('NEW-B')).json()
    path = url+'/products/'+row['id']
    assert client.put(path, json=payload(row, code=other['code'])).status_code == 409
    result = client.get(path).json()
    assert result['revision'] == row['revision'] and result['code'] == 'NEW-A'
    assert result['history'][0]['actor_id'] == me['user']['id']
