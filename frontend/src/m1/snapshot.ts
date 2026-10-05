import { api } from "./api";
import type { DashboardView, RiskReport, RunView } from "./types";

export async function readSnapshotBundle(projectId: string, read = api) {
  const [dashboard, runs] = await Promise.all([
    read<DashboardView>(`/projects/${projectId}/dashboard`),
    read<RunView[]>(`/projects/${projectId}/runs?limit=200`),
  ]);
  const risks = await read<RiskReport>(
    `/projects/${projectId}/risks?snapshot_set_id=${encodeURIComponent(dashboard.snapshot_set_id)}`,
  );
  if (risks.snapshot_set_id !== dashboard.snapshot_set_id)
    throw new Error("数据版本不一致，请重新刷新工作台。");
  return { dashboard, runs, risks };
}
