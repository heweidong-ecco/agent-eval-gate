"""端到端(甲):把评测门当被测系统,子进程跑**完整链路**。

链路:装载 → 调被测 → 确定性 → judge → 聚合 → 报告 → trace → exit。
走真进程(不是 in-process `main()`)—— 从**用户实际敲的那条命令**开始,
以**退出码 + 落盘产物**结束,中间不注入任何桩。这样才覆盖 `__main__.py`
与真实的文件系统 / 环境变量 / 进程退出语义。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "eval" / "mini_rag_qa.evals.json"


def _env(**over):
    """按生产默认起环境:观测开着(EVAL_TRACE=1),不读 .env(避免真 judge 被灌入)。"""
    e = dict(os.environ, EVAL_TRACE="1", EVAL_DOTENV="0",
             PYTHONPATH=str(ROOT / "app"))
    e.update(over)
    return e


def _run(*args, timeout=300):
    return subprocess.run([sys.executable, "-m", "eval_gate", *args],
                          capture_output=True, text=True, cwd=str(ROOT),
                          env=_env(), timeout=timeout)


def test_full_chain_exit_0_and_artifacts(tmp_path):
    r = _run("run", "--evals", str(EVALS), "--mode", "good", "--offline",
             "--report-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr

    reports = list(tmp_path.glob("*.local.json"))
    traces = list(tmp_path.glob("*.trace.jsonl"))
    assert reports and traces, "报告或 trace 未落盘"

    doc = json.loads(reports[0].read_text(encoding="utf-8"))
    for key in ("run_id", "judge", "summary", "applied_thresholds", "exit_code", "cases"):
        assert key in doc, f"报告缺字段 {key}"
    assert doc["exit_code"] == 0

    spans = [json.loads(ln) for ln in traces[0].read_text(encoding="utf-8").splitlines() if ln]
    assert spans and len({s["trace_id"] for s in spans}) == 1, "trace_id 未全链路一致"


def test_full_chain_blocks_degraded_sut(tmp_path):
    """劣化被测(--mode bad)→ exit 1,且报告里能看到 blocker。"""
    r = _run("run", "--evals", str(EVALS), "--mode", "bad", "--offline",
             "--report-dir", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "BLOCK" in r.stdout

    doc = json.loads(next(tmp_path.glob("*.local.json")).read_text(encoding="utf-8"))
    assert doc["exit_code"] == 1 and doc["blockers"]
    assert doc["summary"]["redteam_hits"] > 0


def test_trace_subcommand_renders_span_tree(tmp_path):
    r = _run("run", "--evals", str(EVALS), "--mode", "good", "--offline",
             "--report-dir", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    run_id = next(tmp_path.glob("*.local.json")).name.replace(".local.json", "")

    t = _run("trace", "--run", run_id, "--trace-dir", str(tmp_path))
    assert t.returncode == 0, t.stdout + t.stderr
    assert "run.evaluate" in t.stdout
    assert "sut.call" in t.stdout


def test_report_is_not_written_for_crash_path(tmp_path):
    """投毒评测集 → exit 3,且**不产出报告**(没跑出结果就不要留一份像样的产物)。"""
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 1, "evals": []}', encoding="utf-8")
    r = _run("run", "--evals", str(bad), "--offline", "--report-dir", str(tmp_path))
    assert r.returncode == 3
    assert list(tmp_path.glob("*.local.json")) == []


def test_e2e_does_not_leak_answer_text_into_logs(tmp_path):
    """整链路仍须守住脱敏口径:结构化日志(stderr)里任何一条记录都不含长文本。

    口径来自 `observability/日志-schema.md:1`「长文本正文不入日志」+ `需求基线.md:149`。
    回答原文只允许以 `{len, sha8}` 摘要形态出现。
    """
    r = _run("run", "--evals", str(EVALS), "--mode", "good", "--offline",
             "--report-dir", str(tmp_path))
    assert r.returncode == 0

    def _long_strings(node):
        if isinstance(node, str):
            return [node] if len(node) > 300 else []
        if isinstance(node, dict):
            return [s for v in node.values() for s in _long_strings(v)]
        if isinstance(node, list):
            return [s for v in node for s in _long_strings(v)]
        return []

    lines = [ln for ln in r.stderr.splitlines() if ln.strip().startswith("{")]
    assert lines, "stderr 未产出结构化日志(无法证明脱敏)"
    leaked = [s for ln in lines for s in _long_strings(json.loads(ln))]
    assert leaked == [], f"日志出现长文本(疑泄漏原文,{len(leaked)} 处)"
