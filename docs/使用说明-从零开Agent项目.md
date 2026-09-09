# 使用说明 · 用 product-agent-dev-os 从零开 & 跑一个 Agent 项目(完整步骤)

> 适用:一人全栈,用 Claude Code 造 Agent 系统/AI 应用。读完本文 = 知道"新项目从哪来、每天怎么推进、怎么留痕、怎么维护 Kit"。
> 依赖:本 Kit(M0~M2 完成)+ 用户级 skills 已装(superpowers、agent-system-creator、new-project-launch、gate-review、留痕-checks、grilling)。

---

## 〇、一句话模型
> **Kit(存规则/模板)→ 拷出"新项目"(存真实工作)→ 项目里 Claude 按 CLAUDE/ROADMAP/RUNBOOK 推进 → 全程 git/GitHub 留痕。** Kit 平时不改;新 Agent 项目用它拷贝生成。

---

## 一、开新项目(选 A 自动 / 选 B 手动)

### 方式 A · new-project-launch skill 自动(推荐)
1. 打开一个 **Claude Code 窗口**(在你想放项目的父目录,如 `~/Desktop/Product`)。
2. 触发:
   - 直接说:"启动一个新 Agent 项目,名字 `<kebab-name>`,一句话简介 `<…>`"
   - 或 `/new-project-launch`,再给 `<name>` 与简介。
3. skill 会:建 `<父目录>/<name>/` → 拷 `scaffold/agent/` → 填 CLAUDE/需求基线/ROADMAP 占位 → `git init` → (GitHub 通时)建 private 仓+labels+issue#1 → 提示下一步。
4. 完成后,进入该新项目文件夹继续(见第三节)。

### 方式 B · 手动(不依赖 skill,可离线)
```bash
cp -R /Users/heweidong/Desktop/Product/product-agent-dev-os/scaffold/agent/ ./<新项目名>/
cd <新项目名>
rm 初始化-runbook.md            # 一次性引导文件,拷完即删
# 按 初始化-runbook.md 曾写的内容做(等价):
#  1) 填占位:CLAUDE.md(项目名/简介)、需求基线.md、ROADMAP.md 当前指针
#  2) git init -b main; git add -A; git commit
#  3) GitHub private 仓 + push + labels + issue#1(网络通时)
```

### 建仓那步的网络/gh 说明
- 本地建项目、填占位、git init **完全离线可用**。
- GitHub 建仓 + push + labels 需 GitHub 可达 + gh 已装;gh 不可用 → 网页建仓后 `git remote add origin <url> && git push -u origin main`。

---

## 二、新项目里"改什么"(首次只改这 4 处)
| 文件 | 改 |
|---|---|
| `CLAUDE.md` | 项目名/一句话简介/事实源;当前指针(初始指向"阶段1 需求战略") |
| `需求基线.md` | 填:痛点基线(现场观察/埋点/访谈)、ROI 预判、数据分级、AI 可行性表(B 阶段1 卡) |
| `总纲.md` | 七层架构占位(接入/调度/执行/记忆/工具/数据/安全)+ 前端极简·Console·后端边界 + 14 模块注册表 + L1/L2/L3 指标表 + 横切原则 checklist |
| `ROADMAP.md` | 按 B 6阶段×12步 摊节点;指针写法:`分支|阶段X-步骤Y|模块:<名>|L3基线:<…>|北极星:<…>` |

`eval/`、`observability/`、`contracts/`、`templates/` 按 B 阶段2/4 边做边填。

---

## 三、日常推进(每个开发日/每个阶段)
1. **读指针**:Claude 启动自动读 项目`CLAUDE.md` → `ROADMAP.md` 当前指针 → 进入 B 对应 阶段/步骤/模块。
2. **按 RUNBOOK 走**:项目 `docs/RUNBOOK.md`(拷自 Kit)每阶段给 入口/产出/门;阶段卡详情引 `知识库-Agent-System/04-分阶段工作流/04-阶段X`(若没拷,回 Kit 看 `docs/RUNBOOK.md` + `知识库-Agent-System/`)。
3. **阶段1 用 agent-system-creator**:痛点→方案→ROI(触发 `agent-system-creator`,B 六阶段主持;superpowers 当它节点引擎)。
4. **每功能/模块 = 一个节点**:superpowers 流程(spec→plan→TDD→review);模块并行用 worktree+子代理。
5. **每天**:ROADMAP 上推进 1 个节点到"可测"→ commit。

---

## 四、留痕与发布(贯穿)
- issue 模板/labels / 分支 commit 规范 / PR 模板(附 评估集回归、是否改 Prompt·工具·记忆、观测证据、契约漂移)/ CI(eval-gate) → 见项目 `github/` 或 Kit `github/`。
- 发布点:tag + Release 必附《L1/L2/L3 对比表》;监控事件 → 关联回 issue → 复盘(B 阶段6/07)。
- 提交/PR 前可跑 `留痕-checks`;阶段门跑 `gate-review`。

---

## 五、Kit 自身维护(偶尔)
- 改 `知识库-Agent-System/` 某层 → 按 `docs/知识库同步映射.md` 同步到对应蒸馏件 → (如需)重打包 .skill。
- 改 Kit 结构/规则 → 先开 DEC(`docs/DEC-选型模板.md`),不静默改。
- 装/更新用户级 skills:`cp -R <kit>/skills/<名> ~/.claude/skills/`(本机已装,见 README)。

---

## 六、检查点 / 排查
- 新会话不认指针 → 读项目 CLAUDE/ROADMAP 顶部;确认在"项目文件夹"而非 Kit 里干活。
- skill 不触发 → 确认在 `~/.claude/skills/` 存在且 description 命中;重启会话。
- GitHub push 失败 → 网络/鉴权;`git remote -v` 核对 URL;等网络通重试。
- 不确定 B 某模块细节 → 回 `知识库-Agent-System/05-独立模块工作流/` 精读该模块;外部参考(07)落地前复核时效。

---
*文档版本 v1.0(2026-09-09)· 对应 Kit M0~M2 状态。*
