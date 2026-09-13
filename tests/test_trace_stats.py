"""P4-2 · 真实 L1 提取原语。口径复用 bench(最近秩法),不另写一套。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md` §三/§五。
"""
import json
from pathlib import Path

from eval_gate.obs import STATUS_ERROR, STATUS_OK, Span
from eval_gate.trace_stats import (baseline_document, error_stats, latency_stats,
                                   merge_runs, overhead_ratio, span_groups,
                                   summarize_run, sut_of, system_error_rate)


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


# ── 轮级摘要 / 聚合 / 基线文档 ─────────────────────────────────
def _write_trace(tmp_path: Path, run_id: str, spans: list[dict]) -> Path:
    p = tmp_path / f"{run_id}.trace.jsonl"
    p.write_text("\n".join(json.dumps(s) for s in spans), encoding="utf-8")
    return p


def _raw(name, ms, status="ok", attrs=None):
    return {"trace_id": "t", "span_id": f"{name}-{ms}", "name": name,
            "kind": "AGENT", "duration_ms": ms, "status": status,
            "attributes": attrs or {}}


def test_summarize_run_groups_by_sut_and_marks_missing(tmp_path):
    p = _write_trace(tmp_path, "r1", [
        _raw("run.evaluate", 1000.0),
        _raw("sut.call", 100.0, attrs={"sut": "fastapi-rag", "case_id": 1}),
        _raw("sut.call", 300.0, attrs={"sut": "fastapi-rag", "case_id": 2}),
        # 无 judge.grade ⇒ 必须进 missing,而不是算成 0
    ])
    got = summarize_run(p)
    assert got["run_id"] == "r1"
    assert got["cases"] == 2
    assert got["wall_ms"] == 1000.0
    assert got["suts"]["fastapi-rag"]["sut_latency_ms"]["p50"] == 100.0
    assert "judge.grade" in got["missing"]


def test_merge_runs_pools_samples_of_same_sut(tmp_path):
    a = summarize_run(_write_trace(tmp_path, "r1", [
        _raw("sut.call", 10.0, attrs={"sut": "x"}), _raw("sut.call", 20.0, attrs={"sut": "x"})]))
    b = summarize_run(_write_trace(tmp_path, "r2", [
        _raw("sut.call", 30.0, attrs={"sut": "x"})]))
    got = merge_runs([a, b])
    assert got["by_sut"]["x"]["runs"] == 2
    assert got["by_sut"]["x"]["cases"] == 3
    assert got["by_sut"]["x"]["sut_latency_ms"]["max"] == 30.0


def test_merge_runs_recomputes_percentiles_from_pooled_samples(tmp_path):
    """跨轮的原始样本必须**池化后重算** —— 对各轮摘要再平均会得到错的分位数。"""
    a = summarize_run(_write_trace(tmp_path, "r1", [
        _raw("sut.call", 10.0, attrs={"sut": "x"}), _raw("sut.call", 20.0, attrs={"sut": "x"})]))
    b = summarize_run(_write_trace(tmp_path, "r2", [
        _raw("sut.call", 30.0, attrs={"sut": "x"})]))
    got = merge_runs([a, b])
    assert got["by_sut"]["x"]["sut_latency_ms"]["n"] == 3
    assert got["by_sut"]["x"]["sut_latency_ms"]["p50"] == 20.0
    assert "_samples" not in json.dumps(got["runs"], ensure_ascii=False)  # 内部样本不得进产物


def test_baseline_document_carries_basis_and_limitations():
    doc = baseline_document({"by_sut": {}, "runs": []},
                            {"_rev": "2026-09-13", "_basis": "x"})
    assert doc["_rev"] == "2026-09-13"
    assert doc["_limitations"]  # 局限必须随文件走,不能只在报告里


# ── L1 口径(2026-09-13 澄清,见 DEC-012 §2.3)─────────────────────
def test_system_error_rate_excludes_rule_check():
    """⚠️ `rule.check` 的 error 表示「该 case 未过判据」—— 是**评测结论**,不是系统故障。

    按字面把「所有 error span 占比」当错误率,会把「用例没通过」算成「系统出错」。
    """
    spans = [
        _span("sut.call", 100),                                   # ok
        _span("sut.call", 100, status=STATUS_ERROR),              # 系统故障 ✅ 计入
        _span("judge.grade", 100),                                # ok
        _span("judge.grade", 100, status=STATUS_ERROR),           # judge 故障 ✅ 计入
        _span("rule.check", 100, status=STATUS_ERROR),            # 判据未过 ❌ 不计入
        _span("rule.check", 100, status=STATUS_ERROR),
    ]
    got = system_error_rate(spans)
    assert got == {"n": 4, "n_error": 2, "rate": 0.5}


def test_system_error_rate_is_None_when_unmeasurable():
    """无样本 ⇒ None(不是 0)—— 「没测到」不能冒充「错误率 0」。"""
    assert system_error_rate([])["rate"] is None


def test_overhead_ratio_is_gate_own_uncovered_time():
    """门自身编排开销占比 = (根 span − 直接子 span 之和) / 根 span。

    这是 L1 里**唯一"我方可控"**的量(墙钟/被测延迟由外部支配)。
    """
    spans = [
        Span(trace_id="t", span_id="root", name="run.evaluate", kind="CHAIN",
             duration_ms=1000.0, status=STATUS_OK, attributes={}),
        Span(trace_id="t", span_id="a", parent_span_id="root", name="sut.call", kind="AGENT",
             duration_ms=900.0, status=STATUS_OK, attributes={}),
    ]
    got = overhead_ratio(spans)
    assert got["root_ms"] == 1000.0
    assert got["uncovered_ms"] == 100.0
    assert got["ratio"] == 0.1


def test_overhead_ratio_is_None_without_root():
    assert overhead_ratio([])["ratio"] is None


def test_overhead_ratio_finds_run_root_not_first_span():
    """⚠️ 真 CLI 轮次里 **第一个 span 是 `evalset.load`**,`run.evaluate` 在后面。

    第一版直接拿 `spans[0]` 当根(照抄 `bench.attribute_spans` 的约定),
    于是把 `evalset.load`(0.2ms)当成了整轮 ⇒ 占比算成 1.0 ⇒ **误报阻断**。
    """
    spans = [
        Span(trace_id="t", span_id="load", name="evalset.load", kind="CHAIN",
             duration_ms=0.2, status=STATUS_OK, attributes={}),
        Span(trace_id="t", span_id="root", name="run.evaluate", kind="CHAIN",
             duration_ms=1000.0, status=STATUS_OK, attributes={}),
        Span(trace_id="t", span_id="a", parent_span_id="root", name="sut.call", kind="AGENT",
             duration_ms=990.0, status=STATUS_OK, attributes={}),
    ]
    got = overhead_ratio(spans)
    assert got["root_ms"] == 1000.0          # 必须是 run.evaluate,不是 evalset.load
    assert got["uncovered_ms"] == 10.0
    assert got["ratio"] == 0.01


def test_baseline_document_declares_run_to_run_instability():
    """实测发现:同被测同用例集的两轮,sut 总耗时差近 2×。

    这决定了"墙钟"不能当稳定量用 ⇒ 必须随基线文件声明,否则下游会把它当性能保证。
    """
    doc = baseline_document({"by_sut": {}, "runs": []}, {})
    assert any("轮间" in x for x in doc["_limitations"])
