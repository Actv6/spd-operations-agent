import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Input,
  Select,
  Space,
  Tabs,
  Tag,
} from "antd";
import { api, ApiError } from "./api";
import type {
  ActivationView,
  VersionList,
  VersionItem,
  VersionComparison,
  VersionChange,
} from "./types";
import { DataTable } from "./components/DataTable";
import { message, route } from "./ui";
import "./versions.css";

const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "创建时间未记录";
const labels = {
  added: "新增",
  removed: "移除",
  changed: "变化",
  unchanged: "未变化",
};
const short = (id: string) => id.slice(0, 8);
const quantity = (value: string | null, unit: string | null) =>
  value === null
    ? "—"
    : `${value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value} ${unit || ""}`;
export function VersionsPanel({
  projectId,
  refreshKey,
  onPublished,
}: {
  projectId: string;
  refreshKey: number;
  onPublished: () => Promise<void>;
}) {
  const base = `/projects/${projectId}/versions`;
  const { message: toast } = App.useApp();
  const [data, setData] = useState<VersionList | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("versions");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState(false);
  const [comparison, setComparison] = useState<VersionComparison | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [filter, setFilter] = useState("changed");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const saving = useRef(false);
  const retryKey = useRef<{ body: string; key: string } | null>(null);
  const load = useCallback(async () => {
    const version = ++generation.current;
    setLoading(true);
    try {
      const result = await api<VersionList>(base);
      if (version === generation.current) {
        setData(result);
        setError("");
        setFrom(result.current_snapshot_id);
        setTo(
          result.items.find((r) => !r.current)?.id ||
            result.current_snapshot_id,
        );
      }
    } catch (e) {
      if (version === generation.current) setError(message(e));
    } finally {
      if (version === generation.current) setLoading(false);
    }
  }, [base]);
  useEffect(() => {
    void load();
    return () => {
      generation.current++;
      detailGeneration.current++;
    };
  }, [load, refreshKey]);
  async function preview(fromId: string, toId: string) {
    const version = ++detailGeneration.current;
    setOpen(true);
    setDetailLoading(true);
    setDetailError("");
    setComparison(null);
    setReason("");
    setAck(false);
    setConflict(false);
    setFilter("changed");
    retryKey.current = null;
    try {
      const result = await api<VersionComparison>(
        `${base}/compare?from_id=${encodeURIComponent(fromId)}&to_id=${encodeURIComponent(toId)}`,
      );
      if (version === detailGeneration.current) setComparison(result);
    } catch (e) {
      if (version === detailGeneration.current) setDetailError(message(e));
    } finally {
      if (version === detailGeneration.current) setDetailLoading(false);
    }
  }
  async function restore() {
    if (!comparison || saving.current || !ack || reason.trim().length < 5)
      return;
    const body = {
      target_snapshot_id: comparison.to_id,
      expected_revision: comparison.revision,
      reason: reason.trim(),
    };
    const serialized = JSON.stringify(body);
    if (retryKey.current?.body !== serialized)
      retryKey.current = { body: serialized, key: crypto.randomUUID() };
    saving.current = true;
    setBusy(true);
    setDetailError("");
    try {
      await api<ActivationView>(`${base}/restore`, {
        method: "POST",
        body,
        key: retryKey.current.key,
      });
      setOpen(false);
      void toast.success("当前数据版本已切换，历史核查记录保留");
      await load();
      await onPublished();
    } catch (e) {
      setDetailError(message(e));
      if (
        e instanceof ApiError &&
        ["SNAPSHOT_CHANGED", "ALREADY_CURRENT"].includes(e.detail.code)
      ) {
        setConflict(true);
        await load();
      }
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  const options =
    data?.items.map((r) => ({
      value: r.id,
      label: `${date(r.as_of)} · ${short(r.id)}${r.current ? " · 当前" : ""}`,
    })) || [];
  const counts = comparison?.changes.reduce(
    (v, row) => ({ ...v, [row.kind]: v[row.kind] + 1 }),
    { added: 0, removed: 0, changed: 0, unchanged: 0 },
  );
  const canRestore =
    data?.can_restore &&
    comparison &&
    comparison.from_id === comparison.current_snapshot_id &&
    comparison.to_id !== comparison.current_snapshot_id;
  return (
    <>
      <div className="version-context">
        <p>
          查看库存数据的发布历史，比较版本并恢复历史数据。回退保留原业务时点，物资与科室目录按现有档案维护。时间均为北京时间。
        </p>
        <Button onClick={() => route("/app/imports")}>前往数据导入</Button>
      </div>
      <Tabs
        className="version-tabs"
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: "versions", label: `数据版本（${data?.items.length ?? 0}）` },
          { key: "history", label: "切换记录" },
        ]}
      />
      {tab === "versions" ? (
        <DataTable<VersionItem>
          rowKey="id"
          dataSource={data?.items || []}
          loading={loading}
          error={error}
          onRetry={() => void load()}
          scroll={{ x: 1000 }}
          toolbar={
            <div className="version-selectors">
              <label>
                基准版本
                <Select
                  aria-label="基准版本"
                  value={from || undefined}
                  options={options}
                  onChange={setFrom}
                />
              </label>
              <span>→</span>
              <label>
                目标版本
                <Select
                  aria-label="目标版本"
                  value={to || undefined}
                  options={options}
                  onChange={setTo}
                />
              </label>
              <Button
                disabled={!from || !to || from === to}
                onClick={() => void preview(from, to)}
              >
                比较版本
              </Button>
            </div>
          }
          columns={[
            {
              title: "版本 / 业务时点",
              key: "version",
              width: 235,
              render: (_, r) => (
                <div>
                  <strong>{date(r.as_of)}</strong>
                  <div className="version-secondary">
                    {short(r.id)}{" "}
                    {r.current && <Tag color="green">当前使用</Tag>}
                  </div>
                </div>
              ),
            },
            {
              title: "创建时间 / 发布人",
              key: "publication",
              width: 220,
              render: (_, r) => (
                <div>
                  {date(r.created_at)}
                  <div className="version-secondary">{r.actor_name}</div>
                </div>
              ),
            },
            { title: "库存组合", dataIndex: "positions", width: 110 },
            { title: "校验情况", dataIndex: "validation" },
            {
              title: "操作",
              key: "action",
              width: 180,
              fixed: "right",
              render: (_, r) => (
                <Button
                  disabled={r.current}
                  onClick={() => void preview(data!.current_snapshot_id, r.id)}
                >
                  查看差异{data?.can_restore ? "与回退" : ""}
                </Button>
              ),
            },
          ]}
        />
      ) : (
        <DataTable<ActivationView>
          rowKey="id"
          dataSource={data?.history || []}
          loading={loading}
          error={error}
          onRetry={() => void load()}
          scroll={{ x: 850 }}
          emptyDescription="暂无版本切换记录；已有数据可在数据版本中查看"
          columns={[
            {
              title: "操作时间",
              dataIndex: "created_at",
              width: 190,
              render: date,
            },
            {
              title: "操作",
              dataIndex: "action",
              width: 100,
              render: (v) =>
                v === "restore"
                  ? "手动回退"
                  : v === "publish"
                    ? "导入发布"
                    : "场景发布",
            },
            {
              title: "版本变化",
              key: "versions",
              width: 220,
              render: (_, r) =>
                `${r.previous_snapshot_id ? short(r.previous_snapshot_id) : "—"} → ${short(r.snapshot_id)}`,
            },
            { title: "操作人", dataIndex: "actor_name", width: 120 },
            { title: "原因", dataIndex: "reason" },
          ]}
        />
      )}
      <Drawer
        title="版本差异与回退"
        size={1000}
        open={open}
        onClose={() => {
          if (!busy) {
            setOpen(false);
            detailGeneration.current++;
          }
        }}
        closable={!busy}
        mask={{ closable: !busy }}
        keyboard={!busy}
        loading={detailLoading}
      >
        {detailError && <Alert type="error" showIcon title={detailError} />}
        {comparison && (
          <>
            <div className="version-comparison-heading">
              <div>
                <span>基准版本 · {short(comparison.from_id)}</span>
                <strong>{date(comparison.from_as_of)}</strong>
              </div>
              <span>→</span>
              <div>
                <span>目标版本 · {short(comparison.to_id)}</span>
                <strong>{date(comparison.to_as_of)}</strong>
              </div>
            </div>
            <p className="version-note">
              数量显示为“基准 → 目标”，指标按各自业务时点计算。消耗窗口为各自前 14
              个完整自然日；“—”表示不存在或无法估算。回退不会把历史数据标为今日数据。
            </p>
            <div className="version-counts">
              {counts &&
                Object.entries(counts).map(([key, count]) => (
                  <span key={key}>
                    {labels[key as keyof typeof labels]}{" "}
                    <strong>{count}</strong>
                  </span>
                ))}
            </div>
            <DataTable<VersionChange>
              rowKey="key"
              className="version-diff"
              dataSource={comparison.changes.filter(
                (r) => filter === "all" || r.kind !== "unchanged",
              )}
              scroll={{ x: 850 }}
              toolbar={
                <Checkbox
                  checked={filter === "all"}
                  onChange={(e) =>
                    setFilter(e.target.checked ? "all" : "changed")
                  }
                >
                  显示未变化项
                </Checkbox>
              }
              emptyDescription="所选版本没有库存组合变化"
              columns={[
                {
                  title: "物资 / 科室",
                  key: "item",
                  width: 175,
                  render: (_, r) => (
                    <div>
                      <strong>{r.name}</strong>
                      <div className="version-secondary">{r.department}</div>
                    </div>
                  ),
                },
                {
                  title: "类型",
                  dataIndex: "kind",
                  width: 75,
                  render: (v) => labels[v as keyof typeof labels],
                },
                {
                  title: "可用库存",
                  key: "stock",
                  width: 210,
                  render: (_, r) =>
                    `${quantity(r.before_available, r.before_unit)} → ${quantity(r.after_available, r.after_unit)}`,
                },
                {
                  title: "日均消耗",
                  key: "consumption",
                  width: 210,
                  render: (_, r) =>
                    `${quantity(r.before_average, r.before_unit)} → ${quantity(r.after_average, r.after_unit)}`,
                },
                {
                  title: "变化内容",
                  key: "details",
                  render: (_, r) =>
                    r.details.length ? (
                      <ul>
                        {r.details.map((d) => (
                          <li key={d}>{d}</li>
                        ))}
                      </ul>
                    ) : (
                      labels[r.kind]
                    ),
                },
              ]}
            />
            {canRestore ? (
              <section className="version-restore">
                <h3>恢复到目标版本</h3>
                <p>
                  库存、异常中心和新核查将使用目标版本。已生成的导入预览需重新校验；历史
                  AI 核查、证据和个人任务保留。物资档案与科室目录不会回退。
                </p>
                <label htmlFor="restore-reason">回退原因</label>
                <Input.TextArea
                  id="restore-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  minLength={5}
                  maxLength={500}
                  showCount
                  rows={3}
                  placeholder="请说明回退原因，至少 5 个字"
                  disabled={busy || conflict}
                />
                <Checkbox
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                  disabled={busy || conflict}
                >
                  已核对差异及业务时点，确认使用目标版本
                </Checkbox>
                <Space wrap>
                  <Button
                    type="primary"
                    disabled={!ack || reason.trim().length < 5 || conflict}
                    loading={busy}
                    onClick={() => void restore()}
                  >
                    确认回退
                  </Button>
                  {conflict && (
                    <Button
                      onClick={() =>
                        void preview(
                          data!.current_snapshot_id,
                          comparison.to_id,
                        )
                      }
                    >
                      重新预览
                    </Button>
                  )}
                </Space>
              </section>
            ) : (
              <p className="version-note">
                {!data?.can_restore
                  ? "当前账号仅可查看和比较版本。"
                  : "需要回退时，请以当前使用版本为基准，选择其他版本作为目标后重新比较。"}
              </p>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}
