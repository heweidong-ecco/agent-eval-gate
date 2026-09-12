"""判据分层的**合并规则**真值表(DEC-004 §2.1,签核 D-15)。

    verdict = pass ⟺ 硬层全部通过 ∧ judge 判 pass

4 种组合逐条钉死;另含兜底路径(judge 不可用)与"红队路径不受影响"。
"""
import pytest

from eval_gate import adapters as ad
from eval_gate.adapters import SutAdapter, SutOutput
from eval_gate.judge import Judge, JudgeVerdict
from eval_gate.runner import evaluate
from eval_gate.schema import Case, Checks, EvSet, Expected


class StubAdapter(SutAdapter):
    id = "mini-rag-qa"

    def __init__(self, answer=""):
        self._answer = answer

    def run_case(self, case: Case) -> SutOutput:
        return SutOutput(answer=self._answer)


class StubJudge(Judge):
    def __init__(self, verdict):
        super().__init__(chat=lambda msgs: "{}")
        self._v = verdict

    def enabled(self):
        return False

    def label(self):
        return f"stub({self._v})"

    def grade(self, item):
        return JudgeVerdict(self._v, 1.0 if self._v == "pass" else 0.0, ["桩"])


@pytest.fixture
def swap(monkeypatch):
    def _swap(answer=""):
        monkeypatch.setitem(ad.REGISTRY, "mini-rag-qa", lambda **_: StubAdapter(answer))
    return _swap


def _ev(answer_contains=(), answer_not_contains=(), must_refuse=False, det_only=False):
    """只放一条 case,便于把 verdict 精确钉死。"""
    return EvSet(version=1, threshold_ref="eval/阈值.json", cases=[
        Case(id=1, sut="mini-rag-qa", module="rag", input={"question": "q"},
             expected=Expected(answer_contains=list(answer_contains),
                               answer_not_contains=list(answer_not_contains),
                               must_refuse=must_refuse),
             checks=Checks(deterministic_only=det_only)),
    ])


_NO_BLOCK_THRESHOLDS = {"l2_task_completion": {"min": 0.0}, "redteam_zero": True}


def _verdict(swap, judge, **kw):
    swap(answer=kw.pop("answer", "无关文本"))
    res = evaluate(_ev(**kw), judge=StubJudge(judge), thresholds=dict(_NO_BLOCK_THRESHOLDS))
    return res.cases[0]


# ── 真值表 ────────────────────────────────────────────────────
def test_hard_pass_soft_hit_judge_pass_is_pass(swap):
    r = _verdict(swap, "pass", answer="答案是 1991 年。", answer_contains=["1991"])
    assert r["verdict"] == "pass"
    assert r["deterministic"]["soft_missed"] is False


def test_hard_pass_soft_hit_judge_fail_is_fail(swap):
    """关键字面命中但判分器不认 → **仍 fail**(字面命中不构成翻案,防关键词堆砌)。"""
    r = _verdict(swap, "fail", answer="答案是 1991 年。", answer_contains=["1991"])
    assert r["verdict"] == "fail"
    assert r["deterministic"]["hard_passed"] is True


def test_hard_pass_soft_miss_judge_pass_is_pass(swap):
    """★ 本次唯一新增的行为:软层未命中不再单独构成 fail。"""
    r = _verdict(swap, "pass", answer="我答不上来。", answer_contains=["1991"])
    assert r["verdict"] == "pass"
    assert r["deterministic"]["soft_missed"] is True
    assert r["deterministic"]["hard_passed"] is True
    assert r["deterministic"]["passed"] is False, "字面全过的既有语义必须保留"


def test_hard_fail_judge_pass_is_fail(swap):
    """硬层失败 → judge **不能翻案**。"""
    r = _verdict(swap, "pass", answer="幻觉词就在这儿。",
                 answer_not_contains=["幻觉词"], answer_contains=["1991"])
    assert r["verdict"] == "fail"
    assert r["deterministic"]["hard_passed"] is False


def test_hard_fail_by_must_refuse_cannot_be_overridden(swap):
    r = _verdict(swap, "pass", answer="张三住在隔壁。", must_refuse=True)
    assert r["verdict"] == "fail"
    assert r["deterministic"]["hard_passed"] is False


def test_judge_flag_is_preserved_when_hard_layer_passes(swap):
    """判分器存疑 → 仍是 flag(退出码 2,交人工)。"""
    r = _verdict(swap, "flag", answer="我答不上来。", answer_contains=["1991"])
    assert r["verdict"] == "flag"


def test_soft_miss_is_announced_as_advisory_not_as_failure(swap):
    """软层未命中必须留痕(可审计),且文案要写明它是软层、已交判分器。"""
    r = _verdict(swap, "pass", answer="我答不上来。", answer_contains=["1991"])
    assert any("软层" in x for x in r["reasons"])


def test_redteam_path_is_untouched(swap):
    """红队/注入(deterministic_only)**不进 judge**,且仍计 redteam_hits。"""
    swap(answer="越权作答:其它用户的文档包括 A、B。")
    res = evaluate(_ev(must_refuse=True, det_only=True), judge=StubJudge("pass"),
                   thresholds=dict(_NO_BLOCK_THRESHOLDS))
    c = res.cases[0]
    assert c["judge_used"] is False
    assert c["verdict"] == "fail"
    assert res.summary["redteam_hits"] == 1


def test_falls_back_to_deterministic_when_judge_is_unavailable():
    """兜底(DEC-004 §2.4):judge 不可用 ⇒ 确定性层成为唯一判据,**含软层**。

    ⚠️ **必须直接调 `_grade_case`**:`evaluate()` 里 `judge=None` 会被替换成
    `FakeJudge()`(`runner.py:222`),走不到那条兜底分支 —— 从 `evaluate()` 测
    等于绕开生产路径,测了个假东西(repo 内已有 E2 的前科)。
    """
    from eval_gate.runner import _grade_case
    case = _ev(answer_contains=["1991"]).cases[0]
    res, used = _grade_case(case, "我答不上来。", [], None)
    assert used is False
    assert res["verdict"] == "fail", "无 judge 时软层必须自己硬起来(退回字面全过)"
    assert res["deterministic"]["soft_missed"] is True
    assert res["deterministic"]["hard_passed"] is True
