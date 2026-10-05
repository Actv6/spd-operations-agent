"""Small model-facing views; immutable full evidence is persisted separately."""
from decimal import Decimal


def without_sources(value):
    if isinstance(value, dict):
        return {k: without_sources(v) for k, v in value.items() if k not in {"source_rows", "source_hash", "source_path", "hash"}}
    if isinstance(value, list):
        return [without_sources(v) for v in value]
    return value


def project_tool(kind, data, rows):
    if kind == "inventory":
        return [{k: v for k, v in r.items() if k not in {"source_rows", "specification", "snapshot_at"}} for r in data]
    if kind == "batches" and len(rows) > 3:
        items = []
        for r in rows:
            batches = [b for b in data if b['product_id'] == r['item_id'] and b['department_id'] == r['department_id']]
            held = [b for b in batches if Decimal(b['on_hand']) > 0]
            items.append({"item_id": r['item_id'], "department_id": r['department_id'], "name": r['name'], "unit": r['unit'],
                          "batch_count": len(batches), "expired_batches": sum(b['days_to_expiry'] < 0 for b in held),
                          "expiring_batches": sum(0 <= b['days_to_expiry'] <= 30 for b in held),
                          "nearest_expiry": min((b['expiry_date'] for b in held), default=None),
                          "invalid_quantity_batches": sum(b['available'] is None for b in batches)})
        return {"view": "summary", "positions": len(rows), "total_batches": len(data), "detail_included": False,
                "next_step": "已汇总全部选中位置；具体批次数量/日期请按物资与科室缩小到最多3个位置后查询。", "items": items}
    if kind == "consumption" and len(rows) > 3:
        items = [{k: v for k, v in c.items() if k != 'days'} | {
            "missing_dates": [d['date'] for d in c['days'] if d['status'] == 'missing'],
            "invalid_dates": [d['date'] for d in c['days'] if d['status'] == 'invalid']
        } for c in data]
        return {"view": "summary", "positions": len(rows), "detail_included": False,
                "next_step": "已汇总全部选中位置；逐日数量请按物资与科室缩小到最多3个位置后查询。", "items": items}
    return without_sources(data)
