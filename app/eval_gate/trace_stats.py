"""P4-2 · 真实 L1 基线提取:把已有 trace 统计成可对比的量。

依据:B `04-分阶段工作流/04-阶段4-测试验证-v1.0.md` §三(成功率/平均耗时/P99)·
§五第 1 条(可复现)· §五第 3 条(L1/L2 分层基线)。

口径声明(**改口径 = 前后不可比,须走 DEC**):
- 分位数**复用** `bench.summarize_latencies`(最近秩法),不另写一套;
- 延迟只取 `status == ok` 的样本(错误样本的耗时不代表正常性能);
- **空样本 → `rate=None`**,绝不返回 0 —— 「没测到」与「错误率 0」必须能分开。
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .bench import attribute_spans, summarize_latencies
from .obs import STATUS_ERROR, STATUS_OK, Span, read_trace

#: 参与 L1 的 span 名(缺哪个就进 `missing`,不静默算成 0)
_METRIC_SPANS = ("sut.call", "judge.grade")


def span_groups(spans: Sequence[Span]) -> dict[str, list[Span]]:
    out: dict[str, list[Span]] = {}
    for s in spans:
        out.setdefault(s.name, []).append(s)
    return out


def sut_of(span: Span) -> str | None:
    """被测名(`sut.call` 的 `attributes["sut"]`);缺失返回 None(不编造名字)。"""
    v = (span.attributes or {}).get("sut")
    return str(v) if v else None


def error_stats(spans: Sequence[Span], name: str) -> dict:
    """某 span 名的成功/失败计数与错误率。**无样本时 `rate=None`**(不是 0)。"""
    xs = [s for s in spans if s.name == name]
    n_ok = sum(1 for s in xs if s.status == STATUS_OK)
    n_err = sum(1 for s in xs if s.status == STATUS_ERROR)
    n = len(xs)
    return {"n": n, "n_ok": n_ok, "n_error": n_err,
            "rate": (n_err / n) if n else None}


def latency_stats(spans: Sequence[Span], name: str, only_ok: bool = True) -> dict:
    """某 span 名的延迟分布(口径 = `bench.summarize_latencies` 的最近秩法)。"""
    xs = [s for s in spans if s.name == name and (not only_ok or s.status == STATUS_OK)]
    return summarize_latencies([s.duration_ms for s in xs])


# ── L1 口径(2026-09-13 澄清,依据 DEC-012 §2.3)─────────────────
#: 计「系统错误率」的 span。**必须排除 `rule.check`**:
#: 它的 `status=error` 表示「该 case 未过判据」(`runner.py:180,323`)—— 那是**评测结论**,
#: 不是系统故障。按字面把「所有 error span 占比」当错误率,会把「用例没通过」
#: 算成「系统出错」,接线后必然误报。
_SYSTEM_ERROR_SPANS = ("sut.call", "judge.grade")

#: 一轮评测的**根 span 名**(编排开销归属的对象)
RUN_ROOT_SPAN = "run.evaluate"

#: 编排开销占比的**测量地板**(ms)。低于它,该占比由测量噪声支配、不具判别力:
#: 离线桩轮次实测 `root_ms≈1.4ms` ⇒ 占比算出 0.42;而真实轮次 `root_ms≈171,000ms` ⇒ 占比≈0。
#: 故低于地板时**照实报出、但不据此拦**(免得 CI 的离线检查被噪声判红)。
MIN_ROOT_MS_FOR_OVERHEAD = 100.0


def system_error_rate(spans: Sequence[Span]) -> dict:
    """系统错误率 = (`sut.call` + `judge.grade` 的 error) / 两者总数。

    `sut.call` 的 error = 被测调用真失败(超时/5xx/4xx/鉴权/配额/不可解析,带 `error.code`);
    `judge.grade` 的 error **只在 judge 抛异常时**置位(`verdict=fail` 不置,`runner.py:206`)。
    **无样本 → `rate=None`**,不冒充 0。
    """
    xs = [s for s in spans if s.name in _SYSTEM_ERROR_SPANS]
    n = len(xs)
    n_err = sum(1 for s in xs if s.status == STATUS_ERROR)
    return {"n": n, "n_error": n_err, "rate": (n_err / n) if n else None}


def overhead_ratio(spans: Sequence[Span]) -> dict:
    """门自身编排开销占比 = (根 span − 直接子 span 之和) / 根 span。

    这是 L1 里**唯一「我方可控」**的量 —— 墙钟与被测延迟由被测/外部支配
    (2026-09-13 实测轮间可差 2×,见 `baseline_document` 的局限声明)。

    ⚠️ **根要按名字找,不能拿 `spans[0]`**:真实 CLI 轮次里第一个 span 是 `evalset.load`,
    `run.evaluate` 在它后面(`bench.attribute_spans` 的 `spans[0]` 约定只对其自身用法成立)。
    第一版照抄该约定 ⇒ 把 0.2ms 的 `evalset.load` 当整轮 ⇒ 占比算成 1.0 ⇒ 误报阻断
    (被既有 e2e 测试当场抓住)。无 `run.evaluate` → `ratio=None`。
    """
    xs = list(spans)
    root = next((s for s in xs if s.name == RUN_ROOT_SPAN), None)
    if root is None:
        return {"root_ms": 0.0, "uncovered_ms": 0.0, "ratio": None}
    a = attribute_spans([root] + [s for s in xs if s is not root])
    return {"root_ms": a["root_ms"], "uncovered_ms": a["uncovered_ms"],
            "ratio": (a["uncovered_ms"] / a["root_ms"]) if a["root_ms"] else None}


# ── 轮级摘要 / 聚合 / 基线文档 ─────────────────────────────────
def summarize_run(path: str | Path) -> dict:
    """一轮 trace → L1 记录。`missing` 列出**一条样本都没有**的 span 名。"""
    p = Path(path)
    spans = read_trace(p)
    g = span_groups(spans)

    by_sut: dict[str, list[Span]] = {}
    for s in g.get("sut.call", []):
        by_sut.setdefault(sut_of(s) or "unknown", []).append(s)

    suts = {name: {"cases": len(xs),
                   "sut_latency_ms": latency_stats(xs, "sut.call"),
                   "sut_errors": error_stats(xs, "sut.call")}
            for name, xs in by_sut.items()}
    samples = {name: [s.duration_ms for s in xs if s.status == STATUS_OK]
               for name, xs in by_sut.items()}

    root = g.get("run.evaluate", [])
    return {
        "run_id": p.name.split(".")[0],
        "trace": str(p),
        "cases": len(g.get("sut.call", [])),
        "wall_ms": root[0].duration_ms if root else 0.0,
        "judge_latency_ms": latency_stats(spans, "judge.grade"),
        "suts": suts,
        "missing": [n for n in _METRIC_SPANS if not g.get(n)],
        "_samples": samples,      # 内部:跨轮池化用。**不得进产物**(见 _public)
    }


def _public(rec: dict) -> dict:
    """剥掉内部键(`_` 前缀)—— 产物里只留可公布的字段(含 `suts` 一层)。"""
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    out["suts"] = {n: {k: v for k, v in r.items() if not k.startswith("_")}
                   for n, r in (rec.get("suts") or {}).items()}
    return out


def merge_runs(records: list[dict]) -> dict:
    """跨轮**池化原始样本**后重算分位数。

    ⚠️ 不能对各轮的 `p50/p95` 再求平均 —— 分位数不是可加量,那样算出来是错的。
    """
    acc: dict[str, dict] = {}
    for rec in records:
        for name, r in (rec.get("suts") or {}).items():
            a = acc.setdefault(name, {"runs": 0, "cases": 0, "ms": [], "ok": 0, "err": 0})
            a["runs"] += 1
            a["cases"] += r["cases"]
            a["ms"] += list((rec.get("_samples") or {}).get(name) or [])
            a["ok"] += r["sut_errors"]["n_ok"]
            a["err"] += r["sut_errors"]["n_error"]

    by_sut: dict[str, dict] = {}
    for name, a in acc.items():
        n = a["ok"] + a["err"]
        by_sut[name] = {
            "runs": a["runs"], "cases": a["cases"],
            "sut_latency_ms": summarize_latencies(a["ms"]),
            "sut_errors": {"n": n, "n_ok": a["ok"], "n_error": a["err"],
                           "rate": (a["err"] / n) if n else None},
        }
    return {"by_sut": by_sut, "runs": [_public(r) for r in records]}


def baseline_document(merged: dict, meta: dict) -> dict:
    """基线文档 = 聚合结果 + meta + **局限**(局限随文件走,不能只写在报告里)。"""
    doc = dict(meta)
    doc.update(merged)
    doc["_limitations"] = [
        "非并发、非『一天业务流量模式』、无资源使用峰值(业务方 2026-09-13 定夺不做 live 压测)",
        "样本为单轮(每 sut 1–3 轮)⇒ 高分位不稳健(最近秩法在 n<20 时 p99 即 max)",
        "⚠️ **轮间不稳定(实测,原因未查明)**:同一被测 commit、同一 48 条集的两轮,"
        "`sut.call` 总耗时 96.7s vs 187.0s(逐 case 比值中位数 0.46)⇒ 分布可能双峰,"
        "**单轮样本不足以代表稳态**;墙钟由此不可当稳定量用(180s 类阈值会误报)",
        "trace 未记录被测版本/commit(该信息在 `eval/runs/<id>.summary.md` 里)⇒ 跨轮可比性靠对照摘要",
        "T3 回放未做:被测不暴露 tool_calls(实测 0 次)⇒『工具调用』这一环未被验证",
    ]
    return doc
