# GitHub 规范 · 分支与 Commit

> 复用通用工程壳规范;Agent Kit 补注:**提示词(Prompt)/评估集与代码同库版本管理**——可回滚、可 diff(引 B `03-横切设计原则/03-原则-信任进化与隔离-v1.0.md` §一"提示即代码";B `06-持续优化策略/06-优化-版本迭代与发布策略-v1.0.md` §2.1"模型与 Prompt 版本、评估数据集、代码同库管理、可回滚")。凡改动提示词/评估集/模型路由配置,必须与本代码库一起提交,禁止散落在仓库外。

## 分支模型(单人简化版)
- `main`:始终可发布。禁止直接 push,只走 PR merge。
- 开发分支:`feat/<issue#>-<slug>`、`fix/<issue#>-<slug>`、`chore/…`、`docs/…`。
- 命名用 kebab;尽量一个分支一个 issue(留痕可溯)。分支名带 issue 号以便监控事件回链(见 `docs/留痕×指标挂钩.md`)。

## Commit(Conventional Commits)
```
<type>(<scope>): <描述>

type: feat / fix / docs / refactor / test / chore / perf / ci
scope(可选): 模块/组件。Agent 项目 scope 可用 B 14 模块名或其 label 短名:
  如 (task)、(context)、(memory)、(rag)、(router)、(subagent)、(sandbox)、(selfheal)、(时序)、(tool-mcp)、(observability)、(prompt)、(eval)、(monitor)。
```
- 一条 commit 一件事;可引用 issue:`… (refs #12)` 或 `fix #7`(合并后自动关 issue 用 `Closes #7`)。
- 写"为什么"必要时进 body,不写流水账。
- **同库版本纪律(Agent 特有)**:
  - 改 Prompt/评估集/模型版本 → commit 类型照常,但**必须与代码同一分支同一 commit/PR** 入库,并保证评估集版本号随代码可追溯(B `05-模块-评估与测试` §10.3"版本化一切")。
  - 契约(MCP Schema/OpenAPI)变更同样入库,别只在文档里改(契约测试靠它;引 B `02-方法论-工程纪律与CI-CD` §一)。

## PR 留痕
- PR 标题同 commit 风格;描述按 `pr-模板-评审.md`。
- merge 方式:默认 **Squash**(单人主线清晰);大 feature 可用 merge commit 保留历史。
- 合并后删分支;tag 与 changelog 在发布点打(见 `ci-cd-骨架/`)。tag 版本号 `vX.Y.Z`,语义化;发布必附《L1/L2/L3 对比表》(见 `docs/留痕×指标挂钩.md`)。

## 强制体检(提交/PR 前跑 Kit 的 留痕-checks)
- [ ] 无明文密钥/环境变量入库
- [ ] commit 信息规范 + 关联 issue
- [ ] CI 绿(lint/test/build;**含 eval-gate**——若本 PR 改 Prompt/工具/记忆策略)
- [ ] Prompt/评估集/模型版本是否入库且版本号可追溯
- [ ] 无 `.DS_Store`/`node_modules`/`__pycache__` 等误提交
- [ ] 契约(Schema/OpenAPI)变更已同步进 contracts/ 并被引用

---
*变更记录:M1 首版(2026-09-09)。复用旧 Kit 通用规范 + B 补注(提示即代码/评估集同库版本管理)。*
