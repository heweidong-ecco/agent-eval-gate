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


def test_soft_miss_rescued_by_judge_is_counted(swap):
    """**软层未命中、judge 救回** → 计数。

    这是本决策(DEC-004 方案 ④)的**作用面**:量化"确定性层错了几次",
    是长期盯判据质量的口径(DEC-004 §3)。
    """
    swap(answer="完全不含期望要点的答案")
    res = _run(StubJudge("pass"))
    assert res.summary["soft_miss_judge_pass"] > 0


def test_zero_when_soft_layer_and_judge_both_miss(swap):
    """软层未命中且 judge 也判 fail → 两者一致,**不计入救回**(否则指标没意义)。"""
    swap(answer="完全不含期望要点的答案")
    res = _run(StubJudge("fail"))
    assert res.summary["soft_miss_judge_pass"] == 0


def test_rule_hit_but_judge_fail_is_counted(swap):
    """字面命中、judge 不认(关键词堆砌 / judge 误判)→ 计数,值得人看。"""
    swap(answer="1991 PostgreSQL 图 向量数据库")
    res = _run(StubJudge("fail"))
    assert res.summary["rule_hit_judge_fail"] > 0


def test_rule_hit_judge_fail_is_announced_not_silent(swap):
    """打架必须**出声**(结构化日志告警)—— 静默的不一致 = 没人会去看。"""
    swap(answer="1991 PostgreSQL 图 向量数据库")
    stream = io.StringIO()
    ev = load_evals(EVALS)
    evaluate(ev, judge=StubJudge("fail"), thresholds=default_thresholds(),
             tracer=Tracer(enabled=True, log_stream=stream))
    logs = stream.getvalue()
    assert "disagree" in logs or "不一致" in logs, "告警未出现在结构化日志里"


def test_cli_summary_names_the_layer_that_blocked(tmp_path, capsys, swap):
    """CLI 摘要必须**当场说清"谁拦的"**,且措辞必须与**分层后的真实语义**一致。

    这一条针对一个真实过程错误:2026-09-12 连续两轮把"确定性层拦下的"误读成
    "判分器判错",而一手字段其实一直在报告里 —— 只是摘要里看不见,于是被跳过。
    ⇒ 修法不是"再加字段",而是**把归属放到你一定会看到的地方**。

    2026-09-12 二次修正(DEC-004 §3,签核 D-15):判据分层后「期望未命中」
    **已不再拦截**(软层交判分器)⇒ 摘要里若还这么说,就是**假话**。故本题既断言
    归属存在,也断言那句假话**不出现**。
    """
    from eval_gate import cli as cli_mod
    swap(answer="完全不含期望要点的答案")
    rc = cli_mod.main(["run", "--evals", str(EVALS), "--offline",
                       "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "判定归属" in out, "摘要未给出判定归属"
    assert "期望未命中" not in out, "④ 之后『期望未命中』已不再拦截,这句话是假话"
    assert "拦下" in out, "必须指名是谁拦的"
    # 红队/注入条目**根本没走 judge**,不能打成"判定归属见报告(judge=None)" —— 那会把人带偏。
    # ⚠️ 断言必须**精确到条目行**:`"红队/注入"` 这个子串在下面的 blocker 行
    # (「redteam_zero 命中: 红队/注入被突破 2 条」)里也有,松断言会**因错误的原因通过**。
    assert "硬层拦下(红队/注入" in out, "deterministic_only 条目必须单独指名(零容忍路径)"
    assert "judge=None" not in out, "红队条目从不走 judge,不该出现 judge=None"
    assert rc != 0


def test_counters_do_not_change_verdict(swap):
    """**计数只观测、不改判定** —— 加观测不得顺手放松/收紧门。

    口径:同一个 case,判分器从 fail 改判 pass,`soft_miss_judge_pass` 必须变化,
    而**阈值判定所读的字段**(`redteam_hits`)不得因此被"顺手"改动。

    ⚠️ 不要在这里断言 exit code:mini 集两条 `deterministic_only` 用例(红队/注入)
    在两种判分下都必然突破 ⇒ `redteam_zero` 阻断 ⇒ **两种情况下 exit 都是 1**。
    合成一个"exit 应随 judge 变化"的期望 = 造一个假断言。
    """
    swap(answer="完全不含期望要点的答案")
    a = _run(StubJudge("fail"))
    swap(answer="完全不含期望要点的答案")
    b = _run(StubJudge("pass"))
    assert a.summary["soft_miss_judge_pass"] == 0
    assert b.summary["soft_miss_judge_pass"] > 0, "判分器改判后计数必须变化"
    assert a.summary["redteam_hits"] == b.summary["redteam_hits"], \
        "计数不得影响红队统计(红队路径与判分器无关)"
