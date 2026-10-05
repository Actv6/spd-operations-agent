import { useState, useRef, useEffect } from "react";
import { Alert, Button, DatePicker, Form, Input, Space } from "antd";
import { api } from "./api";
import { message } from "./ui";
import { useResource } from "./useResource";
import type { RunView, DraftView, DraftConfirm, TaskView } from "./types";
import "./m2.css";

export function RunActions({
  run,
  enabled,
  onChild,
  onRun,
  onTasks,
}: {
  run: RunView;
  enabled: boolean;
  onChild: (
    mode: "follow_up" | "draft_action",
    question: string,
  ) => Promise<void>;
  onRun: (run: RunView) => void;
  onTasks: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { data: history } = useResource<RunView[]>(
    `/runs/${run.run_id}/conversation`,
  );
  const lock = useRef(false);
  async function submit(mode: "follow_up" | "draft_action") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await onChild(
        mode,
        mode === "draft_action"
          ? "请根据本次核查结果，重新核实依据并生成一份本人内部待办草稿。列出需要核实的步骤，不执行采购、库存变更或报废。"
          : question.trim(),
      );
      setQuestion("");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  return (
    <section className="m2-stack m2-run-actions">
      {(history?.length || 0) > 1 && (
        <>
          <h3>本次会话</h3>
          <div className="m2-conversation">
            {history?.map((r, i) => (
              <Button
                key={r.run_id}
                type={r.run_id === run.run_id ? "primary" : "default"}
                onClick={() => onRun(r)}
              >
                {i + 1}. {r.question.slice(0, 32)}
              </Button>
            ))}
          </div>
        </>
      )}
      {run.draft_id && (
        <DraftReview
          key={run.draft_id}
          draftId={run.draft_id}
          onTasks={onTasks}
        />
      )}
      {run.status === "succeeded" && (
        <>
          <h3>继续核查与处理</h3>
          <p className="secondary-text">
            追问沿用本次物资、科室与快照。查看最新数据请新建核查。
          </p>
          <Input.TextArea
            aria-label="继续追问"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="例如：哪些批次被冻结？缺失的是哪两天？"
            maxLength={2000}
            autoSize={{ minRows: 2, maxRows: 6 }}
          />
          {error && <Alert type="error" title={error} />}
          <Space wrap>
            <Button
              type="primary"
              disabled={!enabled || !question.trim()}
              loading={busy}
              onClick={() => void submit("follow_up")}
            >
              发送追问
            </Button>
            <Button
              disabled={!enabled}
              loading={busy}
              onClick={() => void submit("draft_action")}
            >
              生成待办草稿
            </Button>
          </Space>
        </>
      )}
    </section>
  );
}

function DraftReview({
  draftId,
  onTasks,
}: {
  draftId: string;
  onTasks: () => void;
}) {
  const {
    data: draft,
    error,
    loading,
    reload,
  } = useResource<DraftView>(`/drafts/${draftId}`);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [form] = Form.useForm();
  const lock = useRef(false);
  useEffect(() => {
    if (draft) {
      form.setFieldsValue({
        title: draft.title,
        steps: draft.steps.join("\n"),
        due_date: undefined,
      });
    }
  }, [draft, form]);
  async function confirm(values: {
    title: string;
    steps: string;
    due_date: { format: (pattern: string) => string };
  }) {
    if (!draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    setFailure("");
    const body: DraftConfirm = {
      revision: draft.revision,
      title: values.title,
      steps: values.steps
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      due_date: values.due_date.format("YYYY-MM-DD"),
    };
    try {
      await api<TaskView>(`/drafts/${draft.id}/confirm`, {
        method: "POST",
        body,
      });
      reload();
    } catch (e) {
      setFailure(message(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function reject() {
    if (!draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      await api(`/drafts/${draft.id}/reject`, {
        method: "POST",
        body: { revision: draft.revision },
      });
      reload();
    } catch (e) {
      setFailure(message(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="m2-draft">
      <h3>待办草稿 · 人工确认</h3>
      {!!draft?.review_blockers?.length && (
        <Alert
          type="warning"
          title="相关核查需要人工复核"
          description={draft.review_blockers.map((b) => b.message).join("；")}
          action={<Button onClick={reload}>刷新复核状态</Button>}
        />
      )}
      {error && (
        <Alert
          type="error"
          title={error}
          action={<Button onClick={reload}>重试</Button>}
        />
      )}
      {loading ? (
        <p>正在读取草稿…</p>
      ) : (
        draft &&
        (draft.status === "pending" ? (
          <Form form={form} layout="vertical" onFinish={confirm}>
            <Alert
              className="page-alert"
              type={draft.stale_reason ? "warning" : "info"}
              title={
                draft.stale_reason ||
                draft.review_blockers?.map((b) => b.message).join("；") ||
                "请核对并编辑内容，确认后仅创建你的内部待办。"
              }
            />
            <Form.Item
              name="title"
              label="任务标题"
              rules={[{ required: true, whitespace: true }, { max: 160 }]}
            >
              <Input maxLength={160} />
            </Form.Item>
            <Form.Item
              name="steps"
              label="处理步骤（每行一条，最多8条）"
              rules={[
                { required: true, whitespace: true },
                {
                  validator: (_, value) => {
                    const lines = String(value || "")
                      .split("\n")
                      .filter((s) => s.trim());
                    return lines.length > 0 &&
                      lines.length <= 8 &&
                      lines.every((s) => s.length <= 500)
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error("请输入1至8条步骤，每条最多500字"),
                        );
                  },
                },
              ]}
            >
              <Input.TextArea autoSize={{ minRows: 3 }} />
            </Form.Item>
            <Form.Item
              name="due_date"
              label="截止日期"
              rules={[{ required: true, message: "请选择截止日期" }]}
            >
              <DatePicker
                format="YYYY-MM-DD"
                placeholder="选择截止日期"
                style={{ width: "100%" }}
              />
            </Form.Item>
            {failure && (
              <Alert
                className="page-alert"
                type="error"
                title={failure}
                action={<Button onClick={reload}>刷新草稿</Button>}
              />
            )}
            <Space wrap>
              <Button
                htmlType="submit"
                type="primary"
                loading={busy}
                disabled={
                  !!draft.stale_reason || !!draft.review_blockers?.length
                }
              >
                确认并创建本人待办
              </Button>
              <Button disabled={busy} onClick={() => void reject()}>
                放弃草稿
              </Button>
            </Space>
          </Form>
        ) : (
          <Alert
            type={draft.status === "confirmed" ? "success" : "info"}
            title={
              draft.status === "confirmed" ? "已创建本人待办" : "草稿已放弃"
            }
            action={
              draft.task_id && <Button onClick={onTasks}>前往本人任务</Button>
            }
          />
        ))
      )}
    </div>
  );
}
