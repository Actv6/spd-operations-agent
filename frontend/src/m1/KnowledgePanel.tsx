import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Tabs,
} from "antd";
import type { TableColumnsType } from "antd";
import ReactMarkdown from "react-markdown";
import { IconArrowUpRight, IconSearch } from "@tabler/icons-react";
import { api } from "./api";
import { message } from "./ui";
import { DataTable } from "./components/DataTable";
import { KnowledgeManager } from "./KnowledgeManager";
import type {
  KnowledgeDocumentsView,
  KnowledgeDocumentView,
  KnowledgeDocumentDetail,
  KnowledgeSearchView,
  KnowledgeHit,
} from "./types";

export function KnowledgePanel({
  projectId,
  refreshKey,
  onAnalyze,
}: {
  projectId: string;
  refreshKey: number;
  onAnalyze: (question: string) => void;
}) {
  const [docs, setDocs] = useState<KnowledgeDocumentView[] | null>(null);
  const [tab, setTab] = useState("catalog");
  const [filter, setFilter] = useState("active");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [document, setDocument] = useState<KnowledgeDocumentDetail | null>(
    null,
  );
  const [opening, setOpening] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const selection = useRef(0);
  const documentId = useRef("");
  const [documentError, setDocumentError] = useState("");
  const fetchDocs = () => {
    setError("");
    api<KnowledgeDocumentsView>(`/projects/${projectId}/knowledge/documents`)
      .then((r) => setDocs(r.items))
      .catch((e) => setError(message(e)));
  };
  useEffect(() => {
    fetchDocs();
  }, [projectId, refreshKey]);
  useEffect(
    () => () => {
      selection.current++;
    },
    [projectId],
  );
  async function openDocument(id: string) {
    documentId.current = id;
    const version = ++selection.current;
    setDrawerOpen(true);
    setOpening(true);
    setDocument(null);
    setDocumentError("");
    try {
      const result = await api<KnowledgeDocumentDetail>(
        `/knowledge/documents/${id}`,
      );
      if (version === selection.current) setDocument(result);
    } catch (e) {
      if (version === selection.current) setDocumentError(message(e));
    } finally {
      if (version === selection.current) setOpening(false);
    }
  }
  async function search() {
    if (!query.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<KnowledgeSearchView>(
        `/projects/${projectId}/knowledge/search?q=${encodeURIComponent(query.trim())}`,
      );
      setHits(result.items);
      setSearched(true);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const columns: TableColumnsType<KnowledgeDocumentView> = [
    {
      title: "资料名称",
      dataIndex: "title",
      render: (v, row) => (
        <Button
          type="link"
          className="document-link"
          onClick={() => void openDocument(row.document_id)}
        >
          {v}
        </Button>
      ),
    },
    { title: "版本", dataIndex: "version", width: 80, render: (v) => `v${v}` },
    {
      title: "状态",
      dataIndex: "currently_valid",
      width: 100,
      render: (v) => (
        <Tag color={v ? "success" : "default"}>
          {v ? "当前有效" : "历史版本"}
        </Tag>
      ),
    },
    {
      title: "生效日期",
      dataIndex: "effective_from",
      width: 140,
      className: "numeric",
    },
    { title: "检索片段", dataIndex: "chunk_count", align: "right", width: 100 },
    {
      title: "操作",
      key: "actions",
      width: 90,
      render: (_, row) => (
        <Button
          type="link"
          onClick={() => void openDocument(row.document_id)}
          aria-label={`阅读${row.title}`}
        >
          阅读
        </Button>
      ),
    },
  ];
  return (
    <>
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={<Button onClick={fetchDocs}>重试目录</Button>}
          className="page-alert"
        />
      )}
      <section className="knowledge-panel">
        <Tabs
          activeKey={tab}
          onChange={(key) => {
            setTab(key);
            setQuery("");
            setSearched(false);
            setHits([]);
          }}
          items={[
            {
              key: "manage",
              label: "资料维护",
              children: (
                <KnowledgeManager
                  key={projectId}
                  projectId={projectId}
                  refreshKey={refreshKey}
                  onChanged={fetchDocs}
                />
              ),
            },
            {
              key: "catalog",
              label: `资料目录${docs ? ` · ${docs.filter((d) => d.currently_valid).length} 份有效` : ""}`,
              children: (
                <DataTable<KnowledgeDocumentView>
                  toolbar={
                    <>
                      <Input
                        aria-label="搜索资料名称"
                        prefix={<IconSearch size={18} />}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        allowClear
                        placeholder="搜索资料名称"
                        className="search-input"
                      />
                      <Segmented
                        aria-label="资料版本范围"
                        options={[
                          { label: "当前有效", value: "active" },
                          { label: "全部版本", value: "all" },
                        ]}
                        value={filter}
                        onChange={(v) => setFilter(String(v))}
                      />
                    </>
                  }
                  columns={columns}
                  dataSource={(docs || []).filter(
                    (d) =>
                      (filter === "all" || d.currently_valid) &&
                      d.title.includes(query.trim()),
                  )}
                  rowKey="document_id"
                  loading={!docs && !error}
                  scroll={{ x: 760 }}
                  totalLabel={(n) => `共 ${n} 份资料`}
                  emptyDescription="没有匹配的资料"
                />
              ),
            },
            {
              key: "search",
              label: "检索原文",
              children: (
                <div className="knowledge-search-body">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void search();
                    }}
                    className="search-form"
                  >
                    <Input
                      aria-label="检索问题"
                      prefix={<IconSearch size={18} />}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      maxLength={2000}
                      placeholder="例如：消耗缺两天记录，应该怎么处理？"
                      allowClear
                    />
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={busy}
                      disabled={!query.trim()}
                    >
                      检索
                    </Button>
                  </form>
                  <p className="secondary-text">
                    检索当前项目的有效资料，查看原文后可交给 Agent
                    结合库存核查。
                  </p>
                  {busy ? (
                    <Skeleton active />
                  ) : !searched ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="输入业务问题，查找对应制度与案例"
                    />
                  ) : hits.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="未找到相关依据，请换个关键词或补充资料"
                    />
                  ) : (
                    <div className="knowledge-results">
                      {hits.map((hit) => (
                        <article className="knowledge-hit" key={hit.chunk_id}>
                          <div>
                            <Tag>v{hit.version}</Tag>
                            <span className="secondary-text">
                              {hit.chapter}
                            </span>
                          </div>
                          <h3>
                            <Button
                              type="link"
                              onClick={() => void openDocument(hit.document_id)}
                            >
                              {hit.title}
                            </Button>
                          </h3>
                          <p>{hit.excerpt}</p>
                          <Button
                            type="text"
                            icon={<IconArrowUpRight size={16} />}
                            onClick={() => onAnalyze(query)}
                          >
                            结合库存发起核查
                          </Button>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },
          ]}
        />
      </section>
      <p className="method-note">
        资料已分块入库，按项目授权、生效日期和版本过滤后检索。页面刷新不会重新导入资料。
      </p>
      <Drawer
        open={drawerOpen}
        onClose={() => {
          selection.current++;
          setDrawerOpen(false);
          setOpening(false);
        }}
        title="资料原文"
        size={700}
      >
        {opening ? (
          <Skeleton active />
        ) : document ? (
          <>
            <Space wrap>
              <Tag color={document.currently_valid ? "success" : "default"}>
                {document.currently_valid ? "当前有效" : "历史版本"}
              </Tag>
              <span>
                v{document.version} · {document.effective_from} 生效
              </span>
            </Space>
            <div className="markdown-content">
              <ReactMarkdown>{document.content}</ReactMarkdown>
            </div>
            <details className="source-metadata">
              <summary>来源校验信息</summary>
              <p>{document.source_hash}</p>
              <p>{document.chunk_count} 个检索片段</p>
            </details>
          </>
        ) : documentError ? (
          <Alert
            type="error"
            showIcon
            title={documentError}
            action={
              <Button onClick={() => void openDocument(documentId.current)}>
                重新读取原文
              </Button>
            }
          />
        ) : (
          <Empty description="资料暂不可用" />
        )}
      </Drawer>
    </>
  );
}
