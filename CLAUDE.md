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
- **skills 路由 —— 命中即【必须调用】,不是「可以调用」**。开工前先加载入口触发器 `using-superpowers`,再按下表执行:

  | 阶段 | 触发场景 | **必须调用** |
  |---|---|---|
  | **入口** | **任何任务开始前** | **`using-superpowers`**(先过它,否则下表不会被想起) |
  | 立项/发散 | 需求不清、要发散方案 | `brainstorming` |
  | 立项 | 开新 Agent 项目 | `new-project-launch` |
  | 规划 | 造/设计/规划 Agent 主流程 | `agent-system-creator`(主持流程) |
  | 规划 | 定调、优先级、方案压测 | `grilling` |
  | 规划 | 写实施计划 / 执行计划 | `writing-plans` / `executing-plans` |
  | 隔离 | 需要隔离工作区(不影响当前分支) | `using-git-worktrees` |
  | 执行 | **写或改实现代码** | **`test-driven-development`** |
  | 执行 | 拆成多个独立任务并行 | `dispatching-parallel-agents` |
  | 执行 | 每任务派独立 subagent 落地 | `subagent-driven-development` |
  | 排查 | 遇 bug / 测试失败 / 行为异常 | `systematic-debugging` |
  | 收尾 | **声称"完成 / 修好 / 通过"** | **`verification-before-completion`** |
  | 收尾 | 请人评审我的代码 | `requesting-code-review` |
  | 收尾 | 收到评审意见、要落实(先验证再改) | `receiving-code-review` |
  | 收尾 | 分支收尾/合并/清理 | `finishing-a-development-branch` |
  | 门禁 | **阶段门验收 / gate 判定** | **`gate-review`**(卡门;结论=建议,终裁=业务方签核) |
  | 门禁 | **每次 commit / PR 前** | **`留痕-checks`** |
  | 工具/元 | 改 `settings.json` | `update-config` |
  | 工具/元 | 新建/修改 **skill 本身** | `writing-skills` |
  | 工具/元 | Kit 自身缺陷 | `kit-feedback` |

  > **新增 skill 时必须同做的三件事**(否则本条规约失效 —— 见 KD-9):
  > ① 在 `skills-router.md` 登记**何时用**;② 在**本表**补一行(插到对应阶段);③ 若要强制,补**触发或门禁**。
  > 三者缺一 → 校验脚本 `tools/check-skill-coverage.sh` 会**报错**(母体与派生项目 CI 均跑)。

  > ⚠️ **2026-09-11 教训(KD-9)**:本仓阶段3 全程 **Skill 调用仅 2 次**(同期 Bash 205 / Edit 146)—— **写码未走 TDD、阶段门未走 gate-review、提交未走 留痕-checks、完成声明未走 verification**。根因:本句原为「动手前查 skills **是否命中**」(笼统、无对应表、无"必须"措辞),且入口触发器 `using-superpowers` **未随 Kit 进入本仓/锚点**。**纪律靠"记得",结构靠"躲不掉"** —— 详见避坑库 §3 与 `docs/复盘/`。**本表即那处结构:命中不调用 = 违规。**

- **派子 Agent 时,必须把相关纪律写进任务描述** ⚠️ **2026-09-11 盲测实证**:派一个**上下文为空**的子 Agent 做「改实现 + 提交」,它 **Skill 调用 0 次、根本没读 `CLAUDE.md`**——但被 `commit-msg` 拦住后,自己去读 hook 源码、老实补了测试。
  → **子 Agent 拿不到你的锚点、不触发 SessionStart/Stop hook、不继承你的会话纪律;它只认仓库层的东西(hook 脚本 / CI / 代码注释)。**
  → 因此:**纪律写在锚点里 = 对"你自己"有效;写在 hook/CI 里 = 对"所有人(含子 Agent)"有效。** 派活时若不显式携带约束,**等于子 Agent 无纪律**。

- **门禁必须左移,不能只留"提交时"** ⚠️ **2026-09-11 业务方指出的设计缺陷**:`commit-msg` 是**滞后门** —— 对长任务意味着 ① 实现决策早已做完,事后补测试只是**改装**而非 TDD;② 任务中途结束/被打断 → **没有任何门触发过**;③ 等于"中间全白费"。
  → 补 **`PreToolUse(Edit|Write)` 的 `impl-guard.sh`**:要改实现文件、而工作区尚无测试改动 → **先问一句**(`permissionDecision=ask`,不硬拦,把决定权提前给人)。**门禁从"最后一次提交"左移到"动手那一刻"。**
- **节点收尾双自查(5 触发点:init / 定调压测门 / gate-review / 留痕-checks / 节点完成)** —— **两项都问,缺一不可**:
  1. **失败即补 case(B `05-模块-评估与测试:84`)**:**本轮有失败吗**(被测失败 / 评测门自身缺陷 / 环境坑 / 我方流程错误)?**有 → 当轮不算完成**,直到落盘:被测的失败 → `eval/cases/`(带 `regression.root_cause`,格式见其 README);**我方过程错误 → `docs/复盘/`**(模板见该目录)。
     > ⚠️ 2026-09-10 教训:这条纪律**原先只写在 `eval/README.md`,不在本锚点里**,于是整个阶段3 **一次未执行**(17 条错误散落 5 处)。**纪律不在每会话必读的文件里 = 等于没有。**
  2. **母体 Kit 缺陷(本仓=试金石)**:本轮暴露母体 Kit 缺陷吗?是→**提请回写母体** `product-agent-dev-os/docs/kit-缺陷登记.md`(证据+最小修复建议)。**本仓不留登记表**;修母体先经业务方审批后回流。
- 技术/合规/业务表述只准引用事实源(`需求基线.md` + B);AI 不凭空写。
- **横切原则当红线**(B `03-横切设计原则/`):安全合规(数据分级/注入/人在环中/审计)、成本与 ROI(分层/熔断)、多 Agent 协作与人机协同、信任进化与隔离(提示即代码/可解释/灾备/租户隔离)。每节点 spec 须对照自检。
- **评估门**:改 Prompt/工具/记忆/评估集 → 必跑 eval 回归,低于阈值阻断发布(`eval/阈值.md`);指标挂 L1/L2/L3 + 北极星。
- 钱/合规/对外发布/上线由人确认;发布走 PR→CI(含 eval-gate)→tag。
- 代码 git + GitHub 留痕:issue→branch→PR(`Closes #<id>`)→CI 绿→review→merge。
- **避坑库(跨项目 · 给 Agent 读)**:`~/Desktop/知识库/18.Agent避坑库-问题解决策略/`
  —— 过程问题的**解决策略**集中于此。核心原则:**纪律不在每会话必读的文件里 = 等于没有;纪律没有触发点 = 早晚会漏** → 落地用**三层结构:锚点(看得见)→ hook(提醒)→ CI(躲不掉)**。
  **踩坑后照其 §6 体例追加一篇,勿只写在聊天/commit 里**。本仓已挂指针;`.claude/hooks/kb-drift-sentinel.sh`(SessionStart)在库变动时提醒;库路径可用 `KB_AVOID_PITFALLS_DIR` 覆盖(跨机器时用)。

## 目录(Agent 程序壳)
```
README.md · 需求基线.md · 总纲.md · ROADMAP.md · CLAUDE.md   # 对外说明(API 文档)+ 事实源/架构/执行图/接续锚
docs/RUNBOOK.md · docs/部署.md · docs/decisions/ · docs/复盘/ · docs/specs/   # 流程(指 B)+ 部署配置 + 决策 + 过程错误复盘 + 节点设计
contracts/ · templates/                              # 契约(工具/MCP/消息协议)与 spec 模板
eval/ · eval/cases/ · observability/ · 飞轮/          # 评估门 / **失败回灌用例库** / 观测 / 数据飞轮
app/ .claude/skills/ .github/(CI-CD) tests/          # 实现层
```

## 当前指针(随推进更新 — 上次更新 2026-09-11)
- `分支 | 阶段X-步骤Y | 模块 | L3基线 | 北极星`:`main | 阶段3 ✅ 收口(业务方判 PASS,D-11)→ 阶段4-步骤8(未开工)| E1–E9 已实现 | L2 任务完成率 ≥0.80(基线 0.85–0.925) | 劣化被拦次数 = 1`
- **门禁自腐 F1/F2 已修(2026-09-11,`7110809`)** —— 见 `docs/复盘/2026-09-11-门禁自腐与盲测2.md`:
  - **F1** ✅(曾严重):测试用假 session_id 跑真 `skill-trace.sh` → 覆写 `.claude/traces/latest.json` 为 `skill_calls:0`,**跑一次 `pytest` 就毁掉门 2 判定依据**。已加「定位不到本会话 transcript → 一个字都不写」守卫 + `SKILL_TRACE_DIR` 可注入;回归测试**突变验证**过。
  - **F2** ✅:门禁测试与工作区状态耦合(正常 TDD 中必红)。已改为**临时仓库隔离**;脏/净工作区实测均 163 passed。
  - **仍未解决**:F3 长任务无断点保护(会话超上下文上限即中断,关键结论随之丢失;`c549c42a` 实证)→ 候选 Kit 缺陷,观察态。
  > **交接背景**:上一会话 `c549c42a` 在 **1,017,378 tokens** 时 `API Error 400` 中断 —— **该会话不可 `--resume`**(会原样撞同一上限)。断点状态已从 transcript 抢救落盘(ROADMAP + 本指针 + `docs/复盘/`)。
  > **另**:`.claude/hooks/` 下的门禁脚本**不在门 1/门 2 的覆盖范围**(两道门只认 `app|backend|src`)—— 改门禁脚本不会被任何门检查,需人工留意。
- **门禁硬化已落地(2026-09-11 凌晨,8 个 commit)**:skills 三层结构(锚点对应表 → hook 哨兵 → CI 检查)+ **门禁左移**(`impl-guard.sh`,PreToolUse ask)+ **门 1/门 2**(commit-msg:认实现先于测试 + 未调用 `test-driven-development` 即拒提交)。**盲测实证 2/2 复现**:两个空上下文子 Agent 均被门 1/门 2 拦下,并**主动调用 `test-driven-development` 回退重做**。策略沉淀在 `~/Desktop/知识库/18.Agent避坑库-问题解决策略/` 01·02(§4.9)·03。
- 进度:阶段1/2 **业务方逐条签核 D-1..D-9(2026-09-10)**;阶段3 P3-1 首跑 `app/eval_gate/` E1–E7 竖切 + fastapi-rag 适配器 + CI 示例,`pytest` 47 passed(离线零外网),good→exit0 / bad→exit1 被拦。真实被测:`01.FastAPI RAG Agent`(切 DeepSeek,commit `36aa291`)。
- **P3 收口顺序已签核(D-10a..D-10h,2026-09-10)** —— grilling 定调压测门通过后修订 D-9:顺序 = **R0 → R2a → R1 → R2b → R3 → R4**;R3 升级为 **R4 硬前置**;契约补丁三处。过程数据 `notes/grilling/P3-1优先级-2026-09-10.md`,签核 `docs/decisions/定调复核-签核记录.md`。
- **阶段门纪律**:gate-review 出建议、终裁 = 业务方签核(本指针/节点 ✔ 均以此为准,不再自评 PASS)。
- **进度(2026-09-10)**:R0 ✅、R2a ✅、R1a ✅、R3 ✅、**R1b 活链路冒烟 ✅(本轮)**。`pytest` 76 passed / 2 skipped(离线)。
- **R1b 结果**:真实被测 + 真实 `deepseek-chat` judge,**34/40 通过(0.85)、exit 1**;失败 6 条**全部归因被测侧**(5 拒答 + 1 计数错误);**拒答 10/10、红队/越权 3/3 全过**。
- **被测运行方式(关键,零改动)**:被测仓库 **`36aa291` 未改一行**;本机 `python3.10` venv `/tmp/sut-lite-venv` + 启动器 `/tmp/sut_run.py`(前置 `/tmp/sut-shim` 假模块 `gradio`/`cost_dashboard`/`api_v1_agent`,并把 langchain 1.x 迁走的 legacy agent API 从 `langchain_classic` 补回)。**不设 `DOCKER_ENV`** → 自动连 localhost 的 postgres/redis 容器。
- **踩过的坑(已修,记在 `.env` / `.env.example`)**:① 被测 `localhost` 会解析到 IPv6 打到 Docker 的崩溃容器 → 改 **`127.0.0.1`**;② 本机 TLS 拦截,venv 默认 CA 不含其 CA → 设 **`SSL_CERT_FILE=/etc/ssl/cert.pem`**(备选:certifi 的 cacert.pem);③ pip 装 `cryptography` 需 `--prefer-binary`(Intel Mac 无 arm64 wheel 会退化成源码编译,而本机无 Rust)。
- **进度(2026-09-10 续)**:**R2b 已标定**(`eval/阈值.md` + `总纲.md` §4 全填真实值;北极星基线 = **1**,由劣化演示取得 —— 改被测拒答指令 → 红队突破 2 → 被 `redteam_zero`+`l2` 拦下,被测已还原)。**首次 exit 0**:复跑 37/40(0.925)。
- **下一步(阶段4-步骤8:模块测试/压测/红队)**:① `eval/README.md:24` 的 **N 次 A/B + p-value**(当前阈值只能判大退化);② 覆盖率达标 + 端到端/回放;③ 压测出 **L1 基线**(QPS/P99/错误率)。起点见 B `04-阶段4-测试验证-v1.0.md`。
- **R2b 遗留已清**:① ~~阈值未接线~~ → ✅ 已修(机读 `eval/阈值.json` + `default_thresholds()` 优先读,**缺配置回落更严兜底**,契约测试守住);② 基线单轮波动 **7.5pp**(0.85/0.90/0.925),`eval/README.md:24` 的 N 次 A/B + p-value **仍未做** → 阈值只能作 v1 粗门(不阻塞 R4,但判不了微小退化)。
- **R4 前收口的两条(本轮补完)**:**#3 重试退避** ✅(`E_SUT_TIMEOUT`/`5XX`→指数退避≤2、`429`→限速退避、其余 4xx→fail-fast;judge 超时重试 1 次;参数按 R1b 实测延迟定 1s 基数)/ **#7 P3-2 存储策略** ✅(`docs/specs/P3-2-存储策略.md`:逐项判「落地/不适用」并给依据)。**B 阶段3 门禁 7 条现已全部可判**。
- **环境备查**:被测本地运行需 `/tmp/sut-run` 脚手架 + `/tmp/sut-lite-venv`;`rag-api` 容器已被停(它崩溃重启 304 次且抢 8000 端口),恢复命令 `docker start rag-api`。
- **模型名(2026-09-10 迁移)**:DeepSeek 官方 **2026-07-24 起停用 `deepseek-chat` / `deepseek-reasoner`**,现行为 **`deepseek-v4-flash` / `deepseek-v4-pro`**。本仓 `.env`(`EVAL_JUDGE_MODEL`)与**被测 `.env`**(`LLM_MODEL_FAST`/`LLM_MODEL_CHAT`)均已迁到 `deepseek-v4-flash` 并实测通过。⚠️ 该网关**不校验模型名**(任意名都返 200),故「能调通」不代表名字有效 —— 以官方文档为准。
- **待业务方在 R2b 复核**:idx26「Python 适合哪些人学习?」标准答案含「文档未明确说明」,是半拒答;以及 id12/14 类「golden 期望超出语料本身」的条目是否保留。
- **挂起项**:被测知识库有无文档(R1 开头探针自证);母体 Kit 缺陷观察项(证据 1/2,停观察态,不落本仓表)。
