"""E9 观测契约测试(R3 观测左移;规范 = `observability/trace_id-规范.md` + `日志-schema.md`)。

覆盖 B 阶段3 门禁「全链路 trace_id 贯穿」「观测已左移(有 Trace 视图)」的可验证口径:
① 一次 run 的所有 span 共享同一 trace_id(规范 §6 端到端一致性测试);
② 每条日志必带 trace_id/span_id,一行一 JSON;
③ **日志中不得出现被测回答原文**(需求基线 `:149`)—— 只留 {len, sha8};
④ Trace 视图可渲染;OTLP-JSON 形状合法且 kind 走 OpenInference 属性(不锁仓)。
"""
import io
import json
from pathlib import Path

from eval_gate.cli import main
from eval_gate.judge import FakeJudge
from eval_gate.obs import (KIND_ATTR, Tracer, digest, new_trace_id, read_trace,
                           render_tree, short_trace_id)
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import Case, Checks, EvSet, Expected

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


def _evset(n: int = 3) -> EvSet:
    cases = [Case(id=i, sut="mini-rag-qa", module="rag", tags=[],
                  input={"question": q}, expected=Expected(answer_contains=["1991"]),
                  checks=Checks(), source=None)
             for i, q in enumerate(["Python 哪一年发布?"] * n, 1)]
    return EvSet(version=1, threshold_ref="eval/阈值.md", cases=cases)


def _run(tracer: Tracer):
    return evaluate(_evset(), judge=FakeJudge(), thresholds=default_thresholds(), tracer=tracer)


# --- ① trace_id 全链路一致 -----------------------------------------------------

def test_all_spans_share_one_trace_id():
    tr = Tracer(log_stream=io.StringIO())
    _run(tr)
    assert tr.spans
    assert {s.trace_id for s in tr.spans} == {tr.trace_id}


def test_span_tree_has_root_and_children():
    tr = Tracer(log_stream=io.StringIO())
    _run(tr)
    root = [s for s in tr.spans if s.parent_span_id is None]
    assert len(root) == 1 and root[0].name == "run.evaluate"
    assert root[0].kind == "CHAIN"
    names = {s.name for s in tr.spans}
    assert {"sut.call", "rule.check", "judge.grade"} <= names
    # 每个子 span 都能追溯到根(链路完整,无孤点)
    ids = {s.span_id for s in tr.spans}
    assert all(s.parent_span_id in ids for s in tr.spans if s.parent_span_id)


def test_span_kinds_follow_semantic_convention():
    tr = Tracer(log_stream=io.StringIO())
    _run(tr)
    kinds = {s.name: s.kind for s in tr.spans}
    assert kinds["sut.call"] == "AGENT"       # 外部被测 Agent
    assert kinds["judge.grade"] == "LLM"
    assert kinds["rule.check"] == "CHAIN"


# --- ②③ 结构化日志:字段齐全 + 脱敏 ------------------------------------------

def test_logs_are_one_json_per_line_with_ids():
    stream = io.StringIO()
    tr = Tracer(log_stream=stream)
    _run(tr)
    lines = [l for l in stream.getvalue().splitlines() if l.strip()]
    assert lines
    for line in lines:                        # 一行一事,每行独立 JSON
        rec = json.loads(line)
        assert rec["trace_id"] == tr.trace_id
        assert rec["span_id"]
        assert {"timestamp", "level", "module", "action", "status"} <= set(rec)


def test_logs_never_contain_answer_text():
    """红线:日志只留摘要,原文只在报告里(`需求基线.md:149`)。"""
    stream = io.StringIO()
    tr = Tracer(log_stream=stream)
    res = _run(tr)
    logs = stream.getvalue()
    answer = res.cases[0]["answer"]
    assert answer and answer.strip()
    assert answer not in logs, "日志出现了被测回答原文"
    assert answer[:6] not in logs
    # 相应摘要确实在(证明信息是"被摘要"而非"被丢掉")
    assert digest(answer)["sha8"] in logs


def test_tracer_disabled_is_silent_and_empty():
    stream = io.StringIO()
    tr = Tracer(enabled=False, log_stream=stream)
    _run(tr)
    assert tr.spans == [] and stream.getvalue() == ""


# --- short_trace_id:给人读的短标识 --------------------------------------------

def test_short_trace_id_takes_first_8_of_real_id():
    tid = new_trace_id()
    assert len(tid) == 32
    assert short_trace_id(tid) == tid[:8]


def test_short_trace_id_boundary_exactly_8():
    assert short_trace_id("12345678") == "12345678"


def test_short_trace_id_returns_empty_for_unusable_input():
    """短于 8 位 / 非字符串一律空串,不抛异常(视图渲染不该被坏 id 打断)。"""
    assert short_trace_id("abc") == ""
    assert short_trace_id("") == ""
    assert short_trace_id(None) == ""
    assert short_trace_id(12345678) == ""
    assert short_trace_id(["0123456789"]) == ""


# --- ④ Trace 视图 + OTLP 形状 -------------------------------------------------

def test_trace_view_renders_tree(tmp_path):
    tr = Tracer(log_stream=io.StringIO())
    res = _run(tr)
    p = tr.write_trace(tmp_path / f"{res.run_id}.trace.jsonl")
    spans = read_trace(p)
    view = render_tree(spans, tr.trace_id)
    assert "trace " + tr.trace_id in view
    assert "run.evaluate" in view and "sut.call" in view


def test_otlp_document_shape_and_no_lockin_envelope():
    tr = Tracer(log_stream=io.StringIO())
    _run(tr)
    doc = tr.otlp_document()
    rs = doc["resourceSpans"][0]
    assert rs["resource"]["attributes"][0]["key"] == "service.name"
    spans = rs["scopeSpans"][0]["spans"]
    assert len(spans) == len(tr.spans)
    s = spans[0]
    assert {"traceId", "spanId", "name", "startTimeUnixNano", "status"} <= set(s)
    assert any(a["key"] == KIND_ATTR for a in s["attributes"]), "kind 须走 OpenInference 属性"


def test_export_otlp_is_noop_without_endpoint(monkeypatch):
    monkeypatch.delenv("EVAL_OTLP_ENDPOINT", raising=False)
    tr = Tracer(log_stream=io.StringIO())
    _run(tr)
    assert tr.export_otlp() is False


# --- CLI 端到端:trace 文件 + trace 视图 ---------------------------------------

def test_cli_writes_trace_file_and_renders_view(tmp_path, capsys):
    rc = main(["run", "--evals", str(EVALS), "--mode", "good", "--offline",
               "--report-dir", str(tmp_path)])
    assert rc == 0
    traces = list(tmp_path.glob("*.trace.jsonl"))
    assert len(traces) == 1
    assert read_trace(traces[0])

    rc2 = main(["trace", "--trace-dir", str(tmp_path)])
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "Trace 视图" in out and "run.evaluate" in out


def test_cli_trace_missing_run_returns_usage_error(tmp_path):
    assert main(["trace", "--run", "nope", "--trace-dir", str(tmp_path)]) == 3


# ---- 独立评审(2026-09-11)Critical:错误路径曾泄漏被测响应原文 ----------------

def test_response_body_never_leaks_into_logs_or_trace(tmp_path, monkeypatch):
    """红线回归:被测 4xx 的**响应体**曾被拼进异常消息 → 落 stderr 日志与 `*.trace.jsonl`。

    注入一个含敏感串的 422 响应体(真实场景:FastAPI/pydantic 422 会把请求 `input`
    —— 即被测问题的原文 —— 原样回显),断言该串**不出现在**日志、trace、报告中。

    依据:`observability/日志-schema.md` 规则 1「长文本正文一律不入日志」+
    `需求基线.md:149`(日志禁记录原始敏感)。原有的 happy-path 脱敏测试守不住这条。
    """
    from eval_gate.adapters import REGISTRY, FastApiRagAdapter

    SECRET = "SENSITIVE-CUSTOMER-TEXT-42"
    monkeypatch.setitem(
        REGISTRY, "fastapi-rag",
        lambda **_kw: FastApiRagAdapter(
            base_url="http://x", api_key="k",
            post=lambda url, headers, payload: (
                422, {"detail": [{"loc": ["body", "question"], "msg": "bad", "input": SECRET}]})))

    stream = io.StringIO()
    tr = Tracer(log_stream=stream)
    ev = EvSet(version=1, threshold_ref="eval/阈值.md", cases=[
        Case(id=1, sut="fastapi-rag", module="rag", tags=[], input={"question": SECRET},
             expected=Expected(answer_contains=["x"]), checks=Checks(), source=None)])
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds(), tracer=tr)
    tp = tr.write_trace(tmp_path / "t.trace.jsonl")

    assert SECRET not in stream.getvalue(), "日志出现了被测响应/问题原文"
    assert SECRET not in tp.read_text(encoding="utf-8"), "trace 文件出现了被测响应/问题原文"
    assert SECRET not in json.dumps(res.cases, ensure_ascii=False), "报告(该失败路径)出现了原文"
    assert res.cases[0]["verdict"] == "fail"  # 仍然正确记 fail
