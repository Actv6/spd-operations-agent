import type { ReactNode } from "react";
import {
  Alert,
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Skeleton,
  Space,
  Tag,
  Timeline,
} from "antd";
import {
  IconBook2,
  IconDatabase,
  IconChevronRight,
  IconRotateClockwise,
} from "@tabler/icons-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  AnalysisView,
  EvidenceView,
  EventsView,
  InventoryItem,
  RunView,
} from "./types";
import { number, RunStatus, terminal, quality } from "./ui";

import { EvidenceFacts, InventoryFacts } from "./DataFacts";
import { FactSummary } from "./FactSummary";
import { formatAnswerMarkdown } from "./answerFormatting";
import { HumanReviewPanel } from "./HumanReviewPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { ClaimLedger, ReasonBreakdown } from "./ClaimLedger";

export function ResultPanel({
  open,
  onClose,
  run,
  analysis,
  events,
  loading,
  error,
  onCancel,
  onRetry,
  onReload,
  onEvidence,
  onManualRecheck,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  run: RunView | null;
  analysis: AnalysisView | null;
  events: EventsView["items"];
  loading: boolean;
  error: string;
  onCancel: () => void;
  onRetry: () => void;
  onReload: () => void;
  onEvidence: (id: string) => void;
  onManualRecheck?: () => void;
  actions?: ReactNode;
}) {
  return (
    <Drawer
      title="核查详情"
      open={open}
      onClose={onClose}
      size={760}
      extra={run && <RunStatus status={run.status} />}
    >
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={<Button onClick={onReload}>重试读取</Button>}
          className="page-alert"
        />
      )}
      {run && (
        <>
          <div className="result-question">
            <span className="eyebrow">核查问题</span>
            <h2>{run.question}</h2>
            <p>库存快照 · {run.as_of.slice(0, 16).replace("T", " ")}</p>
          </div>
          {loading ? (
            <Skeleton active />
          ) : (
            <>
              {!terminal(run.status) && (
                <Alert
                  type="info"
                  showIcon
                  title={
                    run.status === "queued" ? "请求已入队" : "Agent 正在核查"
                  }
                  description="后台将查询授权库存、检索有效资料并整理引用。关闭窗口不会中断本次核查。"
                  action={<Button onClick={onCancel}>取消运行</Button>}
                />
              )}
              {run.error && (
                <Alert
                  type="error"
                  showIcon
                  title="本次核查未完成"
                  description={
                    <>
                      {run.error.message}
                      <div className="error-code">{run.error.code}</div>
                    </>
                  }
                  action={
                    <Button
                      icon={<IconRotateClockwise size={16} />}
                      onClick={onRetry}
                    >
                      重新核查
                    </Button>
                  }
                />
              )}
              {run.status === "cancelled" && (
                <Alert
                  type="warning"
                  showIcon
                  title="本次运行已取消"
                  description="取消前已发出的模型请求可能仍产生用量，不会再提交最终结果。"
                  action={<Button onClick={onRetry}>重新核查</Button>}
                />
              )}
              {analysis && run.generation_mode === "mock" ? (
                <Alert
                  type="info"
                  title="历史流程校验记录"
                  description="此记录未调用 AI，原始记录已保留。重新发起核查可获取 AI 分析。"
                  action={<Button onClick={onRetry}>发起核查</Button>}
                />
              ) : (
                analysis && (
                  <>
                    <div className="result-answer">
                      <div className="section-heading">
                        <h3>核查结论</h3>
                        <Tag>
                          {analysis.generation_mode === "rules_only"
                            ? "规则核查结果"
                            : "AI 分析"}
                        </Tag>
                      </div>
                      {analysis.risk_summary && (
                        <div
                          className="result-scan-summary"
                          aria-label="本次工具扫描概况"
                        >
                          <span>
                            已扫描{" "}
                            <strong>
                              {analysis.risk_summary.scanned_positions}
                            </strong>{" "}
                            个组合
                          </span>
                          <span>
                            关注项{" "}
                            <strong>{analysis.risk_summary.findings}</strong> 条
                          </span>
                          <span>
                            暂不可估算{" "}
                            <strong>
                              {analysis.risk_summary.skipped_estimates}
                            </strong>{" "}
                            项
                          </span>
                          {analysis.risk_summary.skipped_estimates > 0 && (
                            <small>
                              数据待核查 {analysis.risk_summary.data_quality} 项
                              · 零消耗 {analysis.risk_summary.zero_consumption}{" "}
                              项
                            </small>
                          )}
                        </div>
                      )}
                      {analysis.insufficient_evidence && (
                        <Alert
                          type="warning"
                          showIcon
                          title="部分依据不足，请先核实缺失资料"
                        />
                      )}
                      {analysis.risk_priority_summary && (
                        <p aria-label="服务端风险分级">
                          高关注{" "}
                          <strong>{analysis.risk_priority_summary.high}</strong>{" "}
                          条 · 中关注{" "}
                          <strong>
                            {analysis.risk_priority_summary.medium}
                          </strong>{" "}
                          条
                        </p>
                      )}
                      {analysis.risk_findings &&
                        analysis.risk_findings.length > 0 && (
                          <Collapse
                            items={[
                              {
                                key: "risk-list",
                                label: "查看本次扫描关注清单",
                                children: (
                                  <ul>
                                    {analysis.risk_findings.map((f) => (
                                      <li key={f.id}>
                                        <Tag
                                          color={
                                            f.priority === "high"
                                              ? "error"
                                              : "warning"
                                          }
                                        >
                                          {f.priority === "high"
                                            ? "高关注"
                                            : "中关注"}
                                        </Tag>
                                        {f.name} · {f.department_name}：
                                        {f.summary}
                                      </li>
                                    ))}
                                  </ul>
                                ),
                              },
                            ]}
                          />
                        )}
                      <div className="markdown-content answer-prose">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {formatAnswerMarkdown(analysis.answer)}
                        </ReactMarkdown>
                      </div>
                      <ReasonBreakdown analysis={analysis} />
                      <ClaimLedger
                        analysis={analysis}
                        onEvidence={onEvidence}
                      />
                    </div>
                    {analysis.inventory.length > 0 && (
                      <section className="result-section">
                        {analysis.inventory.length > 3 ? (
                          <Collapse
                            items={[
                              {
                                key: "facts",
                                label: `库存事实 · ${analysis.inventory.length} 个组合（展开查看）`,
                                children: (
                                  <InventoryFacts rows={analysis.inventory} />
                                ),
                              },
                            ]}
                          />
                        ) : (
                          <>
                            <h3>库存事实</h3>
                            {analysis.inventory.map((row) => (
                              <FactSummary
                                key={`${row.item_id}/${row.department_id}`}
                                row={row}
                              />
                            ))}
                          </>
                        )}
                      </section>
                    )}
                    <section className="result-section">
                      <div className="section-heading">
                        <h3>引用依据</h3>
                        <span>{analysis.citations.length} 条可追溯来源</span>
                      </div>
                      {analysis.citations.length ? (
                        <div className="citation-list">
                          {analysis.citations.map((c, i) => (
                            <Button
                              key={c.evidence_id}
                              className="citation-button"
                              type="text"
                              onClick={() => onEvidence(c.evidence_id)}
                            >
                              <span className="citation-icon">
                                {c.source_kind === "document" ? (
                                  <IconBook2 size={20} />
                                ) : (
                                  <IconDatabase size={20} />
                                )}
                              </span>
                              <span className="citation-copy">
                                <strong>
                                  {i + 1}. {c.title}
                                </strong>
                                <small>
                                  {c.source_kind === "document"
                                    ? `v${c.source_version} · ${String(c.location.chapter || "正文")}`
                                    : "授权库存快照"}
                                  {!c.currently_valid && " · 当前已失效"}
                                </small>
                              </span>
                              <IconChevronRight size={17} />
                            </Button>
                          ))}
                        </div>
                      ) : (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="没有可引用依据"
                        />
                      )}
                    </section>
                    <p className="method-note">{analysis.warnings.join(" ")}</p>
                    <FeedbackPanel
                      key={analysis.analysis_id}
                      analysisId={analysis.analysis_id}
                      onSaved={onReload}
                    />
                  </>
                )
              )}
              {run.generation_mode !== "mock" && events.length > 0 && (
                <Collapse
                  className="run-timeline"
                  ghost
                  items={[
                    {
                      key: "events",
                      label: `运行过程 · ${events.length} 条记录`,
                      children: (
                        <Timeline
                          items={events.map((e) => ({
                            content: (
                              <>
                                <strong>
                                  {e.step === "get_inventory"
                                    ? "查询库存事实"
                                    : e.step === "get_batches"
                                      ? "查询批次效期"
                                      : e.step === "get_consumption"
                                        ? "查询14日消耗"
                                        : e.step === "compute_risks"
                                          ? "扫描范围内异常"
                                          : e.step === "search_knowledge"
                                            ? "检索知识库"
                                            : e.type === "run_started"
                                              ? "开始运行"
                                              : e.type === "analysis_ready"
                                                ? "结果已保存"
                                                : e.type === "run_finished"
                                                  ? "运行结束"
                                                  : "生成与校验"}
                                </strong>
                                <p className="secondary-text">
                                  {String(e.payload.message || "")}{" "}
                                  {new Date(e.occurred_at).toLocaleTimeString(
                                    "zh-CN",
                                  )}
                                </p>
                              </>
                            ),
                          }))}
                        />
                      ),
                    },
                  ]}
                />
              )}
              {terminal(run.status) && (
                <HumanReviewPanel
                  key={run.run_id}
                  runId={run.run_id}
                  onEvidence={onEvidence}
                  onSaved={onReload}
                  onRecheck={onManualRecheck || onRetry}
                />
              )}
              <p className="source-metadata">运行编号 {run.run_id}</p>
            </>
          )}
        </>
      )}
      {actions}
    </Drawer>
  );
}

export function EvidencePanel({
  evidence,
  loading,
  open,
  error,
  onClose,
  onReload,
  identities = [],
}: {
  evidence: EvidenceView | null;
  loading: boolean;
  open: boolean;
  error: string;
  onClose: () => void;
  onReload: () => void;
  identities?: InventoryItem[];
}) {
  return (
    <Drawer
      title="引用来源"
      open={open}
      onClose={onClose}
      size={evidence?.source_kind === "tool" ? 960 : 660}
    >
      {loading ? (
        <Skeleton active />
      ) : evidence ? (
        <>
          <Space>
            <Tag>
              {evidence.source_kind === "document" ? "文档原文" : "数据库快照"}
            </Tag>
            {!evidence.currently_valid && <Tag color="warning">历史依据</Tag>}
          </Space>
          <h2 className="drawer-heading">{evidence.title}</h2>
          {!evidence.currently_valid && (
            <Alert type="warning" title="此来源当前已失效，仅供历史回查" />
          )}
          <p className="secondary-text">
            证据业务时点 · {evidence.as_of.slice(0, 16).replace("T", " ")}
          </p>
          {evidence.source_kind === "document" ? (
            <>
              <p className="secondary-text">
                v{evidence.source_version} ·{" "}
                {String(evidence.location.chapter || "正文")}
              </p>
              <blockquote className="evidence-excerpt">
                {evidence.excerpt}
              </blockquote>
            </>
          ) : (
            <EvidenceFacts
              key={evidence.evidence_id}
              evidence={evidence}
              identities={identities}
            />
          )}
          <Collapse
            ghost
            items={[
              {
                key: "source",
                label: "查看来源定位与校验信息",
                children: (
                  <Descriptions
                    column={1}
                    size="small"
                    items={[
                      {
                        key: "hash",
                        label: "来源 Hash",
                        children: (
                          <span className="hash-text">{evidence.hash}</span>
                        ),
                      },
                      {
                        key: "time",
                        label: "业务时点",
                        children: evidence.as_of,
                      },
                      {
                        key: "loc",
                        label: "原文定位",
                        children:
                          evidence.source_kind === "document"
                            ? `${String(evidence.location.source_path)} · 字符 ${String(evidence.location.start_offset)}–${String(evidence.location.end_offset)}`
                            : `快照 ${evidence.source_version}`,
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        </>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          title={error}
          action={<Button onClick={onReload}>重新读取来源</Button>}
        />
      ) : (
        <Empty description="暂无来源" />
      )}
    </Drawer>
  );
}
