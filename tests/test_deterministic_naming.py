"""DEC-015(签核 D-19 / D-24)· 确定性层结论的两个消费面。

**本模块存在的理由 —— 一个边界**:

同一份确定性结论有**两个消费面**,而它们**可以各自独立处置**(是两处独立字面量):

| 面 | 位置 | 处置 |
|---|---|---|
| ① **报告面**(进 `eval/runs/*.local.json` 的 case 结果) | `runner.py:207` / `runner.py:414` | **已改名** `hits` → `issues`(A-safe,2026-09-14) |
| ② **判分器入参**(发给 judge 的 user message) | `runner.py` → `judge.py` **原样 JSON 化** | **已整个去掉**(A2 / 方案 B1,**2026-09-15,收尾批次 D-24**;跑了真实回归) |

### ② 为什么最后是"去掉"而不是"改名"

`DEC-015 §1.2` 三条依据(均由代码支撑):**硬层结论对 judge 毫无用处**
(硬层不过时 `verdict` 直接判 fail,**judge 的意见被覆盖**)· **会锚定**
(看到 `{"passed": false, ...}` 被引导向"这条有问题",而 `DEC-004` 的设计恰是**软层由 judge 独立判断**)·
**字段未解释 + 名字还反向**(未解释的字段本就该最小化)。

⇒ 处置不是"把名字改对",而是**把这个字段从判分器输入里拿掉**。

### 本模块的作用:把契约**双向**钉住

A-safe 时期这里钉的是「② 必须**没**改」;现在是「② 必须**不在**」。
**这不是守卫松了,是契约变了** —— 原先守"别顺手改",现在守"**别顺手加回来**"。
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


def test_judge_input_has_no_deterministic_field(run_both):
    """**守卫(A2 后的新契约)**:判分器入参**根本没有** `deterministic`。

    与 A-safe 时期那条守卫**相反** —— 那时它必须**在**且键名冻结;现在它必须**不在**。
    若有人把它加回来,这条会红 —— 那是提醒你:`DEC-015 §1.2` 的三条依据**仍然成立**
    (硬层结论对 judge 无用 / 会锚定 / 未解释字段),加回来等于把那个问题重新引入。
    """
    _, judge = run_both()
    assert judge.items, "本轮没有调用判分器,用例失去意义"
    for item in judge.items:
        assert "deterministic" not in item, (
            "判分器入参又出现了 deterministic —— DEC-015 方案 B1 已把它整个去掉(签核 D-24)"
        )


def test_build_item_omits_deterministic():
    """`build_item` 是判分器入参的唯一构造器 ⇒ 它**不得**产出该字段。

    (直接钉构造器,而不是只钉"某一次 run 的产物" —— 前者才挡得住新调用点。)
    """
    from eval_gate.judge import build_item
    it = build_item(1, "q", {"answer_contains": ["x"]}, "a", ["s"])
    assert "deterministic" not in it, f"build_item 又产出该字段:{sorted(it)}"


def test_judge_message_has_exactly_the_four_contracted_keys(run_both):
    """**端到端守卫**:发出去的 user 文本**恰好**是那四个键,且顺序固定。

    只看 `item` 的字典**不够** —— `judge.py` 是把它 **JSON 序列化后**拼进 user message 的,
    序列化顺序与键名都会进**文本**。这条直接盯文本,并**逐字**钉住键集与顺序:
    任何"悄悄多塞一个字段"的改动都会在这里现形(未解释字段进提示词是本仓的既有病根)。
    """
    from eval_gate.judge import Judge as _J
    _, judge = run_both()
    text = _J(chat=lambda msgs: "{}")._messages(judge.items[0])[1]["content"]
    got = list(json.loads(text))
    assert got == ["question", "expected", "sut_answer", "sut_sources"], \
        f"判分器可见文本的键集/顺序变了:{got}"


def test_judge_ignores_deterministic_even_when_present():
    """**纵深防御**:即便有人把一个**带 `deterministic` 的 item** 塞进来
    (旧产物 / 外部调用方 / 未来新调用点),发出去的文本里也**不得**出现它。

    为什么要有这一条:`build_item` 只挡住"用它的调用点";
    而 judge 是**可被外部直接构造 item** 的(`cli.py` 的 calibrate 路径即为一例)。
    """
    from eval_gate.judge import Judge as _J
    legacy = {"question": "q", "expected": {}, "sut_answer": "a", "sut_sources": [],
              "deterministic": {"passed": False, "hits": ["未命中任一期望关键点: ['X']"]}}
    text = _J(chat=lambda msgs: "{}")._messages(legacy)[1]["content"]
    assert "deterministic" not in text, "硬层字段泄漏进了判分器可见文本"
    assert "未命中" not in text, "硬层结论的文案泄漏进了判分器可见文本(会锚定 judge)"
