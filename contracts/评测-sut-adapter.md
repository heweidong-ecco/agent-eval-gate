# 契约 · 被测适配器(E2)

- 版本:v0.1(阶段2-步骤5 定稿) · 归属:`总纲.md` §3 **E2** · 层 5
- 状态:已登记;首个实现 = `fastapi-rag`(真实被测 `01.FastAPI RAG Agent`)与 `mini-rag-qa`(自带自证)
- 语义:评测门不运行/托管被测,只经适配器统一「输入 → 输出」契约取判分素材。

## 适配器接口(实现方必守)
```python
class SutAdapter:
    id: str                                   # mini-rag-qa | fastapi-rag
    async def run_case(self, case) -> SutOutput: ...
```
- 一个 case 的输入来自 evals-schema 的 `input`(含 `question`);输出**必须归一化**为 SutOutput,不允许透传厂商格式。

## SutOutput(归一化输出)
```jsonc
{
  "raw": { "…": "被测原始响应(脱敏后)", },       // 可空;留审计
  "answer": "…",                                  // 必填 str:被测最终回答(纯文本)
  "refused": false,                               // 可选 bool:是否拒绝回答
  "tool_calls": [],                               // 可选 list:被测声称的工具调用序列(v1.1 用)
  "sources": [],                                  // 可选 list:引用/证据(如 RAG source id+preview)
  "meta": { "latency_ms": 1234, "adapter_version": "…", "error": null }
}
```

## 错误分级(供 E5 调度重试/熔断判定)
| 码 | 含义 | 处置(由 E5 决定) |
|---|---|---|
| `E_SUT_TIMEOUT` | 被测超时 | 重试退避 ≤N |
| `E_SUT_5XX` | 被测 5xx/过载 | 重试退避 ≤N |
| `E_SUT_4XX` | 业务 4xx(参数错/限流 429) | 429→限速重试;其余→该 case fail-fast |
| `E_SUT_AUTH` | 鉴权失败(401/403) | fail-fast,报配置错 |
| `E_SUT_QUOTA` | 配额耗尽(如 403 Free quota exhausted) | **整批 aborted**,run degraded(不假装全绿) |
| `E_SUT_BAD_RESPONSE` | 响应无法解析/无 answer | 记证据,该 case fail |

## fastapi-rag 适配器(真实被测 · 映射)
- 被测:`01.FastAPI RAG Agent`(`/rag/search?mode=accurate` + body 生成答案)。
- 请求:header 鉴权(`X-API-Key` 或 JWT;凭证只从本仓 `.env`/密钥托管读,不硬编码、不入库);body `{question, top_k:3, generate_answer:true, citations:true}`;`mode` 走 URL query。
- 响应映射:resp.`answer` → SutOutput.answer;`sources` → SutOutput.sources;`docs` 存 raw(脱敏)。
- 治理:限速 ≤ 被测配额(该被测用户级 ~3 req/s → 适配器内置 pacing/退避);依赖其 DashScope embedding(检索)正常、生成侧可切任意 OpenAI 兼容(被测仓 commit `36aa291`)。
- 版本控制变量:知识库在被测 DB 不在 git → 评测门首跑需**自带 golden 文档集 + seed 步骤**(控制变量),否则检索结果不可复现(来源标注进 run 报告)。

## mini-rag-qa 适配器(自带 · 自证工具用)
- 嵌入式迷你 RAG(如 BM25 over 自带小文档集),无外部服务/额度依赖;输出与 SutOutput 同构。用途:U1 自证 + 北极星/阈值首样本标定(DEC-001)。

## 变更记录
- 2026-09-09 v0.1。
