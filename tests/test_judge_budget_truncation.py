"""T7 · 判分器预算与截断处置(DEC-006,签核 2026-09-12)。

根因(实测):`deepseek-v4-flash` 是推理型模型,`reasoning_tokens` 与 `content`
**共用** `max_tokens`。难例推理吃满上限 ⇒ `finish_reason='length'`、`content` 为空/被截断
⇒ 无 JSON 可解 ⇒ 旧实现**用同样参数重试** ⇒ 再次截断 ⇒ `E_JUDGE_PARSE` ⇒ flag ⇒ exit 2。

本文件守三条(A1/A2/A3):
- A1 默认预算够推理(4096);
- A2 `finish_reason='length'` ⇒ 判为「预算不足」,重试**放大预算 + 换提示语**;
- A3 观测留痕:失败结论必须自带一手证据,且计数可核对。

零 token:全部用注入桩,不发真实 HTTP。
"""
import pytest

from eval_gate.config import JudgeConfig, judge_config
from eval_gate.judge import (MAX_TOKENS_CEILING, Judge, _openai_chat_http,
                             build_item)

VALID = '{"verdict":"pass","score":1,"reasons":["命中"],"evidence_refs":[],"labels":[]}'


def _cfg(**kw):
    base = dict(base_url="http://127.0.0.1:9", api_key="k", model="m",
                timeout_s=1, max_tokens=512, retries=1)
    base.update(kw)
    return JudgeConfig(**base)


def _stub(responses):
    """桩:(content, finish_reason) 序列;记录每次调用收到的 messages 与 max_tokens。

    末条响应会被重复用于后续调用(模拟"每次都失败")。
    """
    seen: list[dict] = []

    def chat(msgs, max_tokens=None):
        seen.append({"msgs": msgs, "max_tokens": max_tokens})
        content, finish = responses[min(len(seen) - 1, len(responses) - 1)]
        return content, {"total_tokens": 1}, finish

    return chat, seen


def _item():
    return build_item(1, "q", {"answer_contains": ["x"]}, "x")


# ── A1 默认预算 ─────────────────────────────────────────────
def test_default_judge_budget_is_enough_for_reasoning():
    """默认 512 会被推理吃满(实测 content 为空)⇒ 默认必须是 4096 档。"""
    assert JudgeConfig().max_tokens == 4096
    assert MAX_TOKENS_CEILING >= 4096


def test_judge_config_env_override_still_wins(monkeypatch):
    """默认值改了,但显式配置仍须生效(不得把可配项变成硬编码)。"""
    monkeypatch.setenv("EVAL_JUDGE_MAX_TOKENS", "1234")
    assert judge_config().max_tokens == 1234


# ── A2 截断识别与「不同参数」重试 ──────────────────────────
def test_truncated_response_retries_with_doubled_budget():
    """截断 ⇒ 重试必须**放大预算**(旧的"同样参数重试"对根因结构性无效)。"""
    chat, seen = _stub([("", "length"), (VALID, "stop")])
    j = Judge(_cfg(max_tokens=512), chat=chat)
    v = j.grade(_item())
    assert v.verdict == "pass"
    assert len(seen) == 2
    assert seen[1]["max_tokens"] == 1024, "第二次尝试必须把预算翻倍"
    assert "截断" in seen[1]["msgs"][-1]["content"], "重试提示语须说明真实原因(截断)"
    assert "不是合法 JSON" not in seen[1]["msgs"][-1]["content"], "旧提示语对截断有误"


def test_budget_escalation_is_capped():
    """放大须封顶 —— 否则一次截断可能把成本上限顶穿。"""
    chat, seen = _stub([("", "length"), (VALID, "stop")])
    j = Judge(_cfg(max_tokens=MAX_TOKENS_CEILING), chat=chat)
    j.grade(_item())
    assert seen[1]["max_tokens"] == MAX_TOKENS_CEILING


def test_non_truncated_failure_does_not_escalate_budget():
    """真正"模型不守格式"(finish_reason='stop')⇒ 不放大预算,沿用旧提示语。

    两种根因不得混为一谈 —— 否则会把预算无谓地放大。
    """
    chat, seen = _stub([("抱歉,我不太确定", "stop"), (VALID, "stop")])
    j = Judge(_cfg(max_tokens=512), chat=chat)
    v = j.grade(_item())
    assert v.verdict == "pass"
    assert seen[1]["max_tokens"] is None, "非截断重试不得改变预算"
    assert "不是合法 JSON" in seen[1]["msgs"][-1]["content"]


def test_truncation_across_both_attempts_still_flags():
    """放大预算后仍截断 ⇒ 仍不静默给分,仍记 flag(契约语义不变)。"""
    chat, seen = _stub([("", "length")])
    v = Judge(_cfg(max_tokens=512), chat=chat).grade(_item())
    assert v.verdict == "flag" and v.score == 0.0
    assert len(seen) == 2


# ── A3 失败自带一手证据 + 计数可核对 ───────────────────────
def test_parse_flag_reason_carries_finish_reason_evidence():
    """失败结论必须自带可归因证据 —— 否则下次只能靠花 token 复现(复盘 #2)。"""
    chat, _ = _stub([("", "length")])
    v = Judge(_cfg(max_tokens=512), chat=chat).grade(_item())
    r = v.reasons[0]
    assert "E_JUDGE_PARSE" in r
    assert "length" in r, "须写明 finish_reason"
    assert "2" in r, "须写明尝试次数"


def test_usage_counters_track_truncation_and_retries():
    """计数进 `usage` ⇒ 自动落进 run JSON(calls 与用例数可核对,R4)。"""
    chat, _ = _stub([("", "length"), (VALID, "stop")])
    j = Judge(_cfg(max_tokens=512), chat=chat)
    j.grade(_item())
    assert j.usage["calls"] == 2
    assert j.usage["retries"] == 1
    assert j.usage["truncated"] == 1
    assert j.usage["parse_failures"] == 1
    assert j.usage["parse_flags"] == 0


def test_clean_call_leaves_counters_at_zero():
    """顺利的一条不得污染计数(否则"有没有异常"就看不出来了)。"""
    j = Judge(_cfg(), chat=lambda msgs: (VALID, {"total_tokens": 1}, "stop"))
    j.grade(_item())
    assert (j.usage["retries"], j.usage["truncated"],
            j.usage["parse_failures"], j.usage["parse_flags"]) == (0, 0, 0, 0)


def test_diagnostics_expose_last_attempt_for_trace():
    """trace 侧要能取到「这条为什么走得慢」:尝试次数与每次的 finish_reason。"""
    chat, _ = _stub([("", "length"), (VALID, "stop")])
    j = Judge(_cfg(max_tokens=512), chat=chat)
    j.grade(_item())
    d = j.last_diagnostics
    assert d["attempts"] == 2
    assert d["finish_reasons"] == ["length", "stop"]


def test_effective_config_makes_budget_visible_in_artifact():
    """A4:「实际用的什么预算」必须在产物里看得见(本会话就卡在这)。"""
    cfg = _cfg(max_tokens=4096, retries=1)
    ec = Judge(cfg).effective_config()
    assert ec["model"] == "m" and ec["max_tokens"] == 4096 and ec["retries"] == 1


# ── 底层:_openai_chat_http 必须回传 finish_reason ───────────
def test_chat_http_returns_finish_reason(monkeypatch):
    """不把 finish_reason 取出来 ⇒ 截断与"不守格式"永远分不开。"""
    import json as _json

    class _R:
        def __init__(self, payload):
            self._b = _json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    payload = {"choices": [{"message": {"content": VALID}, "finish_reason": "length"}],
               "usage": {"total_tokens": 3}}
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _R(payload))
    content, usage, finish = _openai_chat_http(_cfg(), [{"role": "user", "content": "x"}])
    assert content == VALID and usage["total_tokens"] == 3 and finish == "length"


def test_chat_http_honours_budget_override(monkeypatch):
    """放大预算必须真的出现在请求体里 —— 否则"放大"只是自说自话。"""
    import json as _json
    sent: list[dict] = []

    class _R:
        def read(self):
            return _json.dumps({"choices": [{"message": {"content": VALID},
                                             "finish_reason": "stop"}],
                                "usage": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        sent.append(_json.loads(req.data.decode()))
        return _R()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _openai_chat_http(_cfg(max_tokens=512), [{"role": "user", "content": "x"}], 2048)
    assert sent[0]["max_tokens"] == 2048


# ── T8:判分器的**口径边界**必须写进 prompt(提示即代码 ⇒ 要有回归测试)──
def _sys_prompt() -> str:
    from eval_gate.judge import Judge
    j = Judge(_cfg())
    return j._messages(build_item(1, "q", {"answer_contains": ["x"]}, "x"))[0]["content"]


def test_prompt_states_answer_contains_is_any_one_hit():
    """守着 dbc2416 修好的那条语义 —— 它此前**没有回归测试**,改 prompt 时可能被静默丢掉。"""
    sysp = _sys_prompt()
    assert "含其一即符" in sysp
    assert "任意一个" in sysp


def test_prompt_states_refusal_boundary_rule():
    """**T8 主角**:被测整句是拒答、但句中出现了候选词时,不得因"没真正回答"改判 flag/fail。

    M1 首测暴露分歧 3/3 全是这个形状(半拒答)→ 判分器给 flag,而业务方裁定口径是 pass。
    根因:prompt 只说了「含其一即符」,没说"拒答语境下也算" ⇒ 模型用常识补位给了"存疑"。
    """
    sysp = _sys_prompt()
    assert "拒答" in sysp
    assert "即算满足" in sysp or "也要判 pass" in sysp
    assert "不得" in sysp and ("flag" in sysp)


def test_exemption_is_scoped_to_refusal_context_in_the_text_itself():
    """⚠️ **收窄的边界,写成能红的判据**(2026-09-24 改,`DEC-019` 的 β / 签核 D-28)。

    **原守卫为什么不算数**:它是
        `assert "答非所问" not in sysp.replace("答非所问时", "")`
    —— **纯字符串检查**,**在洞存在时照样绿**:
    提示词**段尾**那句「但『**是否真正作答**』不改变字面命中的结论」**读起来是普遍规则**
    (条件只写在**段首**),判分器据此**把豁免扩大到了非拒答**;
    而"答非所问"四个字**确实没写进提示词** ⇒ 守卫查的东西与要守的性质**隔了一层**。
    实测后果:3 条「堆齐候选词却没回答」的样本被放行(`DEC-019 §1.3`)。

    **本守卫改法 = 契约 + 局部性**:那句豁免**必须显式带"仅拒答"的条件,且条件就在它旁边**。
    - 红的方式:把条件删掉/挪远 ⇒ 本条**必红**;
    - ⚠️ 它仍是**文本层**的 —— **语义层由金丝雀守**(`tools/judge_canary.py`,
      喂构造答案 ⇒ 断言 0 条 pass);金丝雀要**真判分器** ⇒ 付费、**不进 CI**。
    """
    lines = _sys_prompt().splitlines()
    idx = [i for i, ln in enumerate(lines) if "不改变字面命中" in ln]
    assert idx, "提示词里应当有那条豁免句 —— 没有它,本测试的前提就变了"
    for i in idx:
        near = "".join(lines[max(0, i - 1): i + 1])
        assert "拒答" in near, f"豁免句旁边必须出现『拒答』:{near!r}"
        assert any(w in near for w in ("仅", "只", "限")), (
            f"豁免句必须**显式带条件**(仅拒答语境);现在它读起来像普遍规则:{near!r}")
