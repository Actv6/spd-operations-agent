import { useState } from "react";
import { Alert, Empty, Select, Tag } from "antd";
import { DataTable } from "./components/DataTable";
import { number, quality } from "./ui";
import type {
  BatchView,
  ConsumptionDay,
  ConsumptionView,
  EvidenceView,
  InventoryItem,
  RiskFinding,
  RiskReport,
  ReasonGroup,
} from "./types";
import { ReasonGroups } from "./ClaimLedger";

const batchLabels: Record<string, string> = {
  released: "已放行",
  held: "冻结",
  quarantined_expired: "过期隔离",
  quarantine: "隔离",
  blocked: "冻结",
};
export function BatchFacts({
  rows,
  identities = [],
  showScope = false,
}: {
  rows: BatchView[];
  identities?: InventoryItem[];
  showScope?: boolean;
}) {
  return (
    <DataTable<BatchView>
      className="detail-facts-table"
      rowKey="id"
      dataSource={rows}
      scroll={{ x: showScope ? 1180 : 980 }}
      emptyDescription="此范围没有批次记录"
      columns={[
        ...(showScope
          ? [
              {
                title: "物资 / 科室",
                key: "scope",
                width: 200,
                render: (_: unknown, r: BatchView) =>
                  scopeName(r.product_id, r.department_id, identities),
              },
            ]
          : []),
        { title: "批次", dataIndex: "id", width: 210 },
        { title: "到期日", dataIndex: "expiry_date", width: 125 },
        {
          title: "距到期",
          dataIndex: "days_to_expiry",
          width: 130,
          render: (v: number) =>
            v < 0 ? <Tag color="red">已过期 {-v} 天</Tag> : `${v} 天`,
        },
        { title: "单位", dataIndex: "unit", width: 65 },
        ...(["on_hand", "frozen", "reserved", "available"] as const).map(
          (key, index) => ({
            title: ["在库", "冻结", "预留", "可用"][index],
            dataIndex: key,
            width: 85,
            render: number,
          }),
        ),
        {
          title: "状态",
          dataIndex: "status",
          width: 110,
          render: (v: string) => batchLabels[v] || `待核实（${v}）`,
        },
      ]}
    />
  );
}
function scopeName(
  item: string,
  department: string,
  identities: InventoryItem[],
) {
  const row = identities.find(
    (r) => r.item_id === item && r.department_id === department,
  );
  return row
    ? `${row.name} · ${row.department_name}`
    : `${item} · ${department}`;
}
export function ConsumptionFacts({
  rows,
  identities = [],
}: {
  rows: ConsumptionView[];
  identities?: InventoryItem[];
}) {
  const [selected, setSelected] = useState("");
  const key = (r: ConsumptionView) => `${r.item_id}/${r.department_id}`;
  const current = rows.find((r) => key(r) === selected) || rows[0];
  if (!current) return <Empty description="此范围没有消耗记录" />;
  return (
    <div className="m2-stack">
      {rows.length > 1 && (
        <label className="evidence-scope-select">
          选择物资与科室
          <Select
            aria-label="选择证据物资与科室"
            value={key(current)}
            onChange={setSelected}
            options={rows.map((r) => ({
              value: key(r),
              label: scopeName(r.item_id, r.department_id, identities),
            }))}
          />
        </label>
      )}
      <div className="detail-facts-summary">
        <strong>
          记录 {current.observed_days}/14 天 · 日均{" "}
          {number(current.daily_average)} {current.unit}/日
        </strong>
        <p>
          {current.quality_issues.map((q) => quality[q] || q).join("；") ||
            "消耗窗口截至快照日前一天"}
          。缺日保持缺失，不按零消耗处理。
        </p>
      </div>
      <DataTable<ConsumptionDay>
        className="detail-facts-table"
        rowKey="date"
        dataSource={current.days}
        pagination={false}
        scroll={{ x: 430 }}
        columns={[
          { title: "日期", dataIndex: "date", width: 150 },
          {
            title: `消耗 (${current.unit})`,
            dataIndex: "quantity",
            width: 130,
            render: number,
          },
          {
            title: "记录状态",
            dataIndex: "status",
            width: 150,
            render: (v: string) =>
              v === "confirmed" ? (
                "已确认"
              ) : (
                <Tag color="orange">
                  {v === "missing" ? "缺失，未补零" : "待核实"}
                </Tag>
              ),
          },
        ]}
      />
    </div>
  );
}
export function InventoryFacts({ rows }: { rows: InventoryItem[] }) {
  return (
    <DataTable<InventoryItem>
      className="detail-facts-table"
      rowKey={(r) => `${r.item_id}/${r.department_id}`}
      dataSource={rows}
      scroll={{ x: 710 }}
      columns={[
        {
          title: "物资 / 科室",
          key: "item",
          width: 210,
          render: (_, r) => (
            <div>
              <strong>{r.name}</strong>
              <div className="secondary-text">
                {r.display_code} · {r.department_name}
              </div>
            </div>
          ),
        },
        {
          title: "可用库存",
          key: "available",
          width: 120,
          render: (_, r) => `${number(r.available)} ${r.unit}`,
        },
        {
          title: "日均消耗",
          key: "average",
          width: 120,
          render: (_, r) => `${number(r.daily_average)} ${r.unit}/日`,
        },
        {
          title: "覆盖基线",
          key: "coverage",
          width: 110,
          render: (_, r) =>
            r.coverage_days === null
              ? "无法估算"
              : `${number(r.coverage_days)} 天`,
        },
        {
          title: "数据状态",
          key: "quality",
          width: 150,
          render: (_, r) =>
            r.quality_issues.map((q) => quality[q] || q).join("；") ||
            (Number(r.daily_average) === 0 && r.daily_average !== null
              ? "零消耗，无法估算覆盖"
              : "记录完整"),
        },
      ]}
    />
  );
}
export function EvidenceFacts({
  evidence,
  identities = [],
}: {
  evidence: EvidenceView;
  identities?: InventoryItem[];
}) {
  const facts = evidence.facts;
  if (Array.isArray(facts?.inventory))
    return <InventoryFacts rows={facts.inventory as InventoryItem[]} />;
  if (Array.isArray(facts?.batches))
    return (
      <BatchFacts
        rows={facts.batches as BatchView[]}
        identities={identities}
        showScope
      />
    );
  if (Array.isArray(facts?.consumption))
    return (
      <ConsumptionFacts
        rows={facts.consumption as ConsumptionView[]}
        identities={identities}
      />
    );
  if (
    facts?.risks &&
    typeof facts.risks === "object" &&
    Array.isArray((facts.risks as RiskReport).findings)
  ) {
    const report = facts.risks as RiskReport;
    return (
      <>
        <div className="detail-facts-summary">
          <strong>
            已扫描 {report.scanned_positions} 个组合 · {report.findings.length}{" "}
            条关注项
          </strong>
          <p>
            暂不可估算 {report.skipped_estimates} 项。
            {report.estimate_gap_counts
              ? `其中数据待核查 ${report.estimate_gap_counts.data_quality ?? "未记录"} 项、零消耗 ${report.estimate_gap_counts.zero_consumption ?? "未记录"} 项。`
              : "此历史证据未记录分类计数。"}
          </p>
        </div>
        <ReasonGroups groups={Array.isArray(facts.reason_breakdown) ? facts.reason_breakdown as ReasonGroup[] : null} />
        <DataTable<RiskFinding>
          className="detail-facts-table"
          rowKey="id"
          dataSource={report.findings}
          scroll={{ x: 690 }}
          emptyDescription="本次扫描未发现关注项"
          columns={[
            {
              title: "物资 / 科室",
              key: "item",
              width: 200,
              render: (_, r) => (
                <div>
                  <strong>{r.name}</strong>
                  <div className="secondary-text">{r.department_name}</div>
                </div>
              ),
            },
            {
              title: "关注级别",
              dataIndex: "priority",
              width: 110,
              render: (v) =>
                v === "high" ? <Tag color="orange">优先核实</Tag> : "关注",
            },
            { title: "核查依据", dataIndex: "summary", width: 380 },
          ]}
        />
      </>
    );
  }
  return (
    <>
      <Alert
        type="warning"
        title="此历史证据暂不支持表格展示，以下保留原始摘录。"
      />
      <pre className="evidence-raw">
        {evidence.excerpt || "未保存可展示的摘录，请检查来源定位信息。"}
      </pre>
    </>
  );
}
