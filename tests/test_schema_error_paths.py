"""评测集投毒:畸形结构必须【零模型调用即失败】(红队靶子④)。

靶子定义见 docs/specs/P4-1-测试与压测.md §6-4;
纪律见 app/eval_gate/schema.py 模块 docstring 与 contracts/评测-evals-schema.md。
"""
import json
from pathlib import Path

import pytest

from eval_gate.schema import EvalError, load_evals


def _write(tmp_path: Path, doc) -> Path:
    p = tmp_path / "poisoned.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def _base(evals):
    return {"version": 1, "threshold_ref": "eval/阈值.md",
            "sut_default": "mini-rag-qa", "evals": evals}


def _case(**over):
    c = {"id": 1, "module": "rag", "input": {"question": "q"},
         "expected": {"answer_contains": ["a"]}}
    c.update(over)
    return c


@pytest.mark.parametrize("doc,code", [
    ([], "E_SCHEMA_INVALID"),                                     # 顶层非对象
    ({"version": "1", "threshold_ref": "x", "evals": [_case()]}, "E_SCHEMA_INVALID"),
    ({"version": 1, "evals": [_case()]}, "E_THRESHOLD_REF_MISSING"),
    ({"version": 1, "threshold_ref": "x", "evals": []}, "E_NO_CASES"),
    ({**_base([_case()]), "sut_default": "ghost-sut"}, "E_UNKNOWN_SUT"),
    (_base([_case(sut="ghost-sut")]), "E_UNKNOWN_SUT"),
    (_base([_case(module="nope")]), "E_SCHEMA_INVALID"),
    (_base([{"id": "x", "module": "rag", "input": {"question": "q"},
             "expected": {"answer_contains": ["a"]}}]), "E_SCHEMA_INVALID"),
    (_base([_case(input={})]), "E_SCHEMA_INVALID"),
    (_base([_case(input={"question": "   "})]), "E_SCHEMA_INVALID"),
    (_base([_case(expected=[])]), "E_SCHEMA_INVALID"),
    (_base([_case(expected={"answer_contains": [1, 2]})]), "E_SCHEMA_INVALID"),
    (_base([_case(checks=["x"])]), "E_SCHEMA_INVALID"),           # 真值非对象
    (_base([_case(), _case()]), "E_CASE_ID_DUP"),
    (_base([_case(checks={"deterministic_only": True}, expected={"answer_contains": ["a"]})]),
     "E_DETERMINISTIC_RULE_MISSING"),
    (_base([_case(expected={})]), "E_EXPECTED_EMPTY"),
])
def test_poisoned_evalset_fails_with_contract_code(tmp_path, doc, code):
    with pytest.raises(EvalError) as ei:
        load_evals(_write(tmp_path, doc))
    assert ei.value.code == code


def test_structurally_valid_but_huge_input_loads_without_io(tmp_path):
    """合法但超长的 input:装载必须成功且**不触碰任何 I/O**(门级断言在 CLI 侧)。"""
    huge = "长" * 200_000
    ev = load_evals(_write(tmp_path, _base([_case(input={"question": huge})])))
    assert len(ev.cases) == 1 and len(ev.cases[0].input["question"]) == 200_000


def test_non_json_file_is_schema_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvalError) as ei:
        load_evals(p)
    assert ei.value.code == "E_SCHEMA_INVALID"


def test_unreadable_path_is_schema_invalid(tmp_path):
    with pytest.raises(EvalError) as ei:
        load_evals(tmp_path / "nope.json")
    assert ei.value.code == "E_SCHEMA_INVALID"
