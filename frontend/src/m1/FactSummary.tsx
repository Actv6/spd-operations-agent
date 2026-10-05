import type { InventoryItem } from "./types";
import { number, quality } from "./ui";

export function FactSummary({ row }: { row: InventoryItem }) {
  return (
    <section className="fact-block">
      <header>
        <strong>{row.name.replace("（模拟）", "")}</strong>
        <span className="secondary-text">
          {row.display_code || row.item_id} · {row.department_name || ""}
        </span>
      </header>
      <div className="fact-numbers">
        <div>
          <span>可用库存</span>
          <strong>
            {number(row.available)} <small>{row.unit}</small>
          </strong>
        </div>
        <div>
          <span>日均消耗</span>
          <strong>
            {number(row.daily_average)} <small>{row.unit}/日</small>
          </strong>
        </div>
        <div>
          <span>覆盖基线</span>
          <strong>
            {row.coverage_days === null ? "待核实" : number(row.coverage_days)}{" "}
            <small>{row.coverage_days === null ? "" : "天"}</small>
          </strong>
        </div>
      </div>
      {row.quality_issues.length > 0 && (
        <p className="attention-text">
          {row.quality_issues.map((q) => quality[q] || q).join("；")} ·
          有效消耗记录 {row.observed_days}/14 天
        </p>
      )}
    </section>
  );
}

