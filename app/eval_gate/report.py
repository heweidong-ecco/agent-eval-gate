"""E7 报告落盘(contracts/评测-report.md)。

run/report 结构写为 eval/runs/<run_id>.local.json(.gitignore 已忽略 *.local.json),
逐条保留证据;报告必带 judge 模型/版本与评测集版本(可回溯、跨模型不可比可审计)。
"""
from __future__ import annotations

import json
from pathlib import Path


def write_run(result, outdir: str | Path, ev_path: str | Path, quality: str, judge_label: str) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{result.run_id}.local.json"
    doc = {
        "run_id": result.run_id,
        "evals_file": str(ev_path),
        "sut_quality": quality,
        "judge": judge_label,
        "summary": result.summary,
        "applied_thresholds": result.applied_thresholds,
        "blockers": result.blockers,
        "exit_code": result.exit_code,
        "cases": result.cases,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
