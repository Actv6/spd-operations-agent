"""Deterministic, snapshot-scoped operations. No provider calls or business writes."""
from datetime import datetime, timedelta
from decimal import Decimal
from .data import inventory, canonical_hash

RULESET = "m2-screening-1"


def details(snapshot, item_ids=None, department_ids=None):
    rows = inventory(snapshot, item_ids, department_ids)
    permitted = {(r['item_id'], r['department_id']): r for r in rows}
    day = datetime.fromisoformat(snapshot.as_of).date()
    batches = []
    for b in snapshot.facts['inventory_batches']:
        row = permitted.get((b['product_id'], b['department_id']))
        if row is None:
            continue
        on, frozen, reserved = (Decimal(str(b[k])) for k in ['on_hand_base', 'frozen_base', 'reserved_base'])
        remaining = (datetime.fromisoformat(b['expiry_date']).date() - day).days
        valid = min(on, frozen, reserved) >= 0 and frozen + reserved <= on
        batches.append({'id': b['id'], 'product_id': b['product_id'], 'department_id': b['department_id'], 'expiry_date': b['expiry_date'],
                        'days_to_expiry': remaining, 'on_hand': str(on), 'frozen': str(frozen), 'reserved': str(reserved),
                        'available': str(on - frozen - reserved if b['status'] == 'released' and remaining >= 0 else Decimal(0)) if valid else None,
                        'status': b['status'], 'unit': row['unit']})
    consumption = []
    for row in rows:
        days = []
        for offset in range(14, 0, -1):
            date = (day - timedelta(days=offset)).isoformat()
            uses = [u for u in snapshot.facts['consumption_daily'] if u['product_id'] == row['item_id'] and u['department_id'] == row['department_id'] and u['date'] == date]
            valid = len(uses) == 1 and uses[0]['record_type'] == 'confirmed_consumption' and Decimal(str(uses[0]['quantity_base'])) >= 0
            days.append({'date': date, 'quantity': str(Decimal(str(uses[0]['quantity_base']))) if valid else None,
                         'status': 'confirmed' if valid else 'missing' if not uses else 'invalid', 'source_rows': [u['id'] for u in uses]})
        consumption.append({'item_id': row['item_id'], 'department_id': row['department_id'], 'unit': row['unit'], 'days': days,
                            'observed_days': row['observed_days'], 'daily_average': row['daily_average'], 'quality_issues': row['quality_issues']})
    return {'snapshot_set_id': snapshot.id, 'as_of': snapshot.as_of, 'batches': batches, 'consumption': consumption}


def risks(snapshot, item_ids=None, department_ids=None):
    rows = inventory(snapshot, item_ids, department_ids)
    batch_rows = details(snapshot, item_ids, department_ids)['batches']
    findings = []
    def add(row, kind, priority, summary, sources):
        findings.append({'id': canonical_hash([snapshot.id, row['item_id'], row['department_id'], kind]),
                         'item_id': row['item_id'], 'department_id': row['department_id'], 'name': row['name'], 'department_name': row['department_name'],
                         'kind': kind, 'priority': priority, 'summary': summary, 'source_rows': sources})
    for row in rows:
        if row['quality_issues']:
            labels = {'MISSING_CONSUMPTION_DAYS': '14日消耗缺日', 'STALE_SNAPSHOT': '库存记录超过24小时', 'INVALID_BATCH_QUANTITY': '批次数量异常',
                      'MISSING_BATCHES': '缺少批次', 'UNSUPPORTED_CONSUMPTION': '消耗记录待核实', 'DUPLICATE_CONSUMPTION_DAY': '消耗日期重复'}
            add(row, 'quality', 'high', '、'.join(labels.get(q, q) for q in row['quality_issues']) + '；暂停覆盖估算', row['source_rows'])
        if row['coverage_days'] is not None and Decimal(row['coverage_days']) < 7:
            add(row, 'low_coverage', 'medium', f"覆盖基线 {row['coverage_days']} 天，低于本地7天关注阈值；需补查供应信息", row['source_rows'])
        affected = [b for b in batch_rows if b['product_id'] == row['item_id'] and b['department_id'] == row['department_id'] and Decimal(b['on_hand']) > 0 and b['days_to_expiry'] <= 30]
        if affected:
            expired = sum(b['days_to_expiry'] < 0 for b in affected)
            summary = f"{len(affected)} 个在库批次到期或30天内到期，其中已过期 {expired} 个；按批次核实"
            add(row, 'expiry', 'high' if expired else 'medium', summary, [b['id'] for b in affected])
    findings.sort(key=lambda f: (0 if f['priority'] == 'high' else 1, f['item_id'], f['department_id'], f['kind']))
    return {'snapshot_set_id': snapshot.id, 'as_of': snapshot.as_of, 'ruleset_version': RULESET,
            'scanned_positions': len(rows), 'skipped_estimates': sum(r['coverage_days'] is None for r in rows),
            'estimate_gap_counts': {'data_quality': sum(bool(r['quality_issues']) for r in rows), 'zero_consumption': sum(not r['quality_issues'] and r['daily_average'] is not None and Decimal(r['daily_average']) == 0 for r in rows)},
            'thresholds': {'coverage_days': 7, 'expiry_days': 30}, 'findings': findings}
