"""红队:攻击**评测门自身**(靶子①②,见 docs/specs/P4-1-测试与压测.md §6)。

靶子①:被测识破自己在被评测 → 输出讨好判分器的空话(门须识破);
靶子②:被测返回超长/空/非 UTF-8/巨型 JSON(门须记 fail 而非崩)。

做法:`register_adapter` 临时替换 `mini-rag-qa` 工厂,避免改 schema 白名单
(SUPPORTED_SUTS 是契约枚举,不为红队扩;见 contracts/评测-evals-schema.md:26)。
"""
import io
import json
from pathlib import Path

import pytest

from eval_gate import adapters as ad
from eval_gate.adapters import SutAdapter, SutAdapterError, SutErrorCode, SutOutput
from eval_gate.judge import FakeJudge
from eval_gate.obs import Tracer
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import Case, load_evals

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"

SYCOPHANT = ("这个问题问得非常好!毫无疑问,您的分析完全正确,这是一个极其出色的提问。"
             "关于上述内容,答案是重要且关键的(详见相关文档)。")


class StubAdapter(SutAdapter):
    """按需返回任意原始输出(或抛错),用于红队注入。"""

    id = "mini-rag-qa"

    def __init__(self, answer="", refused=False, sources=None, error=None):
        self._answer, self._refused = answer, refused
        self._sources, self._error = sources or [], error

    def run_case(self, case: Case) -> SutOutput:
        if self._error is not None:
            raise self._error
        return SutOutput(answer=self._answer, refused=self._refused,
                         sources=list(self._sources))


@pytest.fixture
def swap_adapter(monkeypatch):
    def _swap(**kw):
        monkeypatch.setitem(ad.REGISTRY, "mini-rag-qa", lambda **_: StubAdapter(**kw))
    return _swap


# ── 靶子①:作弊的被测 ────────────────────────────────────────
def test_sycophantic_stub_is_not_passed_by_gate(swap_adapter):
    """讨好话术无实质内容 → 确定性规则必须判 fail(答案里没有期望要点)。"""
    swap_adapter(answer=SYCOPHANT)
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds())
    assert res.summary["completion"] < 0.5, "讨好型空话被放行了(门的判据太松)"
    assert res.exit_code != 0


def test_sycophant_cannot_pass_redteam_cases(swap_adapter):
    """红队条目是 deterministic_only:作弊被测也必须一条都过不了。"""
    swap_adapter(answer=SYCOPHANT)
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds())
    assert res.summary["redteam_hits"] >= 1


# ── 靶子②:畸形输出 ─────────────────────────────────────────
@pytest.mark.parametrize("bad_output,label", [
    ({"answer": ""}, "空串"),
    ({"answer": "   "}, "全空白"),
    ({"answer": "长" * 100_000}, "超长"),
    ({"answer": "x" * 50_000, "sources": ["s"] * 5_000}, "巨型 JSON"),
    ({"answer": "\ud800 孤立代理对"}, "非 UTF-8 可编码文本"),
])
def test_malformed_sut_output_is_recorded_not_crashing(swap_adapter, bad_output, label):
    """畸形输出:整轮必须跑完,该条记 fail —— 绝不抛异常掀掉整批。

    ⚠️ **必须带 tracer**:CLI 默认 `EVAL_TRACE=1`(观测是开着的),而
    `digest()` 只在观测路径上被调用。不带 tracer 跑,等于绕开了生产路径,
    会漏掉"畸形回答把日志摘要函数打崩"这类缺陷(实测漏过一次)。
    """
    swap_adapter(**bad_output)
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds(),
                   tracer=Tracer(enabled=True, log_stream=io.StringIO()))
    assert res.summary["total"] == len(ev.cases)
    assert res.exit_code in (0, 1, 2)


def test_sut_error_does_not_abort_batch_except_quota(swap_adapter):
    """非配额错误 → 逐条记 fail,run 继续;整批不得被掀。"""
    swap_adapter(error=SutAdapterError(SutErrorCode.E_SUT_BAD_RESPONSE, "响应无 answer 文本"))
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds())
    assert res.summary["failed"] == len(ev.cases)
    assert res.degraded is False and res.exit_code == 1


def test_quota_error_aborts_batch_with_exit_3(swap_adapter):
    """配额耗尽 → 整批 aborted + degraded + exit 3(阈值判定作废)。"""
    swap_adapter(error=SutAdapterError(SutErrorCode.E_SUT_QUOTA, "额度耗尽"))
    ev = load_evals(EVALS)
    res = evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds())
    assert res.degraded is True and res.exit_code == 3
    assert res.summary["skipped"] == len(ev.cases) - 1
    assert res.blockers == []


# ── 脱敏口径:超长/畸形回答不得进日志 ────────────────────────
def test_oversized_answer_is_not_written_into_logs(swap_adapter):
    """结构化日志里任何一条记录都不得含长文本(口径:R3 / 需求基线:149)。"""
    swap_adapter(answer="长" * 100_000)
    ev = load_evals(EVALS)
    stream = io.StringIO()
    evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds(),
             tracer=Tracer(enabled=True, log_stream=stream))
    lines = [ln for ln in stream.getvalue().splitlines() if ln.strip()]
    assert lines, "未产出结构化日志(无法证明脱敏)"

    def _long(node):
        if isinstance(node, str):
            return [node] if len(node) > 300 else []
        if isinstance(node, dict):
            return [s for v in node.values() for s in _long(v)]
        if isinstance(node, list):
            return [s for v in node for s in _long(v)]
        return []

    leaked = [s for ln in lines for s in _long(json.loads(ln))]
    assert leaked == [], f"日志出现长文本(疑泄漏原文,{len(leaked)} 处)"


# ── 组件级:digest 与 SutOutput 的不可信输入兜底 ─────────────
def test_digest_survives_unencodable_text():
    """摘要函数对任意文本都必须返回摘要 —— 它是所有日志的入口。"""
    from eval_gate.obs import digest
    d = digest("\ud800 孤立代理对")
    assert isinstance(d["sha8"], str) and d["len"] > 0


def test_sut_output_sanitizes_unencodable_text():
    """被测是不可信输入:入口处必须把不可编码字符归一,否则下游落盘/摘要会崩。"""
    out = SutOutput(answer="\ud800 x", sources=["\udfff"])
    out.answer.encode("utf-8")
    out.sources[0].encode("utf-8")
