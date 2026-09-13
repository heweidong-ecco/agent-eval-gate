"""E7 报告落盘(contracts/评测-report.md)。

run/report 结构写为 eval/runs/<run_id>.local.json(.gitignore 已忽略 *.local.json),
逐条保留证据;报告必带 judge 模型/版本与评测集版本(可回溯、跨模型不可比可审计)。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from eval_gate.config import ROOT


# ── 契约声明字段的取值(DEC-016)────────────────────────────────
# 契约 `评测-report.md:20-28` 声明了 run 记录的 11 个字段,而 2026-09-13 实测**产物只有 4 个**
# (该缺口 `docs/部署.md:96` 2026-09-11 已登记却未修)。以下三处把缺的补齐。
def _evals_meta(ev_path) -> tuple[object, str | None]:
    """从评测集文件读出 `(version, sha12)`。读不到 ⇒ `(None, None)`,**不抛**。"""
    try:
        raw = Path(ev_path).read_bytes()
        return json.loads(raw.decode("utf-8")).get("version"), \
            hashlib.sha256(raw).hexdigest()[:12]
    except (OSError, ValueError, AttributeError):
        return None, None


def _threshold_rev() -> str | None:
    """生效阈值文件的 `_rev`(它变 ⇒ 判定口径变,产物必须能自答)。"""
    try:
        return json.loads((ROOT / "eval" / "阈值.json").read_text(encoding="utf-8")).get("_rev")
    except (OSError, ValueError, AttributeError):
        return None


def _git_commit() -> str | None:
    """本仓(门自身)的 commit —— 与**被测**的版本是两件事,不要混。"""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


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
    _ev_ver, _ev_sha = _evals_meta(ev_path)
    doc = {
        "run_id": result.run_id,
        # 契约声明的「这轮用的是什么」字段(DEC-016 补齐;此前只有 evals_file 路径)
        "eval_version": _ev_ver,
        "evals_file_sha": _ev_sha,
        "threshold_rev": _threshold_rev(),
        "git_commit": _git_commit(),
        "started_at": getattr(result, "started_at", None),
        "evals_file": str(ev_path),
        "judge": judge_label,
        # judge 成本(L1 / 契约 评测-judge.md:44「记录字段(报告侧必存)」)
        "judge_usage": result.judge_usage,
        # 生效 judge 配置(A4):"这轮实际用的什么预算"必须可从产物回答
        "judge_config": getattr(result, "judge_config", None),
        # DEC-016:被测侧自证(judge 侧早已自证;被测侧此前一个字段都没有)
        "sut": getattr(result, "sut_info", None),
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
