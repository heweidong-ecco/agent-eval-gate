"""E2 fastapi-rag 真实被测适配器(01.FastAPI RAG Agent /rag/search)。

离线:注入 post 桩,不发真实网络。契约见 contracts/评测-sut-adapter.md。
"""
import json

import pytest

from eval_gate.adapters import FastApiRagAdapter, SutAdapterError, SutErrorCode, list_adapters
from eval_gate.schema import Case, Checks, Expected


def case_for(q: str) -> Case:
    return Case(id=1, sut="fastapi-rag", module="rag", tags=[],
                input={"question": q}, expected=Expected(answer_contains=["x"]),
                checks=Checks(), source=None)


def _ok_response():
    return {
        "answer": "Python 于 1991 年发布。",
        "sources": [{"id": "doc-1", "source": "s1", "content_preview": "…"}],
        "docs": [{"content": "…", "source": "s1", "similarity": 0.9}],
        "pipeline": "accurate", "timing": {},
    }


def test_registered_in_registry():
    assert "fastapi-rag" in list_adapters()


def test_fastapi_adapter_builds_request_and_maps_response():
    captured = {}

    def post(url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return 200, _ok_response()

    a = FastApiRagAdapter(base_url="http://sut.example:8000", api_key="k-test", post=post)
    out = a.run_case(case_for("Python 哪一年发布?"))

    assert "/api/v1/rag/search" in captured["url"]
    assert "mode=accurate" in captured["url"]
    assert captured["payload"]["question"] == "Python 哪一年发布?"
    assert captured["payload"]["generate_answer"] is True
    assert captured["payload"]["top_k"] == 3
    # 契约 contracts/评测-sut-adapter.md:39「header 鉴权(X-API-Key 或 JWT)」——
    # 被测把 Bearer 一律当 JWT 验签,故 API Key 必须走 X-API-Key(R0 纠错)。
    assert captured["headers"]["X-API-Key"] == "k-test"
    assert "Authorization" not in captured["headers"]
    assert out.answer == "Python 于 1991 年发布。"
    assert out.sources == ["doc-1"]
    assert out.raw["docs"]


def test_fastapi_adapter_maps_403_quota_to_typed_error():
    def post(url, headers, payload):
        return 403, {"detail": "Free quota exhausted"}

    a = FastApiRagAdapter(base_url="http://sut.example:8000", api_key="k", post=post)
    with pytest.raises(SutAdapterError) as e:
        a.run_case(case_for("q"))
    assert e.value.code == SutErrorCode.E_SUT_QUOTA


def test_fastapi_adapter_maps_401_auth_to_typed_error():
    def post(url, headers, payload):
        return 401, {"detail": "unauthorized"}

    a = FastApiRagAdapter(base_url="http://sut.example:8000", api_key="k", post=post)
    with pytest.raises(SutAdapterError) as e:
        a.run_case(case_for("q"))
    assert e.value.code == SutErrorCode.E_SUT_AUTH


def test_fastapi_adapter_bad_200_shape_fails():
    def post(url, headers, payload):
        return 200, {"answer": None}

    a = FastApiRagAdapter(base_url="http://sut.example:8000", api_key="k", post=post)
    with pytest.raises(SutAdapterError) as e:
        a.run_case(case_for("q"))
    assert e.value.code == SutErrorCode.E_SUT_BAD_RESPONSE
