"""证据归档(DEC-014 §4.1):被引用的 trace ⇒ **脱敏关键 span 摘录**入库。

依据 2026-09-13 灾备演练(`tools/dr_drill.sh`)的首次实测:
trace 只在本地(`.gitignore:24`)⇒ 机器丢失后 **L1 基线无法重算**、报告/复盘引用失效 ⇒ **MTTR 无界**。

⚠️ **本文件必须自造 trace,不许依赖 `eval/runs/` 的真实产物** ——
那些 `.trace.jsonl` **被 gitignore**,CI 上根本不存在。
(2026-09-13 的真实教训:初版 glob 本地 trace,本地绿、**CI 红 `StopIteration`**。
⇒ 判据不能依赖"我机器上恰好有的东西"。)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "archive_evidence.py"


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def _write_trace(path: Path) -> Path:
    """造一条**合成 trace**:含统计需要的字段,也含**必须被剥掉**的敏感字段。"""
    spans = [
        {"trace_id": "t", "span_id": "root", "name": "run.evaluate", "kind": "CHAIN",
         "start_time_ms": 1.0, "duration_ms": 1000.0, "status": "ok",
         "attributes": {"evals_version": 1}},
        {"trace_id": "t", "span_id": "s1", "parent_span_id": "root", "name": "sut.call",
         "kind": "AGENT", "start_time_ms": 2.0, "duration_ms": 600.0, "status": "ok",
         "attributes": {"case_id": 1, "sut": "fastapi-rag",
                        # ⚠️ 敏感:必须被剥掉
                        "answer": "被测答案原文,绝不该进 git"}},
        {"trace_id": "t", "span_id": "j1", "parent_span_id": "root", "name": "judge.grade",
         "kind": "LLM", "start_time_ms": 3.0, "duration_ms": 300.0, "status": "ok",
         "attributes": {"case_id": 1, "verdict": "pass", "attempts": 1,
                        "finish_reasons": "stop", "judge": "x@y"}},
        {"trace_id": "t", "span_id": "r1", "parent_span_id": "root", "name": "rule.check",
         "kind": "CHAIN", "start_time_ms": 4.0, "duration_ms": 0.1, "status": "error",
         "attributes": {"case_id": 1, "passed": False},
         "error": {"code": "E_TEST", "msg": "异常原文也不该进 git"}},
    ]
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in spans),
                    encoding="utf-8")
    return path


def test_excerpt_is_enough_to_recompute(tmp_path):
    """**归档摘录必须够重算**:改名回 `.trace.jsonl` 后统计**逐字一致**。

    这是归档的全部意义 —— 若重算不出同样的数,归档就只是安慰剂。
    """
    trace = _write_trace(tmp_path / "r1.trace.jsonl")
    out = tmp_path / "r1.spans.jsonl"
    assert _run("--trace", str(trace), "--out", str(out)).returncode == 0

    sys.path.insert(0, str(ROOT / "app"))
    from eval_gate.trace_stats import summarize_run
    # ⚠️ 恢复时必须**保留原文件名**:`summarize_run` 的 `run_id` 取自文件名
    # (初版改名成 restored.trace.jsonl ⇒ run_id 跟着变 ⇒ 比不过,是**测试**的错)
    restore_dir = tmp_path / "restored"
    restore_dir.mkdir()
    restored = restore_dir / trace.name
    restored.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")

    def _stats(p):
        d = summarize_run(p)
        d.pop("trace", None)      # 路径本身当然不同 —— 比的是**统计量**
        return d

    assert _stats(restored) == _stats(trace), "归档摘录重算不出同样的统计"


def test_excerpt_carries_no_answer_text(tmp_path):
    """摘录里**不得**出现被测答案原文 / 异常原文 —— 与既有脱敏纪律一致。"""
    trace = _write_trace(tmp_path / "r1.trace.jsonl")
    out = tmp_path / "r1.spans.jsonl"
    assert _run("--trace", str(trace), "--out", str(out)).returncode == 0

    text = out.read_text(encoding="utf-8")
    assert "被测答案原文" not in text, "答案原文泄漏进归档"
    assert "异常原文" not in text, "异常原文泄漏进归档"
    for raw in text.splitlines():
        d = json.loads(raw)
        assert set(d) <= {"trace_id", "span_id", "parent_span_id", "name", "kind",
                          "start_time_ms", "duration_ms", "status", "attributes",
                          "error_code"}, f"摘录里出现了白名单外的字段:{sorted(set(d))}"
        assert "answer" not in d.get("attributes", {})


def test_missing_source_returns_3(tmp_path):
    """源 trace 不存在 ⇒ exit 3(不静默产出空归档)。"""
    assert _run("--trace", str(tmp_path / "没有.jsonl"),
                "--out", str(tmp_path / "o.jsonl")).returncode == 3
