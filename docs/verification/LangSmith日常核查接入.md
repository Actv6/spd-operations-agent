# LangSmith 日常核查接入

2026-10-04，用户“接入”授权网页核查的追踪上传。实现及自检：当前 Codex；未执行独立业务验收。此范围扩展为观测接入，不续跑已停止的真实模型质量评测，不修改库存交易或历史答案。

## 使用

项目已启用 LANGSMITH_TRACING=true 并重启本地服务。网页新发起的 DeepSeek 核查完成后，本地保存脱敏轨迹，由 worker 后台每15秒扫描上传。打开 https://smith.langchain.com，在 Tracing Projects 中找 spd-local-agent（以实际 LANGSMITH_PROJECT 为准）；第一次成功上传后项目才出现。根记录名称 AI核查，Metadata 的 app_run_id 对应网页核查ID，snapshot_id 对应事实快照，attempt_fence 区分重试。输入包含问题/范围，输出包含状态/答案，子记录包含真实请求消息、工具参数与结果、耗时、实际usage。没有返回usage时保持未知，不填造tokens。

不补录旧网页运行。之前手动评测仍在 spd-v11-live-d00fb556，接入受控测试在 spd-tracing-integration-test；后者明确标注 controlled_test/no-model-call，不代表真实 DeepSeek 验收。

## 契约与故障处理

HTTP、工具/事件契约和数据库Schema不变。新增服务端观测配置；业务计算、权限、交易与输出保护不变。worker 在真实 execute 路径收集显式轨迹，provider 输入为实际HTTP payload（不含认证header），不上传原始 reasoning。关闭开关、缺少LangSmith Key或mock模式不创建轨迹。

本地 outbox 默认 backend/var/langsmith，文件权限0600；上传状态和记录ID回执在每个文件中。固定ID回读验证成功后不再上传；网络错误/索引延迟由下一轮扫描重试。上传独立后台线程运行，不阻塞业务调用；保存/上传/收尾错误仅输出异常类，不改变核查结果。失败、取消和租约失效按数据库最终状态记录，错误只含代码。尚未完成云端记录不会声称上传成功。

上传当前生成业务场景中的提问、模型消息、工具资料与答案，按白名单排除账号、密钥、密码、Cookie、CSRF等字段，并遮蔽已配置密钥和邮箱文本。这不是通用企业数据脱敏系统；真实企业资料接入仍需单独处理。

## 验证

- 后端全量212项通过：langsmith-live-20261004/backend-tests.xml。
- 最终收尾异常隔离加固后，Agent及追踪专项再次运行，见 final-targeted-tests.xml。
- 网页API创建运行→实际worker→缺少provider配置失败→脱敏outbox，受控端到端测试通过；mock/关闭开关、磁盘故障、模型用量/工具异常记录、云端重试及幂等验证通过。
- 新模块受控云端检查：3条根/工具/失败模型记录回读验证通过，新增真实模型调用0。原始回执位于 cloud-smoke；仅受控集成证明，不是新真实模型质量复测。
- 新网页真实模型调用尚未由本次任务发起；用户之后的网页核查将生成日常追踪。旧P1质量问题未修复。

关闭方式：backend/.env 设置 LANGSMITH_TRACING=false 后重启worker。Key不进入前端。修改 LANGSMITH_PROJECT / ENDPOINT / WORKSPACE_ID 同样需要重启worker。

## 用户网页核查追踪与排版跟进

用户反馈后检查到日常项目 spd-local-agent 的实际核查已生成8条记录，截图打开的是旧评测项目。同时原补传逻辑在首个未索引记录后停止，导致后续子记录验证延迟。已改为每条独立补传，并用文件锁避免后台/手动上传并发覆盖回执。本次实际核查8/8条均回读验证通过；追加模型调用0。

前端只对明确的加粗业务标签建立小标题，并把已核实事实的分号段落显示为列表；保留答案原文、数字与建议序号。工作台组件21项、追踪6项测试及TypeScript检查通过。实际页面视觉效果需用户刷新查看；没有新模型质量通过声明。
