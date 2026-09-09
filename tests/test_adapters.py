"""E2 被测适配器:注册中心 + 归一化输出 + 错误分级枚举。"""
import pytest

from eval_gate.adapters import SutErrorCode, get_adapter, register_adapter, list_adapters
from eval_gate.schema import Case, Checks, Expected


def case_for(q: str) -> Case:
    return Case(
        id=1, sut="mini-rag-qa", module="rag", tags=[],
        input={"question": q},
        expected=Expected(answer_contains=["1991"]),
        checks=Checks(), source=None,
    )


def test_mini_rag_qa_is_registered_and_runs():
    assert "mini-rag-qa" in list_adapters()
    out = get_adapter("mini-rag-qa", quality="faithful").run_case(case_for("Python 哪一年发布?"))
    assert out.answer and "1991" in out.answer
    assert out.sources  # 有检索证据
    assert out.refused is False


def test_adapter_refuses_out_of_scope():
    out = get_adapter("mini-rag-qa", quality="faithful").run_case(
        case_for("谁知道隔壁王老师家在几楼?")
    )
    assert out.refused is True


def test_unknown_adapter_raises_keyerror():
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_sut_error_codes_cover_contract_taxonomy():
    for code in ("E_SUT_TIMEOUT", "E_SUT_5XX", "E_SUT_4XX", "E_SUT_AUTH", "E_SUT_QUOTA", "E_SUT_BAD_RESPONSE"):
        assert code in {c.name for c in SutErrorCode}


def test_register_adapter_roundtrip():
    register_adapter("dummy", lambda **kw: None)
    assert "dummy" in list_adapters()
    # 移除避免污染后续
    from eval_gate import adapters as A
    del A.REGISTRY["dummy"]
