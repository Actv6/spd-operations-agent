import { after, test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const server = await createServer({
  configFile: false,
  plugins: [react()],
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: "custom",
});
after(() => server.close());
const { DataTable } = await server.ssrLoadModule(
  "/src/m1/components/DataTable.tsx",
);
const { PageHeader } = await server.ssrLoadModule(
  "/src/m1/components/PageHeader.tsx",
);
const { readSnapshotBundle } = await server.ssrLoadModule(
  "/src/m1/snapshot.ts",
);
const { formatAnswerMarkdown } = await server.ssrLoadModule(
  "/src/m1/answerFormatting.ts",
);
const { EvidenceFacts } = await server.ssrLoadModule("/src/m1/DataFacts.tsx");
const { ClaimLedger, ClaimEntries, ReasonBreakdown } = await server.ssrLoadModule("/src/m1/ClaimLedger.tsx");
const { number: displayQuantity } =
  await server.ssrLoadModule("/src/m1/ui.tsx");
const { readCsvFile, checkCsvFile, CSV_MAX_BYTES } = await server.ssrLoadModule('/src/m1/components/csvFile.ts');
const rows = Array.from({ length: 24 }, (_, i) => ({
  id: i + 1,
  name: `item-${i + 1}`,
}));
const base = {
  rowKey: "id",
  columns: [{ title: "名称", dataIndex: "name" }],
  dataSource: rows,
};
const render = (props = {}) =>
  renderToStaticMarkup(h(DataTable, { ...base, ...props }));

const { ReviewStatusTag } = await server.ssrLoadModule('/src/m1/HumanReviewPanel.tsx');
test("claim labels distinguish exact facts, quotes and unverified advice", () => {
  const claims = [
    {id:"c1", kind:"fact",text:"反应杯缺日",evidence_ids:["e1"],fact_ids:["f1"],verification:"tool_exact"},
    {id:"c2", kind:"policy",text:"缺失记录不得补零",evidence_ids:["e2"],fact_ids:[],verification:"document_quote"},
    {id:"c3", kind:"suggestion",text:"核对台账",evidence_ids:["e1"],fact_ids:[],verification:"unverified"},
  ];
  const html=renderToStaticMarkup(h(ClaimEntries,{claims,onEvidence:()=>{}}));
  for(const label of ["工具事实匹配","原文匹配","待人工核实","查看c1的依据1","核对台账"])
    assert.ok(html.includes(label),label);
  assert.ok(!html.includes("语义已通过"));
});
test("reason members remain separate and historical answers receive no invented checks", () => {
  const analysis={reason_breakdown:[
    {reason:"MISSING_CONSUMPTION_DAYS",label:"14日消耗缺日",count:1,positions:[{name:"反应杯",department_name:"检验科"}],evidence_ids:["e1"]},
    {reason:"STALE_SNAPSHOT",label:"库存快照超过24小时",count:1,positions:[{name:"采样管",department_name:"检验科"}],evidence_ids:["e1"]},
  ]};
  const html=renderToStaticMarkup(h(ReasonBreakdown,{analysis}));
  for(const label of ["14日消耗缺日","库存快照超过24小时","反应杯","采样管","分项不能相加"])
    assert.ok(html.includes(label),label);
  assert.equal(renderToStaticMarkup(h(ReasonBreakdown,{analysis:{}})),"");
  assert.equal(renderToStaticMarkup(h(ClaimLedger,{analysis:{},onEvidence:()=>{}})),"");
});

test("shared slots surround one native Ant Design table", () => {
  const html = render({
    heading: "目录",
    toolbar: h("input", { "aria-label": "搜索" }),
    tabs: "全部",
  });
  for (const cls of [
    "data-table-heading",
    "data-table-toolbar",
    "data-table-tabs",
    "ant-table",
  ])
    assert.ok(html.includes(cls));
  assert.equal((html.match(/<table\b/g) || []).length, 1);
});
test("default pagination renders ten rows and correct total", () => {
  const html = render();
  assert.equal((html.match(/data-row-key=/g) || []).length, 10);
  assert.ok(html.includes("共 24 条"));
});
test("page override and disabled pagination are preserved", () => {
  assert.equal(
    (render({ pagination: { pageSize: 20 } }).match(/data-row-key=/g) || [])
      .length,
    20,
  );
  const html = render({ pagination: false });
  assert.equal((html.match(/data-row-key=/g) || []).length, 24);
  assert.ok(!html.includes('<ul class="ant-pagination'));
});
test("empty, error, retry and loading states remain available", () => {
  const html = render({
    dataSource: [],
    emptyDescription: "没有资料",
    emptyAction: h("button", null, "新建"),
    error: "载入失败",
    onRetry: () => {},
  });
  for (const text of ["没有资料", "新建", "载入失败", "重 试"])
    assert.ok(html.includes(text), `Missing ${text}`);
  assert.ok(render({ loading: true }).includes("ant-spin-spinning"));
});
test("compact header preserves zero count and precise timestamp", () => {
  const html = renderToStaticMarkup(
    h(PageHeader, {
      title: "库存数据",
      count: 0,
      asOf: "2026-09-27T09:00:00+08:00",
      actions: h("button", null, "刷新"),
    }),
  );
  assert.ok(html.includes('page-count">0'));
  assert.ok(html.includes("2026-09-27 09:00"));
  assert.ok(html.includes('dateTime="2026-09-27T09:00:00+08:00"'));
  assert.ok(!html.includes("eyebrow"));
});

test("risk refresh stays pinned when current snapshot changes", async () => {
  const calls = [];
  const read = async (path) => {
    calls.push(path);
    if (path.endsWith("/dashboard"))
      return { snapshot_set_id: "snapshot-A", inventory: [] };
    if (path.includes("/runs?")) return [];
    if (path.includes("/risks?snapshot_set_id=snapshot-A"))
      return { snapshot_set_id: "snapshot-A", findings: [] };
    throw new Error("Unpinned request would read newly published snapshot-B");
  };
  const bundle = await readSnapshotBundle("project", read);
  assert.equal(bundle.dashboard.snapshot_set_id, bundle.risks.snapshot_set_id);
  assert.ok(
    calls.includes("/projects/project/risks?snapshot_set_id=snapshot-A"),
  );
});

test("mixed snapshot bundle is rejected", async () => {
  const read = async (path) =>
    path.endsWith("/dashboard")
      ? { snapshot_set_id: "A" }
      : path.includes("/runs?")
        ? []
        : { snapshot_set_id: "B" };
  await assert.rejects(readSnapshotBundle("project", read), /数据版本不一致/);
});

test("answer presentation recognizes labels without changing numbers or claims", () => {
  const input =
    "结论：库存120瓶，日均20瓶，覆盖6天。\n\n待确认：尚未查逐批明细。\n\n以下为建议，非制度要求：核实供应信息。";
  const output = formatAnswerMarkdown(input);
  assert.ok(output.includes("#### 结论\n\n库存120瓶，日均20瓶，覆盖6天。"));
  assert.ok(output.includes("#### 以下为建议，非制度要求"));
  assert.ok(output.includes("尚未查逐批明细。"));
  assert.equal(
    formatAnswerMarkdown("建议：核实到货；核对库存。"),
    "#### 建议\n\n- 核实到货；\n- 核对库存。",
  );
});
test("authored markdown and fenced code are left untouched", () => {
  for (const input of [
    "## 结论\n\n- **库存** 120瓶\n- [来源](https://example.test)",
    "```text\n\n结论：不可改动\n```",
    "| 日期 | 数量 |\n|---|---|\n|9月22日|null|",
  ])
    assert.equal(formatAnswerMarkdown(input), input);
});
test("long prose is separated at sentence boundaries without dropping text", () => {
  const input = "甲".repeat(110) + "。" + "乙".repeat(90) + "。";
  const output = formatAnswerMarkdown(input);
  assert.ok(output.includes("\n\n"));
  assert.equal(output.replaceAll("\n\n", ""), input);
});

const renderEvidence = (facts, excerpt = "") =>
  renderToStaticMarkup(
    h(EvidenceFacts, {
      evidence: { facts, excerpt, evidence_id: "evidence-test" },
    }),
  );
test("batch evidence renders preserved expiry, quantity and Chinese status", () => {
  const html = renderEvidence({
    batches: [
      {
        id: "LOT-EXPIRED",
        product_id: "P1",
        department_id: "D1",
        expiry_date: "2026-09-25",
        days_to_expiry: -2,
        on_hand: "80",
        frozen: "80",
        reserved: "0",
        available: "0",
        unit: "盒",
        status: "quarantined_expired",
      },
    ],
  });
  for (const text of ["LOT-EXPIRED", "2026-09-25", "过期隔离", "P1", "D1"])
    assert.ok(html.includes(text), text);
  assert.ok(!html.includes("quarantined_expired"));
});
test("consumption evidence shows missing days without zero filling", () => {
  const html = renderEvidence({
    consumption: [
      {
        item_id: "P1",
        department_id: "D1",
        unit: "瓶",
        observed_days: 12,
        daily_average: null,
        quality_issues: ["MISSING_CONSUMPTION_DAYS"],
        days: [
          { date: "2026-09-22", quantity: null, status: "missing" },
          { date: "2026-09-23", quantity: "0", status: "confirmed" },
        ],
      },
    ],
  });
  for (const text of [
    "12",
    "2026-09-22",
    "缺失，未补零",
    "消耗记录缺日",
    "2026-09-23",
    "已确认",
    "—",
  ])
    assert.ok(html.includes(text), text);
});
test("risk evidence preserves distinct quality and zero-consumption counts", () => {
  const html = renderEvidence({
    risks: {
      scanned_positions: 24,
      skipped_estimates: 3,
      estimate_gap_counts: { data_quality: 2, zero_consumption: 1 },
      findings: [
        {
          id: "risk1",
          name: "反应杯",
          department_name: "检验科",
          priority: "high",
          summary: "14日消耗缺日；暂停覆盖估算",
        },
      ],
    },
  });
  for (const text of [
    "24",
    "3",
    "数据待核查",
    "零消耗",
    "反应杯",
    "暂停覆盖估算",
  ])
    assert.ok(html.includes(text), text);
});
test("unknown evidence retains original excerpt instead of a blank panel", () => {
  const html = renderEvidence(
    { legacy_data: [] },
    "原始历史证据：库存 0.0001 瓶",
  );
  assert.ok(html.includes("暂不支持表格展示"));
  assert.ok(html.includes("库存 0.0001 瓶"));
});
test("display quantities preserve small and large decimal values", () => {
  assert.equal(displayQuantity("0.0001"), "0.0001");
  assert.equal(displayQuantity("999999999999.9999"), "999,999,999,999.9999");
  assert.equal(displayQuantity("20.0000"), "20");
  assert.equal(displayQuantity(null), "—");
});
test("bracketed historical headings get hierarchy without rewriting claims", () => {
  const output = formatAnswerMarkdown(
    "【扫描范围与跳过估算】24 个组合，跳过 3 项。\n\n【高关注（high）】\n\n- 过期 2 天",
  );
  assert.ok(
    output.includes("#### 扫描范围与跳过估算\n\n24 个组合，跳过 3 项。"),
  );
  assert.ok(output.includes("#### 高关注（high）"));
  assert.ok(output.includes("- 过期 2 天"));
});

test("historical risk evidence without breakdown remains readable and does not invent zeros", () => {
  const html = renderEvidence({
    risks: { scanned_positions: 24, skipped_estimates: 3, findings: [] },
  });
  assert.ok(html.includes("未记录"));
  assert.ok(html.includes("24"));
  assert.ok(!html.includes("数据待核查 0"));
});


test('CSV slice decoding preserves UTF-8 across chunk boundaries and reports progress', async () => {
  const content = 'a'.repeat(256 * 1024 - 1) + '库存,科室\r\n'.repeat(20000);
  const file = new File([content], 'large.csv');
  const progress = [];
  const actual = await readCsvFile(file, new AbortController().signal, (p) => progress.push(p));
  assert.equal(actual, content);
  assert.ok(progress.length > 1);
  assert.equal(progress.at(-1), 100);
});
test('CSV rejects wrong types, empty files, over-limit bytes and invalid UTF-8', async () => {
  assert.throws(() => checkCsvFile({name:'data.xlsx',size:20}), /CSV/);
  assert.throws(() => checkCsvFile({name:'empty.csv',size:0}), /为空/);
  assert.throws(() => checkCsvFile({name:'large.csv',size:CSV_MAX_BYTES + 1}), /10MB/);
  await assert.rejects(readCsvFile(new File([new Uint8Array([0xff])], 'bad.csv'), new AbortController().signal, () => {}), /UTF-8/);
});
test('cancelled CSV reads stop before delivering content', async () => {
  const controller = new AbortController();
  await assert.rejects(readCsvFile(new File(['x'.repeat(600000)], 'cancel.csv'), controller.signal, () => controller.abort()), {name:'AbortError'});
});

test('bold business labels become sections while facts and numbered advice survive', () => {
  const input = '**已核实事实**：在库120瓶；日均20瓶；覆盖6天。\n\n**待确认状态**：交期尚未核实。\n\n**需核实事项（建议）**：\n\n1. 核对包装12瓶。';
  const output = formatAnswerMarkdown(input);
  for (const title of ['已核实事实','待确认状态','需核实事项（建议）']) assert.ok(output.includes('#### '+title));
  for (const fact of ['在库120瓶','日均20瓶','覆盖6天','交期尚未核实','1. 核对包装12瓶。']) assert.ok(output.includes(fact));
});

test('human review labels stay separate from model run success', () => {
  for (const [status, label] of Object.entries({pending:'待人工复核',confirmed:'人工确认',error:'发现错误 / 有争议',insufficient:'资料不足'})) {
    const markup=renderToStaticMarkup(h(ReviewStatusTag,{status}));
    assert.ok(markup.includes(label));
    assert.ok(!markup.includes('AI运行成功'));
  }
});
