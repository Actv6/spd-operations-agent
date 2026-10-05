import { useState } from "react";
import { Button, Input, Space, Tabs, Tag } from "antd";
import { DataTable } from "./components/DataTable";
import type { RiskReport, RiskFinding } from "./types";
import "./m2.css";

const kindLabels = {
  quality: "数据缺口",
  low_coverage: "低覆盖",
  expiry: "效期关注",
};
export function RiskPanel({
  data,
  loading,
  reload,
  onAnalyze,
  onDetails,
}: {
  data: RiskReport;
  loading: boolean;
  reload: () => void;
  onAnalyze: (finding?: RiskFinding) => void;
  onDetails: (finding: RiskFinding) => void;
}) {
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const rows = (data?.findings || []).filter(
    (f) =>
      (kind === "all" || f.kind === kind) &&
      `${f.name}${f.department_name}${f.summary}`.includes(query),
  );
  return (
    <div className="m2-stack risk-panel">
      <section className="risk-overview" aria-label="当前快照筛查概况">
        <dl className="risk-metrics">
          <div>
            <dt>已扫描范围</dt>
            <dd>{data.scanned_positions}<span>个组合</span></dd>
            <dd className="risk-metric-note">物资 × 科室 · 当前快照</dd>
          </div>
          <div>
            <dt>关注项</dt>
            <dd>{data.findings.length}<span>条</span></dd>
            <dd className="risk-metric-note">数据缺口、低覆盖与效期关注</dd>
          </div>
          <div>
            <dt>暂不可估算覆盖</dt>
            <dd>{data.skipped_estimates}<span>项</span></dd>
            <dd className="risk-metric-note">数据待核查 {data.estimate_gap_counts.data_quality} 项 · 零消耗 {data.estimate_gap_counts.zero_consumption} 项</dd>
          </div>
        </dl>
        <details className="risk-method">
          <summary>筛查口径与范围</summary>
          <p>基于页面所示快照完整扫描。覆盖不足 {data.thresholds.coverage_days} 天、在库批次 {data.thresholds.expiry_days} 天内到期为当前核查阈值；缺少交期与在途信息时，不能直接判断断供。</p>
        </details>
      </section>
      <DataTable<RiskFinding>
        loading={loading}
        onRetry={reload}
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 880 }}
        tabs={
          <Tabs
            activeKey={kind}
            onChange={setKind}
            items={[
              { key: "all", label: "全部异常" },
              ...Object.entries(kindLabels).map(([key, label]) => ({
                key,
                label,
              })),
            ]}
          />
        }
        toolbar={
          <div className="m2-toolbar risk-toolbar">
            <Input
              aria-label="搜索异常"
              placeholder="搜索物资、科室或异常"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              allowClear
            />
            <div className="risk-toolbar-actions">
              <Button loading={loading} onClick={reload}>重新扫描</Button>
              <Button onClick={() => onAnalyze()}>分析当前项目</Button>
            </div>
          </div>
        }
        columns={[
          {
            title: "物资 / 科室",
            key: "name",
            width: 200,
            render: (_, f) => (
              <>
                <strong>{f.name}</strong>
                <div className="secondary-text">{f.department_name}</div>
              </>
            ),
          },
          {
            title: "类型",
            dataIndex: "kind",
            width: 115,
            render: (v: RiskFinding["kind"]) => kindLabels[v],
          },
          {
            title: "关注级别",
            dataIndex: "priority",
            width: 110,
            render: (v) => (
              <Tag color={v === "high" ? "orange" : "blue"}>
                {v === "high" ? "优先核实" : "关注"}
              </Tag>
            ),
          },
          { title: "核查依据", dataIndex: "summary" },
          {
            title: "操作",
            key: "actions",
            width: 175,
            render: (_, f) => (
              <Space>
                <Button size="small" onClick={() => onDetails(f)}>
                  明细
                </Button>
                <Button size="small" type="link" onClick={() => onAnalyze(f)}>
                  AI 核查
                </Button>
              </Space>
            ),
          },
        ]}
        emptyDescription="当前规则和快照下没有匹配的关注项"
      />
    </div>
  );
}
