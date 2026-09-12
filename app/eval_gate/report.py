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


def judge_accounting(judge_usage: dict | None, judged_cases: int) -> str:
    """判分器记账一行(计数口径见 `judge.Judge.usage`,DEC-006 A3)。

    要点:**`calls` 比用例数多出来的那几次,就是"被重试掩盖的失败次数"** ——
    重试本身不会说话,只有这个差额能让它现形(2026-09-12:报告显示 1 条解析失败,
    实际首答失败 2 条,差额来自 `calls=47` 与 `judge_used=45`)。
    缺计数键(旧产物/替身)按 0 处理,不得抛错。
    """
    u = judge_usage or {}
    calls = int(u.get("calls") or 0)
    if not calls:
        return ""
    parts = [f"judge 记账: 调用 {calls} / 用例 {judged_cases}"]
    extra = calls - judged_cases
    if extra > 0:
        parts.append(f"⚠️ 多出 {extra} 次 = 被重试掩盖的失败"
                     f"(解析 {int(u.get('parse_failures') or 0)}"
                     f" · 截断 {int(u.get('truncated') or 0)})")
    else:
        parts.append("无额外调用(无重试)")
    if int(u.get("parse_flags") or 0):
        parts.append(f"⚑ 解析失败记 flag {int(u.get('parse_flags') or 0)} 条")
    return " · ".join(parts)


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
        # 生效 judge 配置(A4):"这轮实际用的什么预算"必须可从产物回答
        "judge_config": getattr(result, "judge_config", None),
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
