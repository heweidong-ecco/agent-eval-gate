"""E7 报告落盘(contracts/评测-report.md)。

run/report 结构写为 eval/runs/<run_id>.local.json(.gitignore 已忽略 *.local.json),
逐条保留证据;报告必带 judge 模型/版本与评测集版本(可回溯、跨模型不可比可审计)。
"""
from __future__ import annotations

import json
from pathlib import Path


def format_duration(seconds) -> str:
    """秒数 → 给人读的时长串:不足 1 分钟 `45s`,否则 `1m30s`(秒位显式保留)。

    报告/日志展示用;末尾的 `s` 单位不可省(便于与 `ms` 区分)。
    """
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    return f"{total // 60}m{total % 60}s"


def format_ratio(v) -> str:
    """0..1 的比率 → 给人读的百分比串(`0.85` → `85%`)。

    报告/日志展示用。口径:整数百分比不带小数点;真小数保留(`0.855` → `85.5%`),
    不做四舍五入成整数 —— 展示要能反映真实精度。`%g` 顺带吃掉二进制浮点噪声
    (`0.07 * 100 == 7.000000000000001`,不能漏进串里)。
    """
    return f"{v * 100:g}%"


def write_run(result, outdir: str | Path, ev_path: str | Path, judge_label: str) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{result.run_id}.local.json"
    doc = {
        "run_id": result.run_id,
        "evals_file": str(ev_path),
        "judge": judge_label,
        # judge 成本(L1 / 契约 评测-judge.md:44「记录字段(报告侧必存)」)
        "judge_usage": result.judge_usage,
        "summary": result.summary,
        "applied_thresholds": result.applied_thresholds,
        "blockers": result.blockers,
        # R0:熔断/整批 aborted 的承载字段(契约 contracts/评测-report.md exit 3)
        "degraded": result.degraded,
        "degraded_reason": result.degraded_reason,
        "exit_code": result.exit_code,
        "cases": result.cases,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
