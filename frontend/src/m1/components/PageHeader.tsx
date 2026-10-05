import type { ReactNode } from "react";
import { Tooltip } from "antd";
import "./workspace-components.css";

/** One compact page heading across the workspace; no duplicated promotional copy. */
export function PageHeader({
  title,
  count,
  asOf,
  actions,
}: {
  title: string;
  count?: number;
  asOf?: string;
  actions: ReactNode;
}) {
  return (
    <header className="workspace-page-header">
      <div className="page-title">
        <h1>{title}</h1>
        {count !== undefined && <span className="page-count">{count}</span>}
      </div>
      <div className="page-commands">
        {asOf && (
          <Tooltip
            title={`库存业务时点 ${asOf}；消耗口径为此前14个完整自然日，不是实时数据刷新时间。`}
          >
            <time className="page-as-of" dateTime={asOf}>
              数据时点：{asOf.replace("T", " ").slice(0, 16)}
            </time>
          </Tooltip>
        )}
        <div className="page-actions">{actions}</div>
      </div>
    </header>
  );
}
