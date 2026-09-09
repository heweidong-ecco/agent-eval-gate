---
name: 留痕-checks
description: 仓库留痕与卫生体检(提交/PR 前跑)——检查 commit 规范、issue 关联、CI 状态、是否有明文密钥/误提交文件,并体检"是否动了 Prompt/工具/记忆/评估集却没附 eval 回归"(eval-gate 提示)。用户在"提交前检查/留痕体检/CI 红了吗/仓库干净吗/改 Prompt 要附什么"等时使用。
---

# 留痕-checks · 仓库体检(提交/PR 前跑)

作用:保证"代码全程 git+GitHub 留痕"不被破坏:**规范、可溯、无泄漏、改 Agent 可回归**。

## 检查项(只读为主)
1. **未提交/未跟踪**:`git status`——有无 `.env`/密钥/`node_modules`/`__pycache__`/`.DS_Store` 等将被误提交的文件。
2. **commit 规范**:`git log --oneline -10` 是否 Conventional(`feat/fix/docs/… (scope)`);每条是否单件事。
3. **密钥扫描**:`git grep -nE "(sk-|ghp_|AKIA|password\s*=|BEGIN .*PRIVATE)"` 于应忽略的路径/文件;新加 `.env*` 不入库。
4. **CI 状态**:有 `gh` 时 `gh pr checks` / 查询最近 run;无则提示用户看 Actions。
5. **issue 关联**:当前/最近 commit 是否带 `#<id>` 或 PR 描述 `Closes #<id>`。
6. **误提交文件**:新增文件是否都在合理目录(git status 过一眼)。
7. **⭐ Agent 变更回归检查(新增)**:本次改动(commit 集 / PR diff)是否动了 **Prompt / 工具 Schema / 记忆策略 / 评估集** 之一?
   - 判定:diff 涉及 `prompts/`、`contracts/tools-mcp`、`总纲.md` 记忆策略、`eval/`、或"提示即代码"相关文件。
   - 若动了且**未附** eval 回归 → ⚠️ 阻断:提示按 `eval/README.md` 跑回归(对照 `eval/阈值.md`),并把结果/证据贴进 PR。
8. **⭐ eval-gate 提示**:PR/发布是否过 CI 里的 eval-gate(独立于代码门);发布/tag 是否附《评估报告 + L1/L2/L3 对比》(引 B 05-模块-评估与测试 / 06-优化-版本迭代)。CI 里若只有代码门没有评估门 → ⚠️ 提示补。

## 输出格式
```
留痕-checks
- commit 规范:OK/问题(示例)
- 密钥/敏感:OK/⚠️ <路径>
- 误提交候选:OK/⚠️ <路径>
- CI:绿 / 未查(gh 不可用)
- issue 关联:OK/缺(当前改动应引 #)
- Agent 变更回归:未动 / 动(Prompt|工具|记忆|评估集)→ 已附回归 / ⚠️ 缺回归
- eval-gate:CI 已含 / ⚠️ 未见(发布需附评估+L1/L2/L3 对比)
结论:可通过提交 / 先修 <…>
```

## 纪律
- 只读体检不擅自改;发现密钥/危险项/缺回归即提示并阻断,交由用户处理。
- gh 不可用时如实标"未自动查",不假装已绿。
- 「是否动 Prompt/工具/记忆/评估集」判不准时标 ⚠️ 存疑并问用户,不静默跳过。
