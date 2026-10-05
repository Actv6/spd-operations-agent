import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Alert, App as AntApp, Button, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { api, ApiError } from "./api";
import type { MeView } from "./types";
import { message, route } from "./ui";
import "./workbench.css";
const Auth = lazy(() => import("./Auth").then(m => ({ default: m.Auth })));
const Workspace = lazy(() => import("./Workspace").then(m => ({ default: m.Workspace })));

const theme = {
  token: {
    colorPrimary: "#245edb",
    colorText: "#202c3f",
    colorTextSecondary: "#59677a",
    colorBorder: "#dce2ea",
    colorBgLayout: "#f5f7fa",
    colorSuccess: "#218365",
    colorWarning: "#a96c10",
    colorError: "#c23945",
    borderRadius: 6,
    fontSize: 16,
    controlHeight: 48,
    fontFamily:
      '"PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  components: {
    Table: {
      headerBg: "#f7f9fb",
      cellPaddingBlockMD: 12,
      cellPaddingInlineMD: 16,
    },
    Drawer: { paddingLG: 24 },
    Tabs: { horizontalMargin: "0 0 16px 0" },
  },
};

export function WorkbenchApp() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <Suspense fallback={<div className="initial-loading" role="status">正在载入工作空间…</div>}><SessionApp /></Suspense>
      </AntApp>
    </ConfigProvider>
  );
}

function SessionApp() {
  const [me, setMe] = useState<MeView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [path, setPath] = useState(location.pathname);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setMe(await api<MeView>("/me"));
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError(message(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const change = () => setPath(location.pathname);
    const expire = () => {
      setMe(null);
      route("/login");
    };
    window.addEventListener("popstate", change);
    window.addEventListener("m1-session-expired", expire);
    return () => {
      window.removeEventListener("popstate", change);
      window.removeEventListener("m1-session-expired", expire);
    };
  }, [load]);
  if (loading)
    return (
      <div className="initial-loading">
        <img src="/brand/spd-logo-v1.png" width={48} height={48} alt="SPD 运营助手" />
        <p role="status">正在载入工作空间…</p>
      </div>
    );
  if (error)
    return (
      <div className="initial-loading">
        <Alert
          type="error"
          title={error}
          action={<Button onClick={() => void load()}>重新连接</Button>}
        />
      </div>
    );
  if (!me)
    return (
      <Auth
        key={path}
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

