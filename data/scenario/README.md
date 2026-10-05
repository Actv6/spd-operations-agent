# 企业业务场景数据

由用户授权生成，企业、医院、产品档案和制度均为虚构场景；不代表实际企业记录、合规制度或医疗用途。业务界面使用自然业务名称，来源信息保留在每条记录的 synthetic 和 provenance.json 中。

在项目根运行 `backend/.venv/bin/python scripts/generate_enterprise_scenario.py` 可复现。原始 `data/synthetic` 不覆盖；此版本保留数量、批次、消耗和内部关联，增加 MAT 业务编码、规格与自然名称。医院 A 有 24 个产品库存位置；医院 B 数据仍按项目隔离。缺日和旧快照是刻意保留的数据质量场景。

业务时间固定为 2026-09-27 09:00，不伪装成实时企业数据。新文档使用独立 2.0 版本和 hash。首次注册直接导入此目录，旧项目通过 `app.cli publish-scenario` 发布新版本。发布不会覆盖历史快照、分析或证据原文。

## 扩展知识资料

`backend/.venv/bin/python scripts/generate_enterprise_knowledge.py` 生成独立发布 `enterprise-kb-20260927-1`：12 份操作指引、24 份物资主数据卡、6 个医院 A 案例，共 42 份，版本 1.0；清单为 `enterprise_manifest.json`。医院 B 仅可导入其中 36 份共享资料，不可导入医院 A 案例。

在 backend 目录执行 `.venv/bin/python -m app.cli publish-scenario` 为已有项目导入两个清单；重复执行新增数为零。新注册自动导入。医院 A 的原有 4 份有效资料加上新 42 份，共 46 份、124 个片段。版本元数据片段保留，但检索排序会排除纯版本行。这里是检索入库，不是模型训练，也没有生成假向量。
