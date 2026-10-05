import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Collapse,
  Drawer,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Tabs,
  Tag,
} from "antd";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { api, ApiError } from "./api";
import type {
  CatalogDetail,
  CatalogList,
  CatalogView,
  CatalogWrite,
} from "./types";
import { DataTable } from "./components/DataTable";
import { date, message, route } from "./ui";
import "./catalog.css";

type Kind = "products" | "departments";
const fieldLabels: Record<string, string> = {
  code: "编码",
  name: "名称",
  specification: "规格",
  base_unit: "基础单位",
  active: "状态",
};
function valueText(key: string, value: unknown) {
  return key === "active"
    ? value
      ? "启用"
      : "停用"
    : String(value || "未填写");
}

export function CatalogPanel({
  projectId,
  kind,
  refreshKey,
}: {
  projectId: string;
  kind: Kind;
  refreshKey: number;
}) {
  const product = kind === "products";
  const noun = product ? "物资" : "科室";
  const base = `/projects/${projectId}/catalog/${kind}`;
  const { message: toast } = App.useApp();
  const [data, setData] = useState<CatalogList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<CatalogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toggle, setToggle] = useState<CatalogView | null>(null);
  const [toggleError, setToggleError] = useState("");
  const [form] = Form.useForm<CatalogWrite>();
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const saving = useRef(false);
  const canEdit = data?.can_edit === true;
  const load = useCallback(async () => {
    const version = ++generation.current;
    setLoading(true);
    try {
      const result = await api<CatalogList>(base);
      if (version === generation.current) {
        setData(result);
        setError("");
      }
    } catch (e) {
      if (version === generation.current) setError(message(e));
    } finally {
      if (version === generation.current) setLoading(false);
    }
  }, [base]);
  useEffect(() => {
    void load();
    return () => {
      generation.current++;
      detailGeneration.current++;
    };
  }, [load, refreshKey]);
  function create() {
    detailGeneration.current++;
    setSelected(null);
    setDetailLoading(false);
    setDetailError("");
    setConflict(false);
    form.resetFields();
    form.setFieldsValue({
      code: "",
      name: "",
      specification: "",
      base_unit: "",
      active: true,
    });
    setOpen(true);
  }
  async function inspect(row: CatalogView) {
    const version = ++detailGeneration.current;
    setSelected(row as CatalogDetail);
    setOpen(true);
    setDetailLoading(true);
    setDetailError("");
    setConflict(false);
    form.resetFields();
    try {
      const detail = await api<CatalogDetail>(`${base}/${row.id}`);
      if (version === detailGeneration.current) {
        setSelected(detail);
        form.setFieldsValue(detail);
      }
    } catch (e) {
      if (version === detailGeneration.current) setDetailError(message(e));
    } finally {
      if (version === detailGeneration.current) setDetailLoading(false);
    }
  }
  async function save(values: CatalogWrite) {
    if (saving.current || detailLoading || !canEdit) return;
    saving.current = true;
    setBusy(true);
    setDetailError("");
    const body = {
      code: values.code,
      name: values.name,
      specification: product ? values.specification || "" : "",
      base_unit: product ? values.base_unit : "",
      active: values.active,
    };
    try {
      await api<CatalogDetail>(selected ? `${base}/${selected.id}` : base, {
        method: selected ? "PUT" : "POST",
        body: selected ? { ...body, revision: selected.revision } : body,
      });
      setOpen(false);
      void toast.success(`${noun}档案已保存`);
      await load();
    } catch (e) {
      setDetailError(message(e));
      setConflict(e instanceof ApiError && e.detail.code === "CATALOG_CHANGED");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function changeStatus() {
    if (!toggle || saving.current) return;
    saving.current = true;
    setBusy(true);
    setToggleError("");
    const { code, name, specification, base_unit, revision } = toggle;
    try {
      await api(`${base}/${toggle.id}`, {
        method: "PUT",
        body: {
          code,
          name,
          specification,
          base_unit,
          revision,
          active: !toggle.active,
        },
      });
      void toast.success(
        toggle.active ? "已停用，历史库存保留" : "已启用，可用于后续导入",
      );
      setToggle(null);
      await load();
    } catch (e) {
      setToggleError(message(e));
      await load();
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  const rows = (data?.items || []).filter(
    (r) =>
      (filter === "all" || r.active === (filter === "active")) &&
      [r.code, r.name, r.specification].some((v) =>
        (v || "").toLowerCase().includes(query.trim().toLowerCase()),
      ),
  );
  return (
    <>
      <div className="catalog-context">
        <p>
          {product
            ? "维护物资编码、名称、规格和基础单位。档案变更随下一次数据导入发布生效。"
            : "维护科室编码和唯一名称。CSV 按科室名称匹配，修改后请重新下载导入模板。"}
        </p>
        <Button onClick={() => route("/app/imports")}>前往数据导入</Button>
      </div>
      {!canEdit && data && (
        <p className="catalog-readonly">
          当前账号可查看目录；维护档案需项目负责人权限。
        </p>
      )}
      <DataTable<CatalogView>
        className="catalog-table"
        rowKey="id"
        dataSource={rows}
        loading={loading}
        error={error}
        onRetry={() => void load()}
        emptyDescription={
          query || filter !== "all" ? "没有匹配的档案" : `暂无${noun}档案`
        }
        scroll={{ x: product ? 900 : 680 }}
        tabs={
          <Tabs
            activeKey={filter}
            onChange={setFilter}
            items={[
              { key: "all", label: `全部（${data?.items.length ?? 0}）` },
              { key: "active", label: "启用中" },
              { key: "inactive", label: "已停用" },
            ]}
          />
        }
        toolbar={
          <>
            <Input
              className="search-input"
              aria-label={`搜索${noun}档案`}
              placeholder={
                product ? "搜索编码、名称或规格" : "搜索科室编码或名称"
              }
              prefix={<IconSearch size={17} />}
              value={query}
              allowClear
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              type="primary"
              icon={<IconPlus size={17} />}
              disabled={!canEdit}
              onClick={create}
            >
              新增{noun}
            </Button>
          </>
        }
        columns={[
          { title: `${noun}编码`, dataIndex: "code", width: 150 },
          { title: `${noun}名称`, dataIndex: "name", width: 180 },
          ...(product
            ? [
                {
                  title: "规格",
                  dataIndex: "specification",
                  render: (v: string) => v || "—",
                },
                { title: "基础单位", dataIndex: "base_unit", width: 95 },
              ]
            : []),
          {
            title: "状态",
            width: 95,
            render: (_, r) => (
              <Tag color={r.active ? "success" : "default"}>
                {r.active ? "启用" : "停用"}
              </Tag>
            ),
          },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 140,
            render: (v) => date(v),
          },
          {
            title: "操作",
            width: 160,
            fixed: "right",
            render: (_, r) => (
              <Space size={4}>
                <Button type="link" onClick={() => void inspect(r)}>
                  {canEdit ? "编辑" : "查看"}
                </Button>
                {canEdit && (
                  <Button
                    type="link"
                    onClick={() => {
                      setToggle(r);
                      setToggleError("");
                    }}
                  >
                    {r.active ? "停用" : "启用"}
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Drawer
        title={`${selected ? (canEdit ? "编辑" : "查看") : "新增"}${noun}档案`}
        open={open}
        width={560}
        closable={!busy}
        maskClosable={!busy}
        onClose={() => {
          if (!busy) {
            detailGeneration.current++;
            setOpen(false);
          }
        }}
        footer={
          canEdit && (
            <div className="catalog-footer">
              <Button
                disabled={busy}
                onClick={() => {
                  detailGeneration.current++;
                  setOpen(false);
                }}
              >
                取消
              </Button>
              <Button
                type="primary"
                loading={busy}
                disabled={detailLoading || conflict}
                onClick={() => form.submit()}
              >
                保存档案
              </Button>
            </div>
          )
        }
      >
        {detailError && (
          <Alert
            type="error"
            showIcon
            title={detailError}
            action={
              selected && (
                <Button disabled={busy} onClick={() => void inspect(selected)}>
                  重新读取
                </Button>
              )
            }
          />
        )}
        {detailLoading ? (
          <p role="status">正在读取档案…</p>
        ) : (
          <Form
            form={form}
            layout="vertical"
            disabled={!canEdit || busy || conflict}
            onFinish={save}
            className="catalog-form"
          >
            <Form.Item
              label={`${noun}编码`}
              name="code"
              rules={[
                { required: true, whitespace: true, message: "请输入编码" },
                {
                  pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/,
                  message:
                    "仅使用字母、数字、点、横线或下划线，以字母或数字开头",
                },
              ]}
              extra="编码在当前项目内唯一，保存时统一为大写；停用后仍保留编码。"
            >
              <Input
                maxLength={100}
                placeholder={product ? "例如 MAT-0025" : "例如 DEP-004"}
              />
            </Form.Item>
            <Form.Item
              label={`${noun}名称`}
              name="name"
              rules={[
                { required: true, whitespace: true, message: "请输入名称" },
              ]}
              extra={
                !product
                  ? "科室名称必须唯一，与导入文件中的科室名称保持一致。"
                  : undefined
              }
            >
              <Input maxLength={100} />
            </Form.Item>
            {product && (
              <>
                <Form.Item label="规格" name="specification">
                  <Input maxLength={200} placeholder="例如 500 mL/瓶" />
                </Form.Item>
                <Form.Item
                  label="基础单位"
                  name="base_unit"
                  rules={[
                    {
                      required: true,
                      whitespace: true,
                      message: "请输入基础单位",
                    },
                  ]}
                  extra={
                    selected?.unit_locked
                      ? "已用于库存快照，单位不可直接修改。如需另一基础单位，请新建物资编码。"
                      : "库存与消耗数量均使用此单位，不会自动换算采购包装。"
                  }
                >
                  <Input
                    maxLength={30}
                    disabled={
                      selected?.unit_locked || !canEdit || busy || conflict
                    }
                    placeholder="例如 瓶、支、盒"
                  />
                </Form.Item>
              </>
            )}
            <Form.Item
              label="状态"
              name="active"
              valuePropName="checked"
              extra="停用后限制新导入，现有库存与历史核查仍保留。"
            >
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          </Form>
        )}
        {selected?.history && (
          <Collapse
            className="catalog-history"
            items={[
              {
                key: "history",
                label: `修改记录（${selected.history.length}）`,
                children: (
                  <ol>
                    {[...selected.history].reverse().map((h, i) => (
                      <li key={i}>
                        <strong>{h.action}</strong>
                        <span>
                          {h.actor} · {date(h.at)}
                        </span>
                        {Object.keys(h.after)
                          .filter((k) => h.before[k] !== h.after[k])
                          .map((k) => (
                            <p key={k}>
                              {fieldLabels[k] || k}：
                              {k in h.before
                                ? `${valueText(k, h.before[k])} → `
                                : ""}
                              {valueText(k, h.after[k])}
                            </p>
                          ))}
                      </li>
                    ))}
                  </ol>
                ),
              },
            ]}
          />
        )}
      </Drawer>
      <Modal
        title={`${toggle?.active ? "停用" : "启用"}${noun}？`}
        open={!!toggle}
        onCancel={() => !busy && setToggle(null)}
        onOk={() => void changeStatus()}
        confirmLoading={busy}
        okText={toggle?.active ? "确认停用" : "确认启用"}
        cancelText="取消"
        closable={!busy}
        maskClosable={!busy}
        cancelButtonProps={{ disabled: busy }}
      >
        <p>
          {toggle?.code} · {toggle?.name}
        </p>
        <p>
          {toggle?.active
            ? "停用后，新导入将拒绝使用此档案；现有库存和历史核查保持不变。已生成的待发布预览需重新校验。"
            : "启用后，可在新的 CSV 导入中使用此档案。请重新下载模板并校验。"}
        </p>
        {toggleError && <Alert type="error" showIcon title={toggleError} />}
      </Modal>
    </>
  );
}
