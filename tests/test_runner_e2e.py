"""E5/E6 端到端:改被测 prompt(quality)→ 评测门拦截劣化(good 过 / bad 拦)。"""
from pathlib import Path

from eval_gate.judge import FakeJudge
from eval_gate.runner import RunResult, default_thresholds, evaluate
from eval_gate.schema import load_evals

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


def run(quality: str) -> RunResult:
    ev = load_evals(EVALS)
    return evaluate(ev, quality=quality, judge=FakeJudge(), thresholds=default_thresholds())


def test_good_quality_passes_gate():
    res = run("faithful")
    assert res.exit_code == 0, res.blockers
    assert res.summary["passed"] == res.summary["total"]
    assert res.summary["redteam_hits"] == 0


def test_bad_quality_blocked_by_gate():
    res = run("hallucinate")
    assert res.exit_code == 1
    assert res.summary["passed"] == 0
    assert res.summary["redteam_hits"] > 0
    assert any("redteam" in b or "l2" in b or "任务完成" in b for b in res.blockers)


def test_deterministic_only_cases_skip_judge():
    ev = load_evals(EVALS)
    res = evaluate(ev, quality="faithful", judge=FakeJudge(), thresholds=default_thresholds())
    det = [c for c in res.cases if c["deterministic_only"]]
    assert det and all(c["judge_used"] is False for c in det)
    judged = [c for c in res.cases if not c["deterministic_only"]]
    assert judged and all(c["judge_used"] for c in judged)  # FakeJudge 参与普通用例


def test_impossible_threshold_blocks_even_good():
    ev = load_evals(EVALS)
    thr = default_thresholds()
    thr["l2_task_completion"]["min"] = 1.01  # 永远达不到
    res = evaluate(ev, quality="faithful", judge=FakeJudge(), thresholds=thr)
    assert res.exit_code == 1


def test_redteam_hit_counts_in_report():
    res = run("hallucinate")
    failed_det = [c for c in res.cases if c["deterministic_only"] and c["verdict"] == "fail"]
    assert len(failed_det) == res.summary["redteam_hits"] >= 1
