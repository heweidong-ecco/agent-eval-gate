"""judge 金丝雀(`tools/judge_canary.py`)—— "**该拦的拦**"的证据。

## 为什么必须有它(收尾批次 PR-5 / A2 的验收②)

A2 把 `deterministic` 从判分器输入里拿掉了 ⇒ **改变了判分器看到的东西**。
按本仓纪律,改判分器输入必须跑真实回归 —— 但**一轮回归只能证明"分数没变"**,
而全部轮次都在天花板上(16/16 轮 1.0)⇒ 那一轮**证明不了"该拦的拦"**。

⇒ 金丝雀补的正是这一块:**若干条"必须被拦"的构造答案**,断言 **0 条 pass**。
**没有它,"去掉一个字段没让判分器变松"这件事没有任何证据。**

## ⚠️ 本文件全部零 token

真跑金丝雀要调模型(≈1 万 token,手动,不进 CI —— 它不该在每次 PR 都烧钱)。
本文件用**桩判分器**测**工具自己的逻辑**:它**能不能红**。
(一个"从来没红过"的检查,和没有检查是一回事 —— 本仓 `A5`。)

⇒ **本文件不证明判分器变好了**;它证明的是**金丝雀这杆枪能响**。
  真结论在那次手动运行里。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "judge_canary.py"
FIXTURES = ROOT / "tools" / "judge_canary_cases.json"

sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


class _StubJudge:
    """桩判分器:按预设结论回话,用来测**工具的逻辑**,不碰模型(零 token)。"""

    def __init__(self, verdict, score=None):
        self._v = verdict
        self._s = 1.0 if verdict == "pass" else 0.0
        self.seen: list[dict] = []

    def label(self):
        return "stub"

    def grade(self, item):
        from eval_gate.judge import JudgeVerdict
        self.seen.append(item)
        return JudgeVerdict(self._v, self._s, ["桩"])


def _run_inproc(verdict):
    import judge_canary
    return judge_canary.run(judge_canary.load_cases(FIXTURES), _StubJudge(verdict))


# ── ① 工具必须**能红** ────────────────────────────────────────────────────

def test_canary_goes_red_when_a_bad_answer_passes():
    """**突变验证**:只要有**一条**被判 pass ⇒ 退出码必须非 0。

    没有这条,金丝雀就可能是个"从来没红过"的检查 —— 那它证明不了任何事。
    """
    rc, report = _run_inproc("pass")
    assert rc != 0, f"全被判 pass 却没红:{report}"
    assert report["passed_count"] == len(report["items"])


def test_canary_is_green_only_when_nothing_passes():
    """对照:全部被拦 ⇒ 退出码 0(否则它就是个永远红的检查)。"""
    rc, report = _run_inproc("fail")
    assert rc == 0, report
    assert report["passed_count"] == 0


def test_flag_counts_as_blocked_not_passed():
    """`flag` = 交人复核,**不是 pass**。把它算成放过会让金丝雀虚绿。"""
    rc, report = _run_inproc("flag")
    assert rc == 0, f"flag 被算成了放过:{report}"
    assert report["passed_count"] == 0


# ── ② 金丝雀必须真的打到判分器 ───────────────────────────────────────────

def test_canary_actually_calls_the_judge_for_every_case():
    """每条构造答案都要**真的过一遍判分器** —— 否则"0 条 pass"可能只是没跑。"""
    judge = _StubJudge("fail")
    import judge_canary
    cases = judge_canary.load_cases(FIXTURES)
    judge_canary.run(cases, judge)
    assert len(judge.seen) == len(cases), f"只判了 {len(judge.seen)}/{len(cases)} 条"


def test_canary_sends_no_deterministic_to_the_judge():
    """**与 A2 同一条契约**:金丝雀也不能把确定性层结论塞给判分器。

    (金丝雀是"新调用点"的活样本 —— 它要是塞了,B1 就在新路径上被绕过了。)
    """
    judge = _StubJudge("fail")
    import judge_canary
    judge_canary.run(judge_canary.load_cases(FIXTURES), judge)
    for item in judge.seen:
        assert "deterministic" not in item, "金丝雀把确定性层结论塞给了判分器"


# ── ③ fixture 本身要立得住 ───────────────────────────────────────────────

def test_fixtures_are_wellformed_and_bounded():
    """fixture 必须齐全、id 唯一、**条数 ≤10**(计划书 §六 写死的上限)。

    多出来的字段(尤其 `why`)不是装饰:**每条都要写清"为什么它必须被拦"**,
    否则后人看到一条常年红的金丝雀,会把它当噪声删掉。
    """
    doc = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = doc["cases"]
    assert 0 < len(cases) <= 10, f"条数越界:{len(cases)}"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"id 重复:{ids}"
    for c in cases:
        for k in ("id", "question", "expected", "sut_answer", "why"):
            assert k in c, f"case {c.get('id')} 缺字段 {k}"
        assert c["why"].strip(), f"case {c['id']} 没写为什么必须被拦"


def test_fixtures_cover_the_narrowed_boundary():
    """必须**覆盖 `DEC-009 §4` 刻意收窄的那条边界** —— 堆砌候选词但**答非所问**。

    那条边界是:"拒答语境"才字面即符;**非拒答的答非所问须切题**。
    ⇒ 金丝雀里必须有这类样本,否则**最该被拦的那一类没被测到**。
    """
    doc = json.loads(FIXTURES.read_text(encoding="utf-8"))
    kinds = {c.get("kind") for c in doc["cases"]}
    assert "stacked_non_answer" in kinds, \
        f"缺「堆砌候选词但答非所问」这一类(现有:{sorted(kinds)})"


# ── ④ CLI 可跑(不调模型的那条路)──────────────────────────────────────

def test_cli_rejects_missing_fixtures_with_a_clear_error(tmp_path):
    """fixture 找不到 ⇒ 退出码 2 + 可读信息(**不是 traceback**)。"""
    r = subprocess.run([sys.executable, str(TOOL), "--fixtures", str(tmp_path / "无.json")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in (r.stdout + r.stderr)
