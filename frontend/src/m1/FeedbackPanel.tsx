import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Radio, Space, Tag } from "antd";
import { api } from "./api";
import { message } from "./ui";
import type { FeedbackList, FeedbackView, FeedbackWrite } from "./types";

export function FeedbackPanel({
  analysisId,
  onSaved,
}: {
  analysisId: string;
  onSaved?: () => void;
}) {
  const [data, setData] = useState<FeedbackList | null>(null);
  const [rating, setRating] = useState<FeedbackWrite["rating"]>("helpful");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const epoch = useRef(0);
  const pending = useRef(false);
  const requestKey = useRef({ body: "", key: "" });
  useEffect(() => {
    const version = ++epoch.current;
    const controller = new AbortController();
    setData(null);
    setError("");
    setSaved(false);
    api<FeedbackList>(`/analyses/${analysisId}/feedback`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (epoch.current === version) setData(r);
      })
      .catch((e) => {
        if (!controller.signal.aborted && epoch.current === version)
          setError(message(e));
      });
    return () => {
      epoch.current++;
      controller.abort();
    };
  }, [analysisId, reload]);
  async function submit() {
    if (pending.current || !data?.can_submit) return;
    const body = { rating, comment: comment.trim() };
    if (rating === "needs_correction" && !body.comment) return;
    const serialized = JSON.stringify(body);
    if (requestKey.current.body !== serialized)
      requestKey.current = { body: serialized, key: crypto.randomUUID() };
    const version = epoch.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const result = await api<FeedbackView>(
        `/analyses/${analysisId}/feedback`,
        { method: "POST", body, key: requestKey.current.key },
      );
      if (epoch.current !== version) return;
      setData(
        (previous) =>
          previous && {
            ...previous,
            items: [
              result,
              ...previous.items.filter((r) => r.id !== result.id),
            ],
          },
      );
      setSaved(true);
      onSaved?.();
      setComment("");
      requestKey.current = { body: "", key: "" };
    } catch (e) {
      if (epoch.current === version) setError(message(e));
    } finally {
      pending.current = false;
      if (epoch.current === version) setBusy(false);
    }
  }
  return (
    <section className="result-section" aria-label="核查反馈">
      <h3>这次核查是否有帮助？</h3>
      {error && (
        <Alert
          type="error"
          title={error}
          action={
            !data && (
              <Button onClick={() => setReload((x) => x + 1)}>重试读取</Button>
            )
          }
        />
      )}
      {saved && (
        <Alert type="success" title="反馈已保存；纠错反馈需要人工复核处理" />
      )}
      {data?.can_submit && (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Radio.Group
            value={rating}
            disabled={busy}
            onChange={(e) => {
              setRating(e.target.value);
              setSaved(false);
            }}
            options={[
              { label: "有帮助", value: "helpful" },
              { label: "需要修正", value: "needs_correction" },
            ]}
          />
          <Input.TextArea
            aria-label="反馈说明"
            value={comment}
            maxLength={1000}
            showCount
            rows={3}
            disabled={busy}
            placeholder={
              rating === "needs_correction"
                ? "请指出需要核实的数字、依据或建议"
                : "可填写节省了哪些工作，或还需要什么信息"
            }
            onChange={(e) => {
              setComment(e.target.value);
              setSaved(false);
            }}
          />
          <Button
            loading={busy}
            disabled={rating === "needs_correction" && !comment.trim()}
            onClick={() => void submit()}
          >
            提交反馈
          </Button>
        </Space>
      )}
      {data && !data.can_submit && (
        <p className="secondary-text">仅发起人可提交本次核查反馈。</p>
      )}
      {!!data?.items.length && (
        <details className="source-metadata">
          <summary>我的反馈记录 · {data.items.length} 条</summary>
          {data.items.map((r) => (
            <p key={r.id}>
              <Tag>{r.rating === "helpful" ? "有帮助" : "需要修正"}</Tag>
              {r.comment || "未填写说明"}{" "}
              <small>{new Date(r.created_at).toLocaleString()}</small>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
