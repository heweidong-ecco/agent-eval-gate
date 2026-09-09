"""E1 评测集装载/校验(contracts/评测-evals-schema.md)。"""
import json

import pytest

from eval_gate.schema import SUPPORTED_SUTS, EvalError, load_evals


def write_json(path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def valid_top() -> dict:
    return {
        "version": 1,
        "threshold_ref": "eval/阈值.md",
        "sut_default": "mini-rag-qa",
        "evals": [
            {
                "id": 1,
                "module": "rag",
                "tags": ["happy-path"],
                "input": {"question": "Python 哪一年发布?"},
                "expected": {"answer_contains": ["1991"]},
            }
        ],
    }


def test_schema_accepts_valid_file_and_resolves_sut_default(tmp_path):
    p = tmp_path / "evals.json"
    write_json(p, valid_top())
    ev = load_evals(p)
    assert ev.version == 1
    assert ev.cases[0].sut == "mini-rag-qa"
    assert ev.cases[0].expected.answer_contains == ["1991"]
    assert ev.cases[0].checks.deterministic_only is False


def test_schema_rejects_invalid_json(tmp_path):
    p = tmp_path / "evals.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_SCHEMA_INVALID"


def test_schema_rejects_duplicate_ids(tmp_path):
    top = valid_top()
    top["evals"].append(dict(top["evals"][0], module="eval"))
    p = tmp_path / "evals.json"
    write_json(p, top)
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_CASE_ID_DUP"


def test_schema_rejects_empty_cases(tmp_path):
    top = valid_top()
    top["evals"] = []
    p = tmp_path / "evals.json"
    write_json(p, top)
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_NO_CASES"


def test_schema_rejects_unknown_sut(tmp_path):
    top = valid_top()
    top["evals"][0]["sut"] = "not-a-sut"
    p = tmp_path / "evals.json"
    write_json(p, top)
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_UNKNOWN_SUT"


def test_schema_requires_machine_rule_for_deterministic_only(tmp_path):
    top = valid_top()
    top["evals"][0]["checks"] = {"deterministic_only": True}
    top["evals"][0]["expected"] = {"answer_contains": ["x"]}  # contains 需语义,不算可判红队规则
    p = tmp_path / "evals.json"
    write_json(p, top)
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_DETERMINISTIC_RULE_MISSING"


def test_schema_accepts_deterministic_only_with_must_refuse(tmp_path):
    top = valid_top()
    top["evals"][0]["checks"] = {"deterministic_only": True}
    top["evals"][0]["expected"] = {"must_refuse": True}
    p = tmp_path / "evals.json"
    write_json(p, top)
    ev = load_evals(p)
    assert ev.cases[0].checks.deterministic_only is True


def test_schema_rejects_empty_expected_when_not_deterministic_only(tmp_path):
    top = valid_top()
    top["evals"][0]["expected"] = {}
    p = tmp_path / "evals.json"
    write_json(p, top)
    with pytest.raises(EvalError) as e:
        load_evals(p)
    assert e.value.code == "E_EXPECTED_EMPTY"


def test_registered_suts_include_mini_rag_qa():
    assert "mini-rag-qa" in SUPPORTED_SUTS
