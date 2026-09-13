"""P4-2 · 真实 L1 基线提取:把已有 trace 统计成可对比的量。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md` §三(成功率/平均耗时/P99)·
§五第 1 条(可复现)· §五第 3 条(L1/L2 分层基线)。

口径声明(**改口径 = 前后不可比,须走 DEC**):
- 分位数**复用** `bench.summarize_latencies`(最近秩法),不另写一套;
- 延迟只取 `status == ok` 的样本(错误样本的耗时不代表正常性能);
- **空样本 → `rate=None`**,绝不返回 0 —— 「没测到」与「错误率 0」必须能分开。
"""
from __future__ import annotations

from typing import Sequence

from .bench import summarize_latencies
from .obs import STATUS_ERROR, STATUS_OK, Span


def span_groups(spans: Sequence[Span]) -> dict[str, list[Span]]:
    out: dict[str, list[Span]] = {}
    for s in spans:
        out.setdefault(s.name, []).append(s)
    return out


def sut_of(span: Span) -> str | None:
    """被测名(`sut.call` 的 `attributes["sut"]`);缺失返回 None(不编造名字)。"""
    v = (span.attributes or {}).get("sut")
    return str(v) if v else None


def error_stats(spans: Sequence[Span], name: str) -> dict:
    """某 span 名的成功/失败计数与错误率。**无样本时 `rate=None`**(不是 0)。"""
    xs = [s for s in spans if s.name == name]
    n_ok = sum(1 for s in xs if s.status == STATUS_OK)
    n_err = sum(1 for s in xs if s.status == STATUS_ERROR)
    n = len(xs)
    return {"n": n, "n_ok": n_ok, "n_error": n_err,
            "rate": (n_err / n) if n else None}


def latency_stats(spans: Sequence[Span], name: str, only_ok: bool = True) -> dict:
    """某 span 名的延迟分布(口径 = `bench.summarize_latencies` 的最近秩法)。"""
    xs = [s for s in spans if s.name == name and (not only_ok or s.status == STATUS_OK)]
    return summarize_latencies([s.duration_ms for s in xs])
