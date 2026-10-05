import { useState } from "react";
import {
  Button,
  Descriptions,
  Drawer,
  Input,
  Select,
  Space,
  Alert,
} from "antd";
import type { TableColumnsType } from "antd";
import { IconSearch, IconSparkles, IconFilterOff } from "@tabler/icons-react";
import type { InventoryItem } from "./types";
import { number, quality } from "./ui";
import { DataTable } from "./components/DataTable";

export function InventoryPanel({
  rows,
  asOf,
  onAnalyze,
  onDetails,
  initialQuality = "all",
}: {
  rows: InventoryItem[];
  asOf: string;
  onAnalyze: (row: InventoryItem) => void;
  onDetails?: (row: InventoryItem) => void;
  initialQuality?: string;
}) {
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("all");
  const [status, setStatus] = useState(initialQuality);
  const [selected, setSelected] = useState<InventoryItem | null>(null);
  const [page, setPage] = useState(1);
  const departments = [
    ...new Map(
      rows.map((r) => [r.department_id, r.department_name || r.department_id]),
    ).entries(),
  ];
  const visible = rows.filter(
    (r) =>
      `${r.name} ${r.display_code} ${r.specification}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()) &&
      (department === "all" || r.department_id === department) &&
      (status === "all" ||
        (status === "quality"
          ? r.quality_issues.length > 0
          : r.coverage_days !== null && Number(r.coverage_days) < 7)),
  );
  const columns: TableColumnsType<InventoryItem> = [
    {
      title: "物资名称 / 编码",
      key: "name",
      width: 220,
      render: (_, r) => (
        <div className="item-identity">
          <Button
            type="link"
            onClick={() => setSelected(r)}
            aria-label={`查看${r.name}详情`}
          >
            {r.name}
          </Button>
          <span>{r.display_code || r.item_id}</span>
        </div>
      ),
    },
    {
      title: "科室",
      dataIndex: "department_name",
      width: 100,
      render: (v, r) => v || r.department_id,
    },
    {
      title: "可用库存",
      dataIndex: "available",
      width: 130,
      align: "right",
      sorter: (a, b) => Number(a.available ?? -1) - Number(b.available ?? -1),
      render: (v, r) => (
        <span className="numeric">
          {number(v)} <span className="secondary-text">{r.unit}</span>
        </span>
      ),
    },
    {
      title: "日均消耗",
      dataIndex: "daily_average",
      width: 115,
      align: "right",
      render: (v, r) => (
        <span className="numeric">
          {number(v)} <span className="secondary-text">{r.unit}/日</span>
        </span>
      ),
    },
    {
      title: "覆盖基线",
      dataIndex: "coverage_days",
      width: 120,
      align: "right",
      sorter: (a, b) =>
        Number(a.coverage_days ?? -1) - Number(b.coverage_days ?? -1),
      render: (v) => (
        <span
          className={`numeric ${v !== null && Number(v) < 7 ? "attention-text" : ""}`}
        >
          {v === null ? "待核实" : `${number(v)} 天`}
        </span>
      ),
    },
    {
      title: "数据状态",
      key: "quality",
      width: 180,
      render: (_, r) =>
        r.quality_issues.length ? (
          <Space orientation="vertical" size={4}>
            {r.quality_issues.map((q) => (
              <span key={q} className="status-inline attention-text">
                <i />
                {quality[q] || q}
              </span>
            ))}
          </Space>
        ) : (
          <span className="status-inline">
            <i />
            记录完整
          </span>
        ),
    },
    {
      title: "操作",
      key: "actions",
      width: 115,
      fixed: "right",
      render: (_, r) => (
        <Button
          type="link"
          icon={<IconSparkles size={15} />}
          onClick={() => onAnalyze(r)}
          aria-label={`核查${r.name}`}
        >
          核查
        </Button>
      ),
    },
  ];
  return (
    <>
      <DataTable<InventoryItem>
        toolbar={
          <>
            <Input
              prefix={<IconSearch size={18} />}
              placeholder="搜索物资名称或编码"
              aria-label="搜索物资"
              allowClear
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              className="search-input"
            />
            <Select
              aria-label="筛选科室"
              value={department}
              onChange={(v) => {
                setDepartment(v);
                setPage(1);
              }}
              options={[
                { value: "all", label: "全部科室" },
                ...departments.map(([value, label]) => ({ value, label })),
              ]}
            />
            <Select
              aria-label="筛选库存状态"
              value={status}
              onChange={(v) => {
                setStatus(v);
                setPage(1);
              }}
              options={[
                { value: "all", label: "全部状态" },
                { value: "quality", label: "数据待核查" },
                { value: "low", label: "覆盖不足 7 天" },
              ]}
            />
            {(search || department !== "all" || status !== "all") && (
              <Button
                icon={<IconFilterOff size={16} />}
                onClick={() => {
                  setSearch("");
                  setDepartment("all");
                  setStatus("all");
                  setPage(1);
                }}
              >
                重置
              </Button>
            )}
          </>
        }
        rowKey={(r) => `${r.item_id}/${r.department_id}`}
        columns={columns}
        dataSource={visible}
        scroll={{ x: 980 }}
        totalLabel={(total) => `共 ${total} 项物资`}
        emptyDescription="没有匹配的物资，请调整搜索或筛选条件"
        pagination={{
          current: page,
          onChange: (p) => setPage(p),
        }}
      />
      <p className="method-note">
        覆盖基线 = 可用库存 ÷ 近 14
        个完整自然日日均消耗；不含逐日在途与效期变化。“不足 7
        天”仅为筛选条件，不代表已确认缺货。
      </p>
      <Drawer
        title="物资详情"
        open={!!selected}
        onClose={() => setSelected(null)}
        size={560}
        extra={
          selected && (
            <Button
              type="primary"
              icon={<IconSparkles size={16} />}
              onClick={() => {
                onAnalyze(selected);
                setSelected(null);
              }}
            >
              发起核查
            </Button>
          )
        }
      >
        {selected && (
          <>
            <h2 className="drawer-heading">{selected.name}</h2>
            {onDetails && (
              <Button
                className="page-alert"
                onClick={() => {
                  onDetails(selected);
                  setSelected(null);
                }}
              >
                批次与消耗明细
              </Button>
            )}
            <p className="secondary-text">{selected.display_code}</p>
            <Descriptions
              column={1}
              className="detail-descriptions"
              items={[
                {
                  key: "spec",
                  label: "规格",
                  children: selected.specification || "未登记",
                },
                {
                  key: "department",
                  label: "科室",
                  children: selected.department_name || selected.department_id,
                },
                {
                  key: "available",
                  label: "可用库存",
                  children: `${number(selected.available)} ${selected.unit}`,
                },
                {
                  key: "daily",
                  label: "日均消耗",
                  children: `${number(selected.daily_average)} ${selected.unit}/日`,
                },
                {
                  key: "coverage",
                  label: "覆盖基线",
                  children:
                    selected.coverage_days === null
                      ? "待核实"
                      : `${number(selected.coverage_days)} 天`,
                },
                {
                  key: "days",
                  label: "消耗记录",
                  children: `${selected.observed_days} / 14 天`,
                },
                {
                  key: "time",
                  label: "核查业务时间",
                  children: asOf.replace("T", " "),
                },
                {
                  key: "row-time",
                  label: "库存行时间",
                  children: selected.snapshot_at.replace("T", " "),
                },
              ]}
            />
            {selected.quality_issues.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title="数据需要先核实"
                description={selected.quality_issues
                  .map((q) => quality[q] || q)
                  .join("；")}
              />
            )}
            <p className="method-note">
              来源关联 {selected.source_rows.length}{" "}
              条库存、批次与消耗记录。历史快照不可覆盖。
            </p>
          </>
        )}
      </Drawer>
    </>
  );
}
