"""判定归属:tell「谁拦的」,并在两套判据打架时出声。

**动机(2026-09-12 实证)**:某条 case 连续两轮被判 fail,我两次把根因归成"判分器误判" ——
而真相是**确定性层**判的 fail(期望候选缺一种措辞形态)。错误的来源不是数据缺失,
而是**报告只存了合并后的 verdict,没存"确定性层怎么判"与"judge 怎么判"**,只能凭现象推断。

⇒ 本模块即那处结构:① 报告可分辨**谁拦的**;② 两套判据**不一致**时**出声**(不改判定)。
"""
import io
import json

import pytest

from eval_gate import adapters as ad
from eval_gate.adapters import SutAdapter, SutOutput
from eval_gate.judge import Judge, JudgeVerdict
from eval_gate.obs import Tracer
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import Case, Checks, Expected, load_evals
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


class StubAdapter(SutAdapter):
    """固定返回同一个答案,便于精确控制"命中 / 未命中期望"。"""

    id = "mini-rag-qa"

    def __init__(self, answer="", quality=None):
        self._answer = answer

    def run_case(self, case: Case) -> SutOutput:
        return SutOutput(answer=self._answer)


class StubJudge(Judge):
    """固定 verdict 的桩 judge。"""

    def __init__(self, verdict: str):
        super().__init__(chat=lambda msgs: "{}")
        self._v = verdict
        self.calls = 0

    def enabled(self) -> bool:
        return False

    def label(self) -> str:
        return f"stub({self._v})"

    def grade(self, item):
        self.calls += 1
        return JudgeVerdict(self._v, 1.0 if self._v == "pass" else 0.0, ["桩"])


@pytest.fixture
def swap(monkeypatch):
    def _swap(answer=""):
        monkeypatch.setitem(ad.REGISTRY, "mini-rag-qa", lambda **_: StubAdapter(answer))
    return _swap


def _run(judge):
    ev = load_evals(EVALS)
    return evaluate(ev, judge=judge, thresholds=default_thresholds())


def test_report_records_both_layers_separately(swap):
    """报告必须能分辨**谁拦的**:确定性层判定 与 judge 判定 分开记录。"""
    swap(answer="随便答一句,不含任何期望要点")
    res = _run(StubJudge("pass"))
    for r in res.cases:
        if r.get("judge_used"):
            assert "judge_verdict" in r, "带 judge 的条目必须记录 judge 自己的判定"
            assert "deterministic" in r, "必须记录确定性层判定"
            break
    else:
        pytest.fail("本轮没有走 judge 的条目,用例失去意义")


def test_rule_fail_but_judge_pass_is_counted_as_disagreement(swap):
    """**确定性层判 fail 而 judge 判 pass** = 两套判据打架 → 必须计数。

    这个形状恰恰是"期望候选漏了一种措辞"(测到语义对、但字面没命中)的信号 ——
    2026-09-12 那次归因错误,若当时有这个计数就会立刻看见。
    """
    swap(answer="完全不含期望要点的答案")
    res = _run(StubJudge("pass"))
    assert res.summary["rule_judge_disagreements"] > 0


def test_agreement_is_zero_when_layers_agree(swap):
    """两套判据一致时,计数必须为 0(否则这个指标没有意义)。"""
    ev = load_evals(EVALS)
    # 让被测返回**所有期望要点都不命中**的答案,而 judge 也判 fail → 两者一致
    swap(answer="完全不含期望要点的答案")
    res = _run(StubJudge("fail"))
    assert res.summary["rule_judge_disagreements"] == 0


def test_disagreement_is_announced_not_silent(swap):
    """不一致必须**出声**(结构化日志告警)—— 静默的不一致 = 没人会去看。"""
    swap(answer="完全不含期望要点的答案")
    stream = io.StringIO()
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=StubJudge("pass"), thresholds=default_thresholds(),
                   tracer=Tracer(enabled=True, log_stream=stream))
    assert res.summary["rule_judge_disagreements"] > 0
    logs = stream.getvalue()
    assert "disagree" in logs or "不一致" in logs, "告警未出现在结构化日志里"


def test_cli_summary_states_who_blocked_each_failing_case(tmp_path, capsys, swap):
    """CLI 摘要必须**当场说清"谁拦的"** —— 不让人从 verdict 反推。

    这一条针对的是一个真实过程错误:2026-09-12 连续两轮把"确定性层拦下的"误读成
    "判断器判错",而一手字段其实一直在报告里 —— 只是摘要里看不见,于是被跳过。
    ⇒ 修法不是"再加字段",而是**把归属放到你一定会看到的地方**。
    """
    from eval_gate import cli as cli_mod
    swap(answer="完全不含期望要点的答案")
    rc = cli_mod.main(["run", "--evals", str(EVALS), "--offline",
                       "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "判定归属" in out, "摘要未给出判定归属"
    assert "确定性层拦下" in out
    assert rc != 0


def test_disagreement_does_not_change_verdict(swap):
    """**只观测、不改判定**:计数出现，但 exit 语义仍由既有规则决定。

    这是硬约束 —— 加观测不能顺手把门放松或收紧。
    """
    swap(answer="完全不含期望要点的答案")
    res_fail = _run(StubJudge("fail"))
    swap(answer="完全不含期望要点的答案")
    res_pass = _run(StubJudge("pass"))
    assert res_fail.exit_code == res_pass.exit_code, "judge 的判定不应改变本用例的 exit 语义"
