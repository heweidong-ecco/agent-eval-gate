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
import json
import sys
from pathlib import Path

from eval_gate.calib import compute_agreement
from eval_gate.config import judge_config
from eval_gate.judge import FakeJudge, Judge, build_item
from eval_gate.obs import STATUS_ERROR, Tracer, read_trace, render_tree
from eval_gate.report import judge_accounting, write_run
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
    c = sub.add_parser("calibrate", help="judge 校准:算 judge-人工一致率(M1/E7)")
    c.add_argument("--refs", required=True, help="人工标注参照集 JSON(见 eval/judge_refs.json)")
    c.add_argument("--offline", action="store_true", help="用离线 FakeJudge(不发真实模型请求)")
    c.add_argument("--threshold", default="eval/阈值.json", help="阈值文件(取 judge_human_agreement.min)")
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
        # DEC-006 A4:生效预算打印出来 —— 判分器的"输出预算"直接决定它能不能给出合法 JSON,
        # 而推理型模型的 reasoning 与 content **共用**该上限(2026-09-12 实测踩到)。
        jc = getattr(judge, "effective_config", lambda: None)()
        if jc:
            print(f"  生效 judge 配置: model={jc.get('model')} · max_tokens={jc.get('max_tokens')}"
                  f" · retries={jc.get('retries')} · timeout={jc.get('timeout_s')}s")
        print(f"  通过 {s['passed']}/{s['total']} · 失败 {s['failed']} · 存疑 {s['flag']} · 跳过 {s['skipped']} · 红队突破 {s['redteam_hits']} · 达标率 {s['completion']:.2f}")
        # DEC-006 A3:"calls 比用例多出来的那几次"是**被重试掩盖的失败** —— 不打印就没人会发现。
        accounting = judge_accounting(result.judge_usage,
                                      sum(1 for c in result.cases if c.get("judge_used")))
        if accounting:
            print(f"  {accounting}")
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


def _cmd_calibrate(args) -> int:
    """算 judge-人工一致率(M1 / E7,`contracts/评测-judge.md:47`)。

    这是门的结论的**外部锚**:在此之前"判分器判得准不准"只有门自己的说法。
    """
    try:
        doc = json.loads(Path(args.refs).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[eval-gate] 标注集不可读/不是合法 JSON: {e}", file=sys.stderr)
        return 2
    refs = doc.get("refs") if isinstance(doc, dict) else doc
    if not isinstance(refs, list) or not refs:
        print("[eval-gate] 标注集为空(期望 {\"refs\": [...]})", file=sys.stderr)
        return 2
    # 缺字段**报错**,不静默跳过 —— 静默跳过 = 偷偷改分母
    for r in refs:
        missing = [k for k in ("ref_id", "question", "expected", "sut_answer") if not r.get(k)]
        if missing:
            print(f"[eval-gate] 标注集条目缺字段:ref_id={r.get('ref_id')!r} 缺 {missing}",
                  file=sys.stderr)
            return 2

    if args.offline:
        judge: Judge = FakeJudge()
        print("[eval-gate] 离线模式(FakeJudge):一致率**仅供链路自证**,不是真实判分器的一致性")
    else:
        cfg = judge_config()
        judge = Judge(cfg) if cfg.enabled() else FakeJudge()
        if not cfg.enabled():
            print("[eval-gate] 未配置 EVAL_JUDGE_* → 退回 FakeJudge(结果仅供链路自证)")

    items = []
    for r in refs:
        verdict = None
        if r.get("human") is not None:
            item = build_item(0, r["question"], r["expected"], r["sut_answer"])
            verdict = judge.grade(item).verdict
        items.append({"ref_id": r["ref_id"], "human": r.get("human"), "judge_verdict": verdict})

    out = compute_agreement(items)
    usage = getattr(judge, "usage", {}) or {}
    print(f"[eval-gate] judge 校准 · {args.refs} · judge={judge.label()}")
    print(f"  条目 {out['n_total']}:已标注 {out['n_labeled']} · "
          f"未标注 {out['n_unlabeled']} · 说不清 {out['n_unsure']} · "
          f"用例有问题 {out['n_case_issue']} · flag {out['n_flag']}")
    if out["excluded_ids"]:
        # 被剔除的条**点名** —— 尤其"用例有问题"那类:它是回灌评测集的线索,不能悄悄消失
        print(f"    剔除:{', '.join(out['excluded_ids'])}")
    if out["agreement"] is None:
        print("  ⚠️ 没有可用的已标注条目 ⇒ 无法计算一致率")
        print("     (未标注 ≠ 判分器判错:它只是还没被标)")
    else:
        print(f"  {out['agreement']:.2f}  (judge_human_agreement = 一致 {out['n_agree']}"
              f" / 已标注 {out['n_labeled']})")
        if out["agreement_excl_flag"] is not None:
            print(f"  副指标(剔 flag 后):{out['agreement_excl_flag']:.2f}")
        if out["n_false_negative"]:
            bad = [d["ref_id"] for d in out["detail"] if not d["agree"] and d["human"]]
            print(f"  ⚠️ 误杀 {out['n_false_negative']} 条(人判满足、判分器判不通过):{', '.join(bad)}")
        if out["n_false_positive"]:
            bad = [d["ref_id"] for d in out["detail"] if not d["agree"] and not d["human"]]
            print(f"  ⚠️ 漏放 {out['n_false_positive']} 条(人判不满足、判分器却放行):{', '.join(bad)}")
    mn = _judge_agreement_min(args.threshold)
    if mn is not None:
        print(f"  阈值 judge_human_agreement.min = {mn:.2f}"
              + ("" if out["agreement"] is None
                 else f" ⇒ {'达标 ✅' if out['agreement'] >= mn else '未达标 ❌'}"))
    if usage.get("calls"):
        print(f"  judge 调用 {usage['calls']} 次 · token {usage.get('total_tokens', 0)}")
    return 0


def _judge_agreement_min(path: str) -> float | None:
    """读阈值里的 `judge_human_agreement.min`(同时认顶层与 `_doc_only` 下的写法)。"""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for src in (doc, doc.get("_doc_only") or {}):
        try:
            return float((src.get("judge_human_agreement") or {})["min"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "trace":
        return _cmd_trace(args)
    if args.cmd == "calibrate":
        return _cmd_calibrate(args)
    return _cmd_run(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
