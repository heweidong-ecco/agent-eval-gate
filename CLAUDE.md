# CLAUDE.md · agent-eval-gate 接续规约

> 新会话启动锚点。改占位即可用:`agent-eval-gate` / `/Users/heweidong/Desktop/Product/product-agent-dev-os/知识库-Agent-System` / 「当前指针」。
> 领域权威 = B 知识库(`知识库-Agent-System`,只增不改);本文件纪律引 Kit `README.md` 消歧(术语:memory/观测/MCP/CI 门 勿串义)。

## 项目
- 一句话:给其它 Agent 系统做「生产就绪评测门」:评估集 + LLM-as-Judge + 回放回归 + CI eval-gate。目标用户=跑 Agent/AI 应用的团队;解决他们『能不能上线、上线质量可不可量化』的痛点。。事实源 = `需求基线.md`(业务口径以它为准;B 阶段1 成果物落这里)。
- 完整流程 = `docs/RUNBOOK.md`(自本 Kit 拷入;指 B 6阶段×12步 + 14 模块)。
- B 知识库绝对路径:`/Users/heweidong/Desktop/Product/product-agent-dev-os/知识库-Agent-System`,如 `/Users/heweidong/Desktop/Product/product-agent-dev-os/知识库-Agent-System`(含 README 分层索引;阶段卡在 `04-分阶段工作流/`,模块在 `05-独立模块工作流/`)。

## 接续协议
1. 读本文件 → `ROADMAP.md`「当前指针」。
2. 当前指针格式:`分支 | 阶段X-步骤Y | 模块 | L3基线 | 北极星`。例:`main | 阶段1-步骤1 | 无 | 人工介入率 <40% | 工单自动解决率 ≥60%`。
3. 找到 ▶ 或下一 ⬜ 节点 → 读对应 spec(见 `templates/_spec.md`)→ 按 RUNBOOK(指 B 阶段卡)继续。
4. 每步骤/阶段完成:改 ROADMAP 状态 + commit(Conventional)+ 更新本文件指针。
5. 每选型进 `docs/decisions/DEC-*.md`;外部数据带来源、标"外部参考",不冒充。

## 纪律(精简;全量见 B 横切原则 + Kit README)
- 动手前查 skills 是否命中:**agent-system-creator**(造 Agent 主流程,触发优先)主持;superpowers=编码/测试引擎;gate-review / 留痕-checks 卡门(路由见 Kit `skills-router.md`)。
- 技术/合规/业务表述只准引用事实源(`需求基线.md` + B);AI 不凭空写。
- **横切原则当红线**(B `03-横切设计原则/`):安全合规(数据分级/注入/人在环中/审计)、成本与 ROI(分层/熔断)、多 Agent 协作与人机协同、信任进化与隔离(提示即代码/可解释/灾备/租户隔离)。每节点 spec 须对照自检。
- **评估门**:改 Prompt/工具/记忆/评估集 → 必跑 eval 回归,低于阈值阻断发布(`eval/阈值.md`);指标挂 L1/L2/L3 + 北极星。
- 钱/合规/对外发布/上线由人确认;发布走 PR→CI(含 eval-gate)→tag。
- 代码 git + GitHub 留痕:issue→branch→PR(`Closes #<id>`)→CI 绿→review→merge。

## 目录(Agent 程序壳)
```
需求基线.md · 总纲.md · ROADMAP.md · CLAUDE.md       # 排版层(事实源/架构/执行图/接续锚)
docs/RUNBOOK.md · docs/decisions/                    # 流程(指 B)+ 决策
contracts/ · templates/                              # 契约(工具/MCP/消息协议)与 spec 模板
eval/ · observability/ · 飞轮/                       # 评估门/观测/数据飞轮(Agent 特有)
app/ .claude/skills/ .github/(CI-CD) tests/          # 实现层
```

## 当前指针(随推进更新 — 上次更新 2026-09-09)
- `分支 | 阶段X-步骤Y | 模块 | L3基线 | 北极星`:main | 阶段3-步骤6 | E1–E6 竖切(离线自证✔,阶段3 未完) | <首样本定> | <首样本定>
- 进度:阶段1 ✔ · 阶段2 全节点(P2-1/2/3 + contracts + spec)✔;阶段3-步骤6 P3-1 首跑:`app/eval_gate/` E1–E7 竖切,`pytest` 42 passed(离线零外网);演示 good→exit0 / bad→exit1 被拦。真实被测已登记:`01.FastAPI RAG Agent`(chat 已 env 可配、切 DeepSeek,commit `36aa291`)。
- **⚠️ 待你确认**:`docs/decisions/决策确认清单-P1-P2.md`(C1 架构定位 / C2 命名 / A5 MVP 范围影响最大)。阶段门 PASS 由你验收,非自评。
- **下一步**:P3-1 收口(fastapi-rag 真适配 + 真 judge 冒烟 + 契约测试 + CI 示例);北极星/阈值用首样本标定。
