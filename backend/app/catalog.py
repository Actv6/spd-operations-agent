"""Project master data; snapshot facts are never rewritten by catalog changes."""
from copy import deepcopy
from datetime import datetime, timezone
import time
import unicodedata
from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .models import CatalogEntry, Project, Snapshot, Membership, uid
from .auth import require_project
from .data import snapshot_for, canonical_hash
from .errors import AppError
from .catalog_schemas import CatalogKind, CatalogWrite, CatalogUpdate, CatalogView, CatalogDetail, CatalogList

FIELDS = ['code', 'name', 'specification', 'base_unit', 'active']


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def editable(db, user_id, project_id):
    member = db.get(Membership, (user_id, project_id))
    return bool(member and member.role in {'owner', 'demo_owner'})


def editor(db, user_id, project_id):
    project = require_project(db, user_id, project_id)
    if not editable(db, user_id, project_id):
        raise AppError('FORBIDDEN', '当前账号没有主数据维护权限', 403)
    return project


def lock_project(db, project_id):
    # Same lock as snapshot publishing: catalog edits and publication must serialize.
    db.execute(update(Project).where(Project.id == project_id).values(name=Project.name))


def entries(db, project_id):
    return list(db.scalars(select(CatalogEntry).where(CatalogEntry.project_id == project_id).order_by(CatalogEntry.kind, CatalogEntry.code).execution_options(populate_existing=True)))


def ensure_catalog(db, project_id):
    if db.scalar(select(CatalogEntry.id).where(CatalogEntry.project_id == project_id).limit(1)):
        return
    lock_project(db, project_id)
    if db.scalar(select(CatalogEntry.id).where(CatalogEntry.project_id == project_id).limit(1)):
        return
    base = snapshot_for(db, project_id)
    for kind in ['products', 'departments']:
        for index, source in enumerate(base.facts[kind], 1):
            name = unicodedata.normalize('NFKC', source['name']).strip()
            code = source.get('display_code', source['id']) if kind == 'products' else source.get('code', f'DEP-{index:03d}')
            db.add(CatalogEntry(project_id=project_id, kind=kind, source_id=source['id'], code=code.upper(), name=name,
                department_name_key=name.casefold() if kind == 'departments' else None,
                specification=source.get('specification', ''), base_unit=source.get('base_unit', ''), active=True,
                source_metadata={'source_snapshot_id': base.id, 'original': deepcopy(source)},
                history=[{'at': iso(time.time()), 'actor': '系统', 'action': '从现有快照初始化', 'before': {}, 'after': {'code': code, 'name': name}}]))
    db.flush()


def fingerprint(rows):
    return canonical_hash(sorted([[r.id, r.revision] for r in rows]))


def frozen_catalog(rows, hospital):
    result = {'products': [], 'departments': []}
    for r in rows:
        original = deepcopy(r.source_metadata.get('original', {}))
        original.update(id=r.source_id, name=r.name, active=r.active)
        if r.kind == 'products':
            original.update(display_code=r.code, specification=r.specification, base_unit=r.base_unit)
        else:
            original.update(code=r.code, hospital_id=hospital)
        result[r.kind].append(original)
    return result


def used_products(db, project_id):
    return {p['product_id'] for facts in db.scalars(select(Snapshot.facts).where(Snapshot.project_id == project_id)) for p in facts['inventory_snapshots']}


def view(row, used, detail=False):
    result = {k: getattr(row, k) for k in FIELDS + ['id', 'kind', 'revision']}
    result.update(unit_locked=row.kind == 'products' and row.source_id in used, updated_at=iso(row.updated_at))
    if detail:
        result['history'] = row.history
    return result


def check_kind(body, kind):
    if kind == 'products' and not body.base_unit:
        raise AppError('INVALID_CATALOG', '物资基础单位不能为空', 422)
    if kind == 'departments' and (body.base_unit or body.specification):
        raise AppError('INVALID_CATALOG', '科室不应设置物资单位或规格', 422)


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError('CATALOG_DUPLICATE', '编码已存在，或科室名称重复（包含已停用记录）', 409)


def register_routes(app, db_dep, user_dep):
    def get_entry(db, project_id, kind, entry_id):
        row = db.get(CatalogEntry, entry_id, populate_existing=True)
        if not row or row.project_id != project_id or row.kind != kind:
            raise AppError('NOT_FOUND', '档案不存在或不可访问', 404)
        return row

    @app.get('/api/v1/projects/{project_id}/catalog/{kind}', response_model=CatalogList)
    def list_entries(project_id: str, kind: CatalogKind, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        ensure_catalog(db, project_id)
        db.commit()
        rows = entries(db, project_id)
        used = used_products(db, project_id) if kind == 'products' else set()
        return {'items': [view(r, used) for r in rows if r.kind == kind], 'can_edit': editable(db, user.id, project_id), 'catalog_hash': fingerprint(rows)}

    @app.get('/api/v1/projects/{project_id}/catalog/{kind}/{entry_id}', response_model=CatalogDetail)
    def read_entry(project_id: str, kind: CatalogKind, entry_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return view(get_entry(db, project_id, kind, entry_id), used_products(db, project_id), True)

    @app.post('/api/v1/projects/{project_id}/catalog/{kind}', response_model=CatalogDetail, status_code=201)
    def create_entry(project_id: str, kind: CatalogKind, body: CatalogWrite, user=Depends(user_dep), db=Depends(db_dep)):
        editor(db, user.id, project_id)
        check_kind(body, kind)
        lock_project(db, project_id)
        ensure_catalog(db, project_id)
        values = body.model_dump()
        row = CatalogEntry(project_id=project_id, kind=kind, source_id=uid(), **values,
            department_name_key=body.name.casefold() if kind == 'departments' else None,
            source_metadata={'kind': 'user_master_data'},
            history=[{'at': iso(time.time()), 'actor': user.display_name, 'actor_id': user.id, 'action': '新增', 'before': {}, 'after': values}])
        db.add(row)
        commit(db)
        return view(row, set(), True)

    @app.put('/api/v1/projects/{project_id}/catalog/{kind}/{entry_id}', response_model=CatalogDetail)
    def edit_entry(project_id: str, kind: CatalogKind, entry_id: str, body: CatalogUpdate, user=Depends(user_dep), db=Depends(db_dep)):
        editor(db, user.id, project_id)
        check_kind(body, kind)
        lock_project(db, project_id)
        row = get_entry(db, project_id, kind, entry_id)
        if row.revision != body.revision:
            raise AppError('CATALOG_CHANGED', '该档案已被更新，请重新读取后修改', 409)
        used = used_products(db, project_id)
        if row.kind == 'products' and row.source_id in used and row.base_unit != body.base_unit:
            raise AppError('UNIT_IN_USE', '该物资已用于库存快照，基础单位不能直接修改；请为另一基础单位新建物资编码', 409)
        before = {k: getattr(row, k) for k in FIELDS}
        after = body.model_dump(exclude={'revision'})
        if before != after:
            action = '停用' if row.active and not body.active else '启用' if not row.active and body.active else '编辑'
            for k, value in after.items():
                setattr(row, k, value)
            row.department_name_key = row.name.casefold() if kind == 'departments' else None
            row.revision += 1
            row.updated_at = time.time()
            row.history = [*row.history, {'at': iso(row.updated_at), 'actor': user.display_name, 'actor_id': user.id, 'action': action, 'before': before, 'after': after}]
        commit(db)
        return view(row, used, True)
