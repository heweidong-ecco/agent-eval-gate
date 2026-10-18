# eval/corpus · 评测语料清单(正文**不入本仓**)

## 为什么正文不在这里

本仓是 **Public**。被测知识库的正文可能包含业务内容,不能进公开仓的历史
(历史删不干净,同 `Product/CLAUDE.md` §一 对密钥/大件的要求)。

⇒ 正文放在**仓外、且不在任何 git 仓内**:

```
~/Desktop/Product-external/eval-corpus/fastapi_rag_eval_corpus-20261018.jsonl
```

本目录只放 **`manifest.json`**:行数 · 来源计数 · **sha256** · 生成来源。
`seed_eval_corpus.py` 在灌库前会**校验 sha256**,不一致就**拒绝** —— 不是警告后继续。

## 当前清单

| 项 | 值 |
|---|---|
| 行数 | **125** |
| sha256 | `manifest.json` |
| 生成来源 | `rag_eval_20261018`(生产 `rag_db` 的克隆,过滤 junk source + 按 content 去重) |
| 用途 | `DEC-019` 完整 live 回归(`docs/reports/DEC-019-live回归-2026-10-18.md`) |

## 导出(重新生成语料)

```bash
python3 tools/export_eval_corpus.py \
  --db rag_eval_20261018 \
  --out ~/Desktop/Product-external/eval-corpus/fastapi_rag_eval_corpus-20261018.jsonl \
  --manifest /tmp/manifest.json
# 把 /tmp/manifest.json 的 sha256 / rows / sources 同步进 eval/corpus/manifest.json
```

## 灌入被测(seed)

```bash
export EVAL_SUT_FASTAPI_API_KEY=...
python3 tools/seed_eval_corpus.py \
  --corpus ~/Desktop/Product-external/eval-corpus/fastapi_rag_eval_corpus-20261018.jsonl \
  --manifest eval/corpus/manifest.json \
  --base-url http://127.0.0.1:8000

# 只校验不发请求
python3 tools/seed_eval_corpus.py ... --dry-run
```

## 纪律

1. **不要把语料正文贴进 issue / PR / 聊天记录** —— 本仓是 Public;
2. 清单与文件不一致 ⇒ **拒绝导入**,先查是哪一边变了;
3. 换语料 = 换实验条件 ⇒ 报告里必须写明新的 sha256,旧结论不能直接对比;
4. 灌库前确认目标库是**隔离库**(如 `rag_eval_20261018`),不要灌生产 `rag_db`。
