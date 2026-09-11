#!/usr/bin/env python3
"""压测/基准采集(离线,零外网)—— 量「门自身开销」与「外部依赖开销」的分离。

用法:
    python tools/bench.py --evals eval/fastapi_rag_golden.evals.json \\
        --n 3 --concurrency 1,2,4 --inject-sut-ms 0,50,200 \\
        --out docs/reports/P4-1/bench-2026-09-11.json

做法:为 `mini-rag-qa` 注册**延迟桩适配器**(只 sleep,不读语料)+ 注入延迟的桩 judge,
用 `Tracer` 采 span,**离线**分离出:
  - `gate_own_overhead_ms_per_case` = 根 span 里**未被任何子 span 覆盖**的部分 / case 数
    → 这是**门自身编排开销**(不含被测与 judge);
  - `span_attribution` = 各子 span(如 `sut.call` / `judge.grade`)的均值耗时与占比。

并发度用**多个独立 `evaluate()` 线程**实现 —— **不改 runner 的串行语义**(那是有契约的)。

⚠️ 本脚本的绝对延迟反映的是**桩**的注入值,不是真实被测/judge 的性能;
它的用途是验证**分离方法**与给出「门自身开销」的量级。真实链路的数字以
`eval/runs/<run_id>.trace.jsonl` 为准(见 docs/reports/P4-1/端到端测试报告.md)。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from eval_gate import __version__ as GATE_VERSION              # noqa: E402
from eval_gate import adapters as ad                           # noqa: E402
from eval_gate.adapters import SutAdapter, SutOutput           # noqa: E402
from eval_gate.bench import (attribute_spans, bench_document,  # noqa: E402
                             summarize_latencies)
from eval_gate.judge import Judge, JudgeVerdict                # noqa: E402
from eval_gate.obs import Tracer                               # noqa: E402
from eval_gate.runner import evaluate                          # noqa: E402
from eval_gate.schema import load_evals                        # noqa: E402


class SleepAdapter(SutAdapter):
    """延迟桩:只按 ms 睡,返回固定答案 —— 用于**分离**门开销与外部开销。

    `quality` 形参是**必需的**:`runner.evaluate` 用 `get_adapter(sut, quality=...)`
    调工厂,少这个形参会 TypeError(阶段3 R0 已在这处栽过一次)。
    """

    id = "mini-rag-qa"

    def __init__(self, ms: float = 0.0, quality: str | None = None):
        self.ms = ms
        self.quality = quality

    def run_case(self, case):
        if self.ms:
            time.sleep(self.ms / 1000.0)
        return SutOutput(answer="桩回答", sources=["s1"])


class SleepJudge(Judge):
    """延迟桩 judge:只按 ms 睡,一律 pass(不参与判分逻辑)。"""

    def __init__(self, ms: float):
        super().__init__(chat=lambda msgs: "{}")
        self.ms = ms

    def enabled(self) -> bool:
        return False

    def label(self) -> str:
        return f"sleep({self.ms}ms)"

    def grade(self, item):
        if self.ms:
            time.sleep(self.ms / 1000.0)
        return JudgeVerdict("pass", 1.0, ["桩"])


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _one_round(ev, sut_ms: float, judge_ms: float, tracer: Tracer) -> float:
    """跑一轮(单线程内),返回 completion。注册表在同一配置下写入同值,无竞态。"""
    res = evaluate(ev, judge=SleepJudge(judge_ms), tracer=tracer)
    return float(res.summary["completion"])


def _sut_ids(ev) -> list[str]:
    """评测集里实际用到的被测 id(去重、保序)。

    ⚠️ 必须**按评测集取**,不能写死 `mini-rag-qa`:golden 集的被测是 `fastapi-rag`,
    只桩住 mini 的话,fastapi 会走**真实 HTTP + 超时重试退避**(每 case ~3s),
    压测会静默变成"等超时"(实测踩过:600s 没跑完第一个配置)。
    """
    seen: list[str] = []
    for c in ev.cases:
        if c.sut not in seen:
            seen.append(c.sut)
    return seen


def _measure_config(ev, sut_ms: float, judge_ms: float, k: int, n: int) -> dict:
    cases = len(ev.cases)
    per_unit_ms: list[float] = []       # 每轮摊到单个并发单元的墙钟
    overhead_per_case: list[float] = []
    by_name_sum: dict[str, float] = {}
    root_total = 0.0
    samples = 0
    total_wall_ms = 0.0

    for sut_id in _sut_ids(ev):
        ad.REGISTRY[sut_id] = lambda **_: SleepAdapter(sut_ms)

    for _ in range(n):
        tracers = [Tracer(enabled=True) for _ in range(k)]
        threads = [threading.Thread(target=_one_round, args=(ev, sut_ms, judge_ms, t))
                   for t in tracers]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall_ms = (time.perf_counter() - t0) * 1000.0
        total_wall_ms += wall_ms
        per_unit_ms.append(wall_ms / k)           # 摊到每个并发单元
        for tr in tracers:
            a = attribute_spans(tr.spans)
            samples += 1
            root_total += a["root_ms"]
            overhead_per_case.append(a["uncovered_ms"] / cases if cases else 0.0)
            for name, v in a["by_name"].items():
                by_name_sum[name] = by_name_sum.get(name, 0.0) + v["ms"]

    total_cases = cases * n * k
    return {
        "throughput_cps": round(total_cases / max(total_wall_ms / 1000.0, 1e-9), 3),
        "per_case_ms": summarize_latencies([m / cases for m in per_unit_ms] if cases else []),
        "batch_wall_ms_per_unit": summarize_latencies(per_unit_ms),
        "gate_own_overhead_ms_per_case": summarize_latencies(overhead_per_case),
        "span_attribution": {
            name: {"ms": round(ms / samples, 3),
                   "share": round(ms / root_total, 4) if root_total else 0.0}
            for name, ms in sorted(by_name_sum.items())
        },
        "_samples": samples,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="压测/基准采集(离线)")
    ap.add_argument("--evals", required=True)
    ap.add_argument("--n", type=int, default=3, help="每个配置重复轮数")
    ap.add_argument("--concurrency", default="1", help="并发度列表,逗号分隔")
    ap.add_argument("--inject-sut-ms", default="0", help="被测注入延迟(ms)列表")
    ap.add_argument("--inject-judge-ms", default="0", help="judge 注入延迟(ms)列表")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    try:
        ev = load_evals(args.evals)
    except Exception as e:                                  # noqa: BLE001
        print(f"[bench] 评测集不可用: {e}", file=sys.stderr)
        return 3
    if args.n < 1:
        print("[bench] --n 至少 1", file=sys.stderr)
        return 3

    try:
        concs = [int(x) for x in args.concurrency.split(",") if x.strip()]
        suts = [float(x) for x in args.inject_sut_ms.split(",") if x.strip()]
        judges = [float(x) for x in args.inject_judge_ms.split(",") if x.strip()]
    except ValueError as e:
        print(f"[bench] 参数列表解析失败: {e}", file=sys.stderr)
        return 3
    if not concs or min(concs) < 1:
        print("[bench] --concurrency 须为 ≥1 的整数列表", file=sys.stderr)
        return 3

    t_start = time.perf_counter()
    configs = []
    for sut_ms in suts:
        for judge_ms in judges:
            for k in concs:
                c = _measure_config(ev, sut_ms, judge_ms, k, args.n)
                c.update({"concurrency": k, "inject_sut_ms": sut_ms,
                          "inject_judge_ms": judge_ms})
                configs.append(c)
                print(f"[bench] K={k} sut={sut_ms}ms judge={judge_ms}ms "
                      f"-> {c['throughput_cps']} case/s, "
                      f"门自身开销/case p50={c['gate_own_overhead_ms_per_case']['p50']}ms")

    doc = bench_document(
        evals_file=args.evals, cases=len(ev.cases),
        params={"concurrency": concs, "inject_sut_ms": suts,
                "inject_judge_ms": judges, "n_per_config": args.n},
        command="python " + " ".join(sys.argv[1:]),
        measurements={"configs": configs},
        commit=_commit(), version=GATE_VERSION,
        started=t_start, elapsed_s=round(time.perf_counter() - t_start, 3),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[bench] 基准数据: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
