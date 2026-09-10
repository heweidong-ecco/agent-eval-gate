"""E3 确定性规则引擎(contracts/评测-evals-schema expected 语义)。"""
from eval_gate.schema import Case, Checks, Expected
from eval_gate.rules import is_empty_answer, run_deterministic


def case_with(**kw) -> Case:
    base = dict(
        id=1, sut="mini-rag-qa", module="rag", tags=[],
        input={"question": "q"},
        expected=Expected(answer_contains=[], answer_not_contains=[], must_refuse=False),
        checks=Checks(deterministic_only=False), source=None,
    )
    base.update(kw)
    return Case(**base)


def test_must_refuse_true_accepts_refusal_lexicon():
    c = case_with(expected=Expected(must_refuse=True))
    r = run_deterministic(c, "抱歉,资料中没有相关内容。")
    assert r.passed is True and r.hits == []


def test_must_refuse_true_rejects_non_refusal_answer():
    c = case_with(expected=Expected(must_refuse=True))
    r = run_deterministic(c, "张三住在隔壁,他家的猫叫咪咪。")
    assert r.passed is False
    assert any("拒答" in h for h in r.hits)


def test_not_contains_hits_fails():
    c = case_with(expected=Expected(answer_not_contains=["幻觉词XYZ"]))
    r = run_deterministic(c, "答案是幻觉词XYZ没错。")
    assert r.passed is False
    assert r.hits  # 命中禁现词


def test_not_contains_absent_passes():
    c = case_with(expected=Expected(answer_not_contains=["幻觉词XYZ"]))
    r = run_deterministic(c, "干净的答案。")
    assert r.passed is True


def test_contains_any_present_passes():
    c = case_with(expected=Expected(answer_contains=["1991", "1992"]))
    r = run_deterministic(c, "答案是 1992 年。")
    assert r.passed is True


def test_contains_all_absent_fails():
    c = case_with(expected=Expected(answer_contains=["1991"]))
    r = run_deterministic(c, "我答不上来。")
    assert r.passed is False
    assert r.hits


def test_empty_expectations_pass_by_default():
    c = case_with(expected=Expected())
    r = run_deterministic(c, "任意输出")
    assert r.passed is True


def test_is_empty_answer_true_for_blank_and_whitespace():
    assert is_empty_answer("") is True
    assert is_empty_answer("   ") is True
    assert is_empty_answer("\n\t ") is True


def test_is_empty_answer_false_for_non_blank_text():
    assert is_empty_answer("有内容") is False
    assert is_empty_answer("  x ") is False


def test_is_empty_answer_true_for_non_string():
    assert is_empty_answer(None) is True
    assert is_empty_answer(123) is True
    assert is_empty_answer(["a"]) is True
