"""CLI 入口(MVP):`eval-gate run --evals <file> [--mode good|bad] [--offline] [--report-dir DIR]`
与 `eval-gate trace [--run <run_id>]`(Trace 视图)。

exit 语义:0 全绿 / 1 被拦(block)/ 2 存疑需人工 / 3 配置或运行错误。
judge 选择:默认读 EVAL_JUDGE_*;未配置或 --offline → 用 FakeJudge(离线自证)。
观测(R3/E9):默认开启,`EVAL_TRACE=0` 可关;span 落 `eval/runs/<run_id>.trace.jsonl`,
结构化日志走 **stderr**(`2>log.jsonl` 即可采集),设 `EVAL_OTLP_ENDPOINT` 则额外外发 OTLP。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from eval_gate.config import judge_config
from eval_gate.judge import FakeJudge, Judge
from eval_gate.obs import STATUS_ERROR, Tracer, read_trace, render_tree
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
    t = sub.add_parser("trace", help="打印某次 run 的 Trace 视图(span 树)")
    t.add_argument("--run", help="run_id(默认取最近一次)")
    t.add_argument("--trace-dir", default="eval/runs", help="trace 文件目录(默认 eval/runs)")
    return p


def _cmd_run(args) -> int:
    quality = MODE_TO_QUALITY[args.mode]
    tracer = Tracer(enabled=os.getenv("EVAL_TRACE", "1") != "0")
    run_id: str | None = None
    try:
        with tracer.span("evalset.load", kind="CHAIN", path=str(args.evals)) as sp:
            try:
                ev = load_evals(args.evals)
            except EvalError as e:
                if sp is not None:
                    sp.status = STATUS_ERROR
                print(f"[eval-gate] 评测集错误(零模型调用即失败): {e}")
                return 3
            except FileNotFoundError:
                if sp is not None:
                    sp.status = STATUS_ERROR
                print(f"[eval-gate] 文件不存在: {args.evals}")
                return 3
            if sp is not None:
                sp.attributes.update({"evals_version": ev.version, "cases": len(ev.cases)})

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
            # TypeError/ValueError:JSON 合法但结构不对(如顶层是数组)→ 同属配置错误 exit 3,
            # 不能让 `dict.update` 抛出去把 exit code 顶成 traceback(那会与 1=阻断 混淆)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
                print(f"[eval-gate] 阈值文件不可读/结构不对: {e}")
                return 3

        result = evaluate(ev, quality=quality, judge=judge, thresholds=thresholds, tracer=tracer)
        run_id = result.run_id
        with tracer.span("report.write", kind="CHAIN", dir=str(args.report_dir)):
            path = write_run(result, args.report_dir, args.evals, judge.label())

        s = result.summary
        print(f"[eval-gate] run={result.run_id} judge={judge.label()} quality={quality}")
        print(f"  通过 {s['passed']}/{s['total']} · 失败 {s['failed']} · 存疑 {s['flag']} · 跳过 {s['skipped']} · 红队突破 {s['redteam_hits']} · 达标率 {s['completion']:.2f}")
        if result.degraded:
            print(f"  ⚠ DEGRADED(整批 aborted,不算全绿): {result.degraded_reason}")
        # 判定归属:未通过条目**当场说清是谁拦的**,不让人从 verdict 反推。
        # 动机(2026-09-12 实证):曾连续两轮把"确定性层拦下的"误读成"判分器判错" ——
        # 一手字段一直都在报告里,但摘要里看不见,于是被跳过。
        # 2026-09-12 二次修正(DEC-004 §3,签核 D-15):判据已分层,措辞必须**按层说** ——
        # 「期望未命中」在分层后**已不再拦截**(软层交判分器),再这么说就是假话。
        bad = [c for c in result.cases if c.get("verdict") not in (None, "pass")]
        if bad:
            print(f"  未通过 {len(bad)} 条(判定归属):")
            for c in bad[:10]:
                det = c.get("deterministic") or {}
                jv = c.get("judge_verdict")
                hard = det.get("hard_passed")
                if c.get("deterministic_only"):
                    # 红队/注入**从不走 judge**(契约不变量)⇒ 必须单独指名,
                    # 否则会打成"判定归属见报告(judge=None)",把人带偏。
                    who = "硬层拦下(红队/注入:不进 judge)"
                elif hard is False and jv != "pass":
                    who = "硬层与判分器都拦下"
                elif hard is False:
                    who = "硬层拦下(必拒/禁现/空回答)"
                elif c.get("judge_used"):
                    who = f"判分器拦下(judge={jv})"
                else:
                    who = f"判定归属见报告(deterministic={det.get('passed')}, judge={jv})"
                note = next((r for r in (c.get("reasons") or [])
                             if "未命中" in r or "禁现" in r), "")
                print(f"    id={c['id']}: {who}" + (f" · {str(note)[:60]}" if note else ""))
            if len(bad) > 10:
                print(f"    …(其余 {len(bad) - 10} 条见报告)")
        for b in result.blockers:
            print(f"  ✗ BLOCK: {b}")
        if result.exit_code == 0:
            print("  ✓ 通过评测门 (exit 0)")
        print(f"  报告: {path}")
        return result.exit_code
    finally:
        # Trace 与报告同目录同名(+ .trace.jsonl);早期失败无 run_id 时用 trace_id 兜底命名。
        # ⚠️ 此处【必须】吞掉自身异常:它是 finally,抛错会顶掉契约 exit code(0/1/2/3)——
        #    而崩溃退出码是 1,**在 CI 里恰好等于「block/阻断发布」**:一个 IO/路径问题会被读成
        #    「质量不过关」。与 `export_otlp()`「失败不阻塞主流程」同一原则
        #    (observability/trace_id-规范.md §7:采集端故障不阻塞业务;Trace 丢失可由结构化日志兜底)。
        name = run_id or f"error-{tracer.trace_id[:8]}"
        if tracer.enabled:
            try:
                tp = tracer.write_trace(Path(args.report_dir) / f"{name}.trace.jsonl")
                if run_id:
                    print(f"  Trace: {tp}")
            except OSError as e:
                print(f"  ⚠ Trace 落盘失败(不影响 exit code): {e}", file=sys.stderr)
            tracer.export_otlp()


def _cmd_trace(args) -> int:
    d = Path(args.trace_dir)
    path = d / f"{args.run}.trace.jsonl" if args.run else None
    if path is None:
        cands = sorted(d.glob("*.trace.jsonl"))
        if not cands:
            print(f"[eval-gate] 未找到 trace 文件: {d}")
            return 3
        path = cands[-1]
    if not path.is_file():
        print(f"[eval-gate] trace 文件不存在: {path}")
        return 3
    spans = read_trace(path)
    print(f"[eval-gate] Trace 视图 · {path}")
    print(render_tree(spans, spans[0].trace_id if spans else None))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return _cmd_trace(args) if args.cmd == "trace" else _cmd_run(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
