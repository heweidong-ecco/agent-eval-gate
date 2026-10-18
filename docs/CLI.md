# CLI 参考

> 入口:`eval-gate`(安装后)或 `python -m eval_gate`。安装见 `README.md` / `docs/部署.md`。
> 子命令:`run` · `trace` · `calibrate` · `stats`。

## 全局

```bash
eval-gate --help
eval-gate <子命令> --help
```

退出码(所有子命令统一,见 `contracts/评测-report.md`):

| code | 含义 |
|---|---|
| `0` | 全绿 |
| `1` | 阻断(通过率低于阈值 / 红队命中;或 `calibrate --fail-on-below` 低于阈值) |
| `2` | 存疑 / 需人工(judge 一致率、flag) |
| `3` | 运行错误 / 熔断 degraded(如 `E_SUT_QUOTA`;此时阈值判定作废) |

---

## `eval-gate run`

跑一轮评测,产出报告 + exit code。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--evals PATH` | ✅ | 评测集 JSON(`eval/*.evals.json`) |
| `--mode good\|bad` | | `good`=忠实(默认);`bad`=劣化,用于**自证门会拦** |
| `--threshold FILE` | | 覆盖阈值文件(同一份 JSON 的数值) |
| `--offline` | | 强制离线 FakeJudge(不调真实模型) |
| `--report-dir DIR` | | 报告目录(默认 `eval/runs`) |

```bash
# 离线自证
python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode good --offline
python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode bad  --offline

# 真实链路(被测 + judge 都要配好)
python -m eval_gate run --evals eval/fastapi_rag_golden.evals.json --report-dir eval/runs
```

产物:

| 文件 | 内容 |
|---|---|
| `<run_id>.local.json` | 逐条证据 / judge 理由 / 汇总 / exit_code(不入库) |
| `<run_id>.trace.jsonl` | span(不入库;被引用时用 `tools/archive_evidence.py` 归档) |
| `<run_id>.summary.md` | 脱敏摘要(可入库) |

> ⚠️ **`local.json` / `trace.jsonl` 被 `.gitignore` 排除**;要让结论可重算,
> 必须归档 `<run_id>.spans.jsonl`(见 `tools/archive_evidence.py` 与 `tools/check_evidence_coverage.py`)。

---

## `eval-gate trace`

打印某次 run 的 span 树。

| 参数 | 说明 |
|---|---|
| `--run RUN` | run_id(默认取最近一次) |
| `--trace-dir DIR` | trace 目录(默认 `eval/runs`) |

```bash
python -m eval_gate trace
python -m eval_gate trace --run 20261018-182724-e6212c1d
```

---

## `eval-gate calibrate`

算 judge 与人工标注的一致率(M1/E7)。

| 参数 | 说明 |
|---|---|
| `--refs REFS` | ✅ 人工标注参照集(默认文件 `eval/judge_refs.json`) |
| `--offline` | 用离线 FakeJudge |
| `--threshold FILE` | 阈值文件(取 `judge_human_agreement.min`) |
| `--fail-on-below` | 低于阈值时 **exit 1**(默认关闭;是否接自动门由使用方决定,`DEC-008 §5`) |

```bash
python -m eval_gate calibrate --refs eval/judge_refs.json
python -m eval_gate calibrate --refs eval/judge_refs.json --fail-on-below
```

> ⚠️ **一致率默认不是阻断项**;参照集用尽后只能写「本参照集已耗尽信息」,不能写"已校准"。

---

## `eval-gate stats`

从已有 trace 产真实 L1 基线(零 token)。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--runs RUNS` | ✅ | run_id 列表(逗号分隔)或 glob,如 `20260912-*` |
| `--trace-dir DIR` | | trace 目录(默认 `eval/runs`) |
| `--out OUT` | ✅ | 基线 JSON 落盘路径 |
| `--rev REV` | | 写入 `_rev`(默认当天) |

```bash
python -m eval_gate stats --runs '20260912-*' --out eval/l1_baseline.json
```

---

## 环境变量(常用)

完整表见 `docs/部署.md §3`。

| 变量 | 说明 |
|---|---|
| `EVAL_JUDGE_BASE_URL` / `_API_KEY` / `_MODEL` | judge;三者缺一 ⇒ 回落离线 FakeJudge |
| `EVAL_JUDGE_MAX_TOKENS` / `_CONCURRENCY` | 默认 **4096** / 4 |
| `EVAL_SUT_FASTAPI_BASE_URL` / `_API_KEY` | 真实被测;base_url 用 `127.0.0.1` |
| `EVAL_SUT_FASTAPI_SNAPSHOT` | 走快照回放(被测不可用时) |
| `EVAL_LIVE` | 置 `1` 才跑 live 冒烟测试 |
| `EVAL_TRACE` | 置 `0` 关观测 |
| `EVAL_OTLP_ENDPOINT` | 外发 OTLP |
| `SSL_CERT_FILE` | 本机 TLS 拦截时必设 |
| `EVAL_SUT_RETRIES` / `_BACKOFF_S` / `_429_BACKOFF_S` | 重试 / 退避 |

**阈值**:运行值取 `eval/阈值.json`;文件缺失时回落**更严**的兜底,绝不放宽门。

---

## 典型工作流

```bash
# 1) 离线自证(零 key、零外网)
python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode good --offline
python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode bad  --offline

# 2) 真实链路(先起被测 + 灌语料,见 docs/部署.md §5)
set -a; . eval/runs/.sut-harness.env; set +a
python -m eval_gate run --evals eval/fastapi_rag_golden.evals.json

# 3) 看 trace
python -m eval_gate trace

# 4) 校准(有人工标注时)
python -m eval_gate calibrate --refs eval/judge_refs.json
```
