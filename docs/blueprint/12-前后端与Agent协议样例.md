# 12 · 前后端与 Agent 协议样例

契约版本：`0.1-review`。这是三条开发线共同评审的接口说明与样例，尚无对应可调用服务。第 06 份文档规定对象和事务，本文件细化 Agent 主路径。冻结后转换为唯一的 OpenAPI/JSON Schema 基线。

## 1. 唯一边界

FE → `/api/v1` 项目 API → 应用服务/队列 → Agent worker → 受控业务工具/检索/模型。FE 不直连 LLM，不接收 LangGraph 原始 checkpoint，不发送角色权限或任意恢复 Command。

HTTP DTO 与内部 tool DTO 分开；应用服务负责映射，字段语义由同一契约定义。接口由 BE 发布、AI 定义运行内容、FE 确认可展示、QA 提供反例，TL 负责基线。

## 2. 发起运行

`POST /api/v1/projects/{project_id}/runs`

认证：服务端会话 + CSRF。Header：`Idempotency-Key` 必需。返回 `202 Accepted`。

| 字段 | 类型/必填 | 约束 |
|---|---|---|
| schema_version | string / 是 | 固定 `1`，指消息形状；不是 HTTP 路径版本 |
| mode | enum / 是 | analyze / follow_up / draft_action |
| question | string / 条件必填 | analyze/follow_up：1–2,000 字；draft_action 可为 null |
| session_id | string 或 null / 是 | null 建新会话；已有会话必须同项目且有权限 |
| parent_run_id | string 或 null / 是 | follow_up/draft_action 必填并可访问；analyze 为 null |
| context.snapshot_set_id | string 或 null / 是 | null 由服务器解析当前已发布版本并固定；不能无版本混算 |
| context.item_ids | string[] / 是 | 空数组代表明确许可范围内的筛选；最大 50；编码均需同项目 |
| context.department_ids | string[] / 是 | 空数组采用当前授权范围；不是全企业 |
| context.analysis_id | string 或 null / 是 | draft_action 必填且与 parent_run 对应 |
| options.window_days | integer / 是 | 首版仅 14；不支持的时间窗返回校验错误 |

不接受 `org_id`、`role`、`model`、`base_url`、`raw_sql` 或客户端 approval_token。数据范围从 URL+身份计算；模型与预算从已发布服务端配置读取。

```json
{
  "schema_version": "1",
  "mode": "analyze",
  "question": "核查生化清洗液的供应风险，并说明依据",
  "session_id": null,
  "parent_run_id": null,
  "context": {
    "snapshot_set_id": "snapshot_demo_01",
    "item_ids": ["SIM-P001"],
    "department_ids": ["SIM-HA-LAB"],
    "analysis_id": null
  },
  "options": {"window_days": 14}
}
```

```json
{
  "schema_version": "1",
  "run_id": "run_demo_01",
  "session_id": "session_demo_01",
  "status": "queued",
  "revision": 1,
  "snapshot_set_id": "snapshot_demo_01",
  "as_of": "2026-09-27T09:00:00+08:00",
  "trace_id": "trace_demo_01"
}
```

这里的 ID 只是独立协议示例，不宣称已存在于数据库。相同 key+相同请求返回同一 run；相同 key+不同请求返回 409。

## 3. 状态和事件

`GET /runs/{run_id}` 返回 run_id、status、revision、mode、snapshot_set_id、as_of、current_step、analysis_id、draft_id、task_id、error 和 updated_at；未产生的资源 ID 明确为 null。

状态：queued → running → needs_input / awaiting_review / succeeded / degraded / failed / cancelled。needs_input 和 awaiting_review 可经合法动作恢复 running；已终止状态不可用普通 PATCH 改回运行，重试创建关联的新 run。degraded 代表有可用规则结果但 AI 未完整成功。

`GET /runs/{run_id}/events?after={cursor}&limit=50` 返回 `items、next_cursor、has_more、run_status`。cursor 在同一 run 内严格递增，用字符串表示；初始为 `0`。返回持久化的业务事件，断网恢复从最后确认 cursor 继续。首版前台约 1 秒轮询、退后台 5 秒；终态停止，限流退避。

```json
{
  "schema_version": "1",
  "run_id": "run_demo_01",
  "cursor": "4",
  "type": "step_completed",
  "step": "query_inventory",
  "occurred_at": "2026-09-27T09:01:02+08:00",
  "payload": {
    "message": "已读取 1 项物资的库存和批次",
    "completed_items": 1,
    "total_items": 1,
    "evidence_ids": ["ev_inventory_01"]
  }
}
```

| type | payload 必需字段 | FE 动作 |
|---|---|---|
| run_started | mode、snapshot_set_id | 展示真实运行状态 |
| step_started / step_completed | message、evidence_ids；数量可为 null | 更新步骤，未知数量不显示伪百分比 |
| clarification_required | interruption_id、revision、question、options | 渲染候选/输入，不使用模型 HTML |
| analysis_ready | analysis_id、generation_mode | 取结果详情；不是直接渲染 token 流为最终结论 |
| draft_ready | draft_id、draft_revision | 展示审阅入口 |
| approval_pending | approval_id | 禁止显示“任务已建立” |
| task_created | approval_id、task_id | 显示建立成功和任务入口 |
| run_finished | status、error 或 null | 停止轮询；显示结果/降级/失败/取消 |

未知事件先记录并刷新 run 摘要，不能页面崩溃或推断成功。未来 SSE 如启用，只改变传输，复用此 envelope、cursor 和鉴权；当前不要求 FE 对接供应商流式格式。

## 4. 分析结果和证据

`GET /analyses/{id}` 返回第 04 份文档的分析结构，再补 server-owned 的 project_id、snapshot_set_id、as_of、ruleset_version、knowledge_release_id、model_release_id、metrics 和 evidence_summary。

数量/金额/小数指标在 API 中为 decimal string，例如 `{metric_id:"metric_coverage_6d", value:"6", unit:"day"}`；不可估计值为 null，并有 reason。0 不能代替 unknown。FE 格式化显示但不重算业务结论。

`GET /evidence/{id}` 返回 source_kind（tool/document）、source_version、title、location、excerpt、hash、as_of 及必要的结构化事实。文档位置为 chapter/page/offset；工具位置为 import/row/batch。没有权限时不能返回标题片段。历史引用失效仍可在有历史权限时查看并显示已撤销，不代表可用于新审批。

## 5. 澄清、草稿与批准

`POST /runs/{id}/answers`：`{interruption_id, expected_revision, answer:{selected_item_ids, text}}`；返回 202 当前 run_id。迟到或不匹配的 interruption 返回 409，跨项目答案无效。

`PATCH /drafts/{id}`：`{expected_revision, title, steps, assignee_id, due_at}`。步骤最多 8 项，每项最多 300 字；标题 1–80 字；assignee 必须是许可项目成员；截止时间带时区且不可早于提交时点。不能 PATCH 关联 finding/证据以替换批准对象。返回新 revision 和不可变草稿视图。

`POST /drafts/{id}/approvals`，Header Idempotency-Key：

```json
{
  "expected_revision": 3,
  "decision": "approve",
  "comment": "已核实负责人和执行范围"
}
```

decision=reject 时 comment 必填；approve 允许简短备注。批准返回 `{approval_id,status:"pending",task_id:null}` 和 HTTP 202；同步记录完成的拒绝返回 HTTP 200、status=rejected，不能排入建任务作业。

`GET /approvals/{id}` 的 status 为 pending / committed / conflicted / rejected。只有 committed 且有 task_id 才展示成功；冲突时返回冲突类型与可访问的新版本摘要，不提供绕过检查的“强制执行”接口。

## 6. BE 与 AI 的内部工具契约

```text
ToolContext（服务器生成）:
  run_id, actor_id, org_id, project_id, permission_version,
  snapshot_set_id, as_of, ruleset_version, knowledge_release_id, deadline

ToolResult[T]:
  schema_version, tool_call_id, status(ok/partial/error), data:T|null,
  evidence_ids, source_versions, complete:boolean, warnings[], error|null
```

get_inventory/get_batches/get_open_orders/compute_risks 只接受已解析 item_ids 和限定参数，不能接受自然语言 SQL。AI 模块验证模型参数后调用 BE 服务，BE 再检查上下文与范围；模型不能构造 ToolContext。

工具错误不要伪装空列表：成功查到 0 个订单为 ok+empty；数据库超时为 error+TIMEOUT；部分查到为 partial+complete=false。FE 是否展示“没有在途”必须基于这个区别。

## 7. 错误与协作验收

| HTTP / code | 语义 | FE/AI 行为 |
|---|---|---|
| 401 / UNAUTHENTICATED | 会话失效 | 要求登录，不继续重试写入 |
| 403 / FORBIDDEN | 对已知范围动作无权限 | 停止；资源存在性敏感时统一 404 |
| 404 / NOT_FOUND | 不存在或不可见资源 | 不展示缓存的旧私有数据 |
| 409 / REVISION_CONFLICT、EVIDENCE_CHANGED、IDEMPOTENCY_CONFLICT | 版本/证据/请求键冲突 | 重新读取并审阅；不能自动批准新版本 |
| 422 / VALIDATION_ERROR | 字段/模式/业务约束不满足 | 定位字段，不丢掉输入 |
| 429 / RATE_LIMITED | 运行配额/请求过多 | 按 Retry-After 退避 |
| 503 / DEPENDENCY_UNAVAILABLE | 接收请求所需依赖不可用 | 不宣称已排队；保留原键查询/重试 |

接受运行后发生的模型错误体现在 run/event 中，不能把旧 POST 的 HTTP 202 改成失败。数据缺失通常产生质量结果，不一律抛 HTTP 500。

联调共同验收：同一套请求样例能驱动 mock 和真服务；FE 能完整显示所有状态；AI 不泄漏原始供应商字段；BE 能正确区分空结果和工具失败；QA 能制造冲突/断网/重试且观察到唯一任务。未通过这些项不能称“接口已同步”。
