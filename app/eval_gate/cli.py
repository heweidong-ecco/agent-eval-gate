"""CLI 入口(MVP):`eval-gate run --evals <file> [--mode good|bad] [--offline] [--report-dir DIR]`。

exit 语义:0 全绿 / 1 被拦(block)/ 2 存疑需人工 / 3 配置或运行错误。
judge 选择:默认读 EVAL_JUDGE_*;未配置或 --offline → 用 FakeJudge(离线自证)。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval_gate.config import judge_config
from eval_gate.judge import FakeJudge, Judge
from eval_gate.report import write_run
from eval_gate.runner import default_thresholds, evaluate
from eval_gate.schema import EvalError, load_evals

MODE_TO_QUALITY = {"good": "faithful", "bad": "hallucinate"}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval-gate", description="Agent 生产就绪评测门(MVP)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮评测并出 exit code")
    r.add_argument("--evals", required=True, help="evals.json 评测集路径")
    r.add_argument("--mode", choices=list(MODE_TO_QUALITY), default="good",
                   help="被测 prompt 质量:good=忠实 / bad=劣化(自证:劣化应被拦)")
    r.add_argument("--threshold", help="可选阈值 JSON(覆盖默认,键 l2_task_completion/redteam_zero)")
    r.add_argument("--offline", action="store_true", help="强制用离线 FakeJudge(不发真实模型请求)")
    r.add_argument("--report-dir", default="eval/runs", help="报告落盘目录(默认 eval/runs)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    quality = MODE_TO_QUALITY[args.mode]

    try:
        ev = load_evals(args.evals)
    except EvalError as e:
        print(f"[eval-gate] 评测集错误(零模型调用即失败): {e}")
        return 3
    except FileNotFoundError:
        print(f"[eval-gate] 文件不存在: {args.evals}")
        return 3

    if args.offline:
        judge: Judge = FakeJudge()
        print("[eval-gate] 离线模式(FakeJudge),未调用真实模型")
    else:
        cfg = judge_config()
        if cfg.enabled():
            judge = Judge(cfg)
        else:
            judge = FakeJudge()
            print("[eval-gate] 未配置 EVAL_JUDGE_*(或 --offline)→ 用 FakeJudge 离线自证")

    thresholds = default_thresholds()
    if args.threshold:
        try:
            with open(args.threshold, encoding="utf-8") as f:
                thresholds.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[eval-gate] 阈值文件不可读: {e}")
            return 3

    result = evaluate(ev, quality=quality, judge=judge, thresholds=thresholds)
    path = write_run(result, args.report_dir, args.evals, judge.label())

    s = result.summary
    print(f"[eval-gate] run={result.run_id} judge={judge.label()} quality={quality}")
    print(f"  通过 {s['passed']}/{s['total']} · 失败 {s['failed']} · 存疑 {s['flag']} · 跳过 {s['skipped']} · 红队突破 {s['redteam_hits']} · 达标率 {s['completion']:.2f}")
    if result.degraded:
        print(f"  ⚠ DEGRADED(整批 aborted,不算全绿): {result.degraded_reason}")
    for b in result.blockers:
        print(f"  ✗ BLOCK: {b}")
    if result.exit_code == 0:
        print("  ✓ 通过评测门 (exit 0)")
    print(f"  报告: {path}")
    return result.exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
