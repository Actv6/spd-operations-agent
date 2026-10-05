import { Component, lazy, Suspense } from "react";
import type { ComponentType, ReactNode } from "react";

class LoadBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div role="alert">
        页面组件载入失败，请保留未提交内容后刷新页面。
        <button onClick={() => location.reload()}>刷新页面</button>
      </div>
    ) : (
      this.props.children
    );
  }
}

function deferred<P extends object>(
  load: () => Promise<{ default: ComponentType<P> }>,
) {
  const Panel = lazy(load);
  return (props: P) => (
    <LoadBoundary>
      <Suspense fallback={<p role="status">正在载入…</p>}>
        <Panel {...props} />
      </Suspense>
    </LoadBoundary>
  );
}

export const InventoryPanel = deferred<
  Parameters<typeof import("./InventoryPanel").InventoryPanel>[0]
>(() =>
  import("./InventoryPanel").then((m) => ({ default: m.InventoryPanel })),
);
export const KnowledgePanel = deferred<
  Parameters<typeof import("./KnowledgePanel").KnowledgePanel>[0]
>(() =>
  import("./KnowledgePanel").then((m) => ({ default: m.KnowledgePanel })),
);
export const RiskPanel = deferred<
  Parameters<typeof import("./RiskPanel").RiskPanel>[0]
>(() => import("./RiskPanel").then((m) => ({ default: m.RiskPanel })));
export const TasksPanel = deferred<
  Parameters<typeof import("./TasksPanel").TasksPanel>[0]
>(() => import("./TasksPanel").then((m) => ({ default: m.TasksPanel })));
export const ItemDetailsPanel = deferred<
  Parameters<typeof import("./ItemDetailsPanel").ItemDetailsPanel>[0]
>(() =>
  import("./ItemDetailsPanel").then((m) => ({ default: m.ItemDetailsPanel })),
);
export const RunActions = deferred<
  Parameters<typeof import("./RunActions").RunActions>[0]
>(() => import("./RunActions").then((m) => ({ default: m.RunActions })));
export const ResultPanel = deferred<
  Parameters<typeof import("./ResultPanel").ResultPanel>[0]
>(() => import("./ResultPanel").then((m) => ({ default: m.ResultPanel })));
export const EvidencePanel = deferred<
  Parameters<typeof import("./ResultPanel").EvidencePanel>[0]
>(() => import("./ResultPanel").then((m) => ({ default: m.EvidencePanel })));

export const ImportsPanel = deferred<
  Parameters<typeof import("./ImportsPanel").ImportsPanel>[0]
>(() => import("./ImportsPanel").then((m) => ({ default: m.ImportsPanel })));

export const CatalogPanel = deferred<
  Parameters<typeof import("./CatalogPanel").CatalogPanel>[0]
>(() => import("./CatalogPanel").then((m) => ({ default: m.CatalogPanel })));

export const VersionsPanel = deferred<
  Parameters<typeof import("./VersionsPanel").VersionsPanel>[0]
>(() => import("./VersionsPanel").then((m) => ({ default: m.VersionsPanel })));
