"""Prepare a small, derived demo projection. No model call or production analysis."""
from pathlib import Path
from datetime import date, timedelta
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/synthetic'
OUT = ROOT / 'frontend/public/demo-data.json'
def read(name):
    return json.loads((DATA / f'{name}.json').read_text())

def main():
    products = {p['id']: p for p in read('products')}
    departments = {p['id']: p for p in read('departments')}
    anchor = date(2026, 9, 27)
    rows = read('consumption_daily')
    inventory = []
    for s in read('inventory_snapshots'):
        p = products[s['product_id']]
        window = [r for r in rows if r['hospital_id'] == s['hospital_id'] and r['department_id'] == s['department_id'] and r['product_id'] == s['product_id'] and date.fromisoformat(r['date']) >= anchor - timedelta(days=14)]
        avg = sum(r['quantity_base'] for r in window) / 14 if len(window) == 14 else None
        inventory.append({**s, 'name': p['name'].replace('（模拟）', ''), 'department': departments[s['department_id']]['name'],
                          'category': p['category'], 'daily_avg': avg, 'observed_days': len(window),
                          'coverage_days': round(s['available_base'] / avg, 1) if avg else None,
                          'units_per_purchase_pack': p['units_per_purchase_pack']})
    docs = [{**d, 'content': (DATA / d['path']).read_text()} for d in read('knowledge_manifest')]
    out = {'manifest': read('manifest'), 'inventory': inventory, 'batches': read('inventory_batches'),
           'orders': read('purchase_orders'), 'documents': docs}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'Prepared {len(inventory)} inventory positions, {len(docs)} documents: {OUT}')

if __name__ == '__main__':
    main()
