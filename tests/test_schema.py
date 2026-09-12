"""E1 评测集装载/校验(contracts/评测-evals-schema.md)。"""
import json

import pytest

from pathlib import Path

from eval_gate.schema import SUPPORTED_SUTS, EvalError, count_modules, load_evals


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
    assert "fastapi-rag" in SUPPORTED_SUTS  # 契约 评测-evals-schema.md:26 的 sut 枚举


GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "fastapi_rag_golden.evals.json"


def test_real_sut_golden_evalset_loads():
    """R2a 转档产物必须可装载:37 条 golden + 3 条自造对抗(签核 D-10e)
    + 8 条 boundary 扩充(2026-09-12,DEC-005)。"""
    ev = load_evals(GOLDEN)
    assert ev.sut_default == "fastapi-rag"
    # 集合构成**写清来源**,不写裸数字 —— 扩充时改这里,能一眼看出是哪一批。
    assert len(ev.cases) == 37 + 3 + 8
    assert all(c.sut == "fastapi-rag" for c in ev.cases)
    # 拒答类:10(转档)+ 3(对抗/越权)+ 1(boundary id=46 苹果创始人)= 14
    assert sum(1 for c in ev.cases if c.expected.must_refuse) == 10 + 3 + 1
    det = [c for c in ev.cases if c.checks.deterministic_only]
    assert [c.id for c in det] == [38, 39, 40], "红队/越权须走确定性引擎,不进 judge"
    assert all(c.source for c in ev.cases), "转档须逐条标 source(可回溯)"


def test_count_modules_empty_returns_empty_dict():
    assert count_modules([]) == {}


def test_count_modules_counts_per_module():
    """按 module 计数 —— 断言**比例关系**,不写死条数(集合会扩充,写死即变过期常量)。"""
    ev = load_evals(GOLDEN)
    counts = count_modules(ev.cases)
    assert set(counts) == {"rag", "eval"}
    assert sum(counts.values()) == len(ev.cases)
    assert counts["eval"] == 3 == sum(1 for c in ev.cases if c.module == "eval")


def test_count_modules_skips_nothing_when_module_repeats(tmp_path):
    top = valid_top()
    top["evals"].append(dict(top["evals"][0], id=2, input={"question": "另一问"}))
    top["evals"].append(dict(top["evals"][0], id=3, module="tool-mcp", input={"question": "第三问"}))
    p = tmp_path / "evals.json"
    write_json(p, top)
    assert count_modules(load_evals(p).cases) == {"rag": 2, "tool-mcp": 1}
