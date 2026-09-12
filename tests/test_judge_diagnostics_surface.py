"""T7 · 判分器诊断信息进入**产物**(DEC-006 A3/A4)。

为什么单独一个文件:判分器自身测得再好,若诊断信息**不进 trace / 不进 run JSON / 不进摘要**,
下一个人仍然只能靠"再花一轮 token 复现"来归因 —— 这正是 2026-09-12 那次排查的处境
(`docs/复盘/2026-09-12-门自身判分器预算缺陷.md` 错误 #2)。
"""
import io
import json
from pathlib import Path

from eval_gate import report
from eval_gate.config import JudgeConfig
from eval_gate.judge import Judge
from eval_gate.obs import Tracer
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import Case, Checks, EvSet, Expected

VALID = '{"verdict":"pass","score":1,"reasons":["命中"],"evidence_refs":[],"labels":[]}'
EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


def _cfg(**kw):
    base = dict(base_url="http://127.0.0.1:9", api_key="k", model="m",
                timeout_s=1, max_tokens=512, retries=1)
    base.update(kw)
    return JudgeConfig(**base)


def _evset(n: int = 1) -> EvSet:
    cases = [Case(id=i, sut="mini-rag-qa", module="rag", tags=[],
                  input={"question": "Python 哪一年发布?"},
                  expected=Expected(answer_contains=["1991"]),
                  checks=Checks(), source=None) for i in range(1, n + 1)]
    return EvSet(version=1, threshold_ref="eval/阈值.md", cases=cases)


def _truncating_judge():
    """第一次尝试被截断、第二次成功 —— 即真实观测到的那个形状。"""
    seen: list = []

    def chat(msgs, max_tokens=None):
        seen.append(max_tokens)
        if len(seen) == 1:
            return "", {"total_tokens": 1}, "length"
        return VALID, {"total_tokens": 1}, "stop"

    return Judge(_cfg(max_tokens=512), chat=chat)


def _run(judge, tracer=None):
    return evaluate(_evset(1), judge=judge, thresholds=default_thresholds(), tracer=tracer)


# ── A3 · trace span 里要看得见"这条为什么走了两次" ──────────
def test_judge_grade_span_carries_attempt_diagnostics():
    tr = Tracer(log_stream=io.StringIO())
    _run(_truncating_judge(), tracer=tr)
    span = next(s for s in tr.spans if s.name == "judge.grade")
    assert span.attributes["attempts"] == 2
    assert span.attributes["finish_reasons"] == "length,stop"


def test_clean_case_span_shows_single_attempt():
    """顺利的一条也记 —— 否则"没有诊断字段"与"没发生异常"分不开。"""
    tr = Tracer(log_stream=io.StringIO())
    j = Judge(_cfg(), chat=lambda msgs: (VALID, {"total_tokens": 1}, "stop"))
    _run(j, tracer=tr)
    span = next(s for s in tr.spans if s.name == "judge.grade")
    assert span.attributes["attempts"] == 1
    assert span.attributes["finish_reasons"] == "stop"


# ── A4 · run JSON 里要看得见"实际用的什么预算" ─────────────
def test_run_result_carries_effective_judge_config(tmp_path):
    j = Judge(_cfg(max_tokens=4096), chat=lambda msgs: (VALID, {"total_tokens": 1}, "stop"))
    res = _run(j)
    assert res.judge_config["max_tokens"] == 4096
    doc = json.loads(report.write_run(res, tmp_path, "ev.json", j.label()).read_text())
    assert doc["judge_config"]["max_tokens"] == 4096
    assert doc["judge_config"]["model"] == "m"
    assert doc["judge_config"]["retries"] == 1


def test_offline_run_records_no_judge_config():
    """离线替身没有"生效预算",不得凭空编一个 —— 产物里宁缺勿假。"""
    from eval_gate.judge import FakeJudge

    assert _run(FakeJudge()).judge_config is None


# ── A3 · 摘要要能一眼看出"被重试掩盖的失败" ────────────────
def test_judge_accounting_flags_hidden_retries():
    """`calls` 比用例数多 ⇒ 那几次是**被重试掩盖的失败**,必须显式点出来(复盘 R4)。"""
    line = report.judge_accounting(
        {"calls": 47, "parse_failures": 2, "truncated": 1, "parse_flags": 1}, judged_cases=45)
    assert "47" in line and "45" in line
    assert "多出 2" in line
    assert "截断 1" in line and "解析 2" in line


def test_judge_accounting_is_quiet_when_nothing_retried():
    line = report.judge_accounting(
        {"calls": 45, "parse_failures": 0, "truncated": 0, "parse_flags": 0}, judged_cases=45)
    assert "多出" not in line
    assert "⚠️" not in line


def test_judge_accounting_tolerates_missing_counters():
    """旧产物 / 替身没有新计数键 —— 不得抛错(否则读旧 run 就崩)。"""
    assert report.judge_accounting({"calls": 3}, judged_cases=3)


# ── A3/A4 · 人看的那一行(CLI 摘要)────────────────────────
def test_cli_summary_shows_effective_budget_and_accounting(tmp_path, monkeypatch, capsys):
    """诊断信息还得**出现在人读的摘要里** —— 只写进 JSON 等于没写。

    用桩 judge 注入(不碰 .env 的真 key:历史教训 E5 —— 真 key 会被灌回并发起真调用)。
    """
    import eval_gate.cli as cli
    from eval_gate.config import JudgeConfig
    from eval_gate.judge import JudgeVerdict

    class _Stub:
        usage = {"calls": 2, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                 "retries": 1, "parse_failures": 1, "truncated": 1, "parse_flags": 0}

        def label(self):
            return "stub@local"

        def enabled(self):
            return True

        def effective_config(self):
            return {"model": "stub", "base_url": "local", "max_tokens": 4096,
                    "retries": 1, "timeout_s": 60.0}

        last_diagnostics: dict = {}

        def grade(self, item):
            return JudgeVerdict("pass", 1.0, ["ok"])

    monkeypatch.setattr(cli, "judge_config",
                        lambda: JudgeConfig(base_url="http://x", api_key="k", model="stub"))
    monkeypatch.setattr(cli, "Judge", lambda cfg: _Stub())

    rc = cli.main(["run", "--evals", str(EVALS), "--mode", "good",
                   "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "生效 judge 配置" in out and "max_tokens=4096" in out
    assert "judge 记账: 调用 2" in out
