# 合成业务数据 v0.1

全部虚构，标识统一使用 SIM。不能当作国药控股广东生物科技有限公司真实业务、真实医院数据或真实产品资料。

基准时点：2026-09-27 09:00（Asia/Shanghai）。历史为此前 90 个完整自然日。记录基准单位数量，不包含患者数据、真实价格和注册证。

- `manifest.json`：版本、固定种子、基准时间及数量。
- `products.json` / `suppliers.json` / `hospitals.json` / `departments.json`：主数据。
- `inventory_snapshots.json` / `inventory_batches.json`：产品位置快照与批次库存。
- `consumption_daily.json`：明确模拟为“已确认实际消耗”，不是申领或科室配送量。
- `purchase_orders.json`：在途订单、部分到货与取消量，数量使用基准单位。
- `knowledge/` / `knowledge_manifest.json`：演示 RAG 文档及版本/权限元数据。
- `gold_cases.json`：14 个预设评测案例。数值案例前提由校验脚本核对，但 Agent 尚未运行。
- `invalid_import_samples.json`：6 个损坏导入案例，与正常数据分开。
- `adversarial_document.json`：隔离的文档提示注入测试，不进入默认知识库。
- `validation_report.json`：脚本实际执行结果及未验证项。

注意：这组资料提供快照、消耗和未结订单，没有完整采购、验收入库、退库、调拨和出库流水，不能用于完整库存账本核销。借助单独生成的模拟制度可以测试引用流程，但真实试点前必须替换为获准的实际制度。

UI 概念图内的合计数是排版示例，不是这组数据的分析结果。导入真实数据后不得继续展示模拟制度为真实依据。
