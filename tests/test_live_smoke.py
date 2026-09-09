"""真实模型/真实被测冒烟(env-gated,默认 skip,绝不影响离线套件)。

启用:设 EVAL_LIVE=1,并配置 EVAL_JUDGE_*(真 judge)与
EVAL_SUT_FASTAPI_BASE_URL/API_KEY(真实被测 01.FastAPI RAG Agent 在跑)。
"""
import os

import pytest

from eval_gate.adapters import FastApiRagAdapter
from eval_gate.config import judge_config
from eval_gate.judge import Judge, build_item

LIVE = os.getenv("EVAL_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="EVAL_LIVE=1 才跑真模型冒烟")
def test_real_judge_grades_a_case():
    cfg = judge_config()
    assert cfg.enabled(), "需配 EVAL_JUDGE_BASE_URL/API_KEY/MODEL"
    j = Judge(cfg)
    item = build_item(1, "Python 哪一年发布?", {"answer_contains": ["1991"]}, "答案是 1991 年。")
    v = j.grade(item)
    assert v.verdict in {"pass", "fail", "flag"}
    print(f"real-judge verdict={v.verdict} score={v.score} reasons={v.reasons}")


@pytest.mark.skipif(not LIVE, reason="EVAL_LIVE=1 才跑真实被测冒烟(需被测服务起)")
def test_fastapi_live_rag_smoke():
    a = FastApiRagAdapter()
    from eval_gate.schema import Case, Checks, Expected

    out = a.run_case(Case(id=1, sut="fastapi-rag", module="rag", tags=[],
                          input={"question": "Python 哪一年发布?"},
                          expected=Expected(answer_contains=["1991"]), checks=Checks()))
    assert out.answer
    print(f"fastapi-rag answer={out.answer[:80]} sources={out.sources}")
