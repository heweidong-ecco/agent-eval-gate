"""L1 接线(DEC-012 方案 C+E):系统错误率 + 门自身开销占比。

依据:`docs/decisions/DEC-012-L1阈值-越线与接线.md`(2026-09-13 采纳)。
核心口径:**系统错误率排除 `rule.check`**(它的 error = 该 case 未过判据,是评测结论)。
"""
import io

from eval_gate.obs import STATUS_ERROR, Tracer
from eval_gate.runner import (_FALLBACK_THRESHOLDS, _KNOWN_THRESHOLDS,
                              l1_gate_verdict)


def _tracer(enabled=True) -> Tracer:
    return Tracer(enabled=enabled, log_stream=io.StringIO())


def _tracer_with_run(sut_status=None, judge_status=None) -> Tracer:
    t = _tracer()
    with t.span("run.evaluate", kind="CHAIN") as root:
        with t.span("sut.call", kind="AGENT", case_id=1) as s:
            if sut_status:
                s.status = sut_status
        with t.span("judge.grade", kind="LLM", case_id=1) as j:
            if judge_status:
                j.status = judge_status
    # ⚠️ 时长必须在**所有 span 关闭之后**设:`with` 退出时会用实测值**覆写** `duration_ms`
    # (第一版把赋值写在块内 ⇒ 被冲掉 ⇒ root≈0,占比算成 0.0)。
    # 干净场景:未被覆盖的编排开销 2ms/1000ms = 0.2%,远低于 5% 阈值
    _ms = {"run.evaluate": 1000.0, "sut.call": 600.0, "judge.grade": 398.0}
    for sp in t.spans:
        sp.duration_ms = _ms[sp.name]
    return t


# ── 阈值表的形状校验与兜底 ─────────────────────────────────────
def test_known_thresholds_accept_new_l1_keys():
    ok = {"max": 0.01}
    assert _KNOWN_THRESHOLDS["l1_system_error_rate"](ok)
    assert _KNOWN_THRESHOLDS["l1_gate_overhead_ratio"](ok)
    # 形状写坏必须能被判不合法(否则会 AttributeError 崩,而不是回落兜底)
    for bad in ({}, {"max": "x"}, {"max": True}, 0.01, None):
        assert not _KNOWN_THRESHOLDS["l1_system_error_rate"](bad), bad


def test_fallback_includes_l1_keys():
    """兜底里必须有 L1 —— 否则阈值文件缺这两个键时它们就"不判"了(等于放宽门)。"""
    assert "l1_system_error_rate" in _FALLBACK_THRESHOLDS
    assert "l1_gate_overhead_ratio" in _FALLBACK_THRESHOLDS


# ── L1 判定 ───────────────────────────────────────────────────
def test_l1_not_applicable_without_tracer():
    """库/单测用法(未传 tracer):L1 不适用,**不得**凭空加阻断项。"""
    metrics, blockers = l1_gate_verdict(None, _FALLBACK_THRESHOLDS)
    assert metrics["measurable"] is False
    assert blockers == []


def test_l1_unmeasurable_when_tracing_disabled_is_blocker():
    """⚠️ 关掉 trace ⇒ 无 span ⇒ L1 不可测 —— 这是**绕过口**,不是通过。"""
    metrics, blockers = l1_gate_verdict(_tracer(enabled=False), _FALLBACK_THRESHOLDS)
    assert metrics["measurable"] is False
    assert any("不可测" in b for b in blockers)


def test_l1_clean_run_has_no_blocker():
    metrics, blockers = l1_gate_verdict(_tracer_with_run(), _FALLBACK_THRESHOLDS)
    assert blockers == []
    assert metrics["measurable"] is True
    assert metrics["system_error_rate"] == 0.0
    assert metrics["gate_overhead_ratio"] == 0.002    # (1000-600-398)/1000


def test_l1_system_error_over_threshold_blocks():
    t = _tracer_with_run(sut_status=STATUS_ERROR)
    metrics, blockers = l1_gate_verdict(t, _FALLBACK_THRESHOLDS)
    assert metrics["system_error_rate"] == 0.5        # 2 个 span 里 1 个故障
    assert any("l1_system_error_rate" in b for b in blockers)


def test_l1_overhead_over_threshold_blocks_and_blames_the_gate():
    """开销超阈是**门自身**的毛病 —— 文案必须说清,免得被读成被测的问题。"""
    t = _tracer()
    with t.span("run.evaluate", kind="CHAIN"):
        pass
    for sp in t.spans:                       # 同上:关闭后才设,否则被覆写
        sp.duration_ms = 1000.0              # 无子 span ⇒ uncovered = 100%
    metrics, blockers = l1_gate_verdict(t, _FALLBACK_THRESHOLDS)
    assert metrics["gate_overhead_ratio"] == 1.0
    assert any("门自身" in b for b in blockers)


def test_l1_overhead_below_measurement_floor_is_reported_not_enforced():
    """极短轮次(离线桩 ~1.4ms)的占比由**测量噪声**支配 ⇒ 报出来,但不据此拦。

    实测:离线 mini 轮 `root_ms≈1.4ms`、占比 0.42 —— 若硬拦,CI 的 `mini-rag-qa`
    检查会变红(`.github/workflows/eval-gate.yml:46`)。真实轮次 root≈171s,远高于地板。
    """
    t = _tracer()
    with t.span("run.evaluate", kind="CHAIN"):
        pass
    for sp in t.spans:                       # 关闭后才设,否则被覆写
        sp.duration_ms = 1.4
    metrics, blockers = l1_gate_verdict(t, _FALLBACK_THRESHOLDS)
    assert metrics["gate_overhead_ratio"] == 1.0     # 仍然照实报出
    assert metrics["gate_overhead_enforced"] is False
    assert blockers == []                            # 但不拦
    assert "地板" in metrics["gate_overhead_note"]


def test_l1_thresholds_are_read_from_config():
    thr = {"l1_system_error_rate": {"max": 0.9}, "l1_gate_overhead_ratio": {"max": 0.9}}
    _, blockers = l1_gate_verdict(_tracer_with_run(sut_status=STATUS_ERROR), thr)
    assert blockers == []       # 放宽到 0.9 后不再拦
