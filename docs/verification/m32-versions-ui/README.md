# M3.2 本地浏览器验收

2026-09-28，Codex IAB，桌面默认视口及390×844响应式检查；执行者Codex，非独立QA。

- versions-desktop.jpg：版本列表、完整业务日期、发布/校验摘要和比较入口。
- restore-preview.jpg：测试项目回退原因与人工勾选后的预览。
- restore-history.jpg：71f9797c→98b31c3f→71f9797c两条手动切换留痕。
- diff-desktop.jpg：与d54aa09a比较的24项档案变化，列出具体科室变更。
- versions-mobile.jpg、restore-mobile.jpg：窄屏选择器、列表和可滚动确认表单。
- database-check.json：迁移前后旧表记录逐行相同、m3201迁移与两条切换记录。

操作仅限M1浏览器测试项目 d185415d-2050-465e-b8d9-4b4cbe1fc9db；没有创建新快照或运行Agent，最终恢复原当前版本71f9797c。测试数据是既有场景资料，不代表真实公司生产记录。

开发过程中导航Icon字段拼写曾导致热更新错误，已修正并通过类型检查及页面实测；新抽屉已改用Ant Design size/mask配置消除新组件的弃用提示。旧组件历史日志不作为本次新增运行失败。
