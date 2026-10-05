import { ReviewStatusTag } from "./HumanReviewPanel";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App as AntApp,
  Avatar,
  Button,
  ConfigProvider,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Skeleton,
  Tabs,
  Tooltip,
} from "antd";
import type { TableColumnsType } from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  IconActivity,
  IconArrowRight,
  IconBook2,
  IconDatabase,
  IconLayoutDashboard,
  IconUpload,
  IconPackage,
  IconBuildingHospital,
  IconLogout,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconShieldCheck,
  IconSparkles,
} from "@tabler/icons-react";
import { api, ApiError } from "./api";
import type {
  AnalysisView,
  DashboardView,
  EventsView,
  EvidenceView,
  InventoryItem,
  MeView,
  RunRequest,
  RunView,
  RiskFinding,
  RiskReport,
} from "./types";
import { date, message, number, route, RunStatus, terminal } from "./ui";
import { readSnapshotBundle } from "./snapshot";
import { DataTable } from "./components/DataTable";
import { PageHeader } from "./components/PageHeader";
import "./workbench.css";
import {
  InventoryPanel,
  KnowledgePanel,
  EvidencePanel,
  ResultPanel,
  ImportsPanel,
  CatalogPanel,
  VersionsPanel,
  RiskPanel,
  ItemDetailsPanel,
  TasksPanel,
  RunActions,
} from "./lazyPanels";

import { Brand } from "./Brand";

const TOUR_STEPS = [
  {
    target: "risk-nav",
    title: "第一步：先看异常",
    body: "这里汇总系统发现的关注项。点进去查看原因，再决定要核实什么。",
  },
  {
    target: "inventory-nav",
    title: "第二步：核对库存",
    body: "在库存数据里看数量、批次、消耗记录和数据时间。缺失的数据要先确认，不能当成 0。",
  },
  {
    target: "new-run",
    title: "第三步：提出问题",
    body: "点这里发起核查。用日常语言写问题即可，也可以先选定某一种物资。",
  },
  {
    target: "knowledge-nav",
    title: "第四步：查看资料依据",
    body: "这里可以搜索项目资料并打开原文。查看回答时，记得对照引用和库存数字。",
  },
  {
    target: "tasks-nav",
    title: "最后：跟进自己的任务",
    body: "需要记录后续动作时，可以确认创建本人任务。完成任务不会自动修改库存或消除异常。",
  },
];

export function Workspace({
  me,
  path,
  onLogout,
}: {
  me: MeView;
  path: string;
  onLogout: () => void;
}) {
  const project = me.projects[0];
  const [dashboard, setDashboard] = useState<DashboardView | null>(null);
  const [riskReport, setRiskReport] = useState<RiskReport | null>(null);
  const [formSnapshot, setFormSnapshot] = useState<DashboardView | null>(null);
  const [focus, setFocus] = useState<"general" | "risk_scan">("general");
  const [runs, setRuns] = useState<RunView[]>([]);
  const [current, setCurrent] = useState<RunView | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisView | null>(null);
  const [events, setEvents] = useState<EventsView["items"]>([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [resultLoading, setResultLoading] = useState(false);
  const [resultError, setResultError] = useState("");
  const [question, setQuestion] = useState("");
  const [item, setItem] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [evidence, setEvidence] = useState<EvidenceView | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [runFilter, setRunFilter] = useState("all");
  const [runSearch, setRunSearch] = useState("");
  const [reviewFilter, setReviewFilter] = useState("all");
  const [detailRow, setDetailRow] = useState<{
    row: InventoryItem;
    snapshotId: string;
  } | null>(null);
  const [panelRefresh, setPanelRefresh] = useState(0);
  const [department, setDepartment] = useState("");
  const [inventoryQuality, setInventoryQuality] = useState("all");
  const guideStorageKey = `spd-first-use-tour-v2:${me.user.id}:${project?.id || "no-project"}`;
  const [tourOpen, setTourOpen] = useState(() => {
    try {
      return localStorage.getItem(guideStorageKey) !== "dismissed";
    } catch {
      return true;
    }
  });
  const [tourStep, setTourStep] = useState(0);
  const [tourRect, setTourRect] = useState<DOMRect | null>(null);
  const selection = useRef(0);
  const evidenceSelection = useRef(0);
  const evidenceId = useRef("");
  const submission = useRef<{ body: string; key: string } | null>(null);
  const sending = useRef(false);
  const refreshVersion = useRef(0);
  const page =
    path === "/app/versions"
      ? "versions"
      : path === "/app/products"
        ? "products"
        : path === "/app/departments"
          ? "departments"
          : path === "/app/imports"
            ? "imports"
            : path === "/app/data"
              ? "data"
              : path === "/app/risks"
                ? "risks"
                : path === "/app/tasks"
                  ? "tasks"
                  : path === "/app/knowledge"
                    ? "knowledge"
                    : "overview";
  useEffect(() => {
    if (!tourOpen) return;
    let frame = 0;
    const update = () => {
      const target = document.querySelector<HTMLElement>(
        `[data-tour="${TOUR_STEPS[tourStep].target}"]`,
      );
      if (!target) {
        frame = requestAnimationFrame(update);
        return;
      }
      target.scrollIntoView({ block: "nearest", inline: "nearest" });
      setTourRect(target.getBoundingClientRect());
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [tourOpen, tourStep]);
  const refresh = useCallback(async () => {
    if (!project) return;
    const version = ++refreshVersion.current;
    setRefreshing(true);
    try {
      const bundle = await readSnapshotBundle(project.id);
      if (version !== refreshVersion.current) return;
      setDashboard(bundle.dashboard);
      setRiskReport(bundle.risks);
      setRuns(bundle.runs);
      setError("");
    } catch (e) {
      if (version === refreshVersion.current) setError(message(e));
    } finally {
      if (version === refreshVersion.current) setRefreshing(false);
    }
  }, [project?.id]);
  useEffect(() => {
    void refresh();
    return () => {
      selection.current++;
      evidenceSelection.current++;
      refreshVersion.current++;
    };
  }, [refresh]);
  const activeRuns = runs.some((r) => !terminal(r.status));
  useEffect(() => {
    if (!activeRuns) return;
    const timer = setInterval(() => void refresh(), 8000);
    return () => clearInterval(timer);
  }, [activeRuns, refresh]);
  async function selectRun(run: RunView) {
    const version = ++selection.current;
    setCurrent(run);
    setAnalysis(null);
    setEvents([]);
    setResultOpen(true);
    setResultLoading(true);
    setResultError("");
    try {
      const [fresh, log] = await Promise.all([
        api<RunView>(`/runs/${run.run_id}`),
        api<EventsView>(`/runs/${run.run_id}/events?limit=200`),
      ]);
      if (version !== selection.current) return;
      setCurrent(fresh);
      setEvents(log.items);
      if (fresh.analysis_id) {
        const result = await api<AnalysisView>(
          `/analyses/${fresh.analysis_id}`,
        );
        if (version === selection.current) setAnalysis(result);
      }
    } catch (e) {
      if (version === selection.current) setResultError(message(e));
    } finally {
      if (version === selection.current) setResultLoading(false);
    }
  }
  useEffect(() => {
    if (!current || terminal(current.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = events.at(-1)?.cursor || "0";
    let retries = 0;
    const runId = current.run_id;
    const version = selection.current;
    async function poll() {
      try {
        const [run, log] = await Promise.all([
          api<RunView>(`/runs/${runId}`),
          api<EventsView>(`/runs/${runId}/events?after=${cursor}&limit=200`),
        ]);
        const result = run.analysis_id
          ? await api<AnalysisView>(`/analyses/${run.analysis_id}`)
          : null;
        if (stopped || version !== selection.current) return;
        retries = 0;
        cursor = log.next_cursor;
        setResultError("");
        setEvents((old) => [
          ...old,
          ...log.items.filter((e) => !old.some((o) => o.cursor === e.cursor)),
        ]);
        if (result) setAnalysis(result);
        setCurrent(run);
        setRuns((old) => old.map((r) => (r.run_id === run.run_id ? run : r)));
        if (terminal(run.status)) {
          void refresh();
          return;
        }
      } catch (e) {
        if (stopped) return;
        setResultError(message(e));
        retries++;
      }
      if (!stopped)
        timer = setTimeout(
          poll,
          Math.min(1000 * 2 ** retries, 15000) * (document.hidden ? 3 : 1),
        );
    }
    timer = setTimeout(poll, 600);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [current?.run_id, current?.status, refresh]);
  function begin(
    row?: InventoryItem,
    preset?: string,
    nextFocus: "general" | "risk_scan" = "general",
  ) {
    if (!dashboard) return;
    setFormSnapshot(dashboard);
    setFocus(nextFocus);
    setItem(row?.item_id || "");
    setDepartment(row?.department_id || "");
    setQuestion(
      preset ||
        (row
          ? `请核查${row.name}的库存、消耗和数据质量，并检索相关制度说明下一步需要核实什么。`
          : ""),
    );
    setSubmitError("");
    setFormOpen(true);
  }
  async function submit() {
    if (
      sending.current ||
      !question.trim() ||
      !project ||
      !formSnapshot ||
      !dashboard ||
      !dashboard.provider_configured ||
      dashboard.generation_mode !== "model"
    )
      return;
    sending.current = true;
    setBusy(true);
    setSubmitError("");
    const body: RunRequest = {
      schema_version: "1",
      mode: "analyze",
      question: question.trim(),
      session_id: null,
      parent_run_id: null,
      context: {
        snapshot_set_id: formSnapshot.snapshot_set_id,
        item_ids: item ? [item] : [],
        department_ids: department ? [department] : [],
        analysis_id: null,
      },
      options: { window_days: 14, focus },
    };
    const serialized = JSON.stringify(body);
    if (submission.current?.body !== serialized)
      submission.current = { body: serialized, key: crypto.randomUUID() };
    try {
      const run = await api<RunView>(`/projects/${project.id}/runs`, {
        method: "POST",
        body,
        key: submission.current!.key,
      });
      submission.current = null;
      setRuns((old) => [run, ...old.filter((r) => r.run_id !== run.run_id)]);
      setFormOpen(false);
      await selectRun(run);
    } catch (e) {
      setSubmitError(message(e));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }
  async function childRun(
    mode: "follow_up" | "draft_action",
    question: string,
  ) {
    if (!current || !current.context)
      throw new Error("原核查范围不可用，请重新读取");
    const body: RunRequest = {
      schema_version: "1",
      mode,
      question,
      parent_run_id: current.run_id,
      session_id: current.session_id,
      context: {
        ...current.context,
        snapshot_set_id: current.snapshot_set_id,
        analysis_id: current.analysis_id,
      },
      options: { window_days: 14 },
    };
    const serialized = JSON.stringify(body);
    if (submission.current?.body !== serialized)
      submission.current = { body: serialized, key: crypto.randomUUID() };
    const run = await api<RunView>(`/projects/${project.id}/runs`, {
      method: "POST",
      body,
      key: submission.current!.key,
    });
    submission.current = null;
    setRuns((old) => [run, ...old.filter((r) => r.run_id !== run.run_id)]);
    await selectRun(run);
  }
  async function retryCurrent() {
    if (!current?.context || sending.current) return;
    sending.current = true;
    setResultError("");
    const body: RunRequest = {
      schema_version: "1",
      mode: current.mode || "analyze",
      question: current.question,
      session_id: current.parent_run_id ? current.session_id : null,
      parent_run_id: current.parent_run_id || null,
      context: current.context,
      options: current.options || { window_days: 14 },
    };
    const serialized = JSON.stringify(body);
    if (submission.current?.body !== serialized)
      submission.current = { body: serialized, key: crypto.randomUUID() };
    try {
      const run = await api<RunView>(`/projects/${project.id}/runs`, {
        method: "POST",
        body,
        key: submission.current!.key,
      });
      submission.current = null;
      setRuns((old) => [run, ...old.filter((r) => r.run_id !== run.run_id)]);
      await selectRun(run);
    } catch (e) {
      setResultError(message(e));
    } finally {
      sending.current = false;
    }
  }
  function analyzeFinding(finding?: RiskFinding) {
    const row = finding
      ? dashboard?.inventory.find(
          (r) =>
            r.item_id === finding.item_id &&
            r.department_id === finding.department_id,
        )
      : undefined;
    begin(
      row,
      finding
        ? `请核查${finding.name}：${finding.summary}。查询对应明细与制度，说明事实、缺口和下一步。`
        : "请扫描当前项目全部物资的库存覆盖、批次效期和数据质量异常，说明扫描范围与跳过估算数量，并按关注级别汇总下一步核查建议。",
      finding ? "general" : "risk_scan",
    );
  }
  function showItemDetails(row: InventoryItem) {
    if (dashboard) setDetailRow({ row, snapshotId: dashboard.snapshot_set_id });
  }
  async function showEvidence(id: string) {
    evidenceId.current = id;
    const version = ++evidenceSelection.current;
    setEvidenceOpen(true);
    setEvidence(null);
    setEvidenceError("");
    setEvidenceLoading(true);
    try {
      const result = await api<EvidenceView>(`/evidence/${id}`);
      if (version === evidenceSelection.current) setEvidence(result);
    } catch (e) {
      if (version === evidenceSelection.current) setEvidenceError(message(e));
    } finally {
      if (version === evidenceSelection.current) setEvidenceLoading(false);
    }
  }
  async function cancel() {
    if (!current) return;
    const version = selection.current;
    try {
      const result = await api<RunView>(`/runs/${current.run_id}/cancel`, {
        method: "POST",
      });
      if (version === selection.current) setCurrent(result);
      void refresh();
    } catch (e) {
      setResultError(message(e));
    }
  }
  const runColumns: TableColumnsType<RunView> = [
    {
      title: "核查问题",
      dataIndex: "question",
      render: (v, r) => (
        <div className="run-question-cell">
          <Button type="link" onClick={() => void selectRun(r)}>
            {v}
          </Button>
          <span>
            {r.generation_mode === "mock" ? "历史流程校验" : "AI 核查"} · #
            {r.run_id.slice(0, 8)}
          </span>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (v) => <RunStatus status={v} />,
    },
    {
      title: "人工复核",
      key: "human-review",
      width: 160,
      render: (_, r) =>
        r.human_review ? (
          <ReviewStatusTag status={r.human_review.status} />
        ) : (
          <span>待人工复核</span>
        ),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 150,
      render: (v) => <span className="numeric secondary-text">{date(v)}</span>,
    },
    {
      title: "操作",
      key: "action",
      width: 90,
      render: (_, r) => (
        <Button type="link" onClick={() => void selectRun(r)}>
          查看
        </Button>
      ),
    },
  ];
  const filteredRuns = runs.filter(
    (r) =>
      (runFilter === "all" ||
        (runFilter === "active" && !terminal(r.status)) ||
        r.status === runFilter) &&
      (reviewFilter === "all" ||
        (reviewFilter === "required"
          ? !!r.human_review?.blocked
          : (r.human_review?.status || "pending") === reviewFilter)) &&
      r.question.toLowerCase().includes(runSearch.trim().toLowerCase()),
  );
  const low =
    dashboard?.inventory.filter(
      (r) => r.coverage_days !== null && Number(r.coverage_days) < 7,
    ) || [];
  const attention =
    dashboard?.inventory.filter((r) => r.quality_issues.length) || [];
  const prioritizedFindings = [...(riskReport?.findings || [])]
    .map((finding, index) => ({ finding, index }))
    .sort((a, b) => {
      const priority =
        (b.finding.priority === "high" ? 1 : 0) -
        (a.finding.priority === "high" ? 1 : 0);
      if (priority) return priority;
      const kind =
        (a.finding.kind === "expiry" ? 1 : 0) -
        (b.finding.kind === "expiry" ? 1 : 0);
      return kind || a.index - b.index;
    })
    .map(({ finding }) => finding);
  const nav = [
    {
      key: "overview",
      label: "核查工作台",
      path: "/app",
      Icon: IconLayoutDashboard,
    },
    { key: "risks", label: "异常中心", path: "/app/risks", Icon: IconActivity },
    {
      key: "tasks",
      label: "本人任务",
      path: "/app/tasks",
      Icon: IconShieldCheck,
    },
    { key: "data", label: "库存数据", path: "/app/data", Icon: IconDatabase },
    {
      key: "products",
      label: "物资档案",
      path: "/app/products",
      Icon: IconPackage,
    },
    {
      key: "departments",
      label: "科室目录",
      path: "/app/departments",
      Icon: IconBuildingHospital,
    },
    {
      key: "versions",
      label: "数据版本",
      path: "/app/versions",
      Icon: IconDatabase,
    },
    {
      key: "imports",
      label: "数据管理",
      path: "/app/imports",
      Icon: IconUpload,
    },
    {
      key: "knowledge",
      label: "知识库",
      path: "/app/knowledge",
      Icon: IconBook2,
    },
  ];
  function dismissGuide() {
    setTourOpen(false);
    try {
      localStorage.setItem(guideStorageKey, "dismissed");
    } catch {
      // The guide still closes for this session when browser storage is unavailable.
    }
  }
  function openGuide() {
    route("/app");
    setTourStep(0);
    setTourOpen(true);
  }
  const tourPanelStyle = tourRect
    ? {
        left: Math.max(16, Math.min(tourRect.left, window.innerWidth - 356)),
        top:
          tourRect.bottom + 230 < window.innerHeight
            ? tourRect.bottom + 14
            : Math.max(16, tourRect.top - 230),
      }
    : { left: 16, top: 16 };
  return (
    <div className="spd-workspace">
      <a href="#workspace-main" className="skip-link">
        跳到主要内容
      </a>
      <aside className="workspace-nav">
        <Brand />
        <div className="project-label">
          {project?.name.split(" · ")[0] || "工作空间"}
        </div>
        <nav aria-label="主要导航">
          {nav.map(({ key, label, path: href, Icon }) => (
            <a
              href={href}
              key={key}
              data-tour={
                key === "risks"
                  ? "risk-nav"
                  : key === "data"
                    ? "inventory-nav"
                    : key === "knowledge"
                      ? "knowledge-nav"
                      : key === "tasks"
                        ? "tasks-nav"
                        : undefined
              }
              aria-current={page === key ? "page" : undefined}
              className={page === key ? "selected" : ""}
              onClick={(e) => {
                if (!e.ctrlKey && !e.metaKey && !e.shiftKey) {
                  e.preventDefault();
                  route(href);
                }
              }}
            >
              <Icon size={20} />
              <span>{label}</span>
              {key === "data" && dashboard && (
                <span
                  className="nav-count"
                  aria-label={`${dashboard.stats.inventory_items} 项物资`}
                >
                  {dashboard.stats.inventory_items}
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="nav-support">
          <IconShieldCheck size={20} />
          <p>
            每一条结论
            <br />
            <strong>都有依据可循</strong>
          </p>
        </div>
        <div className="nav-account">
          <Avatar size={32}>{me.user.display_name.slice(0, 1)}</Avatar>
          <div>
            <strong>{me.user.display_name}</strong>
            <span>项目成员</span>
          </div>
          <Tooltip title="退出登录">
            <Button
              type="text"
              aria-label="退出登录"
              icon={<IconLogout size={18} />}
              onClick={async () => {
                try {
                  await api("/sessions/current", { method: "DELETE" });
                  onLogout();
                } catch (e) {
                  setError(message(e));
                }
              }}
            />
          </Tooltip>
        </div>
      </aside>
      <div className="workspace-body">
        <main id="workspace-main" className="workspace-content">
          <PageHeader
            title={nav.find((n) => n.key === page)?.label || "工作空间"}
            count={
              page === "data"
                ? dashboard?.stats.inventory_items
                : page === "knowledge"
                  ? dashboard?.stats.active_documents
                  : undefined
            }
            asOf={
              ["products", "departments", "versions"].includes(page)
                ? undefined
                : dashboard?.as_of
            }
            actions={
              <>
                <Button icon={<IconBook2 size={17} />} onClick={openGuide}>
                  新手指引
                </Button>
                <Tooltip title="刷新数据">
                  <Button
                    aria-label="刷新数据"
                    loading={refreshing}
                    icon={<IconRefresh size={18} />}
                    onClick={() => {
                      void refresh();
                      setPanelRefresh((v) => v + 1);
                    }}
                  />
                </Tooltip>
                {!["imports", "products", "departments", "versions"].includes(
                  page,
                ) && (
                  <Button
                    type="primary"
                    icon={<IconPlus size={18} />}
                    data-tour="new-run"
                    onClick={() => begin()}
                    disabled={!dashboard}
                  >
                    新建核查
                  </Button>
                )}
              </>
            }
          />
          {tourOpen && tourRect && (
            <div
              className="guided-tour"
              role="dialog"
              aria-modal="true"
              aria-labelledby="guided-tour-title"
            >
              <div
                className="guided-tour-shade"
                style={{ top: 0, left: 0, right: 0, height: tourRect.top }}
              />
              <div
                className="guided-tour-shade"
                style={{
                  top: tourRect.top,
                  left: 0,
                  width: tourRect.left,
                  height: tourRect.height,
                }}
              />
              <div
                className="guided-tour-shade"
                style={{
                  top: tourRect.top,
                  left: tourRect.right,
                  right: 0,
                  height: tourRect.height,
                }}
              />
              <div
                className="guided-tour-shade"
                style={{ top: tourRect.bottom, left: 0, right: 0, bottom: 0 }}
              />
              <div
                className="guided-tour-focus"
                style={{
                  top: tourRect.top,
                  left: tourRect.left,
                  width: tourRect.width,
                  height: tourRect.height,
                }}
              />
              <section className="guided-tour-popover" style={tourPanelStyle}>
                <div className="guided-tour-meta">
                  <span>新手引导</span>
                  <span>
                    {tourStep + 1} / {TOUR_STEPS.length}
                  </span>
                </div>
                <h2 id="guided-tour-title">{TOUR_STEPS[tourStep].title}</h2>
                <p>{TOUR_STEPS[tourStep].body}</p>
                {tourStep === 3 && (
                  <p className="guided-tour-warning">
                    当前是演示场景数据；AI
                    真实复测曾出现事实归因错误，请核对数字与引用。
                  </p>
                )}
                <div className="guided-tour-actions">
                  <Button type="text" onClick={dismissGuide}>
                    跳过
                  </Button>
                  <span />
                  <Button
                    disabled={tourStep === 0}
                    onClick={() => setTourStep((step) => step - 1)}
                  >
                    上一步
                  </Button>
                  {tourStep < TOUR_STEPS.length - 1 ? (
                    <Button
                      type="primary"
                      onClick={() => setTourStep((step) => step + 1)}
                    >
                      下一步
                    </Button>
                  ) : (
                    <Button type="primary" onClick={dismissGuide}>
                      完成
                    </Button>
                  )}
                </div>
              </section>
            </div>
          )}
          {error && (
            <Alert
              showIcon
              type="error"
              title={error}
              action={<Button onClick={() => void refresh()}>重试</Button>}
              className="page-alert"
            />
          )}
          {!project && <Empty description="当前账号尚无可访问项目" />}
          {!dashboard && !error ? (
            <Skeleton active paragraph={{ rows: 8 }} />
          ) : (
            dashboard && (
              <>
                {page === "risks" && riskReport ? (
                  <RiskPanel
                    data={riskReport}
                    loading={refreshing}
                    reload={() => void refresh()}
                    onAnalyze={analyzeFinding}
                    onDetails={(f) => {
                      const row = dashboard.inventory.find(
                        (r) =>
                          r.item_id === f.item_id &&
                          r.department_id === f.department_id,
                      );
                      if (row) showItemDetails(row);
                    }}
                  />
                ) : page === "tasks" ? (
                  <TasksPanel
                    key={panelRefresh}
                    projectId={project.id}
                    onSource={(id) => {
                      void api<RunView>(`/runs/${id}`)
                        .then(selectRun)
                        .catch((e) => setError(message(e)));
                    }}
                  />
                ) : page === "products" || page === "departments" ? (
                  <CatalogPanel
                    key={page}
                    projectId={project.id}
                    kind={page}
                    refreshKey={panelRefresh}
                  />
                ) : page === "versions" ? (
                  <VersionsPanel
                    projectId={project.id}
                    refreshKey={panelRefresh}
                    onPublished={refresh}
                  />
                ) : page === "imports" ? (
                  <ImportsPanel
                    projectId={project.id}
                    refreshKey={panelRefresh}
                    onPublished={refresh}
                  />
                ) : page === "data" ? (
                  <InventoryPanel
                    key={inventoryQuality}
                    rows={dashboard.inventory}
                    asOf={dashboard.as_of}
                    onAnalyze={(row) => begin(row)}
                    onDetails={showItemDetails}
                    initialQuality={inventoryQuality}
                  />
                ) : page === "knowledge" ? (
                  <KnowledgePanel
                    refreshKey={panelRefresh}
                    projectId={project.id}
                    onAnalyze={(q) => begin(undefined, q)}
                  />
                ) : (
                  <>
                    <div className="overview-summary">
                      <div className="summary-primary">
                        <span className="summary-label">项目物资</span>
                        <strong>
                          {number(dashboard.stats.inventory_items)}
                          <small>种</small>
                        </strong>
                        <span className="secondary-text">
                          {
                            new Set(
                              dashboard.inventory.map((r) => r.department_id),
                            ).size
                          }{" "}
                          个科室 · 当前授权范围
                        </span>
                      </div>
                      <button
                        className="summary-action"
                        onClick={() => {
                          setInventoryQuality("quality");
                          route("/app/data");
                        }}
                      >
                        <span className="summary-label">数据待核查</span>
                        <strong className="attention-text">
                          {attention.length}
                          <small>项</small>
                        </strong>
                        <span>
                          查看缺日与旧快照 <IconArrowRight size={15} />
                        </span>
                      </button>
                      <button
                        className="summary-action"
                        onClick={() => {
                          setInventoryQuality("low");
                          route("/app/data");
                        }}
                      >
                        <span className="summary-label">覆盖不足 7 天</span>
                        <strong>
                          {low.length}
                          <small>项</small>
                        </strong>
                        <span>
                          查看筛选结果 <IconArrowRight size={15} />
                        </span>
                      </button>
                      <button
                        className="summary-action"
                        onClick={() => route("/app/knowledge")}
                      >
                        <span className="summary-label">有效知识资料</span>
                        <strong>
                          {dashboard.stats.active_documents ??
                            dashboard.stats.documents}
                          <small>份</small>
                        </strong>
                        <span>
                          {dashboard.stats.knowledge_chunks ?? 0} 个已入库片段{" "}
                          <IconArrowRight size={15} />
                        </span>
                      </button>
                    </div>
                    <div className="overview-grid">
                      <section className="surface attention-surface">
                        <div className="section-heading">
                          <div>
                            <h2>先关注这些物资</h2>
                            <p>按异常关注级别排序，先核实再判断。</p>
                          </div>
                          <Button
                            type="link"
                            onClick={() => {
                              route("/app/risks");
                            }}
                          >
                            全部异常（{riskReport?.findings.length || 0}）{" "}
                            <IconArrowRight size={16} />
                          </Button>
                        </div>
                        <div className="attention-list">
                          {prioritizedFindings.slice(0, 4).map((finding) => (
                            <div key={finding.id} className="attention-row">
                              <span
                                className={`attention-marker ${finding.priority === "high" ? "quality" : "low"}`}
                              >
                                <IconActivity size={19} />
                              </span>
                              <div>
                                <strong>{finding.name}</strong>
                                <span>
                                  {finding.department_name} · {finding.summary}
                                </span>
                              </div>
                              <Button
                                onClick={() => analyzeFinding(finding)}
                                aria-label={`核查${finding.name}`}
                              >
                                核查
                              </Button>
                            </div>
                          ))}
                          {!!riskReport && riskReport.findings.length > 4 && (
                            <p className="secondary-text">
                              另有 {riskReport.findings.length - 4}{" "}
                              条关注项，请查看全部异常。
                            </p>
                          )}
                          {!riskReport?.findings.length && (
                            <Empty
                              image={Empty.PRESENTED_IMAGE_SIMPLE}
                              description="当前筛选口径下没有待关注项"
                            />
                          )}
                        </div>
                      </section>
                      <section className="agent-starter">
                        <span className="agent-emblem">
                          <IconSparkles size={22} />
                        </span>
                        <div>
                          <h2>让 Agent 帮你核查</h2>
                          <p>
                            读库存、查制度、给出带引用的回答。
                            <br />
                            不代替审批，不自动改库存。
                          </p>
                        </div>
                        <Button
                          onClick={() =>
                            begin(
                              undefined,
                              "请核查当前项目中消耗记录缺失和库存快照过期的物资，并根据资料说明处理流程。",
                            )
                          }
                        >
                          核查数据质量 <IconArrowRight size={16} />
                        </Button>
                        <Button
                          type="text"
                          onClick={() =>
                            begin(
                              dashboard.inventory.find(
                                (r) => r.item_id === "SIM-P001",
                              ),
                              "生化清洗液的库存能覆盖多少天？补货需要核实哪些依据？",
                            )
                          }
                        >
                          试试清洗液补货核查 <IconArrowRight size={16} />
                        </Button>
                        <small>
                          <IconBook2 size={14} />
                          已连接项目知识库
                        </small>
                      </section>
                    </div>
                    <DataTable<RunView>
                      heading={
                        <div className="section-heading">
                          <div>
                            <h2>核查记录</h2>
                          </div>
                          <Select
                            aria-label="筛选人工复核"
                            value={reviewFilter}
                            onChange={setReviewFilter}
                            style={{ minWidth: 160 }}
                            options={[
                              { value: "all", label: "全部复核状态" },
                              { value: "required", label: "需要复核 / 处理" },
                              { value: "pending", label: "待人工复核" },
                              { value: "confirmed", label: "人工确认" },
                              { value: "error", label: "发现错误 / 有争议" },
                              { value: "insufficient", label: "资料不足" },
                            ]}
                          />
                          <Input
                            prefix={<IconSearch size={17} />}
                            placeholder="搜索核查问题"
                            aria-label="搜索核查记录"
                            allowClear
                            value={runSearch}
                            onChange={(e) => setRunSearch(e.target.value)}
                            className="run-search"
                          />
                        </div>
                      }
                      tabs={
                        <Tabs
                          activeKey={runFilter}
                          onChange={setRunFilter}
                          items={[
                            { key: "all", label: `全部 ${runs.length}` },
                            {
                              key: "active",
                              label: `进行中 ${runs.filter((r) => !terminal(r.status)).length}`,
                            },
                            { key: "succeeded", label: "已完成" },
                            { key: "failed", label: "失败" },
                            { key: "cancelled", label: "已取消" },
                          ]}
                        />
                      }
                      columns={runColumns}
                      dataSource={filteredRuns}
                      rowKey="run_id"
                      scroll={{ x: 840 }}
                      totalLabel={(n) => `共 ${n} 条记录（最近 200 条）`}
                      emptyDescription="暂无匹配的核查记录"
                      emptyAction={
                        <Button onClick={() => begin()}>发起第一次核查</Button>
                      }
                    />
                  </>
                )}
              </>
            )
          )}
          <footer className="workspace-footer">
            <span>
              <IconShieldCheck size={14} />
              项目权限隔离 · 库存与引用留痕
            </span>
            <div className="connection-state">
              <span className={`connection-dot ${error ? "offline" : ""}`} />
              {error ? "连接异常" : dashboard ? "数据库已连接" : "连接中"}
              <span className="topbar-divider" />
              {dashboard?.provider_configured &&
              dashboard.generation_mode === "model"
                ? "AI 已配置"
                : "AI 待配置"}
            </div>
          </footer>
        </main>
      </div>
      <Drawer
        title="新建 AI 核查"
        open={formOpen}
        onClose={() => {
          if (!busy) setFormOpen(false);
        }}
        size={560}
      >
        <p className="drawer-intro">
          选择查询范围，描述你想核实的问题。Agent
          会调用只读工具，并给出可回查的依据。
        </p>
        <Form
          layout="vertical"
          onFinish={() => void submit()}
          requiredMark={false}
        >
          <Form.Item label="核查物资" htmlFor="run-item">
            <Select
              id="run-item"
              value={item}
              onChange={(value) => {
                setItem(value);
                setDepartment("");
              }}
              showSearch={{ optionFilterProp: "label" }}
              options={[
                { value: "", label: "当前项目全部物资" },
                ...Array.from(
                  new Map(
                    (formSnapshot?.inventory || []).map((r) => [r.item_id, r]),
                  ).values(),
                ).map((r) => ({
                  value: r.item_id,
                  label: `${r.name} · ${r.display_code}`,
                })),
              ]}
            />
          </Form.Item>
          <Form.Item
            label="你的问题"
            htmlFor="run-question"
            required
            extra="描述现象和需要核实的内容，不必输入内部物资编号。"
          >
            <Input.TextArea
              id="run-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：清洗液库存能覆盖几天，补货前还需要核实什么？"
              autoSize={{ minRows: 5, maxRows: 10 }}
              maxLength={2000}
              showCount
            />
          </Form.Item>
          <div className="form-scope">
            <IconDatabase size={18} />
            <div>
              <strong>查询打开表单时的授权快照</strong>
              <span>{formSnapshot?.as_of.replace("T", " ")}</span>
            </div>
          </div>
          {(!dashboard?.provider_configured ||
            dashboard.generation_mode !== "model") && (
            <Alert
              type="warning"
              title="AI 服务尚未配置"
              description="请在服务端配置密钥并重启 API 和 worker。库存和知识检索仍可使用。"
              className="page-alert"
            />
          )}
          {submitError && (
            <Alert
              type="error"
              showIcon
              title={submitError}
              className="page-alert"
            />
          )}
          <Button
            block
            type="primary"
            htmlType="submit"
            icon={<IconSparkles size={18} />}
            loading={busy}
            disabled={
              !question.trim() ||
              !dashboard?.provider_configured ||
              dashboard.generation_mode !== "model"
            }
          >
            开始核查
          </Button>
          <p className="method-note">
            结果仅是核查建议。审批、采购及库存变更仍由有权人员执行。
          </p>
        </Form>
      </Drawer>
      {resultOpen && (
        <ResultPanel
          open={resultOpen}
          onClose={() => setResultOpen(false)}
          run={current}
          analysis={analysis}
          events={events}
          loading={resultLoading}
          error={resultError}
          onCancel={() => void cancel()}
          onRetry={() => void retryCurrent()}
          onReload={() => {
            if (current) void selectRun(current);
            void refresh();
          }}
          onManualRecheck={() => {
            setResultOpen(false);
            route("/app/inventory");
            void refresh();
          }}
          onEvidence={(id) => void showEvidence(id)}
          actions={
            current && (
              <RunActions
                key={`${current.run_id}/${current.human_review?.revision}/${current.human_review?.status}`}
                run={current}
                enabled={
                  !!dashboard?.provider_configured &&
                  dashboard.generation_mode === "model"
                }
                onChild={childRun}
                onRun={(r) => void selectRun(r)}
                onTasks={() => {
                  setResultOpen(false);
                  route("/app/tasks");
                }}
              />
            )
          }
        />
      )}
      {detailRow && (
        <ItemDetailsPanel
          projectId={project.id}
          row={detailRow.row}
          snapshotId={detailRow.snapshotId}
          onClose={() => setDetailRow(null)}
        />
      )}
      {evidenceOpen && (
        <EvidencePanel
          evidence={evidence}
          identities={analysis?.inventory || []}
          onReload={() => {
            if (evidenceId.current) void showEvidence(evidenceId.current);
          }}
          open={evidenceOpen}
          loading={evidenceLoading}
          error={evidenceError}
          onClose={() => {
            evidenceSelection.current++;
            setEvidenceOpen(false);
            setEvidenceLoading(false);
          }}
        />
      )}
    </div>
  );
}
