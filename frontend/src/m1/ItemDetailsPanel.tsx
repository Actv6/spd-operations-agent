import { Alert, Button, Drawer, Skeleton, Tabs } from "antd";
import { useResource } from "./useResource";
import { BatchFacts, ConsumptionFacts } from "./DataFacts";
import type { InventoryItem, ItemDetails } from "./types";
import "./m2.css";

export function ItemDetailsPanel({
  projectId,
  row,
  snapshotId,
  onClose,
}: {
  projectId: string;
  row: InventoryItem;
  snapshotId: string;
  onClose: () => void;
}) {
  const { data, error, loading, reload } = useResource<ItemDetails>(
    `/projects/${projectId}/item-details?item_id=${encodeURIComponent(row.item_id)}&department_id=${encodeURIComponent(row.department_id)}&snapshot_set_id=${encodeURIComponent(snapshotId)}`,
  );
  return (
    <Drawer
      title={`${row.name} · 批次与消耗`}
      open
      onClose={onClose}
      size={960}
    >
      <p>
        {row.department_name}
        {data && ` · 库存快照 ${data.as_of.slice(0, 16).replace("T", " ")}`}
      </p>
      {loading ? (
        <Skeleton active />
      ) : error ? (
        <Alert
          type="error"
          showIcon
          title={error}
          action={<Button onClick={reload}>重新读取明细</Button>}
        />
      ) : (
        data && (
          <Tabs
            items={[
              {
                key: "batches",
                label: "批次明细",
                children: <BatchFacts rows={data.batches} />,
              },
              {
                key: "consumption",
                label: "14日消耗",
                children: (
                  <ConsumptionFacts
                    rows={data.consumption}
                    identities={[row]}
                  />
                ),
              },
            ]}
          />
        )
      )}
    </Drawer>
  );
}
