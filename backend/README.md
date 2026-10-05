# SPD M1 / M2 后端与本地运行

2026-10-01 V1.1更新：API v1.1、迁移v1101、提示v11-quality-1。新增个人反馈和所有者知识维护接口，详见 `../docs/verification/V1.1实施与验收报告.md`。`alembic upgrade head` 会新增反馈和知识变更表，升级既有库前先做一致备份。

本轮本地链路：FastAPI + SQLAlchemy/Alembic + 一进程 worker + LangGraph + React/TypeScript。
当前开发数据库为 SQLite；PostgreSQL 迁移仅完成 SQL 生成检查，尚未连接真实 PostgreSQL。
业务数据采用用户授权生成的企业场景（data/scenario），不代表真实公司记录。注册创建隔离工作空间与澄川医院项目，不授予全局管理员。

## 首次准备

要求 Python 3.11–3.13、uv、Node 22+、pnpm。实测 Python 3.12.14、Node 24.19.0；精确依赖见 `uv.lock`、`../frontend/pnpm-lock.yaml`。

```sh
cd backend
uv sync --frozen
.venv/bin/python -m app.cli init-config
.venv/bin/alembic upgrade head
cd ../frontend
pnpm install --frozen-lockfile
```

`init-config` 只在 `.env` 不存在时生成，包含随机 CSRF secret，权限 0600；不覆盖已有配置。
默认 `LLM_PROVIDER=deepseek`；缺 key 时 AI 待配置，不自动使用模板回答。账号通过注册页创建，无公共管理员账号和默认管理密码。密钥与数据库查看见 `../docs/数据库与密钥配置.md`。

在项目根目录运行：

```sh
backend/.venv/bin/python scripts/start_m1.py
```

浏览器访问 `http://127.0.0.1:4180`，API 在 `http://127.0.0.1:8010/docs`。
前端 `/api` 经 Vite 同源代理，浏览器无需跨域 Cookie；原前端原型在 `/prototype`，其任务仍仅保存在 localStorage。
新 M1 的用户、快照、资料、运行和引用都来自后端数据库，不使用原型的 localStorage 存储。
Ctrl+C 停止启动脚本所创建的 API、worker、Vite。端口已占用时脚本拒绝启动，不结束不明进程。

也可分别运行（均在各自目录，前端端口必须与 ALLOWED_ORIGINS 一致）：

```sh
# backend
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8010
.venv/bin/python -m app.worker
# frontend
pnpm dev -- --host 127.0.0.1 --port 4180 --strictPort
```

本机系统 Python 受 Xcode license 限制时，使用已安装的捆绑 Python，不代用户接受许可：
`/Users/ac/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。
Node 同目录下 `dependencies/node/bin/node`；可设置 `M1_NODE` 指向需要的 Node。

## 数据、文档与备份

注册事务从 `data/scenario` 导入库存/批次/消耗，计算使用 Decimal；14 天缺日、旧快照返回不可估计。原始 data/synthetic 保留用于既有回归测试。旧项目执行 `.venv/bin/python -m app.cli publish-scenario` 发布新快照和文档版本，旧记录不覆盖。
数据基准是 `2026-09-27T09:00:00+08:00`，不是实时库存。库存来源行和快照 hash 保存于证据。
Markdown/纯文本摄入支持可复现 CLI，manifest 字段与现有 knowledge_manifest 一致：

```sh
.venv/bin/python -m app.cli ingest <project_id>
.venv/bin/python -m app.cli ingest <project_id> --manifest /absolute/path/manifest.json
```

同一版本/同一 hash 不重复导入；同版本不同 hash 拒绝覆盖。新文档需新 external_id/version、sha256、所属医院、生效时间与 synthetic 标记。
相对文档路径不能越出 manifest 目录；CLI只接收 md/txt，单文件最大 1 MB。CLI 是受信任的本地管理入口。V1.1在既有知识页增加文本预览/人工发布/停用，网页正文最多50,000字符、文件最多200KB；版本/项目/预览hash均由服务端验证，尚无PDF/Word解析或完整企业审批。
中文重叠双字词元 + BM25 评分；项目/有效版本先过滤再评分；重叠有效版本阻断检索；无命中明确不足。
引用保存不可变原文、document/version/chunk/chapter/offset/hash；历史失效引用可回查但标记失效。

SQLite 默认 `backend/var/spd.db`（忽略提交）。备份时先停止 API 与 worker，再复制整个 `backend/var` 目录；恢复到停机目录后执行迁移检查再启动。运行中的 WAL 数据库不要只复制主 db 文件。
worker 崩溃后租约 90 秒到期才可重新领取；最多 2 次。图节点边界保存应用级 checkpoint；不把 LangGraph 状态暴露给前端。
只读工具在一次事务中保存证据、事件、checkpoint；结果唯一约束为 run_id；fencing 拒绝旧 worker 写入。
取消立即禁止后续提交；已发出的外部模型请求可能等待 timeout 后结束，不能保证退还供应商 token 费用。

## DeepSeek 接入

在仅服务端的 `backend/.env` 中设置 `LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`，按账号可见型号设置 `DEEPSEEK_MODEL`（当前默认 deepseek-flash），重启 API 与 worker。
不要使用 `VITE_*` 保存 key。真实 provider 缺 key、429、网络超时、空/截断 JSON、引用越界均为 failed，不自动回退 mock 或其他供应商。
服务配置已就绪不代表模型质量通过；需要用户提供 key 后核实 `/models` 与实际工具调用、JSON 输出、中文回答、语义引用、usage、时延和费用。
本地 HTTP 模拟传输只验证 adapter 协议，不算真实 DeepSeek 测试。M1 无 rules_only 自动降级；保留其结果枚举供后续显式实现。

依据：[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)、[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。非思考模式；普通接口工具 Schema + 服务端 Pydantic 校验，不宣称 strict beta 已通过。

## PostgreSQL 与 Embedding

有 Docker 时可自行准备本地 PostgreSQL：设置本地 `POSTGRES_PASSWORD` 后运行 `docker compose -f compose.postgres.yml up -d`，将 DATABASE_URL 改为 `postgresql+psycopg://spd:<password>@127.0.0.1:5432/spd`，执行 Alembic 迁移。此配置未在当前机器启动，不能视为验收通过。
SQLite 数据不会自动迁入 PostgreSQL；更换配置后是新库，重新创建演示账号或另行编写有验证的数据迁移。
`optional/pgvector.sql` 是独立 opt-in DDL，需安装 pgvector 的 PostgreSQL 管理员执行；普通 postgres 镜像不自带该扩展。迁移执行与回滚前先备份。Embedding 协议在 `app/providers.py`，尚无实现和密钥；1024 维列预留。M1 不产生向量、不提供向量检索、不下载本地模型。

## 验证与契约

```sh
# backend
.venv/bin/pytest -q --junitxml=../docs/verification/m1-backend-tests.xml
.venv/bin/alembic check
.venv/bin/python -m app.cli openapi ../docs/verification/m1-openapi.json
# frontend
pnpm types:api
pnpm check:api
pnpm typecheck
pnpm build
pnpm test:sites
```

接口基线见 `docs/verification/M1接口与测试基线.md`，类型生成见 `frontend/scripts/generate-m1-types.mjs`。
浏览器测试需 API+worker+Vite 都运行，见 `docs/verification/M1验收报告.md`。
Sites 构建入口保留，仅验证静态封装。M1 有 Python API 和持久数据库，不能把静态 dist 单独发布称为完整上线。


## M2 功能与运行

迁移 `m2001` 新建 task_drafts / personal_tasks，不重写旧快照、资料或分析。
使用原启动命令即可运行 M2，入口仍为 http://127.0.0.1:4180。
- 异常中心：以快照业务日为基准，扫描所有授权物资科室组合；7天覆盖/30天效期为本地核查阈值，不是已批准企业制度。
- 批次/14日消耗明细：库存详情或异常行进入；缺失数量返回 null，不补零。
- 核查结果：支持追问、生成待办草稿。最多12层会话、最近6轮文字上下文，追问绑定原范围和快照，事实需重新工具核查。
- 草稿确认：编辑标题、步骤、截止日期；确认时重查来源有效性和最新快照，旧依据拒绝确认。本人任务没有跨用户分派。
- 任务：待处理→处理中→已完成，完成结果必填；允许取消与重开，保留全部状态记录。任务完成不写库存或修改异常。
- M2 `MAX_TOOL_CALLS=8`，总45秒时限、20个图步骤保持；JSON格式至多一次模型纠正，严格验收失败仍为failed。不静默回退模板。
- 新库迁移与 PostgreSQL 离线SQL检查不代表真实 PostgreSQL 已验收。现有数据仍为 SQLite。

复核用 `.venv/bin/pytest -q --junitxml=../docs/verification/m2-backend-tests.xml`。
OpenAPI 生成文件仍沿用 `m1-openapi.json` 路径供现有前端脚本消费，文档内部版本现为 m2.2（M2.1 里程碑）；数据库迁移仍为 m2001。

## M2.1 质量与预算

- `options.focus= risk_scan` 要求真正扫描本次授权范围；默认 general 保持旧请求幂等哈希。RunView 返回 options，失败重试保留扫描意图。
- 执行扫描后，风险计数由确定性工具保存；模型计数不一致、未核实物资编码或内部字段表达最多纠正一次。与 JSON 纠错共用一次机会；失败仍为 failed，不回退模板。此检查不是逐句语义证明。
- `MAX_INPUT_CHARS=32000`：每次完整模型请求序列化后的字符上限，含工具和输出 Schema；不是 token 数。单个工具返回超过一半字符预算会明确失败。
- `MAX_RUN_TOKENS=32000`：供应商已返回 total_tokens 的累计停止阈值。调用前后检查，已发出的请求可能超限；缺失 usage 不能当作实际零消耗，也不是严格费用上限。
- 超过 3 个物资科室组合时批次/消耗先返回全范围摘要；缩小范围可读明细。缺日/null/质量原因保留，完整工具证据另存，摘要不声称含全部明细。
- 六场景真实评测脚本：在 backend 目录运行 `.venv/bin/python scripts/evaluate_m21.py --live --output ../docs/verification/m21-20260928`（output 为目录）。仅在明确允许向 DeepSeek 发送项目场景数据并消耗配额后运行。使用独立评测 SQLite，不写日常项目；每例 20000、总计 90000 已记录 tokens 为停止阈值，非硬费用上限。

本地验收及真实调用边界见 `../docs/verification/M2.1验收报告.md`。
