"""证据归档(DEC-014 §4.1):被引用的 trace ⇒ **脱敏关键 span 摘录**入库。

依据 2026-09-13 灾备演练(`tools/dr_drill.sh`)的首次实测:
trace 只在本地(`.gitignore:24`)⇒ 机器丢失后 **L1 基线无法重算**、报告/复盘引用失效 ⇒ **MTTR 无界**。
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


def test_excerpt_is_enough_to_recompute(tmp_path):
    """**归档摘录必须够重算**:改名回 `.trace.jsonl` 后,统计结果与原 trace **逐字相同**。

    这是归档的全部意义 —— 若重算不出同样的数,归档就只是安慰剂。
    """
    src = ROOT / "eval" / "runs"
    trace = next(iter(sorted(src.glob("*.trace.jsonl"))))
    out = tmp_path / trace.name.replace(".trace.jsonl", ".spans.jsonl")
    p = _run("--trace", str(trace), "--out", str(out))
    assert p.returncode == 0, p.stderr

    sys.path.insert(0, str(ROOT / "app"))
    from eval_gate.trace_stats import summarize_run
    restored = tmp_path / trace.name
    restored.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")

    def _stats(p):
        d = summarize_run(p)
        d.pop("trace", None)      # 路径本身当然不同 —— 比的是**统计量**
        return d

    assert _stats(restored) == _stats(trace), "归档摘录重算不出同样的统计"


def test_excerpt_carries_no_answer_text(tmp_path):
    """摘录里**不得**出现被测答案原文或报告原文 —— 与既有脱敏纪律一致。

    只保留可机读的结构字段(trace/span/name/kind/时长/状态 + 白名单 attributes)。
    """
    src = ROOT / "eval" / "runs"
    trace = next(iter(sorted(src.glob("*.trace.jsonl"))))
    out = tmp_path / "x.spans.jsonl"
    assert _run("--trace", str(trace), "--out", str(out)).returncode == 0

    for raw in out.read_text(encoding="utf-8").splitlines():
        d = json.loads(raw)
        assert set(d) <= {"trace_id", "span_id", "parent_span_id", "name", "kind",
                          "start_time_ms", "duration_ms", "status", "attributes",
                          "error_code"}, \
            f"摘录里出现了白名单外的字段:{sorted(set(d))}"
        assert "answer" not in d.get("attributes", {})
        assert "error" not in d, "error 可能含异常原文,只保留 error_code"
