"""Fixed-schema CSV validation and manual, transactional snapshot publication."""
import csv
import io
import re
import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from fastapi import Depends, Header, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .auth import require_project
from .data import canonical_hash, inventory, snapshot_for
from .errors import AppError
from .models import DataImport, Membership, Project, Snapshot, User, uid
from .catalog import ensure_catalog, entries, fingerprint, frozen_catalog, lock_project
from .import_schemas import IMPORT_MAX_BYTES, ImportRequest, ImportPublish, ImportList, ImportView, ImportTemplate

from .versions import publication_revision, activate

TZ = timezone(timedelta(hours=8))
HEADERS = {
    'inventory': ['物资编码', '科室', '单位', '在库数量', '冻结数量', '预留数量', '记录时间'],
    'batches': ['批次编号', '物资编码', '科室', '单位', '在库数量', '冻结数量', '预留数量', '有效期', '状态'],
    'consumption': ['物资编码', '科室', '单位', '日期', '消耗数量'],
}
STATUSES = {'可用': 'released', '冻结': 'held', '过期隔离': 'quarantined_expired'}
QUANTITIES = {'在库数量': 'on_hand_base', '冻结数量': 'frozen_base', '预留数量': 'reserved_base'}


def calendar_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError('日期不存在或格式不正确，请使用 YYYY-MM-DD')


def timestamp(value):
    # Do not silently interpret timezone-less timestamps in the server's timezone.
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('时间格式不正确，请使用带时区的日期时间')
    if parsed.tzinfo is None or parsed.microsecond:
        raise ValueError('时间须包含时区且精确到秒，例如 2026-09-27T09:00:00+08:00')
    return parsed.astimezone(TZ).isoformat(timespec='seconds')


def can_publish(db, user_id, project_id):
    member = db.get(Membership, (user_id, project_id))
    return bool(member and member.role in {'owner', 'demo_owner'})


def require_editor(db, user_id, project_id):
    project = require_project(db, user_id, project_id)
    if not can_publish(db, user_id, project_id):
        raise AppError('FORBIDDEN', '当前账号没有数据发布权限', 403)
    return project


def csv_text(headers, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return '\ufeff' + stream.getvalue()


def template(snapshot, catalog=None, catalog_hash=None):
    products = {p['id']: p for p in (catalog or snapshot.facts)['products']}
    departments = {d['id']: d['name'] for d in (catalog or snapshot.facts)['departments']}
    day = datetime.fromisoformat(snapshot.as_of).date()
    def identity(r):
        p = products[r['product_id']]
        return [p.get('display_code', p['id']), departments[r['department_id']], p['base_unit']]
    files = {
        'inventory': csv_text(HEADERS['inventory'], [identity(r) + [r[k] for k in QUANTITIES.values()] + [r['snapshot_at']] for r in snapshot.facts['inventory_snapshots']]),
        'batches': csv_text(HEADERS['batches'], [[r['id']] + identity(r) + [r[k] for k in QUANTITIES.values()] + [r['expiry_date'], next(label for label, value in STATUSES.items() if value == r['status'])] for r in snapshot.facts['inventory_batches']]),
        'consumption': csv_text(HEADERS['consumption'], [identity(r) + [r['date'], r['quantity_base']] for r in snapshot.facts['consumption_daily'] if (day - timedelta(days=14)).isoformat() <= r['date'] < day.isoformat()]),
    }
    return {'base_snapshot_id': snapshot.id, 'as_of': snapshot.as_of, 'files': files, 'catalog_hash': catalog_hash}


def validate(body, base, project, catalog=None):
    issues = []
    def issue(file, row, message, severity='error'):
        issues.append({'file': file, 'row': row, 'severity': severity, 'message': message})
    try:
        as_of = timestamp(body.as_of)
        if datetime.fromisoformat(as_of) < datetime.fromisoformat(base.as_of):
            raise ValueError('业务时点不能早于当前快照')
    except (ValueError, OverflowError):
        raise AppError('INVALID_AS_OF', '业务时点须带时区、精确到秒且不早于当前快照', 422)
    day = datetime.fromisoformat(as_of).date()
    facts = {'products': deepcopy((catalog or base.facts)['products']), 'departments': deepcopy((catalog or base.facts)['departments']), 'inventory_snapshots': [], 'inventory_batches': [], 'consumption_daily': []}
    products = {}
    for p in facts['products']:
        products.setdefault(p.get('display_code', p['id']), []).append(p)
    departments = {}
    for d in facts['departments']:
        departments.setdefault(d['name'], []).append(d)
    seen = {k: set() for k in HEADERS}
    row_numbers = {}
    for file, headers in HEADERS.items():
        content = getattr(body.files, file)
        if len(content.encode('utf-8')) > IMPORT_MAX_BYTES:
            issue(file, None, '文件超过10MB限制'); continue
        try:
            reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff'), newline=''), strict=True)
            if reader.fieldnames is None or len(reader.fieldnames) != len(headers) or set(reader.fieldnames) != set(headers):
                issue(file, 1, '表头不符合模板：' + '、'.join(headers)); continue
            for index, raw in enumerate(reader, 2):
                if index > 10001:
                    issue(file, None, '文件超过10000行限制'); break
                try:
                    if None in raw or any(v is None for v in raw.values()):
                        raise ValueError('列数与表头不一致')
                    r = {k: v.strip() for k, v in raw.items()}
                    if any(not v or len(v) > 100 for v in r.values()):
                        raise ValueError('字段不能为空或超过100字符')
                    ps, ds = products.get(r['物资编码'].upper(), []), departments.get(r['科室'], [])
                    if len(ps) != 1 or len(ds) != 1:
                        raise ValueError('物资编码或科室不存在，或名称存在歧义；请到物资档案/科室目录核对后重新下载模板')
                    p, d = ps[0], ds[0]
                    if not p.get('active', True) or not d.get('active', True):
                        raise ValueError('物资或科室已停用；请从完整导入文件移除对应记录，或在目录中重新启用')
                    if r['单位'] != p['base_unit']:
                        raise ValueError('单位与物资基础单位不一致；请先换算')
                    pair = (p['id'], d['id'])
                    normalized = {'id': uid(), 'hospital_id': project.source_hospital, 'product_id': p['id'], 'department_id': d['id'], 'base_unit': p['base_unit']}
                    for label, key in (QUANTITIES.items() if file != 'consumption' else [('消耗数量', 'quantity_base')]):
                        if not re.fullmatch(r'\d{1,12}(\.\d{1,4})?', r[label]):
                            raise ValueError(label + '须为非负数，最多12位整数、4位小数')
                        normalized[key] = str(Decimal(r[label]))
                    if file != 'consumption' and Decimal(normalized['frozen_base']) + Decimal(normalized['reserved_base']) > Decimal(normalized['on_hand_base']):
                        raise ValueError('冻结数量与预留数量之和超过在库数量')
                    if file == 'inventory':
                        key = pair
                        normalized['snapshot_at'] = timestamp(r['记录时间'])
                        age = datetime.fromisoformat(as_of) - datetime.fromisoformat(normalized['snapshot_at'])
                        if age < timedelta():
                            raise ValueError('记录时间不能晚于业务时点')
                        if age > timedelta(hours=24):
                            issue(file, index, '库存记录超过24小时；发布后暂停此项覆盖估算', 'warning')
                        target = 'inventory_snapshots'
                    elif file == 'batches':
                        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', r['批次编号']):
                            raise ValueError('批次编号须为字母、数字、点、横线或下划线，且以字母或数字开头')
                        key = r['批次编号']
                        normalized['id'] = key
                        normalized['expiry_date'] = calendar_day(r['有效期'])
                        if r['状态'] not in STATUSES:
                            raise ValueError('状态仅支持可用、冻结、过期隔离')
                        normalized.update(status=STATUSES[r['状态']], snapshot_at=as_of)
                        target = 'inventory_batches'
                    else:
                        normalized['date'] = calendar_day(r['日期'])
                        if not (day - timedelta(days=14)).isoformat() <= normalized['date'] < day.isoformat():
                            raise ValueError('消耗日期须位于业务时点前14个完整自然日内')
                        key = (*pair, normalized['date'])
                        normalized['record_type'] = 'confirmed_consumption'
                        target = 'consumption_daily'
                    if key in seen[file]:
                        raise ValueError('重复记录：库存组合、批次编号或每日消耗必须唯一')
                    seen[file].add(key)
                    facts[target].append(normalized)
                    row_numbers[normalized['id']] = index
                except (ValueError, OverflowError) as exc:
                    issue(file, index, str(exc) if str(exc) else '日期或时间格式不正确')
        except csv.Error:
            issue(file, None, 'CSV引号或字段格式不正确')
    positions = {(r['product_id'], r['department_id']): r for r in facts['inventory_snapshots']}
    if not positions:
        issue('inventory', None, '至少需要一个有效库存组合')
    for file, target in [('batches', 'inventory_batches'), ('consumption', 'consumption_daily')]:
        for r in facts[target]:
            if (r['product_id'], r['department_id']) not in positions:
                issue(file, row_numbers[r['id']], '该物资科室组合不在本次库存文件中')
    for pair, r in positions.items():
        batches = [b for b in facts['inventory_batches'] if (b['product_id'], b['department_id']) == pair]
        if not batches:
            issue('inventory', row_numbers[r['id']], '该库存组合缺少批次明细')
        elif any(sum((Decimal(b[k]) for b in batches), Decimal(0)) != Decimal(r[k]) for k in QUANTITIES.values()):
            issue('inventory', row_numbers[r['id']], '在库/冻结/预留数量与批次汇总不一致')
        r['batch_ids'] = [b['id'] for b in batches]
        count = sum((u['product_id'], u['department_id']) == pair for u in facts['consumption_daily'])
        if count < 14:
            issue('inventory', row_numbers[r['id']], f'消耗记录仅{count}/14天，缺日不补零；发布后暂停此项覆盖估算', 'warning')
    removed = {(r['product_id'], r['department_id']) for r in base.facts['inventory_snapshots']} - positions.keys()
    if removed:
        issue('inventory', None, f'整份替换将移除原快照中的{len(removed)}个物资科室组合，请核对差异清单', 'warning')
    errors = sum(i['severity'] == 'error' for i in issues)
    candidate = Snapshot(id='preview', as_of=as_of, facts=facts)
    rows = inventory(candidate) if not errors else []
    before = {(r['item_id'], r['department_id']): r for r in inventory(base)}
    after = {(r['item_id'], r['department_id']): r for r in rows}
    changes = []
    def records(source, table, pair):
        fields = ['id', 'expiry_date', 'status', 'on_hand_base', 'frozen_base', 'reserved_base'] if table == 'inventory_batches' else ['date', 'quantity_base', 'record_type']
        result = []
        for r in source[table]:
            if (r['product_id'], r['department_id']) != pair:
                continue
            if table == 'consumption_daily' and not (day - timedelta(days=14)).isoformat() <= r['date'] < day.isoformat():
                continue
            result.append([str(Decimal(str(r[k])).normalize()) if k.endswith('_base') else r[k] for k in fields])
        return sorted(result)
    if not errors:
        for pair in sorted(before.keys() | after.keys()):
            b, a = before.get(pair), after.get(pair)
            r = a or b
            same = b and a and all(b[k] == a[k] for k in ['available', 'daily_average', 'coverage_days', 'quality_issues', 'snapshot_at'])
            details = []
            if b and a:
                if any(b[k] != a[k] for k in ['name', 'display_code', 'specification', 'department_name', 'unit']):
                    details.append('物资或科室档案变化')
                if not same:
                    details.append('库存、覆盖或数据质量变化')
                if records(base.facts, 'inventory_batches', pair) != records(facts, 'inventory_batches', pair):
                    details.append('批次数量、状态或效期变化')
                if records(base.facts, 'consumption_daily', pair) != records(facts, 'consumption_daily', pair):
                    details.append('每日消耗记录变化')
                same = not details
            changes.append({'details': details, 'name': r['name'], 'department': r['department_name'], 'unit': r['unit'], 'kind': 'added' if not b else 'removed' if not a else 'unchanged' if same else 'changed', 'before_available': b['available'] if b else None, 'after_available': a['available'] if a else None})
    report = {'issues': issues, 'error_count': errors, 'warning_count': len(issues) - errors, 'positions': len(positions), 'inventory': rows, 'changes': changes}
    facts['import_provenance'] = {'kind': 'user_csv', 'catalog_snapshot_id': base.id, 'source_hash': canonical_hash(body.files.model_dump())}
    return as_of, facts, report


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def view(db, job, detail=False):
    result = {k: getattr(job, k) for k in ['id', 'as_of', 'status', 'base_snapshot_id', 'snapshot_id', 'published_by']}
    result.update(created_at=iso(job.created_at), published_at=iso(job.published_at), actor_name=db.get(User, job.actor_id).display_name)
    result.update({k: job.report[k] for k in ['error_count', 'warning_count', 'positions']})
    if detail:
        result.update({k: job.report[k] for k in ['issues', 'inventory', 'changes']})
        result['stale'] = job.status != 'published' and (job.facts.get('import_provenance', {}).get('publication_revision') != publication_revision(db, job.project_id) or snapshot_for(db, job.project_id).id != job.base_snapshot_id or job.facts.get('import_provenance', {}).get('catalog_hash') != fingerprint(entries(db, job.project_id)))
    return result


def register_routes(app, db_dep, user_dep):
    def job_for(db, project_id, job_id):
        job = db.get(DataImport, job_id, populate_existing=True)
        if not job or job.project_id != project_id:
            raise AppError('NOT_FOUND', '导入记录不存在或不可访问', 404)
        return job

    @app.get('/api/v1/projects/{project_id}/import-template', response_model=ImportTemplate)
    def get_template(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        lock_project(db, project_id)
        ensure_catalog(db, project_id)
        rows = entries(db, project_id)
        project = db.get(Project, project_id)
        result = template(snapshot_for(db, project_id), frozen_catalog(rows, project.source_hospital), fingerprint(rows))
        result['publication_revision'] = publication_revision(db, project_id)
        db.commit()
        return result

    @app.get('/api/v1/projects/{project_id}/imports', response_model=ImportList)
    def list_imports(project_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 50, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        jobs = db.scalars(select(DataImport).where(DataImport.project_id == project_id).order_by(DataImport.created_at.desc()).limit(limit)).all()
        return {'items': [view(db, j) for j in jobs], 'can_publish': can_publish(db, user.id, project_id)}

    @app.post('/api/v1/projects/{project_id}/imports', response_model=ImportView, status_code=201)
    def create_import(project_id: str, body: ImportRequest, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)], user=Depends(user_dep), db=Depends(db_dep)):
        project = require_editor(db, user.id, project_id)
        request_hash = canonical_hash(body.model_dump())
        query = select(DataImport).where(DataImport.project_id == project_id, DataImport.actor_id == user.id, DataImport.idempotency_key == idempotency_key)
        existing = db.scalar(query)
        if existing:
            if existing.request_hash != request_hash:
                raise AppError('IDEMPOTENCY_CONFLICT', '同一个请求键对应不同文件', 409)
            return view(db, existing, True)
        lock_project(db, project_id)
        ensure_catalog(db, project_id)
        base = snapshot_for(db, project_id, body.base_snapshot_id)
        catalog_rows = entries(db, project_id)
        catalog_hash = fingerprint(catalog_rows)
        if body.catalog_hash and body.catalog_hash != catalog_hash:
            raise AppError('CATALOG_CHANGED', '主数据目录已更新，请重新下载模板后校验', 409)
        if snapshot_for(db, project_id).id != base.id or body.publication_revision != publication_revision(db, project_id):
            raise AppError('SNAPSHOT_CHANGED', '当前快照已更新，请下载新模板后重新校验', 409)
        as_of, facts, report = validate(body, base, project, frozen_catalog(catalog_rows, project.source_hospital))
        facts['import_provenance']['catalog_hash'] = catalog_hash
        facts['import_provenance']['publication_revision'] = publication_revision(db, project_id)
        job = DataImport(project_id=project_id, actor_id=user.id, base_snapshot_id=base.id, idempotency_key=idempotency_key, request_hash=request_hash, as_of=as_of, facts=facts, report=report, status='invalid' if report['error_count'] else 'ready')
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            job = db.scalar(query)
            if not job or job.request_hash != request_hash:
                raise AppError('IDEMPOTENCY_CONFLICT', '导入请求冲突', 409)
        return view(db, job, True)

    @app.get('/api/v1/projects/{project_id}/imports/{job_id}', response_model=ImportView)
    def get_import(project_id: str, job_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return view(db, job_for(db, project_id, job_id), True)

    @app.post('/api/v1/projects/{project_id}/imports/{job_id}/publish', response_model=ImportView)
    def publish_import(project_id: str, job_id: str, body: ImportPublish, user=Depends(user_dep), db=Depends(db_dep)):
        require_editor(db, user.id, project_id)
        # A write lock works in SQLite as well as PostgreSQL; serialize ALL imports for this project.
        db.execute(update(Project).where(Project.id == project_id).values(name=Project.name))
        job = job_for(db, project_id, job_id)
        if job.status == 'published':
            db.commit()
            return view(db, job, True)
        if job.status != 'ready':
            raise AppError('IMPORT_INVALID', '请修正校验错误后重新上传', 409)
        if snapshot_for(db, project_id).id != job.base_snapshot_id:
            raise AppError('SNAPSHOT_CHANGED', '当前快照已更新，请重新校验文件后发布', 409)
        if job.facts.get('import_provenance', {}).get('catalog_hash') != fingerprint(entries(db, project_id)):
            raise AppError('CATALOG_CHANGED', '主数据目录已更新或此预览来自旧版本，请重新校验文件后发布', 409)
        if job.facts.get('import_provenance', {}).get('publication_revision') != publication_revision(db, project_id):
            raise AppError('SNAPSHOT_CHANGED', '数据版本已切换或预览来自旧版本，请重新校验文件后发布', 409)
        if job.report['warning_count'] and not body.acknowledge_warnings:
            raise AppError('WARNINGS_UNCONFIRMED', '请先确认校验警告与移除清单', 409)
        snapshot = Snapshot(project_id=project_id, as_of=job.as_of, source_hash=canonical_hash(job.facts), facts=job.facts)
        db.add(snapshot)
        db.flush()
        activate(db, project_id, snapshot.id, job.base_snapshot_id, 'publish', user, 'CSV 校验后人工发布')
        job.status, job.snapshot_id = 'published', snapshot.id
        job.published_by, job.published_at = user.id, time.time()
        db.commit()
        return view(db, job, True)
