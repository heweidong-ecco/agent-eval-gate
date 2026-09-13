"""P4-2 · `eval-gate stats`:从已有 trace 产机读 L1 基线(零 token)。"""
import json

from eval_gate.cli import main


def _mk(tmp_path, run_id, spans):
    (tmp_path / f"{run_id}.trace.jsonl").write_text(
        "\n".join(json.dumps(s) for s in spans), encoding="utf-8")


def test_stats_writes_baseline(tmp_path):
    _mk(tmp_path, "r1", [
        {"trace_id": "t", "span_id": "a", "name": "run.evaluate", "kind": "CHAIN",
         "duration_ms": 500.0, "status": "ok", "attributes": {}},
        {"trace_id": "t", "span_id": "b", "name": "sut.call", "kind": "AGENT",
         "duration_ms": 100.0, "status": "ok", "attributes": {"sut": "fastapi-rag"}},
    ])
    out = tmp_path / "l1.json"
    rc = main(["stats", "--runs", "r1", "--trace-dir", str(tmp_path), "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["by_sut"]["fastapi-rag"]["cases"] == 1
    assert doc["_limitations"]


def test_stats_records_env_fingerprint(tmp_path):
    """B §五第 1 条:环境需记录,支撑前后对比 —— 跨机器比吞吐时必须先看它。"""
    _mk(tmp_path, "r1", [
        {"trace_id": "t", "span_id": "b", "name": "sut.call", "kind": "AGENT",
         "duration_ms": 100.0, "status": "ok", "attributes": {"sut": "x"}}])
    out = tmp_path / "l1.json"
    assert main(["stats", "--runs", "r1", "--trace-dir", str(tmp_path), "--out", str(out)]) == 0
    env = json.loads(out.read_text(encoding="utf-8"))["_env"]
    assert env["cpu_count"] and env["python"]


def test_stats_missing_run_returns_3_and_does_not_write(tmp_path):
    out = tmp_path / "l1.json"
    rc = main(["stats", "--runs", "nope", "--trace-dir", str(tmp_path), "--out", str(out)])
    assert rc == 3
    assert not out.exists()      # 不静默产空基线


def test_stats_accepts_glob(tmp_path):
    _mk(tmp_path, "20260912-aaa", [
        {"trace_id": "t", "span_id": "b", "name": "sut.call", "kind": "AGENT",
         "duration_ms": 100.0, "status": "ok", "attributes": {"sut": "x"}}])
    out = tmp_path / "l1.json"
    rc = main(["stats", "--runs", "20260912-*", "--trace-dir", str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["by_sut"]["x"]["cases"] == 1
