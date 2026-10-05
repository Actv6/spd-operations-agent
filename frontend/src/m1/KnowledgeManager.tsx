import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Modal, Select, Space, Tag } from "antd";
import { api } from "./api";
import { message } from "./ui";
import { DataTable } from "./components/DataTable";
import type {
  KnowledgeManagement,
  KnowledgePreview,
  KnowledgeWrite,
  KnowledgeMutation,
  KnowledgeChangeView,
} from "./types";

const empty: KnowledgeWrite = {
  title: "",
  version: "",
  content: "",
  source_note: "",
};

export function KnowledgeManager({
  projectId,
  refreshKey,
  onChanged,
}: {
  projectId: string;
  refreshKey: number;
  onChanged: () => void;
}) {
  const [state, setState] = useState<KnowledgeManagement | null>(null);
  const [form, setForm] = useState<KnowledgeWrite>(empty);
  const [preview, setPreview] = useState<KnowledgePreview | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [retireId, setRetireId] = useState<string>();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState<"publish" | "retire" | null>(null);
  const epoch = useRef(0);
  const editVersion = useRef(0);
  const pending = useRef(false);
  const mutationKey = useRef({ body: "", key: "" });
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;
  useEffect(() => {
    const version = ++epoch.current;
    const abort = new AbortController();
    setState(null);
    setPreview(null);
    setError("");
    setBusy(false);
    api<KnowledgeManagement>(`/projects/${projectId}/knowledge/manage`, {
      signal: abort.signal,
    })
      .then((r) => {
        if (epoch.current === version) setState(r);
      })
      .catch((e) => {
        if (!abort.signal.aborted && epoch.current === version)
          setError(message(e));
      });
    return () => {
      epoch.current++;
      abort.abort();
    };
  }, [projectId, refreshKey, reload]);
  function edit(field: keyof KnowledgeWrite, value: string) {
    editVersion.current++;
    setForm((old) => ({ ...old, [field]: value }));
    setPreview(null);
    setSuccess("");
  }
  async function loadFile(file?: File) {
    if (!file || pending.current) return;
    const version = epoch.current;
    const editAt = editVersion.current;
    try {
      if (!/\.(md|txt)$/i.test(file.name) || file.size > 200000)
        throw new Error("请选择不超过200KB的 Markdown 或文本文件");
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      if (content.length > 50000) throw new Error("资料正文最多50000字");
      if (epoch.current === version && editVersion.current === editAt)
        edit("content", content);
    } catch (e) {
      if (epoch.current === version) setError(message(e));
    }
  }
  async function prepare() {
    if (pending.current) return;
    const version = epoch.current;
    const editAt = editVersion.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await api<KnowledgePreview>(
        `/projects/${projectId}/knowledge/preview`,
        { method: "POST", body: form },
      );
      if (epoch.current === version && editVersion.current === editAt)
        setPreview(result);
    } catch (e) {
      if (epoch.current === version) setError(message(e));
    } finally {
      pending.current = false;
      if (epoch.current === version) setBusy(false);
    }
  }
  async function mutate() {
    if (
      pending.current ||
      !state ||
      !confirm ||
      (confirm === "publish" && !preview)
    )
      return;
    const action = confirm;
    const path =
      action === "publish"
        ? `/projects/${projectId}/knowledge/publish`
        : `/knowledge/documents/${retireId}/retire`;
    const body =
      action === "publish"
        ? {
            ...form,
            catalog_token: preview!.catalog_token,
            preview_hash: preview!.preview_hash,
          }
        : { catalog_token: state.catalog_token, reason: reason.trim() };
    const fingerprint = JSON.stringify([path, body]);
    if (mutationKey.current.body !== fingerprint)
      mutationKey.current = { body: fingerprint, key: crypto.randomUUID() };
    const version = epoch.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api<KnowledgeMutation>(path, {
        method: "POST",
        body,
        key: mutationKey.current.key,
      });
      if (epoch.current !== version) return;
      setPreview(null);
      setConfirm(null);
      setRetireId(undefined);
      setReason("");
      if (action === "publish") setForm(empty);
      setSuccess(
        action === "publish"
          ? "资料已发布，现可参与检索"
          : "资料已停用，历史引用仍可回查",
      );
      mutationKey.current = { body: "", key: "" };
      setReload((x) => x + 1);
      onChangedRef.current();
    } catch (e) {
      if (epoch.current === version) {
        setError(message(e));
        setConfirm(null);
      }
    } finally {
      pending.current = false;
      if (epoch.current === version) setBusy(false);
    }
  }
  return (
    <div className="knowledge-search-body">
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            <Button
              disabled={busy}
              onClick={() => {
                setPreview(null);
                setReload((x) => x + 1);
              }}
            >
              刷新目录
            </Button>
          }
        />
      )}
      {success && <Alert type="success" showIcon title={success} />}
      {state?.can_manage ? (
        <>
          <h3>发布新资料</h3>
          <p className="secondary-text">
            先预览，再人工确认发布。更新同名资料时，先停用旧版本，再使用新版本号发布。
          </p>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <label>
              资料名称
              <Input
                aria-label="新资料名称"
                maxLength={200}
                disabled={busy}
                value={form.title}
                onChange={(e) => edit("title", e.target.value)}
              />
            </label>
            <label>
              版本号
              <Input
                aria-label="新资料版本"
                maxLength={30}
                disabled={busy}
                value={form.version}
                onChange={(e) => edit("version", e.target.value)}
                placeholder="例如：1.0"
              />
            </label>
            <label>
              读取 Markdown / 文本文件
              <input
                aria-label="选择知识文件"
                type="file"
                accept=".md,.txt"
                disabled={busy}
                onChange={(e) => {
                  void loadFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
            <label>
              资料正文
              <Input.TextArea
                aria-label="资料正文"
                maxLength={50000}
                rows={8}
                disabled={busy}
                value={form.content}
                onChange={(e) => edit("content", e.target.value)}
              />
            </label>
            <label>
              来源与发布说明
              <Input.TextArea
                aria-label="资料来源与发布说明"
                maxLength={1000}
                rows={2}
                disabled={busy}
                value={form.source_note}
                onChange={(e) => edit("source_note", e.target.value)}
                placeholder="说明资料来源、适用范围和本次变更"
              />
            </label>
            <Space>
            <Button
              aria-label="预览资料"
              loading={busy}
                disabled={!Object.values(form).every((v) => v.trim())}
                onClick={() => void prepare()}
              >
                预览资料
              </Button>
              <Button
                type="primary"
                disabled={!preview || busy}
                onClick={() => setConfirm("publish")}
              >
                确认发布
              </Button>
            </Space>
            {preview && (
              <div>
                <Tag>{preview.chunk_count} 个检索片段</Tag>
                <span>{preview.effective_from} 生效</span>
                {preview.excerpts.map((excerpt, i) => (
                  <pre
                    key={i}
                    style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                  >
                    {excerpt}
                  </pre>
                ))}
                <small>展示前3个片段，正文以表单中的完整内容为准。</small>
              </div>
            )}
          </Space>
          <h3>停用资料</h3>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Select
              aria-label="待停用资料"
              style={{ width: "100%" }}
              disabled={busy}
              value={retireId}
              placeholder="选择当前有效资料"
              onChange={setRetireId}
              options={state.items
                .filter((d) => d.currently_valid)
                .map((d) => ({
                  value: d.document_id,
                  label: `${d.title} · v${d.version}`,
                }))}
            />
            <Input.TextArea
              aria-label="停用原因"
              maxLength={1000}
              disabled={busy}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="填写停用原因"
            />
            <Button
              danger
              disabled={busy || !retireId || !reason.trim()}
              onClick={() => setConfirm("retire")}
            >
              确认停用
            </Button>
          </Space>
        </>
      ) : state ? (
        <Alert
          type="info"
          title="当前账号可查看资料，维护操作由项目所有者完成"
        />
      ) : (
        <p>正在读取维护权限…</p>
      )}
      <h3>最近变更</h3>
      <DataTable<KnowledgeChangeView>
        rowKey="id"
        loading={!state && !error}
        dataSource={state?.history || []}
        columns={[
          { title: "资料", dataIndex: "title" },
          { title: "版本", dataIndex: "version", width: 80 },
          {
            title: "操作",
            dataIndex: "action",
            width: 80,
            render: (a) => (a === "publish" ? "发布" : "停用"),
          },
          { title: "说明", dataIndex: "reason" },
          {
            title: "时间",
            dataIndex: "created_at",
            render: (t) => new Date(t).toLocaleString(),
          },
        ]}
        scroll={{ x: 700 }}
        emptyDescription="暂无维护记录"
        totalLabel={(n) => `最近 ${n} 条记录（最多100条）`}
      />
      <Modal
        open={!!confirm}
        title={confirm === "publish" ? "发布这份资料？" : "停用这份资料？"}
        onCancel={() => !busy && setConfirm(null)}
        onOk={() => void mutate()}
        confirmLoading={busy}
        cancelButtonProps={{ disabled: busy }}
        okText="确认"
        cancelText="返回核对"
      >
        <p>
          {confirm === "publish"
            ? `${form.title} · v${form.version} 将参与本项目后续检索，请确认正文与来源。`
            : "停用后不再用于新核查；已保存的原文和历史引用保留。"}
        </p>
      </Modal>
    </div>
  );
}
