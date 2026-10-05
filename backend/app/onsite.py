"""Additive fictional hospital onsite collection release; no inventory write-back."""
import json
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import select
from .catalog import lock_project, ensure_catalog, entries, iso
from .data import canonical_hash, snapshot_for
from .models import Project, Snapshot, CatalogEntry
from .versions import activate
from .knowledge import ingest

RELEASE = 'onsite-20260929-v1'
BUNDLE = Path(__file__).resolve().parents[2] / 'data' / 'hospital-onsite'
PRODUCTS = [
 ('一次性输液器', '套', '单支独立包装', 'ER'),
 ('静脉留置针', '支', '24G', 'ER'),
 ('无菌注射器', '支', '10 mL', 'ICU'),
 ('吸痰管', '根', '12Fr', 'ICU'),
 ('医用隔离衣', '件', 'L号', 'ICU'),
 ('一次性使用透析器', '支', '1.6平方米', 'HD'),
 ('血液透析管路', '套', '成人型', 'HD'),
 ('血透穿刺针', '支', '16G', 'HD'),
 ('无菌纱布块', '包', '10×10 cm，5片/包', 'CSSD'),
 ('灭菌指示胶带', '卷', '19 mm×50 m', 'CSSD'),
 ('鼻氧管', '根', '成人型', 'WARD'),
 ('医用护理垫', '片', '60×90 cm', 'WARD'),
]
DEPARTMENTS = {'ICU': '重症医学科', 'HD': '血液透析室', 'CSSD': '消毒供应中心', 'WARD': '内科病区'}


def build(hospital, as_of):
    day = datetime.fromisoformat(as_of).date()
    provenance = {'synthetic': True, 'source_type': 'generated_hospital_onsite_scenario', 'release': RELEASE, 'real_company_data': False}
    facts = {k: [] for k in ['products', 'departments', 'inventory_snapshots', 'inventory_batches', 'consumption_daily']}
    for suffix, name in DEPARTMENTS.items():
        facts['departments'].append(dict(id=f'{hospital}-ONS-{suffix}', hospital_id=hospital, code=f'ONS-{suffix}', name=name, **provenance))
    for n, (name, unit, spec, _) in enumerate(PRODUCTS, 1):
        facts['products'].append(dict(id=f'ONS-P{n:03}', display_code=f'ONS-{n:04}', name=name, base_unit=unit, specification=spec, purchase_unit=unit, units_per_purchase_pack=1, category='驻场耗材', registration_number=None, real_world_use=False, **provenance))
    # Twelve primary placements and six shared consumables at a second department.
    placements = [(n, p[3]) for n, p in enumerate(PRODUCTS, 1)] + [(1, 'WARD'), (2, 'ICU'), (3, 'ER'), (5, 'HD'), (9, 'WARD'), (11, 'ICU')]
    for i, (n, dept) in enumerate(placements):
        product = facts['products'][n-1]
        dept_id = f'{hospital}-ER' if dept == 'ER' else f'{hospital}-ONS-{dept}'
        identity = dict(hospital_id=hospital, product_id=product['id'], department_id=dept_id, base_unit=product['base_unit'], **provenance)
        daily = 8 + (i % 5) * 4
        on = daily * ([3, 12, 18, 24][i % 4])
        frozen, reserved = (daily if i % 6 == 2 else 0), (daily if i % 5 == 1 else 0)
        batch_ids = []
        for j in range(2):
            batch_id = f'ONS-LOT-{hospital}-{n:03}-{dept}-{j+1}'
            batch_ids.append(batch_id)
            facts['inventory_batches'].append(dict(identity, id=batch_id, on_hand_base=on//2, frozen_base=frozen if j == 0 else 0, reserved_base=reserved if j == 1 else 0, expiry_date=(day+timedelta(days=12 if j == 0 and i % 4 == 2 else 240+j*90)).isoformat(), status='released', snapshot_at=as_of))
        facts['inventory_snapshots'].append(dict(identity, id=f'ONS-POS-{hospital}-{n:03}-{dept}', on_hand_base=on, frozen_base=frozen, reserved_base=reserved, available_base=on-frozen-reserved, batch_ids=batch_ids, snapshot_at=as_of, supplier_lead_days=7))
        for offset in range(14, 0, -1):
            date = (day-timedelta(days=offset)).isoformat()
            facts['consumption_daily'].append(dict(identity, id=f'ONS-USE-{hospital}-{n:03}-{dept}-{date}', date=date, quantity_base=daily+(offset%3-1)*2, record_type='confirmed_consumption'))
    return facts


def publish(db, project_ids=None):
    result = []
    query = select(Project).where(Project.synthetic.is_(True))
    if project_ids:
        query = query.where(Project.id.in_(project_ids))
    for project in db.scalars(query):
        if project.source_hospital not in {'SIM-HA', 'SIM-HB'}:
            continue
        lock_project(db, project.id)
        base = snapshot_for(db, project.id)
        # A release is applied once per project, even after manual restoration.
        already = any(s.facts.get('onsite_release') == RELEASE for s in db.scalars(select(Snapshot).where(Snapshot.project_id == project.id)))
        if already:
            result.append({'project_id': project.id, 'added': False})
            continue
        ensure_catalog(db, project.id)
        addition = build(project.source_hospital, base.as_of)
        catalog = entries(db, project.id)
        for kind in ['products', 'departments']:
            for row in addition[kind]:
                code = row.get('display_code', row.get('code'))
                if any(c.kind == kind and (c.source_id == row['id'] or c.code == code or kind == 'departments' and c.name.casefold() == row['name'].casefold()) for c in catalog):
                    raise ValueError(f'驻场数据与已有目录冲突：{code}；未发布')
                db.add(CatalogEntry(project_id=project.id, kind=kind, source_id=row['id'], code=code, name=row['name'], specification=row.get('specification',''), base_unit=row.get('base_unit',''), active=True, department_name_key=row['name'].casefold() if kind == 'departments' else None, source_metadata={'original': row, 'release': RELEASE}, history=[{'at': iso(time.time()), 'actor': '系统', 'action': '驻场场景补充', 'before': {}, 'after': {'code': code, 'name': row['name']}}]))
        facts = deepcopy(base.facts)
        for table, rows in addition.items():
            old_ids = {r['id'] for r in facts[table]}
            if any(r['id'] in old_ids for r in rows):
                raise ValueError(f'驻场数据行号冲突：{table}')
            facts[table].extend(rows)
        facts['onsite_release'] = RELEASE
        facts['onsite_provenance'] = {'synthetic': True, 'real_company_data': False, 'source': 'generated_hospital_onsite_scenario', 'business_as_of': base.as_of}
        snapshot = Snapshot(project_id=project.id, as_of=base.as_of, facts=facts, source_hash=canonical_hash(facts))
        db.add(snapshot)
        db.flush()
        activate(db, project.id, snapshot.id, base.id, 'scenario', reason='补充医院驻场场景数据，保留原业务时点及历史记录')
        documents = ingest(db, project, BUNDLE / 'manifest.json')
        result.append({'project_id': project.id, 'added': True, 'snapshot_id': snapshot.id, 'as_of': snapshot.as_of, 'counts': {k: len(v) for k,v in addition.items()}, 'documents_added': documents})
    db.flush()
    return result
