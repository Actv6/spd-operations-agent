# SPD 运营助手 · M1 前端与保留原型

2026-09-27：M1 新入口在 `src/m1`，注册、会话、库存、运行、引用实际调用 FastAPI。启动 API+worker+前端见 [后端运行说明](../backend/README.md)，验收见 [报告](../docs/verification/M1验收报告.md)。原 `src/App.tsx` 与静态资料保留，访问 `/prototype` 查看旧原型。

2026-09-28 用户授权升级：正式入口改为浅色 Ant Design 6.6.5 企业后台，UI Skills 的 interface-design 指导配色、层级、表格密度、按需抽屉和状态设计。`src/m1/WorkbenchApp.tsx` 为当前入口，`M1App.tsx` 仅为保留的上一版实现。React + TypeScript + Vite，Tabler 图标，ReactMarkdown + remark-gfm 展示结果。旧三列原型仍在 `/prototype`，样式按路由加载。

当前默认使用后端 DeepSeek，不配置密钥时不会生成模板答案。真实查询与词法检索由后端执行；可从库存行、物资详情或新建按钮调用业务 Agent。新资料目录和引用抽屉支持原文、版本和 hash 回查。见 [升级验收](../docs/verification/M1-UI-Agent-RAG升级.md)。

## 运行与构建

M2.1 按 Auth、Workspace、异常、任务、知识库、物资明细、核查结果及证据拆分加载；懒加载失败可重试。工作台通过 `snapshot.ts` 先取仪表盘版本，再显式读取同快照异常报告，统一提交页面状态。已打开的明细和表单保持原版本。`WorkbenchApp.tsx` 只负责会话与入口，工作台实现在 `Workspace.tsx`。

构建后运行 `node scripts/measure-bundle.mjs` 计算各入口的完整静态 JS 依赖体积；不以主入口单包体积代替整页，也不将体积变化称为实测加载时延。验收见 [M2.1 报告](../docs/verification/M2.1验收报告.md)。

2026-09-28 紧凑台账重构：三页统一使用 `src/m1/components/PageHeader.tsx` 与泛型 `DataTable.tsx`。前者管理标题、数量、业务时点和操作；后者封装工具栏/标题/标签插槽、分页默认值、加载/空/错误状态，排序等行为仍由 Ant Design 实现。共享 `workspace-components.css` 控制 24px 桌面与 16px 手机内边距，页面只提供列定义和业务操作。新增页面应复用组件，不能再复制表格外壳。运行 `pnpm test:ui` 验证组件契约，视觉与交互证据见 [本轮验收](../design-qa.md)。

使用 Node.js 22+ 和 pnpm，依赖以 `pnpm-lock.yaml` 为准：

```bash
pnpm install --frozen-lockfile
npm run dev -- --host 127.0.0.1 --port 4180 --strictPort
npm run typecheck
npm run build
```

默认访问 `http://127.0.0.1:4180/`，需后端 8010 与 worker 同时运行。Vite `/api` 同源代理至 API。此地址是本机预览；静态 dist 和 Sites worker 不提供 Python API，不能单独部署为完整 M1。

运行 `npm run types:api` 从 `../docs/verification/m1-openapi.json` 生成前端契约类型，`npm run check:api` 检查漂移。更改共享字段先更新接口基线与后端 Schema，再生成 OpenAPI/类型。密钥不得放入 Vite 环境变量。

## 旧原型演示路径（/prototype）

1. 点第一项任务，查看库存证据与模拟补货规则。
2. 选择负责人，建立待办，再开始处理。
3. 填写处理结果后完成任务；通过“筛选 → 已完成”查看。
4. 刷新页面保留结果，或点“重置演示”恢复八项预设任务。
5. 在数据中心搜索 `SIM-P006`，查看缺失记录导致暂停估计的示例。
6. 在知识库查看有效版与历史版；医院 B 有额外的演示流程文档。

## 旧原型数据边界

`public/demo-data.json` 由根目录的 `scripts/prepare_frontend_data.py` 从合成夹具生成。变更夹具后运行该脚本刷新。所有数据均为虚构演示资料，基准时间固定为 2026-09-27 09:00。

任务是预置场景，并非 Agent 实时发现；覆盖天数是基线算式，尚无逐日到货和效期模拟。当前关键词搜索不等于 RAG。医院过滤在前端完成，完整 JSON 在浏览器可见，不构成安全隔离。存储只在本机浏览器，不能承担真实内部试点业务。

上述旧原型证据见 `design-qa.md`、`qa/interaction-results.json`；不能用于证明 M1 后端验收。M1 证据在 `../docs/verification`。
