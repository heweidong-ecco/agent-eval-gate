# GitHub 规范 · Issue 模板与 Labels(Agent 化)

> 复用通用 labels;Agent Kit 增补:**14 模块 label**(支撑 issue ↔ B 模块留痕)+ 跨切 `eval`/`prompt` label(是否动评估集/提示词)。label 命名建议中文可读 + ASCII 别名(供 `gh` CLI/脚本用);模块 label 全列表对应 B `05-独立模块工作流/` 14 文件(映射见 `docs/RUNBOOK.md` §1.4)。

## Labels(初始化时用 gh/网页建)

### 基础(沿用通用工程壳)
| Label | 含义 |
|---|---|
| `epic` | 阶段/大主题(跨多个 feature;对应 B 某阶段) |
| `feature` | 一个功能/节点(对应 B 步骤产出) |
| `bug` | 缺陷 |
| `tech-debt` | 技术债 |
| `ci` | CI/CD/工具链 |
| `ai` | 涉及 LLM/Agent 能力(与"通用宿主"改动区分) |
| `p1/p2/p3` | 优先级 |
| `reviewed` | 已审(可选) |

### Agent 模块 label(14;ASCII 短名可选)
| Label(建议) | ASCII 别名(可选) | 对应 B 模块文件 |
|---|---|---|
| `module-任务管理` | `task` | `05-模块-任务管理-v1.0.md` |
| `module-上下文管理` | `context` | `05-模块-上下文管理-v1.0.md` |
| `module-记忆模块` | `memory` | `05-模块-记忆模块-v1.0.md` |
| `module-RAG检索` | `rag` | `05-模块-RAG检索增强-v1.0.md` |
| `module-Agent路由` | `router` | `05-模块-Agent路由-v1.0.md` |
| `module-子Agent编排` | `subagent` | `05-模块-子Agent与多Agent编排-v1.0.md` |
| `module-沙箱安全` | `sandbox` | `05-模块-沙箱与安全执行-v1.0.md` |
| `module-自愈` | `selfheal` | `05-模块-自愈策略-v1.0.md` |
| `module-时序控制` | `timing` | `05-模块-时序控制-v1.0.md` |
| `module-工具与MCP` | `tool-mcp` | `05-模块-工具注册与MCP-v1.0.md` |
| `module-追踪观测` | `observability` | `05-模块-全链路追踪与观测-v1.0.md` |
| `module-提示与模型路由` | `prompt-router` | `05-模块-提示工程与模型路由-v1.0.md` |
| `module-评估与测试` | `eval` | `05-模块-评估与测试-v1.0.md` |
| `module-监控告警` | `monitor` | `05-模块-监控告警与仪表盘-v1.0.md` |

### 跨切 status(可与模块 label 叠加)
| Label | 含义 |
|---|---|
| `prompt` | 本 issue/PR **改提示词/Prompt 模板**→ 必须跑评估回归 |
| `eval` | 本 issue/PR **改/补评估集或评估阈值**→ 触发 eval-gate |

> 说明:module label 表示"改的是哪个 B 模块";`prompt`/`eval` 表示"是否动了提示词/评估件",可叠加(例如改记忆模块且补了评估 case → `module-记忆模块` + `eval`)。模块 12/13 的别名 `prompt-router`/`eval` 是"该模块本身",与跨切 `prompt`/`eval` 含义不同;若嫌歧义,跨切可改 `x-prompt`/`x-eval`(待核:label 粒度由 Kit 首用项目定,`02-增删映射表.md` §4-4 仅要求含 14 模块 + eval/prompt)。

## Issue 模板(FEATURE)
```markdown
### 目标 / 用户价值
…
### 需求点(接受标准)
- [ ] …
### 所属 B 模块 / 依赖
- module label:…(14 模块之一或多个)
- 依赖 contracts、其它 issue
### 评估与证据字段(Agent 特有,必答)
- 是否改 Prompt / 工具 / 记忆策略?是 → 哪个、预期影响
- 是否需补/改评估集 case?阈值多少?(先定阈值再看结果——B 05-模块-评估与测试 §10.3)
- 验收挂哪层指标:L1 / L2 / L3 / 北极星?(见 docs/留痕×指标挂钩.md)
### 验收口径(ROADMAP 节点)
…(对应 ROADMAP 某行 / B 阶段门禁)
### 备注(数据/AI 适用性 DEC 等)
…
```

## Issue 模板(BUG)
```markdown
### 现象(可复现步骤)
1. …
### 期望 vs 实际
…
### 评估证据 / 观测(Agent 特有)
- 相关 trace_id / 日志片段(见 B 05-模块-全链路追踪与观测)
- 是否属评估集漏测?若是 → 失败即补 case(B 05-模块-评估与测试 §10.3)
- 复现时的模型/Prompt/工具版本(版本化留痕)
### 环境/提交
…(SHA、分支、日志)
### 影响与优先级
…(关联 issue/工单;L1/L2/L3 哪层受损)
```

## 生命周期
- 想法 → 建 epic/feature issue(label=模块+eval/prompt)→ 分支引用 `#<id>` → PR `Closes #<id>` → 合并自动关。
- 监控事件/用户反馈 → 转 issue(关联原功能 issue)→ 修复走同一闭环(B `04-阶段6-上线运营` 持续改进闭环)。
- 阶段复盘 → 新 issue(改进项),带 owner(=你)+ 截止。

---
*变更记录:M1 首版(2026-09-09)。旧 Kit 通用 labels + 14 模块 label + eval/prompt;feature/bug 模板补评估证据字段。*
