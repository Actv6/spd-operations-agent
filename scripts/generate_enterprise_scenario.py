"""Deterministically produce fictional enterprise fixtures; preserve source fixtures."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/synthetic"
TARGET = ROOT / "data/scenario"
SPECS = ["500 mL/瓶，12 瓶/箱", "1 L/瓶，6 瓶/箱", "100 条/筒，20 筒/箱", "3 水平×5 mL/盒", "50 人份/盒", "2 mL，1000 只/袋", "5 mL，100 支/架", "10 mL，50 支/盒", "200 μL，96 支/盒", "40 mL，100 只/袋", "1000 μL，1000 支/袋", "4 mL，500 只/盒", "7.5 号，50 副/盒", "10×10 cm，5 片/包", "120×180 cm，1 套/包", "3-0，12 包/盒", "23 号，100 片/盒", "10×15 cm，20 片/盒", "5 mL，100 支/盒", "单支独立包装，50 套/箱", "22G，50 支/盒", "M 号，100 只/盒", "2.5 cm×5 m，12 卷/盒", "21G，100 支/盒"]
DOCUMENTS = {
    "SIM-SOP-REPL-v1": ("库存补货与缺货核查规程", """## 第2节 缺货核查
驻点专员每日 09:00 核对科室可用库存、近 14 个完整自然日消耗和已确认在途。可用库存须剔除冻结、预留及已过期批次；覆盖天数为可用库存除以日均消耗，仅作供应风险筛查。
## 补货核查与处理
库存覆盖低于供应商约定交期时，先核实科室需求、采购单位换算、供应商确认到货日及在途剩余量。未经供应商确认的预计到货不计作确定供应。资料缺失时建立核查项，不直接断言缺货日期。
## 责任分工
驻点专员登记物资编码、科室、库存快照、需求量与依据；商务专员确认交期和配送安排；项目经理复核内部处理建议。采购、调拨或退货应由有权人员在相应业务系统中办理。
"""),
    "SIM-SOP-EXP-v1": ("批次效期与库存隔离规程", """## 临期核查
距最后可用日期 30 天以内的批次进入临期核查清单。登记批号、科室、数量、有效期及近 14 天消耗，按先到期先发出原则核实可用范围。临期提醒不直接等于报废数量。
## 过期与冻结
批次有效期为最后可用日期，早于当前业务日期的批次不计入可用库存。质量专员核对冻结台账与实物隔离；冻结、预留不得重复占用同一数量。解冻、调拨和报废须按权限另行办理。
## 记录要求
每次处置保留原批号、原因、经办人与复核记录，不覆盖历史快照。涉及开封后稳定期的产品需另行核实产品说明与科室使用条件。
"""),
    "SIM-SOP-DATA-v1": ("库存与消耗数据质量管理规范", """## 数据时效
库存快照超过 24 小时尚未更新时标记待核查，暂停据此预测覆盖天数。驻点专员核实上传时间、科室与物资编码，并向数据维护人员申请补录或刷新。
## 消耗记录完整性
日均消耗取业务日之前 14 个完整自然日。无消耗必须有显式零记录，缺行不能当作零；少于 14 天、日期重复或冲正口径不明时，暂停日均与覆盖估计。
## 数量核对
对比科室库存汇总与批次数量，核查冻结及预留。单位换算未知、数量负值或冻结加预留大于在库量时阻断相应计算，并保留原始行号供追溯。
"""),
    "SIM-PRODUCT-P001-v1": ("生化清洗液物资档案", """## 物资信息
物资编码 MAT-0001，名称生化清洗液，基础单位瓶，规格 500 mL/瓶，采购包装 12 瓶/箱。归属检验科，供应商为衡远医用供应链有限公司。
## 供应与库存
供应商约定交期 8 天。当前库存与消耗数量以授权快照查询结果为准，不能把文档中的供应约定替代实际到货确认。项目专员需复核包装换算、批次效期及科室临时需求。
"""),
    "SIM-SOP-B-v1": ("青禾医院驻点交接流程", """## 交接范围
仅适用于青禾医院项目。交接人员核对当班异常清单、科室缺料反馈、已确认配送安排及未闭环的数据问题。跨项目资料须通过项目授权后使用。
"""),
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    (TARGET / "knowledge").mkdir(parents=True, exist_ok=True)
    for name in ["inventory_snapshots", "inventory_batches", "consumption_daily", "products", "departments", "suppliers", "hospitals", "purchase_orders"]:
        rows = json.loads((SOURCE / f"{name}.json").read_text())
        for index, row in enumerate(rows):
            if name == "products":
                row["name"] = row["name"].replace("（模拟）", "")
                row["display_code"] = f"MAT-{index+1:04d}"
                row["specification"] = SPECS[index].split("，")[0]
                row["specification"] += f"；采购包装含 {row['units_per_purchase_pack']} {row['base_unit']}"
                row["purchase_unit"] = "采购包装"
            elif name == "hospitals":
                row["name"] = ["澄川医院", "青禾医院"][index]
            elif name == "suppliers":
                row["name"] = ["衡远医用供应链有限公司", "启沅医疗器械有限公司", "嘉禾卫生材料有限公司"][index % 3]
            elif name == "departments" and "name" in row:
                row["name"] = row["name"].replace("（模拟）", "").replace("演示", "")
        write_json(TARGET / f"{name}.json", rows)
    manifest = []
    for entry in json.loads((SOURCE / "knowledge_manifest.json").read_text()):
        if entry["id"] not in DOCUMENTS:
            continue
        title, body = DOCUMENTS[entry["id"]]
        new_id = entry["id"].replace("SIM-", "OPS-").replace("-v1", "-v2")
        content = f"# {title}\n\n版本：2.0　生效日期：2026-09-27\n\n{body}"
        path = f"knowledge/{new_id}.md"
        (TARGET / path).write_text(content)
        manifest.append({**entry, "id": new_id, "title": title, "version": "2.0", "effective_from": "2026-09-27", "path": path,
                         "sha256": hashlib.sha256(content.encode()).hexdigest(), "synthetic": True, "source_type": "generated_enterprise_scenario"})
    write_json(TARGET / "knowledge_manifest.json", manifest)
    write_json(TARGET / "provenance.json", {"synthetic": True, "source": "user-authorized generated enterprise scenario", "version": "enterprise-2", "original": "data/synthetic", "real_company_data": False})
    print(f"Generated enterprise-2 scenario: 24 products, {len(manifest)} document versions")


if __name__ == "__main__":
    main()
