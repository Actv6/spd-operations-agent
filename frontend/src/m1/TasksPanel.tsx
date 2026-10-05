import { useState, useRef, useEffect } from "react";
import { Alert, Button, Drawer, Input, Space, Tabs, Tag, Timeline } from "antd";
import { api } from "./api";
import { message, date } from "./ui";
import { DataTable } from "./components/DataTable";
import { useResource } from "./useResource";
import type { TaskView } from "./types";
import "./m2.css";

const taskLabels = {
  todo: "待处理",
  in_progress: "处理中",
  completed: "已完成",
  cancelled: "已取消",
};
export function TasksPanel({
  projectId,
  onSource,
}: {
  projectId: string;
  onSource: (runId: string) => void;
}) {
  const { data, error, loading, reload } = useResource<TaskView[]>(
    `/projects/${projectId}/tasks`,
  );
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<TaskView | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const detailVersion = useRef(0);
  const saving = useRef(false);
  useEffect(
    () => () => {
      detailVersion.current++;
    },
    [],
  );
  async function openTask(task: TaskView, preserveNote = false) {
    if (saving.current) return;
    const version = ++detailVersion.current;
    setSelected(task);
    if (!preserveNote) setNote("");
    setFailure("");
    setDetailLoading(true);
    try {
      const result = await api<TaskView>(`/tasks/${task.id}`);
      if (version === detailVersion.current) setSelected(result);
    } catch (e) {
      if (version === detailVersion.current) setFailure(message(e));
    } finally {
      if (version === detailVersion.current) setDetailLoading(false);
    }
  }
  async function transition(status: TaskView["status"]) {
    if (!selected || saving.current || detailLoading || failure) return;
    saving.current = true;
    setBusy(true);
    setFailure("");
    try {
      setSelected(
        await api<TaskView>(`/tasks/${selected.id}`, {
          method: "PATCH",
          body: { status, result: note, revision: selected.revision },
        }),
      );
      setNote("");
      reload();
    } catch (e) {
      setFailure(message(e));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <DataTable<TaskView>
        dataSource={(data || []).filter(
          (t) => filter === "all" || t.status === filter,
        )}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey="id"
        scroll={{ x: 720 }}
        tabs={
          <Tabs
            activeKey={filter}
            onChange={setFilter}
            items={[
              { key: "all", label: "全部本人任务" },
              ...Object.entries(taskLabels).map(([key, label]) => ({
                key,
                label,
              })),
            ]}
          />
        }
        columns={[
          {
            title: "任务",
            dataIndex: "title",
            render: (_, t) => (
              <Button
                type="link"
                className="m2-title-button"
                onClick={() => void openTask(t)}
              >
                {t.title}
              </Button>
            ),
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 120,
            render: (v: TaskView["status"]) => (
              <Tag
                color={
                  v === "completed"
                    ? "green"
                    : v === "in_progress"
                      ? "blue"
                      : "default"
                }
              >
                {taskLabels[v]}
              </Tag>
            ),
          },
          {
            title: "截止日期",
            dataIndex: "due_date",
            width: 150,
            sorter: (a, b) => a.due_date.localeCompare(b.due_date),
          },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 150,
            render: date,
          },
          {
            title: "操作",
            key: "actions",
            width: 100,
            render: (_, t) => (
              <Button onClick={() => void openTask(t)}>查看</Button>
            ),
          },
        ]}
        emptyDescription="暂无本人任务；在核查结果中生成并确认待办草稿"
      />
      <Drawer
        closable={!busy}
        mask={{ closable: !busy }}
        keyboard={!busy}
        title="本人待办"
        open={!!selected}
        onClose={() => {
          if (!busy) {
            detailVersion.current++;
            setSelected(null);
          }
        }}
        size={620}
      >
        {selected && (
          <div className="m2-stack">
            <h2>{selected.title}</h2>
            <Space>
              <Tag>{taskLabels[selected.status]}</Tag>
              <span>截止 {selected.due_date}</span>
            </Space>
            <ol>
              {selected.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
            <Alert
              type="info"
              title="任务完成代表本次核查工作已处理，异常是否解除仍需最新数据验证。"
            />
            {!!selected.review_blockers?.length && (
              <Alert
                type="warning"
                title="关联核查需要再次复核，原任务保留"
                description={selected.review_blockers
                  .map((b) => b.message)
                  .join("；")}
              />
            )}
            <Button onClick={() => onSource(selected.run_id)}>
              查看原核查与依据
            </Button>
            {selected.result && <p>最近处理结果：{selected.result}</p>}
            <label htmlFor="task-result">处理结果 / 变更说明</label>
            <Input.TextArea
              id="task-result"
              disabled={busy || detailLoading}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={3000}
              autoSize={{ minRows: 3 }}
              placeholder="记录核对结果、仍缺少的信息或重开原因"
            />
            {failure && (
              <Alert
                type="error"
                title={failure}
                action={
                  <Button onClick={() => void openTask(selected, true)}>
                    刷新任务
                  </Button>
                }
              />
            )}
            <Space wrap>
              {selected.status === "todo" && (
                <Button
                  type="primary"
                  disabled={detailLoading || !!failure}
                  loading={busy}
                  onClick={() => void transition("in_progress")}
                >
                  开始处理
                </Button>
              )}
              {selected.status === "in_progress" && (
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!note.trim() || detailLoading || !!failure}
                  onClick={() => void transition("completed")}
                >
                  填写结果并完成
                </Button>
              )}
              {["todo", "in_progress"].includes(selected.status) ? (
                <Button
                  disabled={busy || detailLoading || !!failure}
                  onClick={() => void transition("cancelled")}
                >
                  取消任务
                </Button>
              ) : (
                <Button
                  disabled={detailLoading || !!failure}
                  loading={busy}
                  onClick={() => void transition("todo")}
                >
                  重新打开
                </Button>
              )}
            </Space>
            <h3>处理记录</h3>
            <Timeline
              items={selected.history.map((h, i) => ({
                key: i,
                content: (
                  <>
                    <strong>
                      {taskLabels[h.status as TaskView["status"]]}
                    </strong>
                    <p>{h.result || "状态已更新"}</p>
                    <small>{date(h.at)}</small>
                  </>
                ),
              }))}
            />
          </div>
        )}
      </Drawer>
    </>
  );
}
