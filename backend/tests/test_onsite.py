from copy import deepcopy
from sqlalchemy import select, func
from app.onsite import build, publish
from app.data import snapshot_for, inventory
from app.models import Project, Snapshot, CatalogEntry, Document
from app.versions import activate
from app.imports import template, validate
from app.import_schemas import ImportRequest
from app.knowledge import search
from conftest import register


def test_publish_preserves_history_is_idempotent_and_importable(client, app):
    project_id = register(client)['projects'][0]['id']
    with app.state.factory() as db:
        base = snapshot_for(db, project_id)
        original = deepcopy(base.facts)
        base_id = base.id
        result = publish(db, [project_id])
        db.commit()
        assert result[0]['counts']['inventory_snapshots'] == 18
        current = snapshot_for(db, project_id)
        assert current.id != base_id and current.as_of == base.as_of
        assert db.get(Snapshot, base_id).facts == original
        assert len(current.facts['products']) == len(original['products']) + 12
        new = [r for r in inventory(current) if r['item_id'].startswith('ONS-')]
        assert len(new) == 18 and all(r['observed_days'] == 14 and not r['quality_issues'] for r in new)
        assert len([r for r in new if float(r['coverage_days']) < 7]) >= 4
        body = ImportRequest.model_validate(template(current))
        report = validate(body, current, db.get(Project, project_id))
        assert report[2]['error_count'] == 0
        assert db.scalar(select(func.count()).select_from(CatalogEntry).where(CatalogEntry.project_id == project_id, CatalogEntry.source_id.like('ONS-P%'))) == 12
        assert search(db, project_id, '驻场交接采集重症医学科')
        count = db.scalar(select(func.count()).select_from(Snapshot))
        assert publish(db, [project_id]) == [{'project_id': project_id, 'added': False}]
        db.commit()
        assert db.scalar(select(func.count()).select_from(Snapshot)) == count
        activate(db, project_id, base_id, current.id, 'restore', reason='验收历史数据回退')
        db.commit()
        assert not publish(db, [project_id])[0]['added']
        assert snapshot_for(db, project_id).id == base_id


def test_other_project_is_untouched(client, app):
    first = register(client)['projects'][0]['id']
    other = register(client, 'onsite-other@example.test')['projects'][0]['id']
    with app.state.factory() as db:
        original = snapshot_for(db, other).id
        publish(db, [first]); db.commit()
        assert snapshot_for(db, other).id == original
        assert db.scalar(select(func.count()).select_from(Document).where(Document.project_id == other, Document.external_id.like('ONS-%'))) == 0


def test_hospital_and_business_time_are_bound():
    facts = build('SIM-HB', '2026-10-02T09:00:00+08:00')
    assert len(facts['consumption_daily']) == 252
    assert all(r['hospital_id'] == 'SIM-HB' for r in facts['inventory_snapshots'])
    assert max(r['date'] for r in facts['consumption_daily']) == '2026-10-01'
    assert min(r['date'] for r in facts['consumption_daily']) == '2026-09-18'
