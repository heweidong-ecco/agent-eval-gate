"""E5/E6 端到端:改被测 prompt(quality)→ 评测门拦截劣化(good 过 / bad 拦)。"""
import json
from pathlib import Path

import pytest

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


# ---- 阈值接线:门必须按 eval/阈值.json 的标定值判(而非硬编码演示值)----------

THRESHOLD_JSON = Path(__file__).resolve().parents[1] / "eval" / "阈值.json"


def test_repo_threshold_file_is_wired():
    """本仓标定值必须真的生效:**0.95**(DEC-013,2026-09-13),不是硬编码的兜底值。"""
    thr = default_thresholds()
    assert thr["l2_task_completion"]["min"] == 0.95
    assert thr["redteam_zero"] is True


def test_fallback_is_never_looser_than_the_threshold_file():
    """兜底**永远不得比生效值松** —— 否则"配置读不到"会静默放宽门。

    2026-09-13 发现的真隐患:文件里的 L2 由 0.80 提到 **0.95** 后,兜底若仍停在 0.9,
    就变成**比生效值松**(读不到配置反而更容易过)—— 直接违反
    `eval/阈值.md` / `docs/部署.md`「读不到 → 回落更严兜底,绝不放宽门」的承诺。
    ⇒ 这条把纪律变成结构:改任一侧而不改另一侧,CI 会红。
    """
    from eval_gate.runner import _FALLBACK_THRESHOLDS as FB
    doc = json.loads(THRESHOLD_JSON.read_text(encoding="utf-8"))
    assert FB["l2_task_completion"]["min"] >= doc["l2_task_completion"]["min"], \
        "兜底不得比文件松:min 必须 ≥"
    for k in ("l1_system_error_rate", "l1_gate_overhead_ratio"):
        assert FB[k]["max"] <= doc[k]["max"], f"兜底不得比文件松:{k}.max 必须 ≤"


def test_load_thresholds_strips_underscore_keys(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"_comment": "x", "_basis": "y",
                             "l2_task_completion": {"min": 0.7}, "redteam_zero": False}),
                 encoding="utf-8")
    thr = default_thresholds(p)
    assert thr["l2_task_completion"]["min"] == 0.7 and thr["redteam_zero"] is False
    assert not any(k.startswith("_") for k in thr)


def test_missing_threshold_file_falls_back_stricter(tmp_path, capsys):
    """缺配置时**不得静默放宽**:回落兜底并告警。

    值绑定兜底常量(不写死字面量)—— "兜底够不够严"由
    `test_fallback_is_never_looser_than_the_threshold_file` 单独守。
    """
    from eval_gate.runner import _FALLBACK_THRESHOLDS as FB
    thr = default_thresholds(tmp_path / "nope.json")
    assert thr["l2_task_completion"]["min"] == FB["l2_task_completion"]["min"]
    assert "兜底" in capsys.readouterr().err


def test_corrupt_threshold_file_falls_back_stricter(tmp_path):
    from eval_gate.runner import _FALLBACK_THRESHOLDS as FB
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    assert (default_thresholds(p)["l2_task_completion"]["min"]
            == FB["l2_task_completion"]["min"])


@pytest.mark.parametrize("bad", [
    {"l2_task_completion": 0.85},                 # 该是对象,给了数字 → 曾 AttributeError
    {"l2_task_completion": None},                 # 曾 AttributeError
    {"l2_task_completion": {"min": True}},        # bool 也是 int,须排除
    {"l2_task_completion": {"min": "0.8"}},       # 字符串不是数值
    {"redteam_zero": "yes"},                      # 该是 bool
])
def test_malformed_threshold_shape_falls_back_stricter(tmp_path, capsys, bad):
    """评审 Important:**合法 JSON 但结构写错**曾直接崩,而非按文档承诺回落更严兜底。

    `eval/阈值.md` / `docs/部署.md` 承诺「读不到/不可信 → 回落更严兜底,绝不放宽门」。
    """
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    thr = default_thresholds(p)
    # 值与兜底常量绑定(而非写死字面量)—— 真正的"够不够严"由
    # `test_fallback_is_never_looser_than_the_threshold_file` 守。
    from eval_gate.runner import _FALLBACK_THRESHOLDS as FB
    assert thr["l2_task_completion"]["min"] == FB["l2_task_completion"]["min"], "必须回落兜底"
    assert "形状不合法" in capsys.readouterr().err, "应告警,不静默"


def test_wired_threshold_actually_gates(tmp_path):
    """端到端:把阈值文件设成 1.01 → 即便 good 也被拦,证明判定确实读的是文件。"""
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"l2_task_completion": {"min": 1.01}}), encoding="utf-8")
    ev = load_evals(EVALS)
    res = evaluate(ev, quality="faithful", judge=FakeJudge(), thresholds=default_thresholds(p))
    assert res.exit_code == 1 and res.applied_thresholds["l2_task_completion"]["min"] == 1.01
