"""Validate fixture relationships and independently specified numerical examples."""
from pathlib import Path
from datetime import date, datetime, timedelta
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'synthetic'


def main():
    def read(name):
        return json.loads((DATA / (name + '.json')).read_text(encoding='utf-8'))
    manifest = read('manifest')
    now = datetime.fromisoformat(manifest['as_of'])
    anchor = now.date()
    checks = []
    def check(name, ok):
        if not ok:
            raise AssertionError(name)
        checks.append(name)
    def unique(rows):
        return len(rows) == len({r['id'] for r in rows})
    hospitals = {r['id'] for r in read('hospitals')}
    depts = {r['id']: r for r in read('departments')}
    suppliers = {r['id'] for r in read('suppliers')}
    products = {r['id']: r for r in read('products')}
    batches = {r['id']: r for r in read('inventory_batches')}
    snaps = {r['id']: r for r in read('inventory_snapshots')}
    usage, orders = read('consumption_daily'), read('purchase_orders')
    for name in ('hospitals', 'departments', 'suppliers', 'products', 'inventory_batches', 'inventory_snapshots', 'consumption_daily', 'purchase_orders', 'gold_cases'):
        check(name + ': unique ids', unique(read(name)))
    check('all scoped rows reference consistent hospitals and departments', all(r['hospital_id'] in hospitals and r['department_id'] in depts and depts[r['department_id']]['hospital_id'] == r['hospital_id'] for r in [*snaps.values(), *batches.values(), *usage, *orders]))
    check('product and supplier references', all(r['product_id'] in products for r in [*snaps.values(), *batches.values(), *usage, *orders]) and all(p['supplier_id'] in suppliers for p in products.values()))
    for s in snaps.values():
        lots = [batches[k] for k in s['batch_ids']]
        check(s['id'] + ': batch scope', all((b['hospital_id'], b['department_id'], b['product_id'], b['snapshot_at']) == (s['hospital_id'], s['department_id'], s['product_id'], s['snapshot_at']) for b in lots))
        check(s['id'] + ': batch totals', all(sum(b[k] for b in lots) == s[k] for k in ('on_hand_base', 'frozen_base', 'reserved_base')))
        available = sum(b['on_hand_base'] - b['frozen_base'] - b['reserved_base'] for b in lots if b['status'] == 'released' and date.fromisoformat(b['expiry_date']) >= anchor)
        check(s['id'] + ': available stock', available == s['available_base'])
    check('nonnegative stock and holds', all(0 <= b['frozen_base'] + b['reserved_base'] <= b['on_hand_base'] for b in batches.values()))
    check('historical observed consumption only', all(r['quantity_base'] >= 0 and anchor - timedelta(days=90) <= date.fromisoformat(r['date']) < anchor and r['record_type'] == 'confirmed_consumption' for r in usage))
    check('base units consistent', all(r['base_unit'] == products[r['product_id']]['base_unit'] for r in [*usage, *orders, *snaps.values()]))
    check('order balances', all(r['outstanding_base'] == r['ordered_base'] - r['received_base'] - r['cancelled_base'] >= 0 for r in orders))
    def window(pid):
        return [r for r in usage if r['hospital_id'] == 'SIM-HA' and r['product_id'] == pid and date.fromisoformat(r['date']) >= anchor - timedelta(days=14)]
    check('G01 120 / 20 = 6; 8 - 6 = 2', len(window('SIM-P001')) == 14 and sum(r['quantity_base'] for r in window('SIM-P001')) == 280 and snaps['SIM-HA-SIM-P001']['available_base'] == 120 and snaps['SIM-HA-SIM-P001']['supplier_lead_days'] == 8 and not any(o['hospital_id'] == 'SIM-HA' and o['product_id'] == 'SIM-P001' for o in orders))
    balance, minimum = 50, 50
    for day in range(1, 15):
        balance += 200 if day == 2 else 0
        balance -= 10
        minimum = min(minimum, balance)
    check('G02 daily inbound example has no 14-day shortage', minimum >= 0 and snaps['SIM-HA-SIM-P002']['available_base'] == 50 and sum(r['quantity_base'] for r in window('SIM-P002')) == 140 and any(o['hospital_id'] == 'SIM-HA' and o['product_id'] == 'SIM-P002' and o['outstanding_base'] == 200 and o['expected_arrival_date'] == '2026-09-29' for o in orders))
    lot = batches['LOT-SIM-HA-SIM-P003-1']
    check('G03 300 - 10 * 5 = 250 (ten-day horizon)', lot['on_hand_base'] == 300 and (date.fromisoformat(lot['expiry_date']) - anchor).days == 10 and sum(r['quantity_base'] for r in window('SIM-P003')) == 70)
    check('G04 expired 80 excluded', snaps['SIM-HA-SIM-P004']['available_base'] == 220 and batches['LOT-SIM-HA-SIM-P004-1']['status'] == 'quarantined_expired')
    check('G05 14 explicit zeros', len(window('SIM-P005')) == 14 and sum(r['quantity_base'] for r in window('SIM-P005')) == 0)
    check('G06 12 observed days, 2 unknown', len(window('SIM-P006')) == 12)
    check('G07 stale 72 hours', (now - datetime.fromisoformat(snaps['SIM-HA-SIM-P007']['snapshot_at'])).total_seconds() == 72 * 3600)
    check('G08 lead unknown', snaps['SIM-HA-SIM-P008']['supplier_lead_days'] is None)
    check('G09 partial inbound is 50', next(o for o in orders if o['id'] == 'PO-SIM-HA-SIM-P009')['outstanding_base'] == 50)
    check('G10 cross-hospital fixture and access scope exist', snaps['SIM-HA-SIM-P010']['available_base'] == 40 and snaps['SIM-HB-SIM-P010']['available_base'] == 600 and read('access_examples')[0]['allowed_hospitals'] == ['SIM-HA'])
    check('G11 800 base units / 100 = 8 packs', snaps['SIM-HA-SIM-P011']['available_base'] == 800 and products['SIM-P011']['units_per_purchase_pack'] == 100)
    docs = read('knowledge_manifest')
    check('knowledge hashes and synthetic labels', all(hashlib.sha256((DATA / d['path']).read_bytes()).hexdigest() == d['sha256'] and d['source_type'] == 'synthetic_demo' for d in docs))
    check('old version marked retired', next(d for d in docs if d['id'] == 'SIM-SOP-REPL-v0')['status'] == 'retired_demo')
    check('adversarial sample excluded by default', read('adversarial_document')['include_in_normal_knowledge_base'] is False)
    report = {'status': 'passed', 'as_of': manifest['as_of'], 'checks_passed': len(checks),
              'checks': checks, 'agent_evaluation_executed': False, 'rag_retrieval_executed': False,
              'server_load_test_executed': False, 'scope': '数据夹具关联、数值与案例前提校验；不是应用/模型/真实业务验收'}
    (DATA / 'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
