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
- 动手前查 skills 是否命中:**agent-system-creator**(造 Agent 主流程,触发优先)主持;superpowers=编码/测试引擎;gate-review / 留痕-checks 卡门;**kit-feedback**(Kit 缺陷反馈)(路由见 Kit `skills-router.md`)。
- **Kit 缺陷反馈(本仓=母体试金石)**:5 触发点(init / 定调压测门 / gate-review / 留痕-checks / 节点完成)末尾自查「本轮暴露母体 Kit 缺陷吗?是→**提请回写母体** product-agent-dev-os `docs/kit-缺陷登记.md`(证据+最小修复建议)」。**本仓/派生项目不留登记表**(记录统一存母体 .git+GitHub);修母体先经业务方审批后回流。
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

## 当前指针(随推进更新 — 上次更新 2026-09-10)
- `分支 | 阶段X-步骤Y | 模块 | L3基线 | 北极星`:main | 阶段3-步骤6 | E1–E9 已签核(E1–E6 竖切离线自证✔) | <首样本定:37golden → R2b 标定> | 劣化被拦次数(D-1)
- 进度:阶段1/2 **业务方逐条签核 D-1..D-9(2026-09-10)**;阶段3 P3-1 首跑 `app/eval_gate/` E1–E7 竖切 + fastapi-rag 适配器 + CI 示例,`pytest` 47 passed(离线零外网),good→exit0 / bad→exit1 被拦。真实被测:`01.FastAPI RAG Agent`(切 DeepSeek,commit `36aa291`)。
- **P3 收口顺序已签核(D-10a..D-10h,2026-09-10)** —— grilling 定调压测门通过后修订 D-9:顺序 = **R0 → R2a → R1 → R2b → R3 → R4**;R3 升级为 **R4 硬前置**;契约补丁三处。过程数据 `notes/grilling/P3-1优先级-2026-09-10.md`,签核 `docs/decisions/定调复核-签核记录.md`。
- **阶段门纪律**:gate-review 出建议、终裁 = 业务方签核(本指针/节点 ✔ 均以此为准,不再自评 PASS)。
- **进度(2026-09-10)**:R0 ✅、R2a ✅、R1a ✅、R3 ✅、**R1b 活链路冒烟 ✅(本轮)**。`pytest` 76 passed / 2 skipped(离线)。
- **R1b 结果**:真实被测 + 真实 `deepseek-chat` judge,**34/40 通过(0.85)、exit 1**;失败 6 条**全部归因被测侧**(5 拒答 + 1 计数错误);**拒答 10/10、红队/越权 3/3 全过**。
- **被测运行方式(关键,零改动)**:被测仓库 **`36aa291` 未改一行**;本机 `python3.10` venv `/tmp/sut-lite-venv` + 启动器 `/tmp/sut_run.py`(前置 `/tmp/sut-shim` 假模块 `gradio`/`cost_dashboard`/`api_v1_agent`,并把 langchain 1.x 迁走的 legacy agent API 从 `langchain_classic` 补回)。**不设 `DOCKER_ENV`** → 自动连 localhost 的 postgres/redis 容器。
- **踩过的坑(已修,记在 `.env` / `.env.example`)**:① 被测 `localhost` 会解析到 IPv6 打到 Docker 的崩溃容器 → 改 **`127.0.0.1`**;② 本机 TLS 拦截,venv 默认 CA 不含其 CA → 设 **`SSL_CERT_FILE=/etc/ssl/cert.pem`**(备选:certifi 的 cacert.pem);③ pip 装 `cryptography` 需 `--prefer-binary`(Intel Mac 无 arm64 wheel 会退化成源码编译,而本机无 Rust)。
- **下一步**:**R2b 标定阈值**(北极星/L1/L2/L3 → 回填 `eval/阈值.md` 与 `总纲.md` §4)→ **R4 阶段3 门禁验收(业务方判 PASS)**。
- **待业务方在 R2b 复核**:idx26「Python 适合哪些人学习?」标准答案含「文档未明确说明」,是半拒答;以及 id12/14 类「golden 期望超出语料本身」的条目是否保留。
- **挂起项**:被测知识库有无文档(R1 开头探针自证);母体 Kit 缺陷观察项(证据 1/2,停观察态,不落本仓表)。
