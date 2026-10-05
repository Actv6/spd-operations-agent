"""Immutable versions with serialized, append-only activations."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from fastapi import Depends, Header
from sqlalchemy import select
from .auth import require_project
from .catalog import lock_project, ensure_catalog
from .data import canonical_hash, inventory, snapshot_for
from .errors import AppError
from .models import Snapshot, SnapshotActivation, DataImport, User, Membership
from .version_schemas import VersionList, VersionComparison, ActivationView, RestoreRequest


def publication_revision(db, project_id):
    return db.scalar(select(SnapshotActivation.revision).where(SnapshotActivation.project_id == project_id).order_by(SnapshotActivation.revision.desc()).limit(1)) or 0


def activate(db, project_id, target_id, previous_id, action, actor=None, reason='', key=None, request_hash=None):
    # Caller must hold the project write lock until commit.
    row = SnapshotActivation(project_id=project_id, snapshot_id=target_id, previous_snapshot_id=previous_id,
        revision=publication_revision(db, project_id)+1, action=action, actor_id=actor.id if actor else None,
        actor_name=actor.display_name if actor else '系统', reason=reason, idempotency_key=key, request_hash=request_hash)
    db.add(row)
    db.flush()
    return row


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def activation_view(row):
    return {k: getattr(row, k) for k in ['id', 'revision', 'snapshot_id', 'previous_snapshot_id', 'action', 'actor_name', 'reason']} | {'created_at': iso(row.created_at)}


def can_restore(db, user, project_id):
    member = db.get(Membership, (user.id, project_id))
    return bool(member and member.role in {'owner', 'demo_owner'})


def compare(before, after):
    def collect(snapshot):
        rows = {(r['item_id'], r['department_id']): r for r in inventory(snapshot)}
        grouped = {}
        day = datetime.fromisoformat(snapshot.as_of).date()
        tables = {
            'inventory_snapshots': ['on_hand_base', 'frozen_base', 'reserved_base', 'snapshot_at'],
            'inventory_batches': ['id', 'on_hand_base', 'frozen_base', 'reserved_base', 'expiry_date', 'status'],
            'consumption_daily': ['date', 'quantity_base', 'record_type'],
        }
        for table, fields in tables.items():
            grouped[table] = defaultdict(list)
            for r in snapshot.facts[table]:
                if table == 'consumption_daily' and not (day - timedelta(days=14)).isoformat() <= r['date'] < day.isoformat():
                    continue
                values = [str(Decimal(str(r[k])).normalize()) if k.endswith('_base') else r[k] for k in fields]
                grouped[table][(r['product_id'], r['department_id'])].append(values)
            for records in grouped[table].values():
                records.sort()
        return rows, grouped
    b_rows, b_groups = collect(before)
    a_rows, a_groups = collect(after)
    result = []
    for pair in sorted(b_rows.keys() | a_rows.keys()):
        b, a = b_rows.get(pair), a_rows.get(pair)
        row = a or b
        details = []
        if b and a:
            if any(b[k] != a[k] for k in ['name', 'display_code', 'specification', 'department_name', 'unit']):
                details.append('物资或科室档案变化')
                for key, label in [('name', '名称'), ('display_code', '编码'), ('specification', '规格'), ('department_name', '科室'), ('unit', '单位')]:
                    if b[key] != a[key]:
                        details.append(f'{label}：{b[key] or "未填写"} → {a[key] or "未填写"}')
            for table, label in [('inventory_snapshots', '在库、冻结、预留数量或记录时间变化'), ('inventory_batches', '批次数量、状态或效期变化'), ('consumption_daily', '每日消耗记录变化')]:
                if b_groups[table].get(pair, []) != a_groups[table].get(pair, []):
                    details.append(label)
            old_position = b_groups['inventory_snapshots'].get(pair, [])
            new_position = a_groups['inventory_snapshots'].get(pair, [])
            if old_position and new_position:
                for index, label in enumerate(['在库', '冻结', '预留']):
                    if old_position[0][index] != new_position[0][index]:
                        details.append(f'{label}：{old_position[0][index]} {b["unit"]} → {new_position[0][index]} {a["unit"]}')
            old_batches = {r[0]: r for r in b_groups['inventory_batches'].get(pair, [])}
            new_batches = {r[0]: r for r in a_groups['inventory_batches'].get(pair, [])}
            expiry_changes = [f"批次 {bid} 效期：{old_batches[bid][4]} → {new_batches[bid][4]}" for bid in sorted(old_batches.keys() & new_batches.keys()) if old_batches[bid][4] != new_batches[bid][4]]
            details.extend(expiry_changes[:10])
            if len(expiry_changes) > 10:
                details.append(f'另有 {len(expiry_changes)-10} 个批次效期变化')
            if any(b[k] != a[k] for k in ['available', 'daily_average', 'coverage_days', 'quality_issues']):
                details.append('可用库存、覆盖或数据质量变化')
        result.append({'key': canonical_hash(pair), 'name': row['name'], 'department': row['department_name'],
            'kind': 'added' if not b else 'removed' if not a else 'changed' if details else 'unchanged', 'details': details,
            'before_available': b['available'] if b else None, 'after_available': a['available'] if a else None,
            'before_average': b['daily_average'] if b else None, 'after_average': a['daily_average'] if a else None,
            'before_unit': b['unit'] if b else None, 'after_unit': a['unit'] if a else None})
    return result


def register_routes(app, db_dep, user_dep):
    @app.get('/api/v1/projects/{project_id}/versions', response_model=VersionList)
    def versions(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        history = db.scalars(select(SnapshotActivation).where(SnapshotActivation.project_id == project_id).order_by(SnapshotActivation.revision.desc())).all()
        current = snapshot_for(db, project_id, history[0].snapshot_id if history else None)
        imports = {j.snapshot_id: j for j in db.scalars(select(DataImport).where(DataImport.project_id == project_id, DataImport.status == 'published'))}
        items = []
        for snapshot in db.scalars(select(Snapshot).where(Snapshot.project_id == project_id).order_by(Snapshot.created_at.desc(), Snapshot.id)):
            job = imports.get(snapshot.id)
            actor = db.get(User, job.published_by or job.actor_id) if job else None
            items.append({'id': snapshot.id, 'as_of': snapshot.as_of, 'created_at': iso(snapshot.created_at) if snapshot.created_at > 1 else None,
                'actor_name': actor.display_name if actor else '系统', 'positions': len(snapshot.facts['inventory_snapshots']),
                'validation': f"导入校验通过 · {job.report['warning_count']} 条已确认警告" if job else '历史版本 · 无导入校验记录', 'current': snapshot.id == current.id})
        return {'items': items, 'history': [activation_view(r) for r in history], 'current_snapshot_id': current.id,
            'revision': history[0].revision if history else 0, 'can_restore': can_restore(db, user, project_id)}

    @app.get('/api/v1/projects/{project_id}/versions/compare', response_model=VersionComparison)
    def comparison(project_id: str, from_id: str, to_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        before, after = snapshot_for(db, project_id, from_id), snapshot_for(db, project_id, to_id)
        # Short project lock binds the preview to one publication revision across databases.
        lock_project(db, project_id)
        result = {'from_id': before.id, 'to_id': after.id, 'from_as_of': before.as_of, 'to_as_of': after.as_of,
            'revision': publication_revision(db, project_id), 'current_snapshot_id': snapshot_for(db, project_id).id,
            'changes': compare(before, after)}
        db.commit()
        return result

    @app.post('/api/v1/projects/{project_id}/versions/restore', response_model=ActivationView)
    def restore(project_id: str, body: RestoreRequest, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)], user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        if not can_restore(db, user, project_id):
            raise AppError('FORBIDDEN', '当前账号没有数据回退权限', 403)
        lock_project(db, project_id)
        request_hash = canonical_hash(body.model_dump())
        existing = db.scalar(select(SnapshotActivation).where(SnapshotActivation.project_id == project_id, SnapshotActivation.actor_id == user.id, SnapshotActivation.idempotency_key == idempotency_key))
        if existing:
            if existing.request_hash != request_hash:
                raise AppError('IDEMPOTENCY_CONFLICT', '同一个请求键对应不同回退操作', 409)
            result = activation_view(existing)
            db.commit()
            return result
        target = snapshot_for(db, project_id, body.target_snapshot_id)
        current = snapshot_for(db, project_id)
        if body.expected_revision != publication_revision(db, project_id):
            raise AppError('SNAPSHOT_CHANGED', '当前版本已切换，请重新预览差异后操作', 409)
        if target.id == current.id:
            raise AppError('ALREADY_CURRENT', '所选版本已是当前版本', 409)
        ensure_catalog(db, project_id)
        row = activate(db, project_id, target.id, current.id, 'restore', user, body.reason, idempotency_key, request_hash)
        result = activation_view(row)
        db.commit()
        return result
