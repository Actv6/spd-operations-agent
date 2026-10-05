import type { ReactNode } from "react";
import { Alert, Button, Empty, Table } from "antd";
import type { TableProps } from "antd";
import "./workspace-components.css";

export type DataTableProps<T extends object> = Omit<
  TableProps<T>,
  "title" | "footer" | "size"
> & {
  heading?: ReactNode;
  tabs?: ReactNode;
  toolbar?: ReactNode;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  error?: string;
  onRetry?: () => void;
  totalLabel?: (total: number) => ReactNode;
};

/** Shared business-table shell. Ant Design owns sorting, pagination and accessibility. */
export function DataTable<T extends object>({
  heading,
  tabs,
  toolbar,
  emptyDescription = "暂无匹配的数据",
  emptyAction,
  error,
  onRetry,
  totalLabel = (total) => `共 ${total} 条`,
  pagination,
  locale,
  className = "",
  ...tableProps
}: DataTableProps<T>) {
  return (
    <section className={`data-table ${className}`}>
      {heading && <div className="data-table-heading">{heading}</div>}
      {tabs && <div className="data-table-tabs">{tabs}</div>}
      {toolbar && <div className="data-table-toolbar">{toolbar}</div>}
      {error && (
        <div className="data-table-feedback">
          <Alert
            type="error"
            showIcon
            title={error}
            action={onRetry && <Button onClick={onRetry}>重试</Button>}
          />
        </div>
      )}
      <Table<T>
        {...tableProps}
        size="middle"
        pagination={
          pagination === false
            ? false
            : {
                defaultPageSize: 10,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50],
                showTotal: totalLabel,
                ...pagination,
              }
        }
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={emptyDescription}
            >
              {emptyAction}
            </Empty>
          ),
          ...locale,
        }}
      />
    </section>
  );
}
