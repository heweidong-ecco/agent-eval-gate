"""M3 · 第二家被测 `ai-field-delivery-toolkit` 的适配器(E2)。

两家两家形态(同 `/prototype/run` 入口,`template` 不同):
- `toolkit-qa`      → `knowledge_qa`(RAG 检索问答,**带引用 + sources**)
- `toolkit-extract` → `information_extraction`(**结构化文本**抽取)

零 token:全程注入 `post`,不发真实请求。
契约:`contracts/评测-sut-adapter.md`(错误分级同 fastapi-rag)。
"""
import json
import urllib.error

import pytest

from eval_gate.adapters import (REGISTRY, SutAdapterError, SutErrorCode,
                                ToolkitExtractAdapter, ToolkitQaAdapter,
                                get_adapter)
from eval_gate.schema import SUPPORTED_SUTS, Case, Checks, Expected


def _case(q="判分器为什么需要足够的 token 预算？", module="rag"):
    return Case(id=1, sut="toolkit-qa", module=module, tags=[],
                input={"question": q}, expected=Expected(answer_contains=["x"]),
                checks=Checks(), source=None)


def _ok_post(result="答:……[1]", sources=None, capture=None):
    def post(url, headers, payload):
        if capture is not None:
            capture.append({"url": url, "payload": payload})
        return 200, {"template": "knowledge_qa", "result": result, "llm_mode": "llm",
                     "sources": sources if sources is not None else [
                         {"chunk": "…", "score": 0.59, "distance": 0.40, "source": "kb1"}]}
    return post


# ── 出参归一化 ──────────────────────────────────────────────
def test_qa_adapter_maps_answer_and_sources():
    out = ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb1", post=_ok_post()).run_case(_case())
    assert out.answer == "答:……[1]"
    assert out.sources, "sources 必须归一化 —— 来源类判据要它"
    assert all(isinstance(s, str) for s in out.sources)


def test_sources_are_short_ids_not_full_chunk_text():
    """**长文本正文不入日志**(observability/日志-schema.md:1)—— sources 要给短标识,不是整段分块。"""
    long_chunk = "很长的分块正文" * 50
    out = ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb1",
                           post=_ok_post(sources=[{"chunk": long_chunk, "source": "kb1"}])).run_case(_case())
    assert all(len(s) < 40 for s in out.sources), f"sources 过长:{out.sources}"
    assert long_chunk not in " ".join(out.sources)


# ── 组请求:两种形态 ────────────────────────────────────────
def test_qa_adapter_sends_qa_template_with_kb():
    cap = []
    ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb-probe",
                     post=_ok_post(capture=cap)).run_case(_case())
    assert cap[0]["url"].endswith("/prototype/run")
    body = cap[0]["payload"]
    assert body["template"] == "knowledge_qa"
    assert body["user_input"] == _case().input["question"], "问题要放进 user_input"
    assert body["kb_run_id"] == "kb-probe", "QA 形态必须带 kb_run_id,否则不走 RAG"


def test_extract_adapter_uses_extraction_template_and_omits_kb():
    """⚠️ `create_extract_agent()` **不接受 kb_run_id**(传了 TypeError → 500)。

    这条测试就是那次"读签名才发现"的回归守护。
    """
    cap = []
    ToolkitExtractAdapter(base_url="http://x/api/v1", post=_ok_post(result="张三 | 人员 | 角色=工程师",
                                                                  capture=cap)).run_case(
        _case("张三是什么角色？", module="task"))
    body = cap[0]["payload"]
    assert body["template"] == "information_extraction"
    assert "kb_run_id" not in body, "抽取形态不得带 kb_run_id(模板不接受该参数)"


# ── 错误分级(与 fastapi-rag 同一套契约)──────────────────
@pytest.mark.parametrize("status,expected", [
    (401, SutErrorCode.E_SUT_AUTH), (403, SutErrorCode.E_SUT_QUOTA),
    (500, SutErrorCode.E_SUT_5XX), (400, SutErrorCode.E_SUT_4XX),
])
def test_http_status_maps_to_contract_error_code(status, expected):
    def post(url, headers, payload):
        return status, {"detail": "boom"}
    with pytest.raises(SutAdapterError) as ei:
        ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb1", post=post).run_case(_case())
    assert ei.value.code is expected


def test_unreachable_endpoint_is_timeout(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SutAdapterError) as ei:
        ToolkitQaAdapter(base_url="http://127.0.0.1:9/api/v1", kb_run_id="kb1").run_case(_case())
    assert ei.value.code is SutErrorCode.E_SUT_TIMEOUT


# ── 两类"看起来像答案、其实不是"的响应 ──────────────────
def test_internal_llm_failure_is_sut_error_not_an_answer():
    """被测**内部** LLM 调用失败时,它会把失败信息当答案返回(HTTP 仍是 200)。

    ⚠️ 判成"答案"就等于**拿被测的基础设施故障去扣它的质量分** ——
    与第一家"配额耗尽被读成质量崩了"同一类错。必须映射成被测错误。
    """
    for marker in ("信息抽取未能完成（LLM 调用失败：…）", "[步骤执行失败：LLM 调用失败（…）]",
                   "推理未能得出最终答案（调用异常：…）"):
        with pytest.raises(SutAdapterError) as ei:
            ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb1",
                             post=_ok_post(result=marker)).run_case(_case())
        assert ei.value.code is SutErrorCode.E_SUT_5XX, f"{marker} 应判为被测侧故障"


def test_empty_result_is_bad_response():
    with pytest.raises(SutAdapterError) as ei:
        ToolkitQaAdapter(base_url="http://x/api/v1", kb_run_id="kb1",
                         post=_ok_post(result="   ")).run_case(_case())
    assert ei.value.code is SutErrorCode.E_SUT_BAD_RESPONSE


# ── 注册与 schema ───────────────────────────────────────────
def test_both_forms_are_registered():
    assert "toolkit-qa" in REGISTRY and "toolkit-extract" in REGISTRY
    assert get_adapter("toolkit-qa").id == "toolkit-qa"


def test_schema_accepts_the_new_sut_names():
    assert {"toolkit-qa", "toolkit-extract"} <= SUPPORTED_SUTS
