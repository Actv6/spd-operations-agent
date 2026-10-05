import csv, io, json
from pathlib import Path
from decimal import Decimal
folder = Path(__file__).resolve().parent
parsed = {}
for kind in ['inventory', 'batches', 'consumption']:
    with (folder / f'{kind}-template.csv').open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f); headers = reader.fieldnames; rows = list(reader)
    parsed[kind] = (headers, rows)
position = parsed['inventory'][1][0]
position['在库数量'] = str(Decimal(position['在库数量']) + 10)
batch = next(r for r in parsed['batches'][1] if r['物资编码'] == position['物资编码'] and r['科室'] == position['科室'])
batch['在库数量'] = str(Decimal(batch['在库数量']) + 10)
parsed['consumption'][1][0]['消耗数量'] = str(Decimal(parsed['consumption'][1][0]['消耗数量']) + 1)
for kind, (headers, rows) in parsed.items():
    with (folder / f'{kind}-filled.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=headers); writer.writeheader(); writer.writerows(rows)
(folder / 'fixture-metadata.json').write_text(json.dumps({'provenance':'generated scenario; not real company records','changes':{'inventory_on_hand':'+10','matching_batch_on_hand':'+10','first_consumption':'+1'},'rows':{k:len(v[1]) for k,v in parsed.items()}},ensure_ascii=False,indent=2))

headers, batches = parsed["batches"]
large = []
for row in batches:
    for index in range(125):
        split = dict(row)
        split["批次编号"] = row["批次编号"] + "-" + "Q" * 65 + f"-{index:03d}"
        assert len(split["批次编号"]) <= 100
        for key in ["在库数量", "冻结数量", "预留数量"]:
            split[key] = format(Decimal(row[key]) / 125, "f")
        large.append(split)
with (folder / "batches-large-filled.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=headers); writer.writeheader(); writer.writerows(large)
assert 1048576 < (folder / "batches-large-filled.csv").stat().st_size < 10 * 1048576
