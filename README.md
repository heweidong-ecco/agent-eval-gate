# agent-eval-gate · Agent 生产就绪评测门

> 给**其它 Agent 系统**做「生产就绪评测门」:评估集 + 确定性规则 + LLM-as-Judge + 阈值门 + Trace。
> 回答一个问题:**这次改动,能不能上线?** —— 用可量化、可复现、可进 CI 的评测结果说话。
>
> 架构定位(签核 D-5):**评测引擎,判"被测的输入 → 输出文本答案(含引用/证据)"**。被测经适配器取(HTTP / 快照 / 回放),本产品**自身不带** Agent 运行时 / 对话记忆 / 工具栈。

---

## 项目状态(2026-10-18 · 自用版结项)

**v0.4.0(自用版)已结项** —— 验收对照与暂缓项见 **`docs/结项报告-自用版-2026-10-18.md`**。

| | |
|---|---|
| 已闭环 | B 六阶段 **12/12** 节点 · M0–M5 · 真实被测 **2 家 / 4 形态** · 最新 live **47/48 · exit 0** · **597 tests** |
| 明确暂缓 | **U2 真实发版 CI**(模板在 `integrations/`;业务方 2026-10-18 决定暂不动另一个仓)· M3 抽取判据 · 背景观察项 |
| 复现 live 回归 | 语料清单 `eval/corpus/` → `tools/seed_eval_corpus.py` → `tools/sut-harness/run_sut.sh` → `eval-gate run` |

> `v1.0.0` **不外推**:前置 = U2 接进真实发版 CI + 至少一个外部使用者验证。

---

## 目录

- [项目状态](#项目状态2026-10-18--自用版结项)
- [30 秒上手](#30-秒上手)
- [CLI](#cli)
- [它怎么判(判分链路)](#它怎么判判分链路)
- [目录](#目录)
- [文档索引](#文档索引)
- [常见问题](#常见问题)
- [开发](#开发)
- [贡献](#贡献)
- [安全](#安全)
- [许可证](#许可证)

---

## 30 秒上手

```bash
# 1) 安装(零运行时依赖,纯标准库;dev 装 pytest)
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# 1b) 激活本地门禁钩子(**必做**,否则提交门禁静默失效)
./tools/setup-hooks.sh      # 把 git 的 core.hooksPath 指向 .githooks/

# 2) 离线自证:用自带的迷你被测跑一轮(不联网、不要密钥)
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode good --offline   # → exit 0
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode bad  --offline   # → exit 1(劣化被拦)

# 3) 看这一轮的 Trace 视图(span 树)
.venv/bin/python -m eval_gate trace
```

接**真实被测**(需其服务在跑 + 密钥)见 `docs/部署.md`。

---

## CLI

| 子命令 | 用途 |
|---|---|
| `run` | 跑一轮评测 → 报告 + exit code |
| `trace` | 打印某次 run 的 span 树 |
| `calibrate` | judge 与人工标注的一致率(M1/E7) |
| `stats` | 从已有 trace 产 L1 基线(零 token) |

完整参数、环境变量与示例见 **`docs/CLI.md`**。

产出:`eval/runs/<run_id>.local.json`(逐条证据)+ `<run_id>.trace.jsonl`(span)+ 结构化日志走 **stderr**(`2>log.jsonl` 采集)。

### exit code 语义(CI 门;契约 `contracts/评测-report.md`)

| code | 含义 | CI 处置 |
|---|---|---|
| `0` | 全绿 | merge 放行 |
| `1` | **block**(l2 低于阈值 / 红队被突破) | **阻断** |
| `2` | conditional / human(judge 存疑 flag) | 人工复核 |
| `3` | 运行错误 / 熔断 degraded(如被测配额耗尽 `E_SUT_QUOTA` → 整批 aborted) | 不算全绿,告警 |

> **不假装全绿**:exit 3 时阈值判定作废(`blockers` 置空),只告警。

---

## 它怎么判(判分链路)

```
评测集 → ① schema 校验(零模型调用即失败,省 token)
      → ② 调被测(适配器统一「输入→输出」)
      → ③ 确定性规则(注入/越权/拒答/格式,不用 LLM,~0ms)
      → ④ LLM-as-Judge(结构化出参;非 JSON → flag,不静默给分)
      → ⑤ 聚合 → 阈值 → exit code → 报告 + Trace
```

**关键语义(契约 `contracts/评测-evals-schema.md:30`)**:`expected.answer_contains` 是「**含其一即符**」——命中任一即算满足,**不是"必须全含"**。judge 提示词已显式复述该语义。

---

## 目录

| 路径 | 内容 |
|---|---|
| `app/eval_gate/` | E1–E9 实现(schema / adapters / rules / judge / runner / report / obs / cli) |
| `contracts/` | **契约**(评测集 schema / 被测适配器 / judge / 报告与阈值)—— 事实源 |
| `eval/` | 评测集、`阈值.md` + `阈值.json`(运行值)、`cases/`(失败回灌)、`runs/`(报告)、`snapshots/`、**`corpus/`(语料清单;正文在仓外)** |
| `tools/` | **`sut-harness/`**(真实被测运行层)· **`export_eval_corpus.py` / `seed_eval_corpus.py`**(语料复现)· `archive_evidence.py` + `check_evidence_coverage.py`(证据归档/覆盖守卫) |
| `integrations/` | **发版 CI 接入模板**(⬜ 未接入 —— 业务方决定暂不动另一个仓) |
| `observability/` | 结构化日志 / trace_id / span 规范 |
| `docs/` | `README.md`(**文档索引**)· `FAQ.md` · `CLI.md` · `部署.md` · `decisions/`(签核)· `specs/`(节点设计)· `复盘/` · **`arch/`(当前架构图)** · **结项报告** |
| `examples/` | 可直接跑的例子(`offline-demo.sh`) |
| `.github/` | issue 模板 · PR 模板 · CI workflow |
| `tests/` | 契约测试与回归(`pytest -q`,离线零外网) |
| 根级健康文件 | `LICENSE`(MIT)· `CONTRIBUTING.md` · `SECURITY.md` · `SUPPORT.md` · `CHANGELOG.md` |

---

## 文档索引

**全部文档的导航 → `docs/README.md`。**

- **常见问题** → **`docs/FAQ.md`**(密钥 / 429 / exit code / 语料 / 环境坑)
- **完整 CLI** → **`docs/CLI.md`**
- **接续与指针** → `CLAUDE.md`(每会话必读)、`ROADMAP.md`(执行图与当前指针)
- **项目结项与暂缓项** → **`docs/结项报告-自用版-2026-10-18.md`**
- **业务口径事实源** → `需求基线.md`;架构蓝图 → `总纲.md`
- **当前架构图(C4 / 组件 / 时序)** → **`docs/arch/README.md`**
- **怎么装、怎么接真实被测、本机环境坑** → **`docs/部署.md`**
- **评测语料怎么复现** → **`eval/corpus/README.md`**
- **阈值与「为何调」** → `eval/阈值.md`(运行值 `eval/阈值.json`)
- **失败案例与教训** → `eval/cases/`、`docs/复盘/`
- **可直接跑的例子** → `examples/`

---

## 常见问题

先看 **`docs/FAQ.md`**。最常见的四类:

- judge 401 / 模型名失效;
- `/health` 200 但答不了(能力探针);
- 生产库被污染(345 行)⇒ 必须用隔离库;
- 429 `QUOTA_EXCEEDED`(被测会话预算 5 万 token)。

---

## 开发

```bash
.venv/bin/python -m pytest -q            # 全量(离线、零外网)
.venv/bin/python -m pytest -q --cov=eval_gate --cov-report=term-missing   # 带覆盖率
```

CI:`.github/workflows/eval-gate.yml` —— 独立成 job(不与代码门合并成一个绿灯),含自证/劣化回归/改动留痕/TDD 痕迹检查。

> **纪律**:改 Prompt / 工具 / 记忆 / **评估集** → 必跑 eval 回归;失败即补 case(`eval/cases/`)。

---

## 贡献

开发环境、TDD/门禁、commit/PR 规则见 **`CONTRIBUTING.md`**;
issue/PR 模板在 `.github/`。行为准则当前**不适用**(单人维护),触发条件见 `DEC-025`。

## 安全

漏洞请走 GitHub **私密漏洞报告**,⛔ 不要开公开 issue —— 见 **`SECURITY.md`**。

## 许可证

**MIT** —— 见 `LICENSE`。贡献即表示同意以 MIT 许可发布。

