import { useState, useRef } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Form,
  Input,
  Select,
  Space,
  Tag,
} from "antd";
import { api } from "./api";
import { message } from "./ui";
import { useResource } from "./useResource";
import { ItemDetailsPanel } from "./ItemDetailsPanel";
import type { HumanReviewView, HumanReviewWrite, InventoryItem } from "./types";

export const reviewLabels = {
  pending: "待人工复核",
  confirmed: "人工确认",
  error: "发现错误 / 有争议",
  insufficient: "资料不足",
};

export function ReviewStatusTag({
  status,
}: {
  status: keyof typeof reviewLabels;
}) {
  return (
    <Tag
      color={
        status === "confirmed"
          ? "success"
          : status === "error"
            ? "error"
            : "warning"
      }
    >
      {reviewLabels[status]}
    </Tag>
  );
}

export function HumanReviewPanel({
  runId,
  onEvidence,
  onSaved,
  onRecheck,
}: {
  runId: string;
  onEvidence: (id: string) => void;
  onSaved: () => void;
  onRecheck: () => void;
}) {
  const { data, error, loading, reload } = useResource<HumanReviewView>(
    `/runs/${runId}/human-review`,
  );
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [selected, setSelected] = useState<InventoryItem | null>(null);
  const lock = useRef(false);
  const retry = useRef({ body: "", key: "" });
  const status = Form.useWatch("status", form);
  async function submit(
    values: Pick<
      HumanReviewWrite,
      | "status"
      | "conclusion"
      | "basis"
      | "next_step"
      | "evidence_ids"
      | "handled_feedback_ids"
    >,
  ) {
    if (!data?.can_submit || lock.current) return;
    const body: HumanReviewWrite = {
      ...values,
      revision: data.revision,
      source_token: data.source_token,
      conclusion: values.conclusion.trim(),
      basis: values.basis.trim(),
      next_step: values.next_step?.trim() || "",
      evidence_ids: values.evidence_ids || [],
      handled_feedback_ids: values.handled_feedback_ids || [],
    };
    const serialized = JSON.stringify(body);
    if (retry.current.body !== serialized)
      retry.current = { body: serialized, key: crypto.randomUUID() };
    lock.current = true;
    setBusy(true);
    setFailure("");
    try {
      await api<HumanReviewView>(`/runs/${runId}/human-review`, {
        method: "POST",
        body,
        key: retry.current.key,
      });
      onSaved();
    } catch (e) {
      setFailure(message(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="result-section human-review" aria-label="人工复核">
      <h3>人工复核</h3>
      {error && (
        <Alert
          type="error"
          title={error}
          action={<Button onClick={reload}>重试读取复核</Button>}
        />
      )}
      {loading && <p>正在读取人工复核记录…</p>}
      {data && (
        <>
          <Space wrap>
            <ReviewStatusTag status={data.status} />
            <span>{data.required ? "需要人工复核" : "可人工抽查"}</span>
          </Space>
          <p className="secondary-text">
            AI运行成功与人工确认分别记录。本人核查会标记为本人自查；人工确认也不代表库存异常已解除。
          </p>
          {data.reasons.length > 0 && <p>{data.reasons.join("；")}</p>}
          {data.stale_reasons.length > 0 && (
            <Alert type="warning" title={data.stale_reasons.join("；")} />
          )}
          {data.manual_only && (
            <Alert
              type="info"
              title="记录人工核查结论"
              description="本次AI未完成。可查看绑定快照和已保存依据，记录人工核查结果；原运行状态保留。"
            />
          )}
          <Collapse
            items={[
              {
                key: "manual-sources",
                label: "人工核对库存、批次与消耗",
                children: (
                  <>
                    <p className="secondary-text">
                      以下记录属于本次绑定快照。请核对业务时间、缺失记录与实际情况。
                    </p>
                    {data.inventory.map((row) => (
                      <p key={`${row.item_id}/${row.department_id}`}>
                        <Button type="link" onClick={() => setSelected(row)}>
                          {row.name} · {row.department_name} · 查看批次与消耗
                        </Button>
                      </p>
                    ))}
                    {!data.inventory.length && (
                      <p>本次范围内没有库存记录，请补查原始资料。</p>
                    )}
                    {data.available_evidence.map((e) => (
                      <p key={e.evidence_id}>
                        <Button onClick={() => onEvidence(e.evidence_id)}>
                          {e.title}
                        </Button>
                      </p>
                    ))}
                  </>
                ),
              },
            ]}
          />
          {data.can_submit ? (
            <Form
              form={form}
              layout="vertical"
              onFinish={submit}
              disabled={busy}
              initialValues={{
                status: "pending",
                conclusion: "",
                basis: "",
                next_step: "",
                evidence_ids: [],
                handled_feedback_ids: [],
              }}
            >
              <Form.Item
                name="status"
                label="复核结论状态"
                rules={[{ required: true }]}
              >
                <Select
                  aria-label="复核结论状态"
                  options={Object.entries(reviewLabels).map(
                    ([value, label]) => ({
                      value,
                      label,
                      disabled:
                        value === "confirmed" && data.stale_reasons.length > 0,
                    }),
                  )}
                />
              </Form.Item>
              <Form.Item
                name="conclusion"
                label="人工结论"
                rules={[
                  {
                    required: true,
                    whitespace: true,
                    message: "请填写人工核查结论",
                  },
                  { max: 2000 },
                ]}
              >
                <Input.TextArea
                  aria-label="人工结论"
                  rows={3}
                  maxLength={2000}
                  placeholder="写明核对了哪些结论，哪里正确或需要修正。"
                />
              </Form.Item>
              <Form.Item
                name="basis"
                label="核查依据与核对过程"
                rules={[
                  {
                    required: true,
                    whitespace: true,
                    message: "请填写核查依据",
                  },
                  { max: 2000 },
                ]}
              >
                <Input.TextArea
                  aria-label="人工核查依据"
                  rows={3}
                  maxLength={2000}
                  placeholder="例如原始台账、制度版本、核对的业务时点和实际核实情况。外部依据由复核人负责核实。"
                />
              </Form.Item>
              <Form.Item name="evidence_ids" label="关联本次已保存依据">
                <Select
                  mode="multiple"
                  aria-label="关联复核依据"
                  options={data.available_evidence.map((e) => ({
                    value: e.evidence_id,
                    label: e.title,
                  }))}
                />
              </Form.Item>
              <Form.Item
                name="next_step"
                label="下一步处理"
                rules={[
                  {
                    required: status === "error" || status === "insufficient",
                    whitespace: true,
                    message: "错误或资料不足时请填写下一步",
                  },
                  { max: 1000 },
                ]}
              >
                <Input.TextArea
                  aria-label="复核下一步"
                  rows={2}
                  maxLength={1000}
                  placeholder="说明谁需要核实什么，或修正资料后重新核查。"
                />
              </Form.Item>
              {data.pending_feedback.length > 0 && (
                <Form.Item
                  name="handled_feedback_ids"
                  label="逐条处理纠错反馈"
                  rules={[
                    {
                      validator: (_, ids: string[]) =>
                        data.pending_feedback.every((f) => ids?.includes(f.id))
                          ? Promise.resolve()
                          : Promise.reject(
                              new Error("请在结论中回应并勾选全部纠错反馈"),
                            ),
                    },
                  ]}
                >
                  <Checkbox.Group>
                    {data.pending_feedback.map((f) => (
                      <p key={f.id}>
                        <Checkbox value={f.id}>
                          {f.comment} ·{" "}
                          {new Date(f.created_at).toLocaleString()}
                        </Checkbox>
                      </p>
                    ))}
                  </Checkbox.Group>
                </Form.Item>
              )}
              {failure && (
                <Alert
                  type="error"
                  title={failure}
                  action={
                    <Button
                      disabled={busy}
                      onClick={() => {
                        reload();
                        setFailure("");
                      }}
                    >
                      刷新复核依据
                    </Button>
                  }
                />
              )}
              <Button type="primary" htmlType="submit" loading={busy}>
                保存人工复核
              </Button>
            </Form>
          ) : (
            <p className="secondary-text">
              仅有项目复核权限的账号可记录人工结论；运行结束后可提交。
            </p>
          )}
          <p className="secondary-text">
            数据或制度有误时，请在数据管理或资料库修正并发布新版本，再基于当前数据重新核查。
          </p>
          <Button onClick={onRecheck}>查看当前库存并重新核查</Button>
          <Collapse
            items={[
              {
                key: "records",
                label: `人工复核历史 · ${data.items.length} 条`,
                children: data.items.length ? (
                  data.items.map((r) => (
                    <article key={r.id} className="review-record">
                      <Space wrap>
                        <ReviewStatusTag status={r.status} />
                        <strong>{r.actor_name}</strong>
                        <Tag>{r.self_review ? "本人自查" : "其他账号复核"}</Tag>
                      </Space>
                      <p>
                        {new Date(r.created_at).toLocaleString()} · 第
                        {r.revision}次记录
                      </p>
                      <p>结论：{r.conclusion}</p>
                      <p>依据：{r.basis}</p>
                      {r.next_step && <p>下一步：{r.next_step}</p>}
                      {r.evidence_ids.map((id) => (
                        <Button key={id} onClick={() => onEvidence(id)}>
                          查看复核关联依据
                        </Button>
                      ))}
                      {r.handled_feedback_ids.length > 0 && (
                        <p>
                          已记录处理 {r.handled_feedback_ids.length} 条纠错反馈
                        </p>
                      )}
                      <p className="source-metadata">
                        绑定快照 {r.snapshot_set_id} ·{" "}
                        {r.analysis_hash
                          ? `原分析校验 ${r.analysis_hash}`
                          : "本次无AI分析，人工独立记录"}
                      </p>
                    </article>
                  ))
                ) : (
                  <p>尚无人工复核记录。</p>
                ),
              },
            ]}
          />
          {selected && (
            <ItemDetailsPanel
              projectId={data.project_id}
              row={selected}
              snapshotId={data.snapshot_set_id}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}
    </section>
  );
}
