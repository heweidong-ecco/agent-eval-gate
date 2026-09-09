---
name: new-project-launch
description: 用 product-agent-dev-os Kit 启动一个新 Agent 项目——拷 scaffold/agent 到目标目录、按初始化-runbook 建仓(git init→GitHub private→labels→issue#1)、装 skills、填 CLAUDE/需求基线/ROADMAP 占位,产出可接续并直接开跑 B 阶段1 的项目锚。用户说"开新 Agent 项目/<名字>/启动一个 Agent 项目"时使用。
---

# new-project-launch · 启动一个新 Agent 项目

作用:把 product-agent-dev-os 的 `scaffold/agent/` 变成一个"在 GitHub、装好 skills、可立刻按 B 阶段1 跑"的新 Agent 项目。

## 前置
- 本 Kit 路径:`/Users/heweidong/Desktop/Product/product-agent-dev-os`(硬编码;若 Kit 已移动,问用户新路径)。
- 用户给定:新项目名 + 一句话简介(若无简介,先问清再动手——不编造简介)。

## 步骤(流程照 scaffold/agent/初始化-runbook.md)
1. 定目录:`<目标父目录>/<新项目名>`(默认 `~/Desktop/Product/<新项目名>`)。
2. 拷贝 scaffold:`cp -R /Users/heweidong/Desktop/Product/product-agent-dev-os/scaffold/agent/ <目录>/`。
3. 填占位:改 `CLAUDE.md`(`agent-eval-gate`/`/Users/heweidong/Desktop/Product/product-agent-dev-os/知识库-Agent-System` = `/Users/heweidong/Desktop/Product/product-agent-dev-os/知识库-Agent-System`/指针)、`需求基线.md`/`总纲.md`/`ROADMAP.md` 标题;补拷 `docs/`、`github/`(当 Kit M1 就绪,见 runbook)。
4. 装 skills:`mkdir -p .claude/skills`;把本 Kit `skills/agent-system-creator`(核心)、`gate-review`、`留痕-checks`、`new-project-launch` 拷入 `.claude/skills/`。
5. `git init -b main`;`git add -A && git commit -m "chore: <项目> 初始化(Agent scaffold)"`。
6. GitHub 私有仓:优先 `gh repo create <owner>/<name> --private --source . --remote origin --push`;gh 不可用时请用户在网页建好给 URL 再 add remote+push。
7. Labels:核心集 `gh label create epic feature bug p1 p2 p3 eval prompt --force` + B 14 模块标签(见 runbook;完整集以 Kit `github/issue-模板-labels.md` 为准)。
8. 建 issue#1(epic: B 阶段1 需求与战略),body 照 issue 模板。
9. 汇报:仓库 URL、issue#1、下一步 = 用 agent-system-creator 开跑 B 阶段1(读 `知识库-Agent-System/04-分阶段工作流/04-阶段1` → 填 `需求基线.md` 痛点基线)。

## 纪律
- 不编造项目简介;简介 = 用户原话/已确认要点。
- 新项目名用 kebab-case(仓库友好)。
- 产物留痕:建仓/issue 都回显,让用户可核对;完成后建议删项目内 `初始化-runbook.md`。
