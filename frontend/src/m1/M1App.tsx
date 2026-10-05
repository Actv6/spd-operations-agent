import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  IconLayoutDashboard,
  IconDatabase,
  IconBook2,
  IconLogout,
  IconSparkles,
  IconArrowRight,
  IconRefresh,
  IconCircleCheck,
  IconClock,
  IconAlertTriangle,
  IconFileText,
  IconChevronRight,
  IconX,
} from "@tabler/icons-react";
import { api, ApiError } from "./api";
import type {
  MeView,
  DashboardView,
  RunView,
  RunRequest,
  AnalysisView,
  EvidenceView,
  EventsView,
  InventoryItem,
  KnowledgeHit,
  KnowledgeSearchView,
} from "./types";
import "./m1.css";

const STATUS: Record<RunView["status"], string> = {
  queued: "等待处理",
  running: "正在核查",
  succeeded: "已完成",
  failed: "运行失败",
  cancelled: "已取消",
};
const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);
const modeName = (mode: string) =>
  mode === "mock"
    ? "历史流程校验"
    : mode === "rules_only"
      ? "规则核查"
      : "AI 分析";
const message = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败，请重试";
const display = (s: string | null | undefined) =>
  s == null
    ? "待核实"
    : Number(s).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const route = (path: string) => {
  history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
};

export function M1App() {
  const [me, setMe] = useState<MeView | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [path, setPath] = useState(location.pathname);
  const refresh = useCallback(async () => {
    setError("");
    setReady(false);
    try {
      const account = await api<MeView>("/me");
      setMe(account);
      if (!location.pathname.startsWith("/app")) route("/app");
    } catch (e) {
      setMe(null);
      if (e instanceof ApiError && e.status === 401) {
        if (!["/register", "/login"].includes(location.pathname))
          route("/login");
      } else setError(message(e));
    } finally {
      setReady(true);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const onRoute = () => setPath(location.pathname);
    const expired = () => {
      setMe(null);
      route("/login");
    };
    window.addEventListener("popstate", onRoute);
    window.addEventListener("m1-session-expired", expired);
    return () => {
      window.removeEventListener("popstate", onRoute);
      window.removeEventListener("m1-session-expired", expired);
    };
  }, [refresh]);
  if (!ready)
    return (
      <div className="m1-loading" role="status">
        正在确认登录状态…
      </div>
    );
  if (error)
    return (
      <div className="m1-auth">
        <section className="m1-auth-card">
          <IconAlertTriangle />
          <h1>服务暂不可用</h1>
          <p role="alert">{error}</p>
          <button className="primary" onClick={() => void refresh()}>
            重新连接
          </button>
        </section>
      </div>
    );
  if (!me)
    return (
      <Auth
        register={path === "/register"}
        onSuccess={(account) => {
          setMe(account);
          route("/app");
        }}
      />
    );
  return (
    <Workspace
      key={me.user.id}
      me={me}
      path={path}
      onLogout={() => {
        setMe(null);
        route("/login");
      }}
    />
  );
}

function Auth({
  register,
  onSuccess,
}: {
  register: boolean;
  onSuccess: (me: MeView) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const me = await api<MeView>(register ? "/registrations" : "/sessions", {
        method: "POST",
        body: { email, password, ...(register ? { display_name: name } : {}) },
      });
      onSuccess(me);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="m1-auth">
      <aside className="m1-auth-intro">
        <div className="m1-wordmark">
          SPD <span>运营助手</span>
        </div>
        <div>
          <span className="m1-eyebrow">OPERATIONS WORKSPACE</span>
          <h2>
            让每一次核查，
            <br />
            都有据可循。
          </h2>
          <p>
            查看库存事实，检索有效资料，
            <br />
            在一个工作台里完成异常核查。
          </p>
        </div>
        <small>供应链运营 · 项目协同</small>
      </aside>
      <main className="m1-auth-card">
        <span className="badge neutral">SPD 运营工作台</span>
        <h1>{register ? "创建你的工作台" : "欢迎回来"}</h1>
        <p>
          {register
            ? "注册后自动建立仅你可访问的工作空间与项目。"
            : "登录后继续查看你的库存与核查记录。"}
        </p>
        <form onSubmit={submit}>
          {register && (
            <label>
              姓名
              <input
                autoComplete="name"
                required
                maxLength={50}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
          )}
          <label>
            邮箱
            <input
              type="email"
              autoComplete="username"
              required
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              minLength={10}
              maxLength={128}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {register && <small>密码至少 10 个字符，请妥善保管。</small>}
          {error && (
            <p className="m1-error" role="alert">
              {error}
            </p>
          )}
          <button className="primary wide" disabled={busy}>
            {busy ? "正在处理…" : register ? "注册并进入" : "登录"}
            <IconArrowRight size={17} />
          </button>
        </form>
        <p className="m1-auth-switch">
          {register ? "已有账号？" : "还没有账号？"}{" "}
          <button
            onClick={() => {
              setError("");
              route(register ? "/login" : "/register");
            }}
          >
            {register ? "前往登录" : "注册账号"}
          </button>
        </p>
      </main>
    </div>
  );
}

function Workspace({
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
  const [runs, setRuns] = useState<RunView[]>([]);
  const [current, setCurrent] = useState<RunView | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisView | null>(null);
  const [events, setEvents] = useState<EventsView["items"]>([]);
  const [question, setQuestion] = useState("");
  const [item, setItem] = useState("SIM-P001");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<EvidenceView | null>(null);
  const [query, setQuery] = useState("补货核查");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searched, setSearched] = useState(false);
  const submission = useRef<{ body: string; key: string } | null>(null);
  const selection = useRef(0);
  const page =
    path === "/app/data"
      ? "data"
      : path === "/app/knowledge"
        ? "knowledge"
        : "overview";
  const refresh = useCallback(async () => {
    if (!project) return;
    try {
      const [d, r] = await Promise.all([
        api<DashboardView>(`/projects/${project.id}/dashboard`),
        api<RunView[]>(`/projects/${project.id}/runs`),
      ]);
      setDashboard(d);
      setRuns(r);
      setError("");
    } catch (e) {
      setError(message(e));
    }
  }, [project?.id]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  async function selectRun(run: RunView) {
    const version = ++selection.current;
    setCurrent(run);
    setAnalysis(null);
    setEvents([]);
    setEvidence(null);
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
      if (version === selection.current) setError(message(e));
    }
  }
  useEffect(() => {
    if (!current || terminal(current.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const runId = current.run_id;
    const version = selection.current;
    let cursor = events.at(-1)?.cursor || "0";
    let retries = 0;
    async function poll() {
      try {
        const [run, log] = await Promise.all([
          api<RunView>(`/runs/${runId}`),
          api<EventsView>(`/runs/${runId}/events?after=${cursor}&limit=200`),
        ]);
        // Fetch the result before entering a terminal state: that transition cleans up this effect.
        const result = run.analysis_id
          ? await api<AnalysisView>(`/analyses/${run.analysis_id}`)
          : null;
        if (stopped || version !== selection.current) return;
        retries = 0;
        setError("");
        cursor = log.next_cursor;
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
        setError(message(e));
        retries++;
      }
      if (!stopped)
        timer = setTimeout(
          poll,
          Math.min(1000 * 2 ** retries, 15000) * (document.hidden ? 5 : 1),
        );
    }
    timer = setTimeout(poll, 600);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // Poll lifetime follows run identity and terminal status, not every received revision.
  }, [current?.run_id, current?.status, refresh]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || !project) return;
    setBusy(true);
    setError("");
    const body: RunRequest = {
      schema_version: "1",
      mode: "analyze",
      question: question.trim(),
      session_id: null,
      parent_run_id: null,
      context: {
        snapshot_set_id: dashboard?.snapshot_set_id || null,
        item_ids: item ? [item] : [],
        department_ids: [],
        analysis_id: null,
      },
      options: { window_days: 14 },
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
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function showEvidence(id: string) {
    try {
      setEvidence(await api<EvidenceView>(`/evidence/${id}`));
    } catch (e) {
      setError(message(e));
    }
  }
  async function searchKnowledge(e: FormEvent) {
    e.preventDefault();
    if (!project) return;
    setBusy(true);
    try {
      const result = await api<KnowledgeSearchView>(
        `/projects/${project.id}/knowledge/search?q=${encodeURIComponent(query)}`,
      );
      setHits(result.items);
      setSearched(true);
      setError("");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const stats = dashboard?.stats;
  return (
    <div className="app-shell m1-shell">
      <aside className="sidebar">
        <div className="brand">SPD 运营助手</div>
        <nav>
          {[
            ["overview", "核查工作台", IconLayoutDashboard, "/app"],
            ["data", "库存数据", IconDatabase, "/app/data"],
            ["knowledge", "知识检索", IconBook2, "/app/knowledge"],
          ].map(([key, label, Icon, url]) => {
            const NavIcon = Icon as typeof IconDatabase;
            return (
              <button
                key={String(key)}
                className={`nav-item ${page === key ? "active" : ""}`}
                aria-label={String(label)}
                aria-current={page === key ? "page" : undefined}
                onClick={() => route(String(url))}
              >
                <NavIcon size={23} />
                <span>{String(label)}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <p>
            让供应更高效
            <br />
            让一线更从容
          </p>
          <p className="m1-version">M1 本地工作台</p>
        </div>
      </aside>
      <header className="topbar">
        <span className="demo-badge">SPD 运营管理</span>
        <div className="header-right">
          <span className="m1-project">{project?.name || "暂无项目"}</span>
          <span className="m1-user">{me.user.display_name}</span>
          <button
            className="icon-button"
            aria-label="退出登录"
            onClick={async () => {
              try {
                await api("/sessions/current", { method: "DELETE" });
                selection.current++;
                onLogout();
              } catch (e) {
                setError(message(e));
              }
            }}
          >
            <IconLogout size={20} />
          </button>
        </div>
      </header>
      <main className={`main ${page === "overview" ? "has-detail" : ""}`}>
        <section className="workspace">
          <div className="page-heading">
            <div>
              <h1>
                {page === "overview"
                  ? "核查工作台"
                  : page === "data"
                    ? "库存数据"
                    : "知识检索"}
              </h1>
              <p>
                {page === "overview"
                  ? "从事实出发，把依据放在手边"
                  : page === "data"
                    ? "已入库的授权项目快照"
                    : "在当前项目的有效资料中查找依据"}
              </p>
            </div>
            <button
              className="icon-button"
              aria-label="刷新数据"
              onClick={() => void refresh()}
            >
              <IconRefresh size={19} />
            </button>
          </div>
          {error && (
            <div className="m1-error m1-banner" role="alert">
              <IconAlertTriangle size={18} />
              <span>{error}</span>
              <button onClick={() => void refresh()}>重试</button>
            </div>
          )}
          {!dashboard && !error && (
            <div className="empty" role="status">
              正在读取数据库…
            </div>
          )}
          {dashboard && (
            <>
              <div className="m1-status-line">
                <span className="m1-status-dot" />
                {error ? "请检查服务提示" : "数据库已连接"}
                <span>
                  {dashboard.provider_configured
                    ? dashboard.generation_mode === "model"
                      ? "AI 已配置"
                      : "流程校验服务"
                    : "AI 服务待配置"}
                </span>
                <span>知识库已连接</span>
              </div>
              {page === "overview" && (
                <>
                  <div className="overview-stats m1-stats">
                    {[
                      ["物资种类", stats?.inventory_items],
                      ["数据待核查", stats?.quality_issues],
                      ["知识版本", stats?.documents],
                      ["核查记录", runs.length],
                    ].map(([name, value]) => (
                      <div key={name}>
                        <span>{name}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="board m1-board">
                    {[
                      {
                        key: "queued",
                        label: "待运行",
                        filter: (r: RunView) => r.status === "queued",
                      },
                      {
                        key: "running",
                        label: "运行中",
                        filter: (r: RunView) => r.status === "running",
                      },
                      {
                        key: "done",
                        label: "历史结果",
                        filter: (r: RunView) => terminal(r.status),
                      },
                    ].map((column, index) => (
                      <section
                        className={`board-column ${index === 1 ? "review" : index === 2 ? "active" : "pending"}`}
                        key={column.key}
                      >
                        <header className="column-heading">
                          <span>
                            {column.label}
                            <strong>{runs.filter(column.filter).length}</strong>
                          </span>
                          <IconChevronRight size={17} />
                        </header>
                        <div className="column-content">
                          {runs.filter(column.filter).map((run) => (
                            <button
                              key={run.run_id}
                              className={`task-card m1-run-card ${current?.run_id === run.run_id ? "selected" : ""}`}
                              onClick={() => void selectRun(run)}
                            >
                              <div className="tags">
                                <span
                                  className={`badge ${run.status === "failed" ? "shortage" : run.status === "succeeded" ? "active" : "neutral"}`}
                                >
                                  {STATUS[run.status]}
                                </span>
                                <span className="badge neutral">
                                  {modeName(run.generation_mode)}
                                </span>
                              </div>
                              <h3>{run.question || "库存与制度核查"}</h3>
                              <p className="task-location">
                                {run.as_of.slice(0, 10)} · 库存快照
                              </p>
                              <p className="task-summary">
                                {run.error?.message ||
                                  (run.status === "succeeded"
                                    ? "查看回答、库存指标与引用来源"
                                    : "后台正在处理此核查请求")}
                              </p>
                              <div className="task-meta">
                                <span className="owner">
                                  #{run.run_id.slice(0, 8)}
                                </span>
                                <time>
                                  {new Date(run.updated_at).toLocaleTimeString(
                                    "zh-CN",
                                    { hour: "2-digit", minute: "2-digit" },
                                  )}
                                </time>
                              </div>
                            </button>
                          ))}
                          {!runs.some(column.filter) && (
                            <div className="column-empty">
                              {index === 0 ? (
                                <IconFileText size={25} />
                              ) : index === 1 ? (
                                <IconClock size={25} />
                              ) : (
                                <IconCircleCheck size={25} />
                              )}
                              <p>
                                {index === 0
                                  ? "提交问题后在此排队"
                                  : index === 1
                                    ? "当前没有运行中的核查"
                                    : "完成的核查会保存在这里"}
                              </p>
                            </div>
                          )}
                          {index === 0 && (
                            <div className="m1-starters">
                              <small>试着问一问</small>
                              {[
                                "生化清洗液缺货时，应核查哪些依据？",
                                "库存消耗记录缺失时如何处理？",
                                "临期物资需要核查哪些资料？",
                              ].map((q, i) => (
                                <button
                                  key={q}
                                  onClick={() => {
                                    setQuestion(q);
                                    setItem(
                                      ["SIM-P001", "SIM-P006", "SIM-P003"][i],
                                    );
                                  }}
                                >
                                  {q}
                                  <IconArrowRight size={15} />
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </section>
                    ))}
                  </div>
                </>
              )}
              {page === "data" && (
                <>
                  <p className="muted m1-snapshot">
                    快照：{dashboard.as_of.replace("T", " ")} · 数量均为基准单位
                  </p>
                  <InventoryTable rows={dashboard.inventory} />
                  <div className="context-note">
                    覆盖天数为库存 ÷ 近 14
                    个完整自然日日均消耗；缺失记录与旧快照暂停估计。该基线尚未加入在途到货和逐日效期变化。
                  </div>
                </>
              )}
              {page === "knowledge" && (
                <>
                  <form
                    className="m1-knowledge-search"
                    onSubmit={searchKnowledge}
                  >
                    <label className="sr-only" htmlFor="knowledge-query">
                      检索问题
                    </label>
                    <input
                      id="knowledge-query"
                      value={query}
                      required
                      maxLength={2000}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="输入制度关键词"
                    />
                    <button className="primary" disabled={busy}>
                      检索
                    </button>
                  </form>
                  <div className="context-note">
                    检索仅包含当前项目有权访问、已生效且未停用的资料。
                  </div>
                  <div className="m1-hits">
                    {hits.map((hit) => (
                      <article key={hit.chunk_id}>
                        <span className="badge active">
                          有效版本 {hit.version}
                        </span>
                        <h2>{hit.title}</h2>
                        <p className="muted">{hit.chapter}</p>
                        <p>{hit.excerpt}</p>
                      </article>
                    ))}
                  </div>
                  {searched && !hits.length && (
                    <div className="empty">
                      没有找到支持该问题的有效资料，请调整关键词。
                    </div>
                  )}
                </>
              )}
            </>
          )}
          <footer className="workspace-footer">
            <span>库存、资料与核查记录统一管理</span>
            <span>账号与核查记录保存于后端数据库</span>
          </footer>
        </section>
        {page === "overview" && (
          <aside className="detail-panel m1-inspector" aria-label="核查详情">
            <div className="detail-top">
              <h2>发起核查</h2>
              <IconSparkles size={21} />
            </div>
            <div className="detail-scroll">
              <form className="m1-question-form" onSubmit={submit}>
                <label>
                  核查物资
                  <select
                    value={item}
                    onChange={(e) => setItem(e.target.value)}
                  >
                    <option value="">当前项目全部物资</option>
                    {dashboard?.inventory.map((r) => (
                      <option key={r.item_id} value={r.item_id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  你的问题
                  <textarea
                    required
                    maxLength={2000}
                    rows={4}
                    placeholder="例如：清洗液缺货时，需要核查哪些依据？"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <button
                  className="primary wide"
                  disabled={
                    busy ||
                    !dashboard?.provider_configured ||
                    dashboard.generation_mode !== "model" ||
                    !question.trim()
                  }
                >
                  {busy ? "正在提交…" : "开始核查"}
                  <IconArrowRight size={17} />
                </button>
                <p className="muted">
                  {!dashboard
                    ? "正在读取服务配置…"
                    : dashboard.provider_configured &&
                        dashboard.generation_mode === "model"
                      ? "依据当前项目库存与知识库进行 AI 核查。"
                      : "请在服务端配置 AI 密钥后开始核查。"}
                </p>
              </form>
              {current && (
                <section className="m1-result" aria-live="polite">
                  <div className="section-heading">
                    <h3>{STATUS[current.status]}</h3>
                    <span className="badge neutral">
                      {modeName(current.generation_mode)}
                    </span>
                  </div>
                  {!terminal(current.status) && (
                    <button
                      className="text-button"
                      onClick={async () => {
                        try {
                          setCurrent(
                            await api<RunView>(
                              `/runs/${current.run_id}/cancel`,
                              { method: "POST" },
                            ),
                          );
                          void refresh();
                        } catch (e) {
                          setError(message(e));
                        }
                      }}
                    >
                      取消本次运行
                    </button>
                  )}
                  {current.error && (
                    <div role="alert" className="m1-error">
                      <p>{current.error.message}</p>
                      <small>{current.error.code}</small>
                    </div>
                  )}
                  {analysis && current.generation_mode === "mock" && (
                    <p className="m1-answer">
                      这条历史记录用于流程校验，未调用
                      AI。原始记录已保留，可重新发起核查以获得 AI 分析。
                    </p>
                  )}
                  {analysis && current.generation_mode !== "mock" && (
                    <>
                      <p className="m1-answer">{analysis.answer}</p>
                      {analysis.insufficient_evidence && (
                        <span className="badge quality">依据不足</span>
                      )}
                      {analysis.inventory.slice(0, 3).map((row) => (
                        <div className="m1-fact" key={row.item_id}>
                          <strong>{row.name}</strong>
                          <div className="evidence-metrics">
                            <div>
                              <span>可用库存</span>
                              <strong>
                                {display(row.available)}
                                {row.available !== null && (
                                  <small>{row.unit}</small>
                                )}
                              </strong>
                            </div>
                            <div>
                              <span>日均消耗</span>
                              <strong>{display(row.daily_average)}</strong>
                            </div>
                            <div>
                              <span>覆盖基线</span>
                              <strong>
                                {display(row.coverage_days)}
                                {row.coverage_days !== null && (
                                  <small>天</small>
                                )}
                              </strong>
                            </div>
                          </div>
                          {row.observed_days < 14 && (
                            <p className="muted">
                              有效消耗记录 {row.observed_days}/14
                              天，记录不完整，暂停估计。
                            </p>
                          )}
                        </div>
                      ))}
                      <h3 className="m1-source-title">
                        引用来源 · {analysis.citations.length}
                      </h3>
                      <div className="m1-citations">
                        {analysis.citations.map((c) => (
                          <button
                            key={c.evidence_id}
                            onClick={() => void showEvidence(c.evidence_id)}
                          >
                            <IconFileText size={19} />
                            <span>
                              {c.title}
                              <small>
                                {c.source_kind === "document"
                                  ? `v${c.source_version} · ${String(c.location.chapter || "")}`
                                  : "数据库工具查询"}
                                {!c.currently_valid ? " · 已失效" : ""}
                              </small>
                            </span>
                            <IconChevronRight size={16} />
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                  {events.length > 0 && current.generation_mode !== "mock" && (
                    <details className="m1-events">
                      <summary>运行记录 · {events.length}</summary>
                      {events.map((e) => (
                        <p key={e.cursor}>
                          <span>{e.cursor}.</span>{" "}
                          {String(
                            e.payload.message ||
                              (e.type === "run_started"
                                ? "运行开始"
                                : e.type === "analysis_ready"
                                  ? "结果已保存"
                                  : e.type === "run_finished"
                                    ? "运行结束"
                                    : e.type),
                          )}
                          <small>{e.step}</small>
                        </p>
                      ))}
                    </details>
                  )}
                  <small className="muted">运行编号：{current.run_id}</small>
                </section>
              )}
            </div>
          </aside>
        )}
      </main>
      {evidence && (
        <EvidenceDialog evidence={evidence} close={() => setEvidence(null)} />
      )}
    </div>
  );
}

function InventoryTable({ rows }: { rows: InventoryItem[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>物资 / 编码</th>
            <th>可用库存</th>
            <th>日均消耗</th>
            <th>覆盖基线</th>
            <th>记录天数</th>
            <th>数据状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.item_id}>
              <td>
                <strong>{r.name}</strong>
                <small>{r.display_code || r.item_id}</small>
                {r.specification && <small>{r.specification}</small>}
              </td>
              <td>
                {display(r.available)} {r.unit}
              </td>
              <td>{display(r.daily_average)}</td>
              <td>
                {display(r.coverage_days)}
                {r.coverage_days !== null ? " 天" : ""}
              </td>
              <td>{r.observed_days}/14</td>
              <td>
                <span
                  className={`badge ${r.quality_issues.length ? "quality" : "active"}`}
                >
                  {r.quality_issues.length ? "待核查" : "快照可用"}
                </span>
                {r.quality_issues.map((q) => (
                  <small key={q}>
                    {{
                      MISSING_CONSUMPTION_DAYS: "消耗记录缺日",
                      STALE_SNAPSHOT: "库存快照过期",
                      INVALID_BATCH_QUANTITY: "批次数量异常",
                    }[q] || q}
                  </small>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceDialog({
  evidence,
  close,
}: {
  evidence: EvidenceView;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} className="dialog m1-evidence-dialog" onCancel={close}>
      <header>
        <h2>{evidence.title}</h2>
        <button
          className="icon-button"
          aria-label="关闭引用详情"
          onClick={close}
        >
          <IconX size={20} />
        </button>
      </header>
      <div className="dialog-content">
        <span className="badge neutral">
          {evidence.source_kind === "document" ? "文档原文" : "数据库快照"}
        </span>
        {!evidence.currently_valid && (
          <p className="m1-error">此来源当前已失效，仅供历史回查。</p>
        )}
        {evidence.source_kind === "document" ? (
          <>
            <p>
              版本 {evidence.source_version} ·{" "}
              {String(evidence.location.chapter || "")}
            </p>
            <blockquote>{evidence.excerpt}</blockquote>
            <p className="muted">
              文件：{String(evidence.location.source_path)}
              <br />
              片段：{String(evidence.location.chunk_id)}
              <br />
              原文字符偏移：{String(evidence.location.start_offset)}–
              {String(evidence.location.end_offset)}
            </p>
          </>
        ) : (
          <InventoryTable
            rows={(evidence.facts?.inventory || []) as InventoryItem[]}
          />
        )}
        <p className="m1-hash">SHA-256：{evidence.hash}</p>
        <p className="muted">基准时间：{evidence.as_of}</p>
      </div>
    </dialog>
  );
}
