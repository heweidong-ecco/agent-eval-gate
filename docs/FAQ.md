# FAQ · 常见问题

> 这些问题**全部来自本仓真实踩过的坑**(报告 / 复盘 / 部署文档),不是通用模板。
> 先看这里;没有答案再按 `SUPPORT.md` 提问。

## 1. 这是什么?和 promptfoo / deepeval / openai evals 有什么区别?

本仓是**CI 门**:给「被测系统的输入 → 输出文本」打分,产出 **exit code**,
让「这次改动能不能上线」变成一个可阻断的检查。
它不是评测数据集市场,也不是 SaaS 看板;核心是 **确定性规则 + LLM-judge + 阈值 + 报告 + 可复现**。
架构见 `docs/arch/README.md`,边界见 `需求基线.md §9`。

## 2. 不联网、没有 key 能跑吗?

能。用自带的迷你被测和离线 FakeJudge:

```bash
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode good --offline   # → exit 0
.venv/bin/python -m eval_gate run --evals eval/mini_rag_qa.evals.json --mode bad  --offline   # → exit 1
```

`--offline` 只是**自证管线**;真实语义判分必须配 judge(`EVAL_JUDGE_*`)。

## 3. judge 报 401 / 模型不存在怎么办?

- **401**:key 失效或被轮换。检查 `.env` 的 `EVAL_JUDGE_API_KEY`;
  ⚠️ **不要**把 key 贴进 issue。
- **模型不存在 / 行为变化**:模型名可能已被官方停用
  (例:DeepSeek 2026-07-24 起停用 `deepseek-chat` / `deepseek-reasoner`)。
  ✅ 但注意:**网关可能不校验模型名** —— 能调通 ≠ 名字有效,以官方文档为准。
- 查看当前生效配置:`eval-gate run ...` 输出的「生效 judge 配置」行。

## 4. `/health` 返回 200,但评测里全 fail?

**`/health` 只查 DB/Redis,不代表被测答得了。**
必须先跑**能力探针**:

```bash
EVAL_SUT_FASTAPI_API_KEY=... tools/sut-harness/run_sut.sh
# 退出码 0 = 就绪且能作答 · 1 = 起不来 · 2 = 起来了但答不了
```

`exit 2` 时**不要**据此判被测质量,先归因环境(模型 / embedding / 语料)。
历史教训见 `docs/复盘/2026-09-11-P4-1-过程错误.md`(E7)。

## 5. 为什么不能直接拿生产库跑评测?

本机生产库 `rag_db` 已混入其它项目/测试语料(实测 **345 行**),
而评测语料只占约 **125 行**。直接跑会让 `top_k` 被无关语料挤占,
失败**无法归因**(分不清是被测退化、判分器变严,还是语料污染)。

⇒ 用**隔离库**(如 `rag_eval_20261018`),原库不动。
原因与代价见 `DEC-023` / `docs/复盘/2026-10-18-语料筛选漏掉seed金标语料.md`。

## 6. 评测语料为什么不在仓库里?换机器怎么复现?

本仓是 **Public**,知识库正文不能进公开仓历史。
因此:**仓内只有清单 + sha256**(`eval/corpus/manifest.json`),正文放仓外
(`~/Desktop/Product-external/eval-corpus/`)。

换机器:
```bash
# 1) 把语料文件放到任意路径(不要放进任何 git 仓)
# 2) 校验 + 灌入(哈希不一致会拒绝)
python3 tools/seed_eval_corpus.py \
  --corpus /path/to/fastapi_rag_eval_corpus-20261018.jsonl \
  --manifest eval/corpus/manifest.json --dry-run
```

## 7. 跑着跑着出现 429 `QUOTA_EXCEEDED`?

新版被测有**会话预算**(默认 **50,000 token / 用户 / 会话 / 日**),
不是限流,是额度用完。48 条一轮会接近这个上限。

处理:
- 起被测时放宽:`EVAL_SUT_SESSION_TOKEN_LIMIT=200000 tools/sut-harness/run_sut.sh`;
- 先查今日已用:`SELECT SUM(total_tokens) FROM token_usage_logs WHERE created_at >= CURRENT_DATE;`
- ⚠️ 别把它读成被测质量崩了:尾部的 `429` 会污染失败归因。

## 8. exit 0 / 1 / 2 / 3 分别是什么?

| code | 含义 | CI 处置 |
|---|---|---|
| `0` | 全绿 | 放行 |
| `1` | 阻断(通过率低于阈值 / 红队命中) | 阻断 |
| `2` | 存疑 / 需人工(judge 一致率、flag) | 人工复核 |
| `3` | 运行错误 / 熔断 degraded(如 `E_SUT_QUOTA`) | 告警,不算绿 |

详见 `contracts/评测-report.md` 的「exit code 语义」。

## 9. judge 和我的人工判断不一致,怎么办?

先跑校准,不要直接改判分器:

```bash
.venv/bin/python -m eval_gate calibrate --refs eval/judge_refs.json
```

- 一致率阈值在 `eval/阈值.json` 的 `judge_human_agreement`(默认 0.80);
- **默认不作阻断项**(`DEC-008 §5`);需要阻断时加 `--fail-on-below`;
- 分歧先看是不是**参照集口径**问题(见 `DEC-017` / `docs/校准/`)。

## 10. 为什么红队 / 拒答 / 禁现词走确定性层,不交给 judge?

这是**契约不变量**:红队与注入类不进 LLM-judge,避免"判分器被说服"。
硬层(必拒 / 禁现 / 空回答)由确定性规则权威,**judge 不可翻案**;
软层(`answer_contains`)才交 judge。见 `DEC-004` / `DEC-022` / `总纲.md §1`。

## 11. 怎么接入我自己的被测?

判据内核不改,只动**适配器层 3 处**(类、注册、`SUPPORTED_SUTS`),
其余是加数据(评测集 / 连接配置 / 语料)。
完整步骤与硬门槛见 **`docs/接入新被测.md`**。

## 12. 能接进我们项目的发版 CI 吗?

**目前没有接。** 本仓只提供模板:
`integrations/fastapi-rag-agent/`(范围 / 顺序 / 验收标准)。
接入要动**另一个仓**的 workflow + secrets,并决定触发方式(建议 **发版 tag / 手动**,不要每个 PR)。
每次 live ≈ 4 万 token,成本必须可控。

## 13. 支持 Windows 吗?

**未验证。** 开发/CI 在 macOS + Linux 上跑;真实被测建议用 Docker。
Windows 用户建议用 WSL2;遇到问题按 `SUPPORT.md` 提 issue。

## 14. 一轮评测大概多少钱?

参考实测(48 条,`deepseek-v4-flash`):
- judge 侧:**约 3–4 万 token**(2026-10-18 那轮 39,697);
- 被测侧:约 4–5 万 token(取决于被测自己的改写/生成);
- 具体数字见 `docs/reports/` 对应报告。
  ⚠️ **开跑前先确认预算**,不要默认"跑一下不要钱"。
