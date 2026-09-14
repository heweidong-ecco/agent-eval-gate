"""DEC-015(签核 D-19)· 确定性层结论的字段命名:`hits` → `issues`。

**本模块存在的理由 —— 一个边界**:

同一份确定性结论有**两个消费面**,而它们**可以各自独立改名**(是两处独立字面量):

| 面 | 位置 | 改名的后果 |
|---|---|---|
| ① **报告面**(进 `eval/runs/*.local.json` 的 case 结果) | `runner.py:207` / `runner.py:414` | 只我们自己读 ⇒ **安全** |
| ② **判分器入参**(发给 judge 的 user message) | `runner.py:223` → `judge.py:234` **原样 JSON 化** | **改了 = 改 judge 输入** ⇒ 按本仓纪律须跑真实回归(≈3 万 token) |

字段名 `hits` 与其内容(**全是问题**)方向相反,该改;但 ② 一改就不是"零行为变化"了。
⇒ 决策:**本次只改 ①**,② 并进方案 B(B 本来就要跑回归,一次覆盖两处)。

⇒ 因此本模块**两头都钉**:① 必须已改名;② **必须还没改** —— 防未来有人"顺手一起改",
   把一件零 token 的事悄悄变成一件需要回归的事(这正是本仓反复复盘的那类错误:
   改动的影响面**没有出现在改动的人眼前**)。
"""
import json
from pathlib import Path

import pytest

from eval_gate import adapters as ad
from eval_gate.adapters import SutAdapter, SutOutput
from eval_gate.judge import Judge, JudgeVerdict
from eval_gate.rules import run_deterministic
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import Case, Checks, Expected, load_evals

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


def _case(**kw) -> Case:
    base = dict(
        id=1, sut="mini-rag-qa", module="rag", tags=[],
        input={"question": "q"},
        expected=Expected(answer_contains=[], answer_not_contains=[], must_refuse=False),
        checks=Checks(deterministic_only=False), source=None,
    )
    base.update(kw)
    return Case(**base)


# ── ① RuleResult(两个面的共同上游)────────────────────────────────────

def test_rule_result_carries_issues_not_hits():
    """字段叫 `issues`(问题清单)—— 与其内容同向。

    反例(旧名):`hits` 读作"命中",而里面装的是"应拒答却输出实质内容""未命中期望"…
    **名字与方向相反**;其中一条文案里还带"命中"、另一条带"未命中",单看名字无法推断方向。
    """
    c = _case(expected=Expected(must_refuse=True))
    r = run_deterministic(c, "张三住在隔壁,他家的猫叫咪咪。")
    assert r.passed is False
    assert r.issues, "新名 issues 应承载问题清单"
    assert any("拒答" in s for s in r.issues)


def test_old_name_hits_is_gone():
    """旧名**移除**,不留又名又留 —— 两套名字并存比名字错更难查。"""
    c = _case(expected=Expected(must_refuse=True))
    r = run_deterministic(c, "张三住在隔壁。")
    assert not hasattr(r, "hits"), "旧名 hits 仍在 ⇒ 改名只做了一半"


def test_empty_issues_when_all_layers_pass():
    """全过时为空 —— 与旧语义一致(改名不得改变行为)。"""
    c = _case(expected=Expected(answer_contains=["猫"]))
    r = run_deterministic(c, "他家的猫叫咪咪")
    assert r.issues == []


# ── ② 报告面:case 结果里的 deterministic 子对象 ───────────────────────

class _StubAdapter(SutAdapter):
    id = "mini-rag-qa"

    def __init__(self, answer=""):
        self._answer = answer

    def run_case(self, case: Case) -> SutOutput:
        return SutOutput(answer=self._answer)


class _CapturingJudge(Judge):
    """记住**判分器实际收到的那份 item**,用于钉住入参契约。"""

    def __init__(self):
        super().__init__(chat=lambda msgs: "{}")
        self.items: list[dict] = []

    def enabled(self) -> bool:
        return False

    def label(self) -> str:
        return "capturing"

    def grade(self, item):
        self.items.append(item)
        return JudgeVerdict("pass", 1.0, ["桩"])


@pytest.fixture
def run_both(monkeypatch):
    """跑一轮,同时拿到**报告条目**与**判分器入参**,供两个面分别断言。"""
    def _run(answer="完全不含期望要点的答案"):
        monkeypatch.setitem(ad.REGISTRY, "mini-rag-qa", lambda **_: _StubAdapter(answer))
        judge = _CapturingJudge()
        res = evaluate(load_evals(EVALS), judge=judge, thresholds=default_thresholds())
        return res, judge
    return _run


def test_report_side_uses_issues(run_both):
    """报告面已改名为 `issues`(旧名 `hits` 不得再出现在报告条目里)。"""
    res, _ = run_both()
    checked = 0
    for r in res.cases:
        d = r.get("deterministic")
        assert d is not None, "报告条目必须带 deterministic 子对象"
        assert "issues" in d, f"报告面未改名:case id={r.get('id')} 的键是 {sorted(d)}"
        assert "hits" not in d, f"报告面旧名残留:case id={r.get('id')}"
        checked += 1
    assert checked > 0, "没有条目被检查到,用例失去意义"


def test_judge_input_key_is_still_hits(run_both):
    """**守卫**:判分器入参的键**仍是 `hits`** —— 本轮**刻意未改**(见模块 docstring)。

    改它 = 改 judge 的 user message = 改判分器输入 ⇒ 必须跑真实回归(DEC-015 方案 B)。
    若有人把它一起改了,这条会红 —— 那是**提醒你去报备预算并跑回归**,不是让你改这条断言。
    """
    _, judge = run_both()
    assert judge.items, "本轮没有调用判分器,用例失去意义"
    for item in judge.items:
        d = item["deterministic"]
        assert "hits" in d, (
            "判分器入参的键被改了 —— 这属于 DEC-015 方案 B,须先报备预算并跑 eval 回归"
        )
        assert "issues" not in d, "判分器入参不该出现新名(那是方案 B 的范围)"


def test_judge_user_message_bytes_unchanged_by_this_rename(run_both):
    """**端到端守卫**:判分器**真正收到的那串 JSON 文本**在本次改名前后逐字不变。

    上面那条只看 `item` 的字典键;而 `judge.py:234` 是把它 **JSON 序列化后**拼进
    user message 的 —— 序列化顺序、键名都可能影响文本。这条直接盯**文本本身**。
    """
    from eval_gate.judge import Judge as _J
    _, judge = run_both()
    item = judge.items[0]
    text = json.dumps({
        "question": item.get("question"), "expected": item.get("expected"),
        "sut_answer": item.get("sut_answer"), "sut_sources": item.get("sut_sources", []),
        "deterministic": item.get("deterministic", {}),
    }, ensure_ascii=False)
    assert '"hits"' in text, "判分器可见文本里应仍是 hits"
    assert '"issues"' not in text, "判分器可见文本不应出现 issues"
