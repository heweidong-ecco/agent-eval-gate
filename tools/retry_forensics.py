#!/usr/bin/env python3
"""重试取证 —— 回答「**这轮慢,是不是重试吃掉的?**」

## 它补的那个洞(2026-09-14 实证)

重试**只**出现在 `tracer.log("warn","sut","retry", …)`,而 `Tracer.log()`
**只写 stderr、不落盘**(`obs.py:244`)—— `*.trace.jsonl` **只有 span、没有日志行**。
⇒ **一轮跑完就再也查不出它重试过没有。**

最要命的推论:`sut.call` 全是 `status=ok` **推不出"没重试"** ——
**重试后成功的同样是 `ok`**,而「每条都多吃一次退避」**恰好是**
「+1.88 s/条的加性常量」的形状 ⇒ 那个解释**曾无法排除,原因是记录不够**。

**已修**:span 现记 `attempts` / `http_status` / `last_error`(成功与抛错两条路径都留)。
本工具把那 份记录变成**可回答的问题**。

## ⚠️ 最重要的一条:缺字段 ≠ 零重试

`attempts` 是 **2026-09-14 才加**的 ⇒ 此前所有 trace **没有这个字段**。
若把"字段缺失"当成 `1`,本工具会对那些轮次**斩钉截铁地报"零重试"** ——
那正是**拿记录不足冒充结论**,与它要修的病**同型**。
⇒ 缺字段一律进 `undecidable`(不可判定),**永不**折成 0 或 1。

## 用法

    python3 tools/retry_forensics.py [--trace-dir eval/runs] [--runs ID ...] [--json]

退出码:0 = 全部可判定且零重试 · 1 = 发现重试 **或** 有不可判定的轮次 · 2 = 用法错误

> 为什么"不可判定"也判 1:两者都意味着**不能用"零重试"来解释延迟差异**。
> 把它们分开打(报告里分开写),但**退出码上同为"没排除干净"** ——
> 调用方要的正是这个二值答案。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

#: 只看这一种 span —— 它是被测调用,重试发生在它身上
SPAN_NAME = "sut.call"


def spans_of(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def analyze(run_id: str, spans: list[dict]) -> dict:
    """单个 run 的重试画像。

    `attempts_hist` 的键是**字符串**(要进 JSON);缺字段的 span **不进**这个直方图。
    """
    calls = [s for s in spans if s.get("name") == SPAN_NAME]
    hist: dict[str, int] = {}
    undecidable = 0
    errors: dict[str, int] = {}
    http: dict[str, int] = {}
    retried_durs: list[float] = []
    plain_durs: list[float] = []

    for s in calls:
        a = (s.get("attributes") or {})
        if "attempts" not in a:
            undecidable += 1
            continue
        n = int(a["attempts"])
        hist[str(n)] = hist.get(str(n), 0) + 1
        d = float(s.get("duration_ms") or 0.0)
        (retried_durs if n > 1 else plain_durs).append(d)
        if n > 1:
            if a.get("last_error"):
                errors[str(a["last_error"])] = errors.get(str(a["last_error"]), 0) + 1
            if a.get("http_status") is not None:
                k = str(a["http_status"])
                http[k] = http.get(k, 0) + 1

    # ⚠️ 只要有一条缺字段,整个 run 就是"不可判定" ——
    #    部分证据不能支撑"零重试"这种全称结论。
    is_undecidable = undecidable > 0
    decisive = [s for s in calls if "attempts" in (s.get("attributes") or {})]

    cost = None
    if retried_durs and plain_durs:
        base = statistics.median(plain_durs)
        cost = sum(retried_durs) - len(retried_durs) * base

    return {
        "run_id": run_id,
        "sut_spans": len(calls),
        "decidable": len(decisive),
        "undecidable_spans": undecidable,
        "undecidable": is_undecidable,
        "attempts_hist": hist,
        "retried": sum(1 for s in calls
                       if int((s.get("attributes") or {}).get("attempts", 1)) > 1
                       and "attempts" in (s.get("attributes") or {})),
        "error_codes": errors,
        "http_status": http,
        "retry_cost_ms": None if cost is None else round(cost, 1),
        "no_baseline": bool(retried_durs and not plain_durs),
    }


def render(doc: dict) -> str:
    lines = []
    for r in doc["runs"]:
        lines.append(f"── {r['run_id']} ──")
        lines.append(f"   {SPAN_NAME} span = {r['sut_spans']}"
                     f"(可判定 {r['decidable']} · 缺 attempts 字段 {r['undecidable_spans']})")
        if r["attempts_hist"]:
            hist = " · ".join(f"attempts={k}: {v} 条" for k, v in sorted(r["attempts_hist"].items()))
            lines.append(f"   {hist}")
        if r["undecidable"]:
            lines.append(
                f"   ⚠️ **不可判定** —— 本轮有 {r['undecidable_spans']} 条 span **没有 `attempts` 字段**"
                f"(该字段 2026-09-14 才加,`DEC-015 §7` 的记录缺口)")
            lines.append("       ⇒ 那时**根本没记** —— 与「没发生」是两回事;"
                         "**不能**据此排除重试")
        elif r["retried"] == 0:
            lines.append("   ⇒ **零重试** —— 本轮延迟差异**不可能**由重试解释")
        else:
            lines.append(f"   ⚠️ 有重试:{r['retried']} 条")
            if r["error_codes"]:
                lines.append("      错误码:" + " · ".join(
                    f"{k}×{v}" for k, v in sorted(r["error_codes"].items())))
            if r["http_status"]:
                lines.append("      HTTP 状态:" + " · ".join(
                    f"{k}×{v}" for k, v in sorted(r["http_status"].items())))
            if r["no_baseline"]:
                lines.append("      重试成本:**无法估计** —— 本轮**没有**未重试的样本作基线")
            elif r["retry_cost_ms"] is not None:
                lines.append(f"      重试成本:相对未重试样本**多花 ≈{r['retry_cost_ms']:.0f} ms**"
                             f"(按未重试中位折算)")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="重试取证(回答:这轮慢是不是重试吃掉的?)")
    ap.add_argument("--trace-dir", default="eval/runs", help="trace 目录(默认 eval/runs)")
    ap.add_argument("--runs", nargs="*", default=None, help="只查这些 run_id(默认全部)")
    ap.add_argument("--json", action="store_true", help="机读产物(供批次报告消费)")
    a = ap.parse_args(argv)

    d = Path(a.trace_dir)
    if not d.is_dir():
        print(f"[retry] trace 目录不存在:{d}", file=sys.stderr)
        return 2
    paths = sorted(d.glob("*.trace.jsonl"))
    if a.runs:
        want = set(a.runs)
        paths = [p for p in paths if p.name[: -len(".trace.jsonl")] in want]
    if not paths:
        print(f"[retry] {d} 下没有匹配的 trace(什么都没查到 ≠ 没有重试)",
              file=sys.stderr)
        return 2

    doc = {"runs": [analyze(p.name[: -len(".trace.jsonl")], spans_of(p)) for p in paths]}

    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"[retry] 扫了 {len(doc['runs'])} 份 trace @ {d}\n")
        print(render(doc))

    bad = [r for r in doc["runs"] if r["undecidable"] or r["retried"]]
    n_und = sum(1 for r in bad if r["undecidable"])
    n_ret = sum(1 for r in bad if r["retried"])
    if bad:
        summary = (f"⇒ {len(bad)} 轮**没能排除重试**:其中不可判定 {n_und} · 有重试 {n_ret}")
    else:
        summary = (f"⇒ 全部 {len(doc['runs'])} 轮**零重试且可判定** —— "
                   f"重试可作为延迟差异的解释被排除")
    # ⚠️ `--json` 时总结**走 stderr**:它进 stdout 会把 JSON 污染成"多段拼接",
    #    下游 `json.loads(stdout)` 当场炸(初版即栽在这,被测试抓到)。
    print(summary, file=sys.stderr if a.json else sys.stdout)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
