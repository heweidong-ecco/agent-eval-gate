"""零 token 复现**真实样本** —— T1 那条 id=19 的两轮原文(DEC-004 §6.5,签核 D-15)。

不是造数据:两段答案**逐字**取自 `eval/runs/` 的落盘产物 ——
- `20260912-002123-0d20f24e.local.json`(第 4 轮,暴露出"软层误杀"的那一轮)
- `20260911-224254-be1c4574.local.json`(第 1 轮,被测**真拒答**,本就不该 pass)

⚠️ `.local.json` **不入库**(只有 `.summary.md` 入库),故此处**硬编码**原文,
不得在运行时去读 run 文件 —— 那会让测试在干净克隆上失效。
候选逐字取自 `eval/fastapi_rag_golden.evals.json` 的 id=19。
"""
from eval_gate.rules import run_deterministic
from eval_gate.schema import Case, Checks, Expected

# 逐字取自 eval/fastapi_rag_golden.evals.json id=19
_EXPECTED = ["用户ID", "用户 ID", "用户id", "用户 id", "用户的ID", "用户的 id"]

# 逐字取自 run 20260912-002123-0d20f24e(该 run 记录里 id=19 的 answer 字段)
_ANSWER_ROUND4 = (
    "多用户数据隔离可以通过在所有查询和修改时都带上当前用户的 ID 进行过滤来实现。[来源:1]"
)

# 逐字取自 run 20260911-224254-be1c4574(该 run 记录里 id=19 的 answer 字段)
_ANSWER_REFUSAL = "根据现有资料，无法回答。"


def _case() -> Case:
    return Case(id=19, sut="fastapi-rag", module="rag",
                input={"question": "多用户数据隔离如何实现？"},
                expected=Expected(answer_contains=list(_EXPECTED)),
                checks=Checks(deterministic_only=False))


def test_round4_wording_misses_the_soft_layer_but_not_the_hard_layer():
    """第 4 轮:软层未命中(候选表覆盖不到「的+空格+大写 ID」),**硬层通过**。

    ⇒ 在 ④ 之下,这条由判分器定夺 —— 而那一轮判分器自己判的是 pass
    (该 run 记录的 reasons 里明写「…应判 pass」),故该条由 fail 变 pass。
    """
    r = run_deterministic(_case(), _ANSWER_ROUND4)
    assert r.hard_passed is True, "这条从来不是硬层问题 —— judge 不能翻案的前提是硬层通过"
    assert r.soft_missed is True, "候选表确实覆盖不到该措辞(这就是 T1 的根因)"
    assert r.passed is False, "字面全过的既有语义仍应为 False"


def test_round1_refusal_also_misses_the_soft_layer():
    """第 1 轮:被测**真拒答** —— 但注意:该条**不是** `must_refuse` 用例,
    所以拒答本身不构成硬层失败;它同样只是"软层未命中"。
    """
    r = run_deterministic(_case(), _ANSWER_REFUSAL)
    assert r.hard_passed is True, "该条不是 must_refuse 用例,拒答不触发硬层"
    assert r.soft_missed is True


def test_the_two_rounds_are_indistinguishable_by_the_soft_layer():
    """把两轮并排:**确定性层无法区分它们** —— 这正是要把 `answer_contains`
    交给判分器(语义判据)的原因,也是 DEC-004 方案 ④ 的直接依据。
    """
    r4 = run_deterministic(_case(), _ANSWER_ROUND4)
    r1 = run_deterministic(_case(), _ANSWER_REFUSAL)
    assert (r4.hard_passed, r4.soft_missed) == (r1.hard_passed, r1.soft_missed)
