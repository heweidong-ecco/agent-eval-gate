"""度量原语:百分位口径、span 开销归属、环境指纹、基准六要素。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md:35-39`
(QPS/P95/P99/错误率 + 「测试要可复现:环境、数据量、参数需记录」)。
"""
import pytest

from eval_gate.bench import (attribute_spans, bench_document, env_fingerprint,
                             percentile, summarize_latencies)
from eval_gate.obs import Span


# ── 百分位口径 ──────────────────────────────────────────────
def test_percentile_uses_nearest_rank_and_clamps():
    """口径 = 最近秩法(index = ceil(q/100*n)-1)。写进 docstring,否则前后不可比。"""
    xs = [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(xs, 50) == 5.0
    assert percentile(xs, 95) == 10.0
    assert percentile(xs, 99) == 10.0
    assert percentile(xs, 0) == 1.0
    assert percentile(xs, 100) == 10.0


def test_percentile_single_value():
    assert percentile([7.0], 99) == 7.0


def test_percentile_rejects_empty_and_bad_q():
    with pytest.raises(ValueError):
        percentile([], 95)
    with pytest.raises(ValueError):
        percentile([1.0], 101)


def test_percentile_does_not_mutate_input():
    xs = [3.0, 1, 2]
    percentile(xs, 50)
    assert xs == [3.0, 1, 2]


# ── 延迟摘要 ────────────────────────────────────────────────
def test_summarize_latencies_shape_and_values():
    s = summarize_latencies([10.0, 20, 30, 40])
    assert set(s) == {"n", "min", "p50", "p95", "p99", "max", "mean"}
    assert s["n"] == 4 and s["min"] == 10.0 and s["max"] == 40.0
    assert s["mean"] == pytest.approx(25.0)


def test_summarize_latencies_empty_is_all_zero_not_crash():
    assert summarize_latencies([])["n"] == 0


# ── span 开销归属 ──────────────────────────────────────────
def _span(name, parent, ms):
    return Span(trace_id="t", span_id=name, name=name, kind="CHAIN",
                parent_span_id=parent, duration_ms=ms)


def test_attribute_spans_splits_root_into_children_and_uncovered():
    root = _span("run.evaluate", None, 100.0)
    spans = [root, _span("sut.call", "run.evaluate", 70.0),
             _span("judge.grade", "run.evaluate", 20.0)]
    a = attribute_spans(spans)
    assert a["root_ms"] == 100.0
    assert a["attributed_ms"] == 90.0
    assert a["uncovered_ms"] == pytest.approx(10.0)
    assert a["by_name"]["sut.call"]["ms"] == 70.0
    assert a["by_name"]["sut.call"]["share"] == pytest.approx(0.7)


def test_attribute_spans_sums_repeated_same_name():
    """同名 span 多次出现(每个 case 一次 sui.call)→ 必须**累加**而不是覆盖。"""
    root = _span("run.evaluate", None, 100.0)
    spans = [root] + [_span("sut.call", "run.evaluate", 10.0) for _ in range(5)]
    a = attribute_spans(spans)
    assert a["by_name"]["sut.call"]["ms"] == pytest.approx(50.0)
    assert a["uncovered_ms"] == pytest.approx(50.0)


def test_attribute_spans_ignores_grandchildren():
    """只算根 span 的**直接**子节点(孙节点的时间已含在其父里,重复计会超 100%)。"""
    root = _span("run.evaluate", None, 100.0)
    spans = [root, _span("sut.call", "run.evaluate", 60.0),
             _span("nested.inner", "sut.call", 60.0)]
    a = attribute_spans(spans)
    assert a["attributed_ms"] == pytest.approx(60.0)
    assert "nested.inner" not in a["by_name"]


def test_attribute_spans_handles_empty():
    a = attribute_spans([])
    assert a["root_ms"] == 0.0 and a["uncovered_ms"] == 0.0 and a["by_name"] == {}


def test_attribute_spans_zero_duration_root_has_zero_share():
    root = _span("run.evaluate", None, 0.0)
    a = attribute_spans([root, _span("sut.call", "run.evaluate", 5.0)])
    assert a["by_name"]["sut.call"]["share"] == 0.0


# ── 环境指纹与六要素 ───────────────────────────────────────
def test_env_fingerprint_has_required_keys():
    e = env_fingerprint()
    for k in ("platform", "python", "machine", "cpu_count"):
        assert k in e and e[k] is not None


def test_driver_produces_six_element_document(tmp_path):
    """驱动级:子进程跑一遍小配置,产物必须含六要素与开销归属。"""
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "bench.json"
    r = subprocess.run([sys.executable, str(root / "tools" / "bench.py"),
                        "--evals", str(root / "eval" / "mini_rag_qa.evals.json"),
                        "--n", "1", "--concurrency", "1", "--inject-sut-ms", "0",
                        "--out", str(out)],
                       capture_output=True, text=True, cwd=str(root), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    for k in ("env", "version", "dataset", "params", "timestamp", "command"):
        assert k in doc, f"六要素缺 {k}"
    cfg = doc["measurements"]["configs"][0]
    assert cfg["throughput_cps"] > 0
    assert cfg["per_case_ms"]["n"] == 1
    assert cfg["gate_own_overhead_ms_per_case"]["p50"] >= 0
    assert "sut.call" in cfg["span_attribution"]


def test_driver_stubs_every_sut_in_the_evalset(tmp_path):
    """golden 集的被测是 `fastapi-rag` —— 桩必须覆盖**评测集实际用到的** sut。

    踩过的坑:只桩住 `mini-rag-qa`,fastapi 就走真实 HTTP + 超时重试退避
    (每 case ~3s),压测静默变成"等超时",600s 连第一个配置都没跑完。
    本用例设了 60s 超时:桩没覆盖到就会超时被抓。
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "bench.json"
    r = subprocess.run([sys.executable, str(root / "tools" / "bench.py"),
                        "--evals", str(root / "eval" / "fastapi_rag_golden.evals.json"),
                        "--n", "1", "--concurrency", "1", "--inject-sut-ms", "0",
                        "--out", str(out)],
                       capture_output=True, text=True, cwd=str(root), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = json.loads(out.read_text(encoding="utf-8"))["measurements"]["configs"][0]
    assert cfg["span_attribution"]["sut.call"]["ms"] >= 0
    # 跑了 40 条 case,且每条都产生了 sut.call span(未被重试拖长)
    assert json.loads(out.read_text(encoding="utf-8"))["dataset"]["cases"] == 40


def test_driver_rejects_bad_concurrency(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "tools" / "bench.py"),
                        "--evals", str(root / "eval" / "mini_rag_qa.evals.json"),
                        "--concurrency", "0", "--out", str(tmp_path / "x.json")],
                       capture_output=True, text=True, cwd=str(root), timeout=120)
    assert r.returncode == 3
    assert "concurrency" in (r.stdout + r.stderr)


def test_bench_document_carries_all_six_elements():
    """B `04-阶段4:39`:环境/版本/数据量/参数/时间/命令 —— 缺一,前后就不可比。"""
    doc = bench_document(evals_file="eval/mini_rag_qa.evals.json", cases=10,
                         params={"concurrency": 1}, command="python tools/bench.py",
                         measurements={"throughput_cps": 1.0}, commit="abc123")
    for k in ("env", "version", "dataset", "params", "timestamp", "command"):
        assert k in doc, f"六要素缺 {k}"
    assert doc["dataset"]["cases"] == 10
    assert doc["version"]["commit"] == "abc123"
    assert doc["measurements"]["throughput_cps"] == 1.0
