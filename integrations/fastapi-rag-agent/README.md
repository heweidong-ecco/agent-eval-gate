# integrations/fastapi-rag-agent · 发版 CI 接入模板(**未接入**)

> **状态:⬜ 未接入。**
> 业务方 2026-10-18 决定:**暂不动 `fastapi-rag-agent` 仓** ⇒ 本目录只放"将来要接时可直接抄"的模板,
> 不改另一个仓、不改它的代码/容器/数据库。

## 将来接入需要动什么(范围先说清)

| 动作 | 动哪个仓 | 具体 |
|---|---|---|
| ① 新增 workflow | **`fastapi-rag-agent`(private)** | 把 `eval-gate.yml.example` 复制成 `.github/workflows/eval-gate.yml` |
| ② 配置 secrets | **`fastapi-rag-agent` 仓设置** | `EVAL_JUDGE_API_KEY`、`EVAL_SUT_FASTAPI_API_KEY`(**只能由仓主设置**) |
| ③ 语料供给 | 私有侧 | 语料正文**不在本公开仓**;需放到私有仓 / 加密 artifact,CI 里还原 |
| ④ 起被测 | CI runner | `postgres + redis + api`(现有 SUT CI 故意不起 postgres) |
| ⑤ 触发 | —— | 建议 **发版 tag / 手动**,⛔ 不建议每个 PR(每次 live ≈4 万 token) |

**不需要动**:被测业务代码、`Dockerfile`、compose、生产数据库。

## 建议的接入顺序

1. 先在本仓把语料 seed 链路跑通(`eval/corpus/README.md`);
2. 在 `fastapi-rag-agent` 里加 **一个** workflow,先只跑 `workflow_dispatch`(手动);
3. 稳定后改成 `push: tags: ['v*']`(发版时跑);
4. 再评估是否 nightly —— **不要**默认每个 PR。

## 为什么现在不接

- 被测仓自己的 `ROADMAP.md` 也把它标为未接入(`B14 已移出本仓`);
- 需要改另一个仓 + 配 secrets + 决定预算与触发,属于**跨仓决策**;
- 本轮目标是本仓自用版结项(见 `docs/结项报告-自用版-2026-10-18.md`)。

## 验收标准(接入完成时)

- 发版 tag / 手动触发后,CI 里能跑完一轮 live 评测并给出 `exit 0/1`;
- 故意劣化 prompt 的提交在 CI 被拦(`--mode bad` 或真实劣化样本);
- 报告与 trace 作为 artifact 上传;
- 语料 sha256 在日志里可见(可追溯这次跑的是哪份语料)。
