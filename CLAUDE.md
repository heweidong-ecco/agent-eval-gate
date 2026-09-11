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
  → **子 Agent 拿得到你的锚点(全文在它上下文里)但不会照做;也不触发 SessionStart/Stop hook、不继承会话纪律。真正有约束力的是仓库层的东西(hook 脚本 / CI / 代码注释)。**
    > ⚠️ **2026-09-11 盲测 5 更正**:本句原写「**拿不到**你的锚点」—— **错的**。只读探针让它逐字引用 CLAUDE.md,命中(它自述来自上下文顶部的 `# claudeMd` 区块)。**没读过 ≠ 没拿到。** 诊断反而更严峻:**锚点在也没用** —— 起作用的是 hook/CI/注入那一层。
  → 因此:**纪律写在锚点里 = 对"你自己"有效;写在 hook/CI 里 = 对"所有人(含子 Agent)"有效。** 派活时若不显式携带约束,**等于子 Agent 无纪律**。
  → ✅ **2026-09-11 已补结构兜底(不再只靠本条文字)**:`.claude/hooks/subagent-guard.sh`(SubagentStart)会把**最小纪律集直接注入子 Agent 上下文**——实测到达(`hook_additional_context`),且子 Agent **照第 6 条报告了格式**。只读型(Explore/Plan)不注入(防噪音)。**任务描述里仍必须写业务约束** —— 结构只兜**纪律**,兜不了**业务上下文**。
  → 让该机制**可证伪**:`tools/check_subagent_injection.py` 断言注入是否真到达;`skill-sentinel.sh`(Stop)在「派过子 Agent 却无一含签名」时出声。

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

## 当前指针(随推进更新 — 上次更新 2026-09-11(阶段4-步骤8 收口))
- `分支 | 阶段X-步骤Y | 模块 | L3基线 | 北极星`:`main | 阶段3 ✅(D-11)→ 阶段4-步骤8 ✅(乙未跑)→ 步骤9 | E1–E9 + 统计层/压测层 | L2 任务完成率 ≥0.80(基线 0.85–0.925) | 劣化被拦次数 = 1`
- **🎯 门的首次真实价值兑现(2026-09-11)**:真实链路评测抓到被测一个**隐蔽的生产缺陷** ——
  `query_rewriter.py` 的 `max_tokens=200` 对推理型模型偏小 → content 为空 → 空查询检索 → 一律回「无法回答」。
  **无任何语义特征**,只有外部独立门能抓到。被测已修(`85e456b`,已推 GitHub)。
  **共修两处**(`85e456b` 查询改写 / `f2dad78` BM25 缓存不失效),均已推 GitHub。
  **基线四轮**:0.75(未修)→ 0.85(修①)→ 0.90(修①② + 5 篇语料)→
  **0.975(39/40、红队突破 0、exit 0 ✅ 门首次通过;+3 篇语料)**。
  ⇒ 首轮 0.75 是缺陷伪影。预算实测 2.35–2.91 万/轮 ⇒ **按 3 万报备**。
  ⚠️ 唯一失败 id=19 是**判分器的稳定误判**(被测答对了),暴露 `judge_human_agreement` **未接线** ⇒ 见 ROADMAP 交接第 3 条。
- **✅ 阶段4-步骤8 已收口(2026-09-11)**:`docs/reports/P4-1/` **7 份报告 + 基准 JSON**;覆盖率 **94.44%**(CI 硬门 85%)、335 用例;门自身开销 **0.051 ms/case**;A/B 装置就绪(N≥20 分辨 5–10pp);红队四靶子**打穿 1 处已修**(孤立代理对)。选型 `DEC-003`;过程错误 7 条见 `docs/复盘/2026-09-11-P4-1-过程错误.md`。
- **🔜 下一步 = 阶段4-步骤9(`P4-2`:系统级全链路/量化)** —— **详见 ROADMAP「交接:下一步做什么」**(三件事:解「乙未跑」的环境阻断 / `ideal_tool_seq` 回放 / 真实 judge 的 A/B)。
- **✅ 两个严重问题已修(2026-09-11)** —— 详见 ROADMAP「本轮完成」与 `notes/blind-test/`:
  - **问题 A(skills 不触发 / KD-9)**:三个口子已堵 —— ①**可规避**改为检测留痕(豁免必须带理由 `[no-test: <理由>]`;`.githooks/post-commit` 绕过留痕,**不受 `--no-verify` 抑制**;CI 用 `tools/check_gate_bypass.py` **逐提交重算**);②拦截力复测(见下,未测到);③用量**修口径不修量级**(失效判据 = **种类覆盖**,不是次数)。
  - **问题 B(子 Agent 拿不到纪律 / 新登记 KD-10)**:`.claude/hooks/subagent-guard.sh`(SubagentStart)**把纪律注入子 Agent 上下文** —— 实机验证到达(`hook_additional_context`),且子 Agent **照注入第 6 条报告了格式**(行为被改变)。到达可证伪:`tools/check_subagent_injection.py`。
  - **F1/F2/F5 全修**:F1(测试污染门 2 证据链)、F2(门禁测试与工作区耦合)、**F5(`impl-guard` 判据锚错仓库 → 在另一检出改实现会误弹 ask → 挂死子 Agent)**。
  - **✅ 已定夺(业务方 2026-09-11)**:**不设"人工覆盖通道"** —— 结构(注入+门禁)会压过显式指令(盲测 5 实测 Agent 拒绝「不用写测试」的指令)。理由:*「给了就是漏洞,子 Agent 会发现并持续跳过,直到被发现」*。**已有**的 `[no-test: <理由>]` 豁免**不变**(它要求写明理由、可审计,与"覆盖通道"不是一回事)。
  - **已登记、暂不处理(业务方指示)**:① **KD-11 长任务无断点保护**(母体 `kit-缺陷登记.md`);② 同 worktree 并行委派互相 reset(建议用 `using-git-worktrees`);③ `using-superpowers` 入口自触发**不稳定 1/2**(**已知边界**,主会话侧已无更好手段)。
  - **门禁「拦截力」**:已用新方法(要求 Agent 走捷径)**间接回答** —— 门不响是因为 **Agent 自己不走捷径**;**不再阻塞**。
  - **母体已回写并回流**(业务方批准):`e7700dd` 登记(KD-9 补证据③ + **新建 KD-10** + 回流清单 14 项)→ **`bbbfcdf` 已回流代码 15 项**(scaffold 首次获得 `tests/` 门禁防腐测试 + 母体自身 CI)。验证 = 在**模拟派生项目**里跑 scaffold 测试(**82 passed**);该步骤已固化进母体 CI 作为**回流漂移探测网**。另:`kb-drift-sentinel.sh` 注释系**反向回流**(母体→本仓)—— **回流不是单向的**。
  > **交接背景**:上一会话 `c549c42a` 在 **1,017,378 tokens** 时 `API Error 400` 中断 —— **该会话不可 `--resume`**(会原样撞同一上限)。断点状态已从 transcript 抢救落盘(ROADMAP + 本指针 + `docs/复盘/`)。
  > **✅ 已扩范围(业务方定夺)**:门 1 / 门 2 / 左移门的判据**已从 `app|backend|src` 扩到含门禁与工具脚本**
  > (`.claude/hooks/`、`.githooks/`、`tools/`)—— 改门禁脚本**现在也有人看着了**。
  > **规则向前生效、不追溯**:扩范围前的历史提交会被 `check_gate_bypass.py` 追溯标记,CI 用 base/before 天然限定为新提交。
  > 若确为纯注释/无行为变化,走**带理由的豁免** `[no-test: <理由>]`(裸标记不再放行)—— 本仓 `bc23a13` 即为一次活例。
- **门禁硬化已落地(2026-09-11 凌晨,8 个 commit)**:skills 三层结构(锚点对应表 → hook 哨兵 → CI 检查)+ **门禁左移**(`impl-guard.sh`,PreToolUse ask)+ **门 1/门 2**(commit-msg:认实现先于测试 + 未调用 `test-driven-development` 即拒提交)。**盲测实证 2/2 复现**:两个空上下文子 Agent 均被门 1/门 2 拦下,并**主动调用 `test-driven-development` 回退重做**。策略沉淀在 `~/Desktop/知识库/18.Agent避坑库-问题解决策略/` 01·02(§4.9)·03。
- 进度:阶段1/2 **业务方逐条签核 D-1..D-9(2026-09-10)**;阶段3 P3-1 首跑 `app/eval_gate/` E1–E7 竖切 + fastapi-rag 适配器 + CI 示例,`pytest` 47 passed(离线零外网),good→exit0 / bad→exit1 被拦。真实被测:`01.FastAPI RAG Agent`(切 DeepSeek,commit `36aa291`)。
- **P3 收口顺序已签核(D-10a..D-10h,2026-09-10)** —— grilling 定调压测门通过后修订 D-9:顺序 = **R0 → R2a → R1 → R2b → R3 → R4**;R3 升级为 **R4 硬前置**;契约补丁三处。过程数据 `notes/grilling/P3-1优先级-2026-09-10.md`,签核 `docs/decisions/定调复核-签核记录.md`。
- **阶段门纪律**:gate-review 出建议、终裁 = 业务方签核(本指针/节点 ✔ 均以此为准,不再自评 PASS)。
- **进度(2026-09-10)**:R0 ✅、R2a ✅、R1a ✅、R3 ✅、**R1b 活链路冒烟 ✅(本轮)**。`pytest` 76 passed / 2 skipped(离线)。
- **R1b 结果**:真实被测 + 真实 `deepseek-chat` judge,**34/40 通过(0.85)、exit 1**;失败 6 条**全部归因被测侧**(5 拒答 + 1 计数错误);**拒答 10/10、红队/越权 3/3 全过**。
- **被测运行方式**:**`tools/sut-harness/run_sut.sh`**(2026-09-11 固化;此前散布在 `/tmp`,重启丢过两次)。
  它是**评测门的运行适配层**,只读挂载被测 `api/` 跑当前代码,不往被测仓塞第三套运行方式;含**能力探针**(`/health` 200 ≠ 答得了,见其 README §陷阱)。
  ⚠️ **被测已不再"零改动"**:2026-09-11 业务方授权修复其真实缺陷 → **`85e456b` 已推 GitHub**。
  此前基线(`36aa291`,34/40)与修后**不可直接比较**。
- **踩过的坑(已修,记在 `.env` / `.env.example`)**:① 被测 `localhost` 会解析到 IPv6 打到 Docker 的崩溃容器 → 改 **`127.0.0.1`**;② 本机 TLS 拦截,venv 默认 CA 不含其 CA → 设 **`SSL_CERT_FILE=/etc/ssl/cert.pem`**(备选:certifi 的 cacert.pem);③ pip 装 `cryptography` 需 `--prefer-binary`(Intel Mac 无 arm64 wheel 会退化成源码编译,而本机无 Rust)。
- **进度(2026-09-10 续)**:**R2b 已标定**(`eval/阈值.md` + `总纲.md` §4 全填真实值;北极星基线 = **1**,由劣化演示取得 —— 改被测拒答指令 → 红队突破 2 → 被 `redteam_zero`+`l2` 拦下,被测已还原)。**首次 exit 0**:复跑 37/40(0.925)。
- **下一步(阶段4-步骤8:模块测试/压测/红队)**:① `eval/README.md:24` 的 **N 次 A/B + p-value**(当前阈值只能判大退化);② 覆盖率达标 + 端到端/回放;③ 压测出 **L1 基线**(QPS/P99/错误率)。起点见 B `04-阶段4-测试验证-v1.0.md`。
- **R2b 遗留已清**:① ~~阈值未接线~~ → ✅ 已修(机读 `eval/阈值.json` + `default_thresholds()` 优先读,**缺配置回落更严兜底**,契约测试守住);② 基线单轮波动 **7.5pp**(0.85/0.90/0.925),`eval/README.md:24` 的 N 次 A/B + p-value **仍未做** → 阈值只能作 v1 粗门(不阻塞 R4,但判不了微小退化)。
- **R4 前收口的两条(本轮补完)**:**#3 重试退避** ✅(`E_SUT_TIMEOUT`/`5XX`→指数退避≤2、`429`→限速退避、其余 4xx→fail-fast;judge 超时重试 1 次;参数按 R1b 实测延迟定 1s 基数)/ **#7 P3-2 存储策略** ✅(`docs/specs/P3-2-存储策略.md`:逐项判「落地/不适用」并给依据)。**B 阶段3 门禁 7 条现已全部可判**。
- **环境备查**:被测本地运行需 `/tmp/sut-run` 脚手架 + `/tmp/sut-lite-venv`;`rag-api` 容器已被停(它崩溃重启 304 次且抢 8000 端口),恢复命令 `docker start rag-api`。
- **模型名(2026-09-10 迁移)**:DeepSeek 官方 **2026-07-24 起停用 `deepseek-chat` / `deepseek-reasoner`**,现行为 **`deepseek-v4-flash` / `deepseek-v4-pro`**。本仓 `.env`(`EVAL_JUDGE_MODEL`)与**被测 `.env`**(`LLM_MODEL_FAST`/`LLM_MODEL_CHAT`)均已迁到 `deepseek-v4-flash` 并实测通过。⚠️ 该网关**不校验模型名**(任意名都返 200),故「能调通」不代表名字有效 —— 以官方文档为准。
- **待业务方在 R2b 复核**:idx26「Python 适合哪些人学习?」标准答案含「文档未明确说明」,是半拒答;以及 id12/14 类「golden 期望超出语料本身」的条目是否保留。
- **挂起项**:被测知识库有无文档(R1 开头探针自证);母体 Kit 缺陷观察项(证据 1/2,停观察态,不落本仓表)。
