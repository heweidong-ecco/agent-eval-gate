"""judge 异常路径与出参越界(红队靶子③:judge 出参越界)。

靶子定义见 docs/specs/P4-1-测试与压测.md §6-3:
「verdict 非法、score 超 [0,1]、超大 reasons → 门须 clamp/拒绝」。
"""
import json

import pytest

from eval_gate.judge import (JudgeError, JudgeVerdict, Judge, _parse_verdict,
                             _openai_chat_http, FakeJudge, build_item)
from eval_gate.config import JudgeConfig


# ── 出参越界(红队③)────────────────────────────────────────────
def test_invalid_verdict_is_rejected_not_scored():
    """verdict 不在 {pass,fail,flag} → 不产出结论(重问/flag),绝不静默给分。"""
    assert _parse_verdict('{"verdict":"perfect","score":1.0}') is None


def test_non_object_json_is_rejected():
    assert _parse_verdict("[1,2,3]") is None
    assert _parse_verdict("not json at all") is None


def test_score_is_clamped_into_unit_interval():
    """score 超 [0,1] 必须 clamp —— 否则会污染 L2 聚合。"""
    assert _parse_verdict('{"verdict":"pass","score":7.5}').score == 1.0
    assert _parse_verdict('{"verdict":"fail","score":-3}').score == 0.0


def test_unparsable_score_falls_back_to_zero_not_crash():
    v = _parse_verdict('{"verdict":"pass","score":"很高"}')
    assert v is not None and v.score == 0.0


def test_huge_reasons_are_kept_but_stringified():
    """超大 / 非串 reasons 一律 str() 化 —— 不崩,也不把非串对象漏进报告。"""
    raw = json.dumps({"verdict": "flag", "score": 0.5,
                      "reasons": [{"a": 1}] * 50, "evidence_refs": None, "labels": None})
    v = _parse_verdict(raw)
    assert v is not None and len(v.reasons) == 50
    assert all(isinstance(r, str) for r in v.reasons)
    assert v.evidence_refs == [] and v.labels == []


def test_verdict_as_dict_round_trips():
    d = JudgeVerdict("pass", 1.0, ["ok"], ["e1"], ["l1"]).as_dict()
    assert d == {"verdict": "pass", "score": 1.0, "reasons": ["ok"],
                 "evidence_refs": ["e1"], "labels": ["l1"]}


# ── 调用失败分级(HTTP / 网络)────────────────────────────────
def _cfg():
    return JudgeConfig(base_url="http://127.0.0.1:9", api_key="k", model="m", timeout_s=1)


@pytest.mark.parametrize("status,expected_code", [
    (401, "E_JUDGE_AUTH"), (403, "E_JUDGE_AUTH"),
    (400, "E_JUDGE_MODEL_UNKNOWN"), (404, "E_JUDGE_MODEL_UNKNOWN"),
    (500, "E_JUDGE_TIMEOUT"), (429, "E_JUDGE_TIMEOUT"),
])
def test_http_status_maps_to_contract_error_code(monkeypatch, status, expected_code):
    """HTTP 状态 → 契约错误码(contracts/评测-judge.md 错误码表)。"""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, status, "boom", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(JudgeError) as ei:
        _openai_chat_http(_cfg(), [{"role": "user", "content": "x"}])
    assert ei.value.code == expected_code


def test_unreachable_endpoint_is_judge_timeout(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(JudgeError) as ei:
        _openai_chat_http(_cfg(), [{"role": "user", "content": "x"}])
    assert ei.value.code == "E_JUDGE_TIMEOUT"


def test_repeated_parse_failure_returns_flag_not_pass():
    """多次非 JSON → verdict=flag(存疑需人工),绝不默认放过。"""
    j = Judge(_cfg(), chat=lambda msgs: "抱歉,我不太确定")
    v = j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert v.verdict == "flag" and v.score == 0.0
    assert "E_JUDGE_PARSE" in v.reasons[0]


# ── usage 与校准 ────────────────────────────────────────────
def test_usage_accumulates_and_tolerates_garbage():
    """usage 字段容错:非法值按 0 计,不得抛错(否则一次脏响应毁整轮)。"""
    j = Judge(_cfg(), chat=lambda msgs: ("{}", {"prompt_tokens": "x", "total_tokens": None}))
    j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert j.usage["calls"] == 1 and j.usage["prompt_tokens"] == 0


def test_grade_ref_returns_agreement_ratio_and_none_on_empty():
    """judge-人工一致率:E7 校准用;空输入 → None(不是 0.0,避免被当成「全不一致」)。"""
    j = FakeJudge()
    assert j.grade_ref([]) is None
    refs = [{"question": "q", "expected": {"answer_contains": ["1991"]},
             "sut_answer": "1991 年", "human": True}]
    assert j.grade_ref(refs) == 1.0


def test_fake_judge_reports_disabled_and_offline_label():
    """FakeJudge 必须自报 enabled()=False 且标签为 `offline` —— 不得谎称是真 judge。"""
    fj = FakeJudge()
    assert fj.enabled() is False
    assert fj.label() == "offline"
    # 反之:配齐三项的真 judge 必须自报 enabled —— 否则会被误当离线替身跳过
    assert Judge(_cfg()).enabled() is True


# ── FakeJudge 的禁现 / 无期望分支 ───────────────────────────
def test_fake_judge_not_contains_branch():
    exp = {"answer_not_contains": ["不该出现"]}
    assert FakeJudge().grade(build_item(1, "q", exp, "答案里不该出现这句")).verdict == "fail"
    assert FakeJudge().grade(build_item(1, "q", exp, "干净答案")).verdict == "pass"


def test_fake_judge_without_expectation_passes_with_lower_score():
    v = FakeJudge().grade(build_item(1, "q", {}, "随便"))
    assert v.verdict == "pass" and v.score == 0.8


def test_fake_judge_must_refuse_branch():
    """拒答负例:FakeJudge 也必须按 must_refuse 判,不得一律放过。"""
    exp = {"must_refuse": True}
    assert FakeJudge().grade(build_item(1, "q", exp, "根据现有资料，无法回答。")).verdict == "pass"
    assert FakeJudge().grade(build_item(1, "q", exp, "1991 年发布。")).verdict == "fail"


# ── 主路径(成功调用)────────────────────────────────────────
class _Resp:
    """urlopen 的最小假响应(上下文管理器 + read())。"""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_success_path_returns_content_and_usage(monkeypatch):
    """httpx 之外的**主路径**:成功响应须取出 content 与 usage(成本记账靠它)。"""
    payload = {"choices": [{"message": {"content": '{"verdict":"pass","score":1}'}}],
               "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(payload))
    content, usage = _openai_chat_http(_cfg(), [{"role": "user", "content": "x"}])
    assert content == '{"verdict":"pass","score":1}'
    assert usage["total_tokens"] == 10


def test_grade_records_usage_through_real_http_path(monkeypatch):
    """judge 成本(L1)必须在这条路上真的被累计 —— 否则 L1 基线是空的。"""
    payload = {"choices": [{"message": {"content": '{"verdict":"pass","score":1}'}}],
               "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(payload))
    j = Judge(_cfg())
    v = j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert v.verdict == "pass"
    assert j.usage == {"calls": 1, "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


def test_timeout_is_retried_once_then_raised(monkeypatch):
    """契约 评测-judge.md:41「超时:重试 1 次 → 仍超时抛 E_JUDGE_TIMEOUT」。"""
    calls = []

    def always_timeout(msgs):
        calls.append(1)
        raise JudgeError("E_JUDGE_TIMEOUT", "judge 不可达/超时")

    j = Judge(_cfg(), chat=always_timeout)
    with pytest.raises(JudgeError) as ei:
        j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert ei.value.code == "E_JUDGE_TIMEOUT"
    assert len(calls) == 2, f"超时应重试 1 次(共 2 次调用),实际 {len(calls)}"


def test_non_timeout_judge_error_is_not_retried():
    """非超时错误(如鉴权失败)不重试 —— 重试也只会再失败一次。"""
    calls = []

    def always_auth_fail(msgs):
        calls.append(1)
        raise JudgeError("E_JUDGE_AUTH", "鉴权失败")

    j = Judge(_cfg(), chat=always_auth_fail)
    with pytest.raises(JudgeError):
        j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert len(calls) == 1


def test_plain_string_chat_is_accepted():
    """注入桩返回裸 str 也要能用(usage 不累计)—— 测试替身的常见形态。"""
    j = Judge(_cfg(), chat=lambda msgs: '{"verdict":"pass","score":1}')
    v = j.grade(build_item(1, "q", {"answer_contains": ["x"]}, "x"))
    assert v.verdict == "pass" and j.usage["calls"] == 0
