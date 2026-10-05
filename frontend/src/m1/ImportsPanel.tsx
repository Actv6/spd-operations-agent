import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Input,
  Modal,
  Space,
  Steps,
  Tabs,
  Tag,
} from "antd";
import { IconUpload, IconArrowRight } from "@tabler/icons-react";
import { api, ApiError } from "./api";
import type {
  ImportFiles,
  ImportList,
  ImportSummary,
  ImportTemplate,
  ImportView,
} from "./types";
import { DataTable } from "./components/DataTable";
import { date, message, number, route } from "./ui";
import { CsvFileUpload } from "./components/CsvFileUpload";
import "./imports.css";

const fileLabels = { inventory: "库存", batches: "批次", consumption: "消耗" };
const businessTime = (value: string) => value.replace("T", " ").slice(0, 19);
const states = { invalid: "校验未通过", ready: "待发布", published: "已发布" };
const changes = {
  added: "新增",
  removed: "移除",
  changed: "变化",
  unchanged: "一致",
};
type FileKind = keyof ImportFiles;
const kinds = Object.keys(fileLabels) as FileKind[];

function download(name: string, text: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ImportsPanel({
  projectId,
  refreshKey,
  onPublished,
}: {
  projectId: string;
  refreshKey: number;
  onPublished: () => Promise<void>;
}) {
  const [data, setData] = useState<ImportList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [template, setTemplate] = useState<ImportTemplate | null>(null);
  const [files, setFiles] = useState<Partial<ImportFiles>>({});
  const [reading, setReading] = useState<Partial<Record<FileKind, boolean>>>(
    {},
  );
  const readingFiles = kinds.some((kind) => reading[kind]);
  const completedFiles = kinds.filter(
    (kind) => files[kind] !== undefined,
  ).length;
  const readingRef = useRef(reading);
  readingRef.current = reading;
  const [asOf, setAsOf] = useState("");
  const [selected, setSelected] = useState<ImportView | null>(null);
  const [detailError, setDetailError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const key = useRef<{ body: string; key: string } | null>(null);
  const lock = useRef(false);
  const requestVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    try {
      const result = await api<ImportList>(`/projects/${projectId}/imports`);
      if (version === requestVersion.current) {
        setData(result);
        setError("");
      }
    } catch (e) {
      if (version === requestVersion.current) setError(message(e));
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => {
    void load();
    return () => {
      requestVersion.current++;
    };
  }, [load, refreshKey]);

  async function start() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setSelected(null);
    setTemplate(null);
    setFiles({});
    setReading({});
    setDetailError("");
    setAck(false);
    setOpen(true);
    try {
      const t = await api<ImportTemplate>(
        `/projects/${projectId}/import-template`,
      );
      setTemplate(t);
      setAsOf(t.as_of.slice(0, 19));
    } catch (e) {
      setDetailError(message(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function validate() {
    if (
      lock.current ||
      kinds.some((kind) => readingRef.current[kind]) ||
      !asOf ||
      !template ||
      !kinds.every((k) => files[k] !== undefined)
    )
      return;
    lock.current = true;
    setBusy(true);
    setDetailError("");
    const body = {
      base_snapshot_id: template.base_snapshot_id,
      catalog_hash: template.catalog_hash,
      publication_revision: template.publication_revision,
      as_of: asOf + "+08:00",
      files,
    };
    const serialized = JSON.stringify(body);
    if (key.current?.body !== serialized)
      key.current = { body: serialized, key: crypto.randomUUID() };
    try {
      setSelected(
        await api<ImportView>(`/projects/${projectId}/imports`, {
          method: "POST",
          body,
          key: key.current.key,
        }),
      );
      setAck(false);
      await load();
    } catch (e) {
      setDetailError(message(e));
      if (
        e instanceof ApiError &&
        ["CATALOG_CHANGED", "SNAPSHOT_CHANGED"].includes(e.detail.code)
      )
        setTemplate(null);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function inspect(row: ImportSummary) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setSelected(null);
    setTemplate(null);
    setDetailError("");
    setAck(false);
    setOpen(true);
    try {
      setSelected(
        await api<ImportView>(`/projects/${projectId}/imports/${row.id}`),
      );
    } catch (e) {
      setDetailError(message(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function publish() {
    if (lock.current || !selected) return;
    lock.current = true;
    setBusy(true);
    setDetailError("");
    try {
      const result = await api<ImportView>(
        `/projects/${projectId}/imports/${selected.id}/publish`,
        { method: "POST", body: { acknowledge_warnings: ack } },
      );
      setSelected(result);
      setConfirm(false);
      await load();
      await onPublished();
    } catch (e) {
      setConfirm(false);
      setDetailError(message(e));
      if (
        e instanceof ApiError &&
        ["CATALOG_CHANGED", "SNAPSHOT_CHANGED"].includes(e.detail.code)
      )
        setSelected((old) => (old ? { ...old, stale: true } : old));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const ready =
    selected?.status === "ready" && !selected.stale && data?.can_publish;
  return (
    <>
      <div className="import-intro">
        <div>
          <strong>导入、校验，再发布</strong>
          <p>
            上传库存、批次与近 14 日消耗。校验预览通过后，由你确认切换项目快照。
          </p>
        </div>
        <Button
          type="primary"
          icon={<IconUpload size={17} />}
          disabled={!data?.can_publish}
          onClick={() => void start()}
        >
          新建导入
        </Button>
      </div>
      {data && !data.can_publish && (
        <p className="import-permission">
          当前账号可查看导入记录；上传与发布需项目负责人权限。
        </p>
      )}
      <DataTable<ImportSummary>
        rowKey="id"
        loading={loading}
        error={error}
        onRetry={() => void load()}
        dataSource={data?.items || []}
        emptyDescription="还没有导入记录"
        scroll={{ x: 780 }}
        toolbar={
          <span className="secondary-text">
            最近 50 次导入 · 校验不会改变当前数据
          </span>
        }
        columns={[
          {
            title: "数据时点",
            dataIndex: "as_of",
            render: (v) => businessTime(v),
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (v: ImportSummary["status"]) => (
              <Tag
                color={
                  v === "invalid"
                    ? "error"
                    : v === "published"
                      ? "success"
                      : "default"
                }
              >
                {states[v]}
              </Tag>
            ),
          },
          {
            title: "校验结果",
            render: (_, r) =>
              `${r.error_count} 个错误 · ${r.warning_count} 个警告`,
          },
          { title: "导入人", dataIndex: "actor_name" },
          {
            title: "创建时间",
            dataIndex: "created_at",
            render: (v) => date(v),
          },
          {
            title: "操作",
            width: 90,
            render: (_, r) => (
              <Button type="link" onClick={() => void inspect(r)}>
                查看
              </Button>
            ),
          },
        ]}
      />
      <Drawer
        title={selected ? "校验与快照预览" : "新建数据导入"}
        open={open}
        width="min(920px, 100vw)"
        onClose={() => {
          if (!busy) {
            setOpen(false);
            setReading({});
            setFiles({});
          }
        }}
        maskClosable={!busy}
        closable={!busy}
        destroyOnHidden
        footer={
          selected ? (
            <div className="import-footer">
              <span>
                {selected.status === "published"
                  ? "已发布，历史核查保留原始快照"
                  : "发布将整份替换当前库存快照"}
              </span>
              <Space>
                {selected.status !== "published" && (
                  <Button
                    disabled={busy}
                    onClick={() => {
                      if (template && !selected.stale) {
                        setSelected(null);
                        setFiles({});
                        setReading({});
                        setDetailError("");
                      } else void start();
                    }}
                  >
                    重新上传
                  </Button>
                )}
                {selected.status === "published" ? (
                  <Button
                    onClick={() => {
                      setOpen(false);
                      route("/app/risks");
                    }}
                    icon={<IconArrowRight size={16} />}
                  >
                    查看异常中心
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    disabled={!ready || (!!selected.warning_count && !ack)}
                    loading={busy}
                    onClick={() => setConfirm(true)}
                  >
                    确认发布
                  </Button>
                )}
              </Space>
            </div>
          ) : template ? (
            <div className="import-footer">
              <span role="status">
                {readingFiles
                  ? "正在读取文件…"
                  : busy
                    ? "正在提交并校验，请稍候…"
                    : `已准备 ${completedFiles}/3 个文件 · 校验不会改变当前数据`}
              </span>
              <Space>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setOpen(false);
                    setReading({});
                    setFiles({});
                  }}
                >
                  取消
                </Button>
                <Button
                  type="primary"
                  loading={busy}
                  disabled={readingFiles || !asOf || completedFiles !== 3}
                  onClick={() => void validate()}
                >
                  校验并生成预览
                </Button>
              </Space>
            </div>
          ) : null
        }
      >
        <Steps
          className="import-steps"
          responsive={false}
          size="small"
          current={selected?.status === "published" ? 2 : selected ? 1 : 0}
          items={[
            { title: "上传文件" },
            { title: "校验预览" },
            { title: "发布快照" },
          ]}
        />
        {detailError && (
          <Alert
            className="import-feedback"
            type="error"
            showIcon
            title={detailError}
          />
        )}
        {!selected && template && (
          <div className="import-form">
            <h3>1. 准备三个 CSV 文件</h3>
            <p className="secondary-text">
              下载当前快照作为填写模板，保留表头、物资编码、科室和基础单位。每文件最多
              10MB、10,000 行，编码为 UTF-8。
            </p>
            <p className="secondary-text">
              需要补充或修正目录时，先维护 <a href="/app/products">物资档案</a>{" "}
              和 <a href="/app/departments">科室目录</a>
              ，再重新下载模板。已停用物资或科室不会从已有库存中消失，但会阻止新导入。
            </p>
            <div className="import-files">
              {kinds.map((kind) => (
                <CsvFileUpload
                  key={kind}
                  label={fileLabels[kind]}
                  description={
                    kind === "inventory"
                      ? "当前库存及占用数量"
                      : kind === "batches"
                        ? "批次、有效期与状态"
                        : "近 14 个完整自然日"
                  }
                  disabled={busy}
                  onDownload={() =>
                    download(
                      `${fileLabels[kind]}模板.csv`,
                      template.files[kind],
                    )
                  }
                  onChange={(content) =>
                    setFiles((old) => ({ ...old, [kind]: content }))
                  }
                  onReadingChange={(value) => {
                    readingRef.current = {
                      ...readingRef.current,
                      [kind]: value,
                    };
                    setReading(readingRef.current);
                  }}
                />
              ))}
            </div>
            <details className="import-guide">
              <summary>查看字段填写规则</summary>
              <ul>
                <li>
                  库存：物资编码、科室、单位、在库数量、冻结数量、预留数量、记录时间。
                </li>
                <li>
                  批次：批次编号、物资编码、科室、单位、在库数量、冻结数量、预留数量、有效期、状态（可用
                  / 冻结 / 过期隔离）。
                </li>
                <li>
                  消耗：物资编码、科室、单位、日期、消耗数量。每个组合每天一条；无消耗填
                  0，缺记录保持缺失。
                </li>
                <li>
                  数量最多 4 位小数，按基础单位填写；日期为
                  YYYY-MM-DD，记录时间须带时区，如 2026-09-27T09:00:00+08:00。
                </li>
                <li>
                  导入不会自动新建档案，请先在物资档案或科室目录完成维护。三个文件共同构成完整快照，未提供的原库存组合会被移除。
                </li>
              </ul>
            </details>
            <h3>2. 设置业务时点</h3>
            <label htmlFor="import-asof">数据截止时间（北京时间）</label>
            <Input
              id="import-asof"
              type="datetime-local"
              step="1"
              value={asOf}
              disabled={busy}
              onChange={(e) =>
                setAsOf(
                  e.target.value.length === 16
                    ? e.target.value + ":00"
                    : e.target.value,
                )
              }
            />
            <p className="secondary-text">
              消耗文件应覆盖该日期之前的 14
              个完整自然日。业务时点不能早于当前快照。
            </p>
          </div>
        )}
        {!selected && !template && (
          <p className="import-feedback">
            {busy ? (
              "正在读取数据…"
            ) : (
              <Button onClick={() => void start()}>重新载入</Button>
            )}
          </p>
        )}
        {selected && (
          <div className="import-preview">
            <div className="import-metrics">
              <div>
                <span>库存组合</span>
                <strong>{selected.positions}</strong>
              </div>
              <div>
                <span>必须修正</span>
                <strong className={selected.error_count ? "import-error" : ""}>
                  {selected.error_count}
                  <small> 个错误</small>
                </strong>
              </div>
              <div>
                <span>需要确认</span>
                <strong>
                  {selected.warning_count}
                  <small> 个警告</small>
                </strong>
              </div>
            </div>
            <p className="secondary-text">
              业务时点：{businessTime(selected.as_of)} ·{" "}
              {states[selected.status]}
              {selected.published_at
                ? ` · 发布于 ${date(selected.published_at)}`
                : ""}
            </p>
            {selected.stale && (
              <Alert
                type="warning"
                showIcon
                title="当前快照或主数据目录已更新，这份预览已过期。请重新下载模板并校验。"
              />
            )}
            {selected.status === "published" && (
              <Alert
                type="success"
                showIcon
                title="此快照已发布。历史核查与引用保持原版本。"
              />
            )}
            <Tabs
              defaultActiveKey={selected.issues.length ? "issues" : "changes"}
              items={[
                {
                  key: "issues",
                  label: `校验问题（${selected.issues.length}）`,
                  children: (
                    <DataTable
                      rowKey={(_, i) => String(i)}
                      dataSource={selected.issues}
                      emptyDescription="未发现校验问题"
                      columns={[
                        {
                          title: "级别",
                          width: 80,
                          render: (_, r) => (
                            <Tag
                              color={
                                r.severity === "error" ? "error" : "warning"
                              }
                            >
                              {r.severity === "error" ? "错误" : "警告"}
                            </Tag>
                          ),
                        },
                        {
                          title: "位置",
                          width: 135,
                          render: (_, r) =>
                            `${fileLabels[r.file as FileKind] || r.file}${r.row ? ` · 第 ${r.row} 行` : ""}`,
                        },
                        { title: "问题与处理", dataIndex: "message" },
                      ]}
                    />
                  ),
                },
                {
                  key: "changes",
                  label: "变更对比",
                  disabled: !!selected.error_count,
                  children: (
                    <>
                      <p className="secondary-text">
                        对比原快照与候选快照的库存及业务记录；“移除”表示该组合不会进入新快照。
                      </p>
                      <DataTable
                        rowKey={(_, i) => String(i)}
                        dataSource={selected.changes}
                        columns={[
                          {
                            title: "物资 / 科室",
                            render: (_, r) => (
                              <>
                                {r.name}
                                <div className="secondary-text">
                                  {r.department}
                                </div>
                              </>
                            ),
                          },
                          {
                            title: "变化",
                            render: (_, r) => (
                              <Tag
                                color={
                                  r.kind === "removed" ? "warning" : "default"
                                }
                              >
                                {changes[r.kind]}
                              </Tag>
                            ),
                          },
                          {
                            title: "变化内容",
                            render: (_, r) => r.details.join("；") || "—",
                          },
                          {
                            title: "原可用库存",
                            render: (_, r) =>
                              `${number(r.before_available)} ${r.unit}`,
                          },
                          {
                            title: "新可用库存",
                            render: (_, r) =>
                              `${number(r.after_available)} ${r.unit}`,
                          },
                        ]}
                      />
                    </>
                  ),
                },
                {
                  key: "inventory",
                  label: "库存预览",
                  disabled: !!selected.error_count,
                  children: (
                    <DataTable
                      rowKey={(r) => r.item_id + r.department_id}
                      dataSource={selected.inventory}
                      scroll={{ x: 620 }}
                      columns={[
                        {
                          title: "物资 / 科室",
                          render: (_, r) => (
                            <>
                              {r.name}
                              <div className="secondary-text">
                                {r.department_name}
                              </div>
                            </>
                          ),
                        },
                        {
                          title: "可用库存",
                          render: (_, r) => `${number(r.available)} ${r.unit}`,
                        },
                        {
                          title: "日均消耗",
                          render: (_, r) => number(r.daily_average),
                        },
                        {
                          title: "覆盖天数",
                          render: (_, r) => number(r.coverage_days),
                        },
                        {
                          title: "有效消耗记录",
                          render: (_, r) => `${r.observed_days}/14 天`,
                        },
                      ]}
                    />
                  ),
                },
              ]}
            />
            {!!selected.warning_count && selected.status === "ready" && (
              <Checkbox
                checked={ack}
                disabled={busy || selected.stale}
                onChange={(e) => setAck(e.target.checked)}
              >
                我已核对全部警告及移除清单，确认保留数据缺口并发布
              </Checkbox>
            )}
          </div>
        )}
      </Drawer>
      <Modal
        title="发布这份数据快照？"
        open={confirm}
        onCancel={() => !busy && setConfirm(false)}
        onOk={() => void publish()}
        confirmLoading={busy}
        okText="发布快照"
        cancelText="返回核对"
        closable={!busy}
        maskClosable={!busy}
        cancelButtonProps={{ disabled: busy }}
      >
        <p>业务时点：{selected && businessTime(selected.as_of)}</p>
        <p>
          发布后，库存和异常中心将使用本次导入的 {selected?.positions}{" "}
          个物资科室组合。未提供的原库存组合会被移除；历史核查仍可查看原数据。
        </p>
      </Modal>
    </>
  );
}
