"""重试取证(`tools/retry_forensics.py`)—— 回答「**这轮慢,是不是重试吃掉的?**」

## 它补的那个洞(2026-09-14 实证,`DEC-015 §7` 同族)

重试**只**出现在 `tracer.log("warn","sut","retry", …)`,而 `Tracer.log()`
**只写 stderr、不落盘**(`obs.py:244`)—— `*.trace.jsonl` **只有 span、没有日志行**。
⇒ **一轮跑完就再也查不出它重试过没有**。

最要命的推论:`sut.call` 全是 `status=ok` **推不出"没重试"** —— **重试后成功的同样是 `ok`**,
而「每条都多吃一次退避」**恰好是「+1.88 s/条的加性常量」的形状**
⇒ 那个解释**曾无法排除,原因是记录不够**,不是因为它不成立。

**已修**:span 现记 `attempts` / `http_status` / `last_error`(成功与抛错两条路径都留)。
本工具把这份记录变成**可回答的问题**。

## ⚠️ 本文件最重要的一条:缺字段 ≠ 零重试

`attempts` 是 **2026-09-14 才加**的 ⇒ 此前所有 trace **没有这个字段**。
若工具把"字段缺失"当成 `1`,它会对那些轮次**斩钉截铁地报"零重试"** ——
而那正是**用记录不足冒充结论**,与它要修的病**同型**。
⇒ 必须有 `unknown` 桶,且**必须显式报出来**。

⚠️ 本文件全部**自造 trace**(不依赖 `eval/runs/`)—— 那些 `.trace.jsonl` 被 gitignore,
CI 上根本不存在(同 `test_archive_evidence.py` 的教训)。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "retry_forensics.py"


def _span(span_id, name, dur, attrs):
    return {"trace_id": "t", "span_id": span_id, "parent_span_id": "root",
            "name": name, "kind": "AGENT", "start_time_ms": 1.0,
            "duration_ms": dur, "status": "ok", "attributes": attrs}


def _write_trace(path: Path, spans):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in spans),
                    encoding="utf-8")
    return path


def _clean_run(n=4, dur=1000.0):
    """零重试:每条 `sut.call` 都带 `attempts=1`。"""
    return [_span(f"s{i}", "sut.call", dur + i, {"case_id": i, "attempts": 1})
            for i in range(n)]


def _retry_storm(n_ok=3, n_retry=2):
    """重试风暴:部分 span `attempts=3` + 错误码,且**明显更慢**(含退避)。"""
    spans = [_span(f"ok{i}", "sut.call", 1000.0 + i, {"case_id": i, "attempts": 1})
             for i in range(n_ok)]
    spans += [_span(f"rt{i}", "sut.call", 5000.0 + i * 100,
                    {"case_id": 100 + i, "attempts": 3,
                     "http_status": 503, "last_error": "E_SUT_5XX"})
              for i in range(n_retry)]
    return spans


def _legacy_run(n=6):
    """旧产物:`sut.call` **完全没有** `attempts` 字段(2026-09-14 之前的形状)。"""
    return [_span(f"old{i}", "sut.call", 1000.0 + i, {"case_id": i}) for i in range(n)]


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def _out(r):
    return r.stdout + r.stderr


# ── ① 零重试 ⇒ 可以**排除**重试这个解释 ────────────────────────────────────

def test_zero_retry_run_excludes_retry_as_an_explanation(tmp_path):
    """全部 `attempts=1` ⇒ 必须给出**可引用的排除结论**,而不是只打印一堆数。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-aaaaaaaa.trace.jsonl", _clean_run())

    r = _run("--trace-dir", str(d))
    assert r.returncode == 0, _out(r)
    assert "零重试" in _out(r), f"没给出排除结论:{_out(r)!r}"


# ── ② 有重试 ⇒ 报出分布与错误码 ───────────────────────────────────────────

def test_retry_storm_is_reported_with_error_codes(tmp_path):
    """重试必须**指名**:多少条、重试到几次、什么错误码。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-bbbbbbbb.trace.jsonl", _retry_storm())

    r = _run("--trace-dir", str(d))
    assert r.returncode == 1, f"有重试却 exit 0:{_out(r)!r}"
    o = _out(r)
    assert "E_SUT_5XX" in o, "没报错误码 —— 只说'有重试'等于没说"
    assert "503" in o, "没报 http_status"
    assert "attempts=3" in o or "'3'" in o or "3 次" in o, f"没报重试到几次:{o!r}"


# ── ③ 缺字段 ⇒ **不可判定**,不得报"零重试" ─────────────────────────────

def test_missing_attempts_field_is_undecidable_not_zero_retry(tmp_path):
    """⚠️ **本文件最重要的一条**。旧 trace 没有 `attempts` 字段 ⇒ 必须判**不可判定**。

    若把缺失当 `1`,工具会对这些轮次报"零重试" —— 而那正是
    **拿记录不足冒充结论**,与它要修的病同型。
    """
    d = tmp_path / "runs"
    _write_trace(d / "20260910-193433-cccccccc.trace.jsonl", _legacy_run())

    r = _run("--trace-dir", str(d))
    o = _out(r)
    assert r.returncode == 1, f"不可判定必须 exit 1(不能与'已排除'同码):{o!r}"
    assert "不可判定" in o or "无法判定" in o, f"没标不可判定:{o!r}"
    assert "零重试" not in o, (
        "把「没有记录」报成了「没有重试」—— 这正是本工具要消灭的那类假结论")


def test_mixed_runs_report_undecidable_bucket_separately(tmp_path):
    """新旧混放 ⇒ 两类**分别**计数,不得混为一谈。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-aaaaaaaa.trace.jsonl", _clean_run())
    _write_trace(d / "20260910-193433-cccccccc.trace.jsonl", _legacy_run())

    r = _run("--trace-dir", str(d))
    o = _out(r)
    assert "20260915-120000-aaaaaaaa" in o and "20260910-193433-cccccccc" in o, \
        f"两个 run 都要出现在报告里:{o!r}"
    assert "零重试" in o and ("不可判定" in o or "无法判定" in o), \
        f"两类结论必须分别出现:{o!r}"
    assert r.returncode == 1, "有不可判定的轮次 ⇒ 不能报全清"


# ── ④ 重试成本:给出可引用的量 ───────────────────────────────────────────

def test_retry_cost_is_estimated_against_non_retried_spans(tmp_path):
    """重试 span 明显更慢时 ⇒ 给出"多花了多少"的估计(与未重试样本比)。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-dddddddd.trace.jsonl", _retry_storm())

    r = _run("--trace-dir", str(d))
    o = _out(r)
    assert "重试成本" in o or "多花" in o, f"没给重试成本估计:{o!r}"


def test_cost_is_reported_as_unestimable_when_no_baseline(tmp_path):
    """**全部** span 都重试过 ⇒ 没有可比基线 ⇒ 必须说"无法估计",不得编一个数。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-eeeeeeee.trace.jsonl",
                 [_span(f"r{i}", "sut.call", 5000.0 + i,
                        {"case_id": i, "attempts": 2}) for i in range(3)])

    r = _run("--trace-dir", str(d))
    assert "无法估计" in _out(r) or "不可估计" in _out(r), \
        f"没有基线却给了个成本数:{_out(r)!r}"


# ── ⑤ 机读产物 ───────────────────────────────────────────────────────────

def test_json_output_is_machine_readable(tmp_path):
    """`--json` 必须产出可解析的结构(供 PR-4 批次报告直接消费)。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260915-120000-bbbbbbbb.trace.jsonl", _retry_storm())

    r = _run("--trace-dir", str(d), "--json")
    doc = json.loads(r.stdout)
    assert doc["runs"], "没有 runs 段"
    one = doc["runs"][0]
    assert one["run_id"] == "20260915-120000-bbbbbbbb"
    assert one["attempts_hist"]["1"] == 3
    assert one["attempts_hist"]["3"] == 2
    assert one["undecidable"] is False
    assert one["error_codes"].get("E_SUT_5XX") == 2


def test_json_marks_legacy_run_undecidable(tmp_path):
    """机读产物也必须区分"零重试"与"没记录" —— 下游不能只看到 0。"""
    d = tmp_path / "runs"
    _write_trace(d / "20260910-193433-cccccccc.trace.jsonl", _legacy_run())

    r = _run("--trace-dir", str(d), "--json")
    one = json.loads(r.stdout)["runs"][0]
    assert one["undecidable"] is True
    assert one["attempts_hist"] == {}, "缺字段不得被填成 1"
