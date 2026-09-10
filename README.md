# agent-eval-gate · Agent 生产就绪评测门

> 给**其它 Agent 系统**做「生产就绪评测门」:评估集 + 确定性规则 + LLM-as-Judge + 阈值门 + Trace。
> 回答一个问题:**这次改动,能不能上线?** —— 用可量化、可复现、可进 CI 的评测结果说话。
>
> 架构定位(签核 D-5):**评测引擎,判"被测的输入 → 输出文本答案(含引用/证据)"**。被测经适配器取(HTTP / 快照 / 回放),本产品**自身不带** Agent 运行时 / 对话记忆 / 工具栈。

---

## 30 秒上手

```bash
# 1) 安装(零运行时依赖,纯标准库;dev 装 pytest)
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# 2) 离线自证:用自带的迷你被测跑一轮(不联网、不要密钥)
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode good --offline   # → exit 0
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode bad  --offline   # → exit 1(劣化被拦)

# 3) 看这一轮的 Trace 视图(span 树)
.venv/bin/python -m eval_gate trace
```

接**真实被测**(需其服务在跑 + 密钥)见 `docs/部署.md`。

---

## CLI

### `eval-gate run` — 跑一轮评测并出 exit code

| 参数 | 必填 | 说明 |
|---|---|---|
| `--evals PATH` | ✅ | 评测集文件(格式见 `eval/README.md` / `contracts/评测-evals-schema.md`) |
| `--mode good\|bad` | | 被测 prompt 质量:good=忠实 / bad=劣化(**自证用**:劣化必须被拦) |
| `--threshold FILE` | | 阈值 JSON,覆盖 `eval/阈值.json` |
| `--offline` | | 强制离线 FakeJudge(**不调真实模型**) |
| `--report-dir DIR` | | 报告落盘目录(默认 `eval/runs`) |

产出:`eval/runs/<run_id>.local.json`(逐条证据)+ `<run_id>.trace.jsonl`(span)+ 结构化日志走 **stderr**(`2>log.jsonl` 采集)。

### `eval-gate trace` — 打印 Trace 视图

| 参数 | 说明 |
|---|---|
| `--run RUN_ID` | 指定 run(默认取最近一次) |
| `--trace-dir DIR` | trace 文件目录(默认 `eval/runs`) |

### exit code 语义(CI 门;契约 `contracts/评测-report.md:40-46`)

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
| `eval/` | 评测集、`阈值.md` + `阈值.json`(运行值)、`cases/`(失败回灌)、`runs/`(报告)、`snapshots/` |
| `observability/` | 结构化日志 / trace_id / span 规范 |
| `docs/` | `RUNBOOK.md`、`decisions/`(签核)、`specs/`(节点设计)、`复盘/`(过程错误集) |
| `tests/` | 契约测试与回归(`pytest -q`,离线零外网) |

---

## 文档索引

- **接续与指针** → `CLAUDE.md`(每会话必读)、`ROADMAP.md`(执行图与当前指针)
- **业务口径事实源** → `需求基线.md`;架构 → `总纲.md`
- **怎么装、怎么接真实被测、本机环境坑** → **`docs/部署.md`**
- **阈值与「为何调」** → `eval/阈值.md`(运行值 `eval/阈值.json`)
- **失败案例与教训** → `eval/cases/`、`docs/复盘/`

---

## 开发

```bash
.venv/bin/python -m pytest -q            # 全量(离线、零外网)
.venv/bin/python -m pytest -q --cov=eval_gate --cov-report=term-missing   # 带覆盖率
```

CI:`.github/workflows/eval-gate.yml` —— 独立成 job(不与代码门合并成一个绿灯),含自证/劣化回归/改动留痕/TDD 痕迹检查。

> **纪律**:改 Prompt / 工具 / 记忆 / **评估集** → 必跑 eval 回归;失败即补 case(`eval/cases/`)。
