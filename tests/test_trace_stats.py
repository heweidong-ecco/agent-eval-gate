"""P4-2 · 真实 L1 提取原语。口径复用 bench(最近秩法),不另写一套。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md` §三/§五。
"""
from eval_gate.obs import STATUS_ERROR, STATUS_OK, Span
from eval_gate.trace_stats import error_stats, latency_stats, span_groups, sut_of


def _span(name, ms, status=STATUS_OK, **attrs):
    return Span(trace_id="t", span_id=f"s{ms}", name=name, kind="AGENT",
                duration_ms=float(ms), status=status, attributes=dict(attrs))


def test_span_groups_buckets_by_name():
    spans = [_span("sut.call", 1), _span("judge.grade", 2), _span("sut.call", 3)]
    g = span_groups(spans)
    assert set(g) == {"sut.call", "judge.grade"}
    assert len(g["sut.call"]) == 2


def test_sut_of_reads_attribute_and_tolerates_absence():
    assert sut_of(_span("sut.call", 1, sut="fastapi-rag")) == "fastapi-rag"
    assert sut_of(_span("sut.call", 1)) is None


def test_error_stats_counts_ok_and_error():
    spans = [_span("sut.call", 1), _span("sut.call", 2, status=STATUS_ERROR),
             _span("sut.call", 3), _span("sut.call", 4)]
    got = error_stats(spans, "sut.call")
    assert got == {"n": 4, "n_ok": 3, "n_error": 1, "rate": 0.25}


def test_error_stats_rate_is_None_when_no_sample():
    """⚠️ 防「没测到」被当成「错误率 0」—— 这是本节点最重要的一条判据。"""
    got = error_stats([_span("sut.call", 1)], "judge.grade")
    assert got["n"] == 0
    assert got["rate"] is None


def test_latency_stats_reuses_nearest_rank_and_filters_errors():
    spans = [_span("sut.call", ms) for ms in range(1, 11)]
    spans.append(_span("sut.call", 9999, status=STATUS_ERROR))  # 错误样本须被剔除
    got = latency_stats(spans, "sut.call")
    assert got["n"] == 10
    assert got["p95"] == 10.0          # 最近秩法:ceil(.95*10)-1 = 9 → 10.0
    assert got["max"] == 10.0
