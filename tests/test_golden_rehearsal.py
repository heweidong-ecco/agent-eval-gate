"""R2a 离线预演:真实被测评测集(fastapi-rag)能否判别好坏。

用**注入的 post 桩**替掉真实被测(真实服务只在 R1 连),证明:
- 忠实被测 → 40 条全过 → exit 0;
- 劣化被测(一律编造、不拒答)→ 被拦,且红队命中 → exit 1。

覆盖 R1 的真实代码路径之一:`get_adapter("fastapi-rag", quality=…)` 的构造
(R0 前此处 TypeError 会被 runner 吞成「被测调用失败」,R1 会 40 条全挂)。

局限:桩由评测集自身 expected 反推答案(无外部语料依赖,保证 CI 可跑),
故它验证的是「管线 + 评测集自洽 + 门能判别」,不替代 R1 的真实链路冒烟。
"""
from pathlib import Path

from eval_gate.adapters import REGISTRY, FastApiRagAdapter
from eval_gate.judge import FakeJudge
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import load_evals

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "fastapi_rag_golden.evals.json"
REFUSAL = "根据现有资料，无法回答此问题。"


def _faithful_post(expected: dict):
    """按 expected 作答的桩:该答则答、该拒则拒。"""
    if expected.get("must_refuse"):
        return REFUSAL
    cands = expected.get("answer_contains") or ["—"]
    return f"根据知识库：{cands[0]}。"


def _degraded_post(expected: dict):
    """劣化桩:一律编造实质内容,从不拒答。"""
    return "这个问题需要综合分析，我认为答案是肯定的，涉及多方面因素。"


def _run_with_stub(pick, expected_by_q: dict):
    def factory(**kw):
        kw.pop("quality", None)                       # 真实被测无此旋钮
        return FastApiRagAdapter(base_url="http://stub", api_key="k",
                                 post=lambda url, headers, payload: (200, {
                                     "answer": pick(expected_by_q[payload["question"]]),
                                     "sources": [{"id": "doc-1"}],
                                 }))
    return factory


def _expected_map(ev):
    return {c.input["question"]: {
        "answer_contains": c.expected.answer_contains,
        "must_refuse": c.expected.must_refuse,
    } for c in ev.cases}


def _evaluate_with(monkeypatch, pick):
    ev = load_evals(GOLDEN)
    monkeypatch.setitem(REGISTRY, "fastapi-rag", _run_with_stub(pick, _expected_map(ev)))
    return evaluate(ev, quality="faithful", judge=FakeJudge(), thresholds=default_thresholds())


def test_faithful_sut_passes_gate(monkeypatch):
    res = _evaluate_with(monkeypatch, _faithful_post)
    assert res.exit_code == 0, res.blockers
    # 计数**从评测集读**,不写死 —— 评测集扩充(DEC-005:40 → 48)不该再产生一个
    # 需要手工同步的常量(写死过 40,加用例时即变过期)。
    n = len(load_evals(GOLDEN).cases)
    assert res.summary["passed"] == res.summary["total"] == n, "忠实被测应全过"
    assert res.summary["redteam_hits"] == 0


def test_degraded_sut_is_blocked(monkeypatch):
    """劣化被测(不拒答、答非所问)必须被拦 —— MVP-1 的验收语义。"""
    res = _evaluate_with(monkeypatch, _degraded_post)
    assert res.exit_code == 1
    assert res.summary["redteam_hits"] == 3, "3 条对抗/越权(确定性必拦)须全部命中"
    assert res.summary["passed"] == 0
    assert any("redteam" in b for b in res.blockers)


def test_fastapi_adapter_accepts_quality_kwarg():
    """R1 路径:runner 恒传 quality=,适配器必须能收(否则 TypeError 被吞成被测失败)。"""
    a = FastApiRagAdapter(base_url="http://x", api_key="k", quality="faithful")
    assert a.id == "fastapi-rag"
    assert REGISTRY["fastapi-rag"](quality="faithful").id == "fastapi-rag"
