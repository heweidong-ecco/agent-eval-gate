# examples/ · 可直接跑的例子

> 这里放**能复制的用法**;评测数据集在 `eval/`,不在这里重复。

## 1. 离线自证(零 key、零外网)

```bash
./examples/offline-demo.sh
```

它做两件事并检查退出码:

- `--mode good --offline` → **exit 0**
- `--mode bad --offline` → **exit 1**(证明"劣化会被拦")

这是最快确认"装好了、门是活的"的方式。

## 2. 真实链路(真实被测 + 真实 judge)

前置:

1. 起被测 + 能力探针:`tools/sut-harness/run_sut.sh`(退出码 0/1/2);
2. 灌评测语料:`tools/seed_eval_corpus.py`(见 `eval/corpus/README.md`);
3. 配好 `.env` 的 `EVAL_JUDGE_*` 与 `EVAL_SUT_FASTAPI_*`。

```bash
set -a; . eval/runs/.sut-harness.env; set +a
export SSL_CERT_FILE=/etc/ssl/cert.pem
.venv/bin/python -m eval_gate run \
  --evals eval/fastapi_rag_golden.evals.json \
  --report-dir eval/runs
```

完整步骤与坑见 **`docs/部署.md §5`**。

## 3. 接入自己的被测

不是复制一个脚本就能完成;需要写适配器(3 处代码)+ 加数据。
先读 **`docs/接入新被测.md`**,按那里的门槛和步骤做。

## 4. 在 CI 里用

本仓 CI 示例:`.github/workflows/eval-gate.yml`。
**真实被测的发版 CI 尚未接入** —— 模板见 `integrations/fastapi-rag-agent/`。
