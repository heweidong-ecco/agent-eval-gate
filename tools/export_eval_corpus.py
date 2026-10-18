#!/usr/bin/env python3
"""把评测语料从被测 Postgres 导出成 JSONL + 清单(正文不入本仓)。

背景
----
本仓是 **Public**;被测知识库的正文**不能**进本仓的历史。
但 live 回归要可复现,就必须有一份**可校验**的语料。
⇒ 正文写到仓外(`~/Desktop/Product-external/eval-corpus/`,不在任何 git 仓内),
   本仓只放 `eval/corpus/manifest.json`(行数 / 来源计数 / sha256)。

用法
----
    python3 tools/export_eval_corpus.py \
      --db rag_eval_20261018 \
      --out ~/Desktop/Product-external/eval-corpus/fastapi_rag_eval_corpus-20261018.jsonl \
      --manifest /tmp/manifest.json

    # 导出后把 manifest 的 sha256 / rows / sources 抄进 eval/corpus/manifest.json
    # (或直接用它覆盖,再把 corpus_path 改成相对路径)

依赖:本机 `docker` + 运行中的 `postgres-rag` 容器(不引 psycopg)。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path

QUERY = (
    "SELECT json_build_object('content', content, 'source', source)::text "
    "FROM documents ORDER BY id;"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="导出评测语料(JSONL)+ 清单")
    ap.add_argument("--db", required=True, help="数据库名(评测用隔离库)")
    ap.add_argument("--out", required=True, help="JSONL 输出路径(建议放 Product-external)")
    ap.add_argument("--manifest", help="可选的清单输出路径")
    ap.add_argument("--container", default="postgres-rag")
    ap.add_argument("--user", default="postgres")
    args = ap.parse_args()

    r = subprocess.run(
        ["docker", "exec", "-i", args.container, "psql", "-U", args.user,
         "-d", args.db, "-At", "-c", QUERY],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[export] psql 失败: {r.stderr.strip()}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            print(f"[export] 非法 JSON 行: {line[:80]}", file=sys.stderr)
            return 1
        if not isinstance(d.get("content"), str) or not isinstance(d.get("source"), str):
            print(f"[export] 行缺 content/source: {line[:80]}", file=sys.stderr)
            return 1
        rows.append({"content": d["content"], "source": d["source"]})

    if not rows:
        print("[export] 没有导出行(库空或表名不对)", file=sys.stderr)
        return 1

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
        encoding="utf-8",
    )
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    counts = dict(sorted(collections.Counter(x["source"] for x in rows).items()))
    print(f"[export] {out} rows={len(rows)} bytes={out.stat().st_size} sha256={sha}")

    if args.manifest:
        manifest = {
            "_doc": "评测语料清单。语料正文不入本仓(本仓 Public);正文放在仓外。seed 前校验 sha256,不一致即拒绝。",
            "corpus": out.name,
            "corpus_path": f"Product-external/eval-corpus/{out.name}",
            "corpus_path_note": "相对于 ~/Desktop;该目录不在任何 git 仓内。",
            "sha256": sha,
            "rows": len(rows),
            "bytes": out.stat().st_size,
            "generated_from": args.db,
            "generator": "tools/export_eval_corpus.py",
            "sources": counts,
        }
        mp = Path(args.manifest).expanduser()
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[export] manifest -> {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
