"""E2 fastapi-rag 的**快照取法**(总纲 D-5:HTTP/快照/回放)。

被测服务不在时(如本机 Docker 起不来),用被测真实产出的快照做离线真实数据评测;
契约 `评测-sut-adapter.md:42` 要求首跑自带可复现的控制变量,故快照入库(`eval/snapshots/`)。
"""
from pathlib import Path

import pytest

from eval_gate.adapters import FastApiRagAdapter, SutAdapterError, SutErrorCode, load_snapshot
from eval_gate.schema import Case, Checks, Expected

SNAP = Path(__file__).resolve().parents[1] / "eval" / "snapshots" / "fastapi_rag_2026-06-29.json"


def case_for(q: str) -> Case:
    return Case(id=1, sut="fastapi-rag", module="rag", tags=[],
                input={"question": q}, expected=Expected(answer_contains=["x"]),
                checks=Checks(), source=None)


def test_snapshot_loads_and_is_unique():
    snap = load_snapshot(SNAP)
    assert len(snap) == 37
    assert all(r.get("question") for r in snap.values())


def test_snapshot_adapter_replays_real_answer():
    a = FastApiRagAdapter(snapshot=SNAP)
    out = a.run_case(case_for("Python 是一门什么样的编程语言？"))
    assert "解释型" in out.answer
    assert out.sources and all(s.startswith("snapshot:") for s in out.sources)
    assert out.meta["source"] == "snapshot"


def test_snapshot_adapter_marks_refusal_outputs():
    a = FastApiRagAdapter(snapshot=SNAP)
    out = a.run_case(case_for("多用户数据隔离如何实现？"))   # 快照中被测回「无法回答」
    assert out.refused is True


def test_snapshot_uncovered_question_fails_closed():
    """缺证据不放行:快照未覆盖 → 记 fail,而非静默跳过或假绿。"""
    a = FastApiRagAdapter(snapshot=SNAP)
    with pytest.raises(SutAdapterError) as e:
        a.run_case(case_for("快照里绝对没有的某个问题？"))
    assert e.value.code == SutErrorCode.E_SUT_BAD_RESPONSE
    assert "快照未覆盖" in str(e.value)


def test_snapshot_takes_precedence_over_http():
    """设了快照就不发网络请求(注入 post 桩若被调用即失败)。"""
    def boom(url, headers, payload):
        raise AssertionError("设了快照不应发 HTTP")

    a = FastApiRagAdapter(snapshot=SNAP, post=boom)
    assert a.run_case(case_for("FastAPI 是什么？")).answer
