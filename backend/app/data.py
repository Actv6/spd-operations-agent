import json
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import select
from .config import DATA
from .models import Snapshot, SnapshotActivation
from .errors import AppError

AS_OF = "2026-09-27T09:00:00+08:00"


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seed_snapshot(db, project):
    facts = {}
    for name in ["inventory_snapshots", "inventory_batches", "consumption_daily", "products", "departments"]:
        rows = json.loads((DATA / f"{name}.json").read_text())
        facts[name] = [r for r in rows if name == "products" or r["hospital_id"] == project.source_hospital]
    source_hash = canonical_hash(facts)
    existing = db.scalar(select(Snapshot).where(Snapshot.project_id == project.id, Snapshot.source_hash == source_hash))
    if existing:
        return existing
    snapshot = Snapshot(project_id=project.id, as_of=AS_OF, source_hash=source_hash, facts=facts)
    db.add(snapshot)
    db.flush()
    return snapshot


def snapshot_for(db, project_id, snapshot_id=None):
    if snapshot_id is None:
        activation = db.scalar(select(SnapshotActivation).where(SnapshotActivation.project_id == project_id).order_by(SnapshotActivation.revision.desc()))
        if activation:
            snapshot_id = activation.snapshot_id
    query = select(Snapshot).where(Snapshot.project_id == project_id)
    if snapshot_id:
        query = query.where(Snapshot.id == snapshot_id)
    snapshot = db.scalar(query.order_by(Snapshot.as_of.desc(), Snapshot.created_at.desc()))
    if not snapshot:
        raise AppError("NOT_FOUND", "快照不存在或不可访问", 404)
    return snapshot


def inventory(snapshot, item_ids=None, department_ids=None):
    facts = snapshot.facts
    positions = facts["inventory_snapshots"]
    valid_items = {p["product_id"] for p in positions}
    valid_departments = {p["department_id"] for p in positions}
    if set(item_ids or []) - valid_items or set(department_ids or []) - valid_departments:
        raise AppError("INVALID_SCOPE", "物资或科室不在许可快照中", 422)
    products = {p["id"]: p for p in facts["products"]}
    departments = {p["id"]: p["name"] for p in facts.get("departments", [])}
    day = datetime.fromisoformat(snapshot.as_of).date()
    result = []
    for p in positions:
        if item_ids and p["product_id"] not in item_ids or department_ids and p["department_id"] not in department_ids:
            continue
        batches = [b for b in facts["inventory_batches"] if b["product_id"] == p["product_id"] and b["department_id"] == p["department_id"]]
        available = Decimal(0)
        issues = []
        for b in batches:
            on, frozen, reserved = (Decimal(str(b[k])) for k in ["on_hand_base", "frozen_base", "reserved_base"])
            if min(on, frozen, reserved) < 0 or frozen + reserved > on:
                issues.append("INVALID_BATCH_QUANTITY")
            elif b["status"] == "released" and b["expiry_date"] >= day.isoformat():
                available += on - frozen - reserved
        if not batches:
            issues.append("MISSING_BATCHES")
        uses = [u for u in facts["consumption_daily"] if u["product_id"] == p["product_id"] and u["department_id"] == p["department_id"] and (day - timedelta(days=14)).isoformat() <= u["date"] < day.isoformat()]
        days = {u["date"] for u in uses}
        if len(days) != 14:
            issues.append("MISSING_CONSUMPTION_DAYS")
        if any(u["record_type"] != "confirmed_consumption" or Decimal(str(u["quantity_base"])) < 0 for u in uses):
            issues.append("UNSUPPORTED_CONSUMPTION")
        if len(uses) != len(days):
            issues.append("DUPLICATE_CONSUMPTION_DAY")
        if datetime.fromisoformat(snapshot.as_of) - datetime.fromisoformat(p["snapshot_at"]) > timedelta(hours=24):
            issues.append("STALE_SNAPSHOT")
        avg = sum((Decimal(str(u["quantity_base"])) for u in uses), Decimal(0)) / Decimal(14) if not any(x in issues for x in ["MISSING_CONSUMPTION_DAYS", "UNSUPPORTED_CONSUMPTION", "DUPLICATE_CONSUMPTION_DAY"]) else None
        if "INVALID_BATCH_QUANTITY" in issues or "MISSING_BATCHES" in issues:
            available = None
        coverage = available / avg if available is not None and avg and not issues else None
        result.append({"item_id": p["product_id"], "name": products[p["product_id"]]["name"], "display_code": products[p["product_id"]].get("display_code", p["product_id"]), "specification": products[p["product_id"]].get("specification", ""), "department_id": p["department_id"], "department_name": departments.get(p["department_id"], p["department_id"]), "unit": p["base_unit"],
                       "available": str(available) if available is not None else None, "daily_average": str(avg.quantize(Decimal("0.0001"))) if avg is not None else None,
                       "coverage_days": str(coverage.quantize(Decimal("0.0001"))) if coverage is not None else None, "observed_days": len(days),
                       "quality_issues": issues, "source_rows": [p["id"]] + [b["id"] for b in batches] + [u["id"] for u in uses], "snapshot_at": p["snapshot_at"]})
    return result
