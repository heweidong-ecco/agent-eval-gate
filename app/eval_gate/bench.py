"""性能度量原语:百分位、span 开销归属、环境指纹、基准六要素。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md:35-39`(QPS/P95/P99/错误率;
「测试要可复现:环境、数据量、参数需记录,支撑前后对比」)。

口径声明(改口径 = 前后不可比,须走 DEC):
- **百分位 = 最近秩法**:`index = ceil(q/100 * n) - 1`,钳制到 `[0, n-1]`;
  小样本下比插值法更保守(不会给出观测中不存在的值)。
- **开销归属**:根 span 的耗时拆成「**直接**子 span 之和(attributed)」与
  「未被 span 覆盖的部分(uncovered = root - attributed)」——
  后者就是**门自身编排开销**,是 L1 该盯的部分。孙节点不重复计(其耗时已含在父里)。
"""
from __future__ import annotations

import math
import os
import platform
import time
from typing import Sequence


def percentile(values: Sequence[float], q: float) -> float:
    """最近秩法百分位(`index = ceil(q/100*n)-1`,钳制到 `[0,n-1]`)。

    空序列或 `q` 越界 → `ValueError`(静默返回 0 会让"没测到"看起来像"很快")。
    不修改入参。
    """
    xs = sorted(values)
    if not xs:
        raise ValueError("percentile 需要非空序列")
    if not 0 <= q <= 100:
        raise ValueError(f"q 须在 [0,100]:{q}")
    idx = max(0, min(len(xs) - 1, math.ceil(q / 100 * len(xs)) - 1))
    return float(xs[idx])


def summarize_latencies(ms: Sequence[float]) -> dict:
    """延迟分布摘要(ms)。空序列 → 全 0(`n=0`,便于直接进报告,不崩)。"""
    xs = list(ms)
    if not xs:
        return {"n": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "max": 0.0, "mean": 0.0}
    return {"n": len(xs), "min": float(min(xs)), "p50": percentile(xs, 50),
            "p95": percentile(xs, 95), "p99": percentile(xs, 99),
            "max": float(max(xs)), "mean": float(sum(xs) / len(xs))}


def attribute_spans(spans) -> dict:
    """把根 span 耗时拆成「直接子 span 之和」与「未被覆盖的编排开销」。

    入参 = `obs.Span` 列表(通常来自 `Tracer.spans`);约定 `spans[0]` 为根。
    同名 span 出现多次(每个 case 一次 `sut.call`)**累加**;孙节点不计入
    (其耗时已含在父节点里,重复计会让占比超 100%)。
    """
    spans = list(spans)
    if not spans:
        return {"root_ms": 0.0, "attributed_ms": 0.0, "uncovered_ms": 0.0, "by_name": {}}
    root = spans[0]
    by_name: dict[str, dict[str, float]] = {}
    for s in spans[1:]:
        if s.parent_span_id != root.span_id:
            continue
        e = by_name.setdefault(s.name, {"ms": 0.0, "share": 0.0})
        e["ms"] += float(s.duration_ms)
    attributed = sum(e["ms"] for e in by_name.values())
    root_ms = float(root.duration_ms)
    for e in by_name.values():
        e["share"] = (e["ms"] / root_ms) if root_ms > 0 else 0.0
    return {"root_ms": root_ms, "attributed_ms": attributed,
            "uncovered_ms": max(0.0, root_ms - attributed), "by_name": by_name}


def env_fingerprint() -> dict:
    """环境指纹(六要素之「环境」)。不含主机名/用户名等可识别信息。"""
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def bench_document(*, evals_file: str, cases: int, params: dict,
                   command: str, measurements: dict, commit: str,
                   started: float | None = None, elapsed_s: float | None = None,
                   version: str = "") -> dict:
    """组装基准数据文档(**六要素**:环境/版本/数据量/参数/时间/命令)。

    六要素缺一,前后两次基准就不可比(B `04-阶段4:39`)—— 故不设默认值,
    强制调用方逐个给出。`measurements` 放本次实测数字。
    """
    return {
        "env": env_fingerprint(),
        "version": {"commit": commit, "gate_version": version},
        "dataset": {"file": evals_file, "cases": cases},
        "params": params,
        "timestamp": {"iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                      "epoch_start": started, "elapsed_s": elapsed_s},
        "command": command,
        "measurements": measurements,
    }
