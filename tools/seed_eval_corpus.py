#!/usr/bin/env python3
"""把评测语料灌进被测(经其 `/api/v1/rag/insert_batch`),seed 前校验清单哈希。

为什么走被测 API 而不是直接写库:
- 不依赖被测的表结构 / 内部连接;只依赖它**自己对外承诺**的导入接口;
- 让被测自己完成 embedding,不会把「我们机器上的向量」带过去。

纪律
----
- **哈希不一致 ⇒ 拒绝**(exit 1),不是警告后继续 —— 否则"复现"是假的;
- `--dry-run` 只校验清单/行数,不发任何网络请求(可零成本预检)。

用法
----
    export EVAL_SUT_FASTAPI_API_KEY=...
    python3 tools/seed_eval_corpus.py \
      --corpus ~/Desktop/Product-external/eval-corpus/fastapi_rag_eval_corpus-20261018.jsonl \
      --manifest eval/corpus/manifest.json \
      --base-url http://127.0.0.1:8000

    # 只校验,不灌:
    python3 tools/seed_eval_corpus.py --corpus ... --manifest ... --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            raise SystemExit(f"[seed] 第 {i} 行不是合法 JSON")
        if not isinstance(d.get("content"), str) or not isinstance(d.get("source"), str):
            raise SystemExit(f"[seed] 第 {i} 行缺 content/source")
        rows.append({"content": d["content"], "source": d["source"]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="按清单校验并灌入评测语料")
    ap.add_argument("--corpus", required=True, help="JSONL 语料路径(仓外)")
    ap.add_argument("--manifest", required=True, help="eval/corpus/manifest.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--api-key", default=os.getenv("EVAL_SUT_FASTAPI_API_KEY", ""))
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corpus = Path(args.corpus).expanduser()
    if not corpus.is_file():
        print(f"[seed] 语料不存在: {corpus}", file=sys.stderr)
        return 1
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))

    actual = hashlib.sha256(corpus.read_bytes()).hexdigest()
    expected = manifest.get("sha256")
    if actual != expected:
        print(f"[seed] sha256 不匹配 —— 拒绝导入\n  期望: {expected}\n  实际: {actual}",
              file=sys.stderr)
        return 1

    rows = _load_rows(corpus)
    want = manifest.get("rows")
    if want is not None and want != len(rows):
        print(f"[seed] 行数不匹配 —— 拒绝导入(清单 {want} / 实际 {len(rows)})", file=sys.stderr)
        return 1

    if args.batch_size <= 0:
        print("[seed] --batch-size 必须 > 0", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[seed] dry-run OK: {len(rows)} 条 · sha256 校验通过 · 来源 {len(manifest.get('sources', {}))} 类")
        return 0

    if not args.api_key:
        print("[seed] 缺 API key:--api-key 或 EVAL_SUT_FASTAPI_API_KEY", file=sys.stderr)
        return 1

    url = args.base_url.rstrip("/") + "/api/v1/rag/insert_batch"
    done = 0
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        body = json.dumps({"documents": batch}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "X-API-Key": args.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[seed] HTTP {e.code} @ {start + 1}-{start + len(batch)}: {detail}",
                  file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"[seed] 连接失败 @ {start + 1}: {e.reason}", file=sys.stderr)
            return 1
        done += len(batch)
        print(f"[seed] {done}/{len(rows)}")

    print(f"[seed] 完成:{done} 条已灌入 {args.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
