#!/usr/bin/env python3
"""把被报告/复盘**引用到的** run 的「**脱敏关键 span 摘录**」归档入库。

依据 `DEC-014 §4.1`(签核 D-17)。起因是 2026-09-13 **灾备演练**的首次实测:

    `eval/runs/*.trace.jsonl` **被 gitignore** ⇒ 结论(脱敏 summary)入库、**原始证据不入库**。
    模拟丢失后 **L1 基线无法重算**(`eval-gate stats` → exit 3)⇒ **MTTR 不可用(无界)**。

本工具把"够重算"的那部分抽出来落成 `<run_id>.spans.jsonl`(**进 git**)——
名字**刻意不叫** `.trace.jsonl`,所以不会被 `.gitignore:24` 吃掉;
恢复时改回 `.trace.jsonl` 即可原样重算(**已在测试里逐字校验**)。

⚠️ **脱敏是硬约束**:只保留结构字段 + **白名单** attributes;
`answer` / `input` / `output` / `error.msg` 一律**丢弃**(它们可能含被测答案原文,
与 `runner.py` 的结构性脱敏纪律一脉相承)。

用法:
    python3 tools/archive_evidence.py --trace eval/runs/<id>.trace.jsonl --out eval/runs/<id>.spans.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: 顶层字段白名单 —— **够重算**(`trace_stats.summarize_run` 只读这些)
TOP_ALLOW = ("trace_id", "span_id", "parent_span_id", "name", "kind",
             "start_time_ms", "duration_ms", "status")

#: attributes 白名单 —— 结构字段;凡可能含自然语言的一律不收
ATTR_ALLOW = ("case_id", "sut", "passed", "verdict", "attempts",
              "finish_reasons", "judge", "module", "mode", "deterministic_only")


def excerpt_line(raw: dict) -> dict:
    """一行 trace → 一行摘录(白名单过滤;丢弃一切可能含原文的字段)。"""
    out = {k: raw[k] for k in TOP_ALLOW if k in raw}
    attrs = raw.get("attributes") or {}
    kept = {k: attrs[k] for k in ATTR_ALLOW if k in attrs}
    if kept:
        out["attributes"] = kept
    if (raw.get("error") or {}).get("code"):
        out["error_code"] = raw["error"]["code"]      # 只留错误码,丢掉 msg
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="归档脱敏关键 span 摘录(DEC-014 §4.1)")
    ap.add_argument("--trace", required=True, help="源 trace(JSONL)")
    ap.add_argument("--out", required=True, help="落盘路径(建议 <run_id>.spans.jsonl,进 git)")
    a = ap.parse_args(argv)

    src = Path(a.trace)
    if not src.is_file():
        print(f"[archive] 源 trace 不存在:{src}", file=sys.stderr)
        return 3
    lines = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.strip():
            lines.append(json.dumps(excerpt_line(json.loads(line)), ensure_ascii=False))
    if not lines:
        print(f"[archive] 源 trace 为空:{src}", file=sys.stderr)
        return 3

    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[archive] {src.name} → {dst}({len(lines)} span)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
