import { Tag } from "antd";
import type { RunView } from "./types";

export const STATUS: Record<RunView["status"], string> = {
  queued: "等待处理",
  running: "正在核查",
  succeeded: "已完成",
  failed: "运行失败",
  cancelled: "已取消",
};
export const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);
export const message = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败，请重试";
export const number = (value: string | number | null | undefined) => {
  if (value == null) return "—";
  const raw = String(value);
  if (/^-?\d+(\.\d+)?$/.test(raw)) {
    const [integer, fraction = ""] = raw.split(".");
    const decimal = fraction.replace(/0+$/, "");
    return (
      integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",") +
      (decimal ? "." + decimal : "")
    );
  }
  return Number.isFinite(Number(value))
    ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 4 })
    : "—";
};
export const date = (s: string) =>
  new Date(s).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
export const route = (path: string) => {
  history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "instant" });
};
export const quality: Record<string, string> = {
  MISSING_CONSUMPTION_DAYS: "消耗记录缺日",
  STALE_SNAPSHOT: "库存快照过期",
  INVALID_BATCH_QUANTITY: "批次数量异常",
  MISSING_BATCHES: "批次缺失",
  DUPLICATE_CONSUMPTION_DAY: "消耗日期重复",
  UNSUPPORTED_CONSUMPTION: "消耗口径待核实",
};
export function RunStatus({ status }: { status: RunView["status"] }) {
  return (
    <Tag
      color={
        {
          queued: "default",
          running: "processing",
          succeeded: "success",
          failed: "error",
          cancelled: "default",
        }[status]
      }
    >
      {STATUS[status]}
    </Tag>
  );
}
export function SectionHeading({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  );
}
