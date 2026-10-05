# V1.1 质量收尾实施报告

2026-10-04。实际作者、实现与自检：当前Codex；无独立QA或业务人员签收。执行依据为[质量收尾与试用验收计划](V1.1质量收尾与试用验收计划.md)。

本轮本地实现和工程回归已完成，原口语缺日问题已修复；扩大检索评测仍有1条作者保留查询漏召回，不能宣称严格质量验收全部通过。未执行新付费模型轮次，未进入业务试点或部署。

## 实际改动

1. 词法检索新增有限业务同义规范化，例如用量→消耗、没填/漏填→缺失、快到期→临期；规范化只用于评分，原正文、hash和引用offset不变。泛用措辞不再单独支撑未知主题；缺失/零消耗/临期做有限主题区分；多片段查询至少匹配两个片段。项目、停用、生效区间和版本冲突检查仍在评分前执行。版本为lexical-quality-2。
2. 从本轮问题识别明确的“不提供建议”或“只说日期”限制，在初始化、最终生成和一次纠正中重申。已知肯定动作建议或行动标题被拒绝，局部否定说明保留；持续违例报ANSWER_SCOPE_VIOLATION且不保存成功分析。提示版本为v11-quality-2。此规则不能证明所有回答都遵守任意自然语言范围。
3. 新运行checkpoint保存最终生成的content和attempt，保留纠正前错误与成功/失败尝试；不保存供应商推理字段。新成功分析的开放审计字典记录检索版本。没有响应的超时不伪造原文，预算仍只阻止追加请求，不能限制在途费用。
4. 新增独立离线脚本、冻结数据集与15项有针对性的工程回归。HTTP/工具Schema和数据库结构不变，无迁移，无新菜单。

## 实测结果

证据位于[v11-quality-close-20261004](v11-quality-close-20261004/)。

| 检查 | 结果 | 证据与含义 |
|---|---|---|
| 后端完整回归 | 200 passed | backend-tests.xml/txt；临时库与mock/受控provider，无真实模型准确率含义 |
| 前端 | 组件20项、包装4项通过 | frontend-tests.txt、sites-tests.txt；合计24项 |
| TypeScript、OpenAPI类型检查 | 通过 | typecheck.txt、api-types.txt；成功输出可为空 |
| 生产构建、Sites包装 | 通过，未发布 | build.txt、sites-build.txt |
| 原v11-dev-1挑战集重跑 | 校验11/11，检索7/7 | original-challenge-rerun.json；原6/7报告未覆盖 |
| 新输出校验集 | 16/16 | after-all.json；修复前14/16 |
| 新开发检索集 | 32/32 | 修复前23/32，修复后目标资料Recall@3与首位命中均24/24；8条应无命中均无命中 |
| 作者保留检索集 | 9/10 | 目标资料8/9命中，一条应无命中正确；非独立业务盲测 |
| 定向浏览器 | 5项通过，页面JS异常0 | browser-focused-results.json；风险分级3/5、反馈校验/故障重试、口语检索、原文读取、390px无整页横向溢出 |
| 日常库只读数量核对 | 与10月1日相同 | daily-db-readonly-counts.json：9快照、110资料、20分析、145证据、25运行、1任务；数量核对不是全行hash证明 |
| 版本冻结 | 167份源码、数据与依赖文件hash | manifest.json；代码、提示、检索、知识及数据集可定位，无Git提交/部署声明 |

新开发集应无命中查询的误召回从6条降到0，非目标资料返回从30次降到0。这只适用于作者构造的11份小语料，不能外推整个场景库或生产检索精度。实际场景口语查询首位命中缺日制度，后续仍可能返回包装单位等不直接支持该问题的片段；不能把所有检索片段自动视为答案依据。

新增工程测试包括：真实场景口语召回与引用定位、明确限定回答、否定与肯定混合句、父快照/历史正文保真、一次纠正/持续失败、纠正用量计入预算、原始最终输出保留、确认前无任务。原有全套回归继续覆盖超时、权限、跨项目、任务与异常分离、发布/停用及历史引用。

## 已知失败与浏览器边界

作者保留查询Q37“14日都是零记录”未命中零消耗资料；原失败保留在after-all.json。没有依据这一查询改代码再称保留集通过。开发32条加保留10条共41/42通过，因此全量离线脚本返回1，严格检索出口未完全满足。下一轮若修复此项，应将它转入已见回归样本并另设保留集。

定向浏览器使用本机Chromium、隔离SQLite库及受控provider，拦截新Agent运行POST；5项通过不能等同于全站本轮通过或真实手机验收。原文抽屉截图已等待动画结束，窄屏在关闭抽屉后检查。

重用的完整资料维护脚本未完整通过：首次依赖加载期间页面导航使风险定位超时；其后出现同文档多片段严格定位歧义、检索按钮定位超时和停用选择框虚拟列表选项超出视口。四次失败、部分成功步骤及截图均保留为browser-first/second/third/fourth-failure，不作为完整通过。该脚本需要重新稳定定位并完整复测，尚不能排除未覆盖的资料维护浏览器问题。已通过的定向脚本只覆盖本轮主要改动；资料维护确定性行为由完整后端回归覆盖。

定向脚本首次在原文尚未加载时立即断言而失败，记录browser-focused-first-failure已保留；增加等待后完成。早期后端回归199通过、1项旧提示版本断言失败，更新版本断言后200通过；首次报告保留为backend-first-failure。npm不在环境PATH，改用已安装Node直接执行项目脚本；未安装依赖或接受Xcode许可。

## 复现与交接

从项目根目录执行：

```sh
backend/.venv/bin/python -m pytest -q backend/tests
backend/.venv/bin/python backend/scripts/evaluate_quality_close.py --split dev --output /private/tmp/spd-quality-dev.json
backend/.venv/bin/python backend/scripts/evaluate_quality_close.py --split all --output /private/tmp/spd-quality-all.json
backend/.venv/bin/python backend/scripts/evaluate_v11_offline.py --output /private/tmp/spd-v11-original.json
```

第三条因Q37返回1，这是保留的质量失败。脚本不加载.env、不调用provider、不读取日常库；作者保留集现在已经曝光，不能用下一次同集复测冒充未知样本。

前端用可用Node运行typescript/bin/tsc --noEmit、scripts/generate-m1-types.mjs --check、两份node --test脚本、vite/bin/vite.js build及scripts/prepare-sites-build.mjs。浏览器复现需先用serve_v11_browser_fixture.py建立新临时库并启动8011，再启动本轮browser-vite.mjs的4181，执行browser-focused.mjs；脚本包含本机Chromium路径与隔离测试账号，不可直接针对日常端口执行。

日常数据库未写入，旧答案和评测报告未覆盖；独立测试已验证父分析逐值相等，本轮没有重做日常库六表全行hash。日常API/worker未重启切换，代码与隔离测试已是新版本，不能据此称日常运行实例已切到新提示。隔离服务在验收后关闭。

## 当前出口

A评测基线、B/C本地实现、D工程回归与冻结已交付，但扩大检索集及完整资料维护浏览器出口存在上述失败，不能标记严格A–D验收全绿。当前仍保持业务试点质量门槛。

后续先把Q37和完整资料维护浏览器脚本作为下一批本地收尾项，再决定真实模型复测版本。计划中的E付费复测未获新额度、未执行；F业务评审未邀请、未签收。真实模型语义、业务价值、PostgreSQL实连与生产部署仍未验证。
