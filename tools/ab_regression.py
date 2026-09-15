#!/usr/bin/env python3
"""A/B 统计回归驱动(离线合成抖动 / `--live` 真实 judge)。

用法(离线,零外网零 token —— 默认):
    python tools/ab_regression.py --evals eval/mini_rag_qa.evals.json \\
        --arm-a 0.98 --arm-b 0.55 --n 12 --repeats 8 --seed 7 \\
        --out docs/reports/P4-1/ab-2026-09-11.json

用法(真实 judge,消耗 token —— 需先向业务方报备预算):
    python tools/ab_regression.py --evals eval/fastapi_rag_golden.evals.json \\
        --live --n 10 --out docs/reports/P4-1/ab-live-<date>.json

**离线模式的方差来源是合成的**(JitterJudge 按概率 p 判 pass,种子固定):
它回答「统计装置能否检出已知大小的差异、需要多少轮」,**不代表真实模型抖动**;
报告里写死了这句话(`warning` 字段),不得冒充真实噪声。

**两臂用不同种子**(`seed` 与 `seed + SEED_OFFSET_B`)而非配对抽样 ——
配对会让装置比真实 A/B 敏感得多,标定出的 N 会偏乐观、不可迁移到 `--live`。
"""
from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from eval_gate.config import judge_config                      # noqa: E402
from eval_gate.judge import Judge, JudgeVerdict                # noqa: E402
from eval_gate.obs import Tracer                               # noqa: E402
from eval_gate.report import write_run                         # noqa: E402
from eval_gate.runner import evaluate                          # noqa: E402
from eval_gate.schema import EvalError, load_evals             # noqa: E402
from eval_gate.stats import ab_verdict                         # noqa: E402

# 两臂种子的固定偏移:让两臂**独立**抽取(真实 A/B 两臂本就互不相关)
SEED_OFFSET_B = 9973

WARNING = ("离线模式的方差来源是**合成抖动**(JitterJudge 按概率判 pass,种子可复现),"
           "不代表真实模型噪声;本文件只用于标定统计装置与给出 N 的下界。"
           "真实 judge 的 A/B 需预算报备后以 --live 运行。")


class JitterJudge(Judge):
    """合成抖动 judge(实验用):每条按固定概率 p 判 pass,种子可复现。

    它**不是**真实模型 —— 只给 A/B 一个已知大小的方差源,用于标定统计装置。
    """

    def __init__(self, p: float, seed: int):
        super().__init__(cfg=judge_config(), chat=lambda msgs: "{}")
        self.p = p
        self._rng = random.Random(seed)

    def enabled(self) -> bool:
        return False

    def label(self) -> str:
        return f"jitter(p={self.p})"

    def grade(self, item: dict) -> JudgeVerdict:
        ok = self._rng.random() < self.p
        return JudgeVerdict("pass" if ok else "fail", 1.0 if ok else 0.0, ["合成抖动"])


class BudgetExceeded(RuntimeError):
    """累计 token 达到上限 ⇒ 熔断(中止本实验,但**留痕**)。"""

    def __init__(self, spent: int, cap: int):
        super().__init__(f"累计 token {spent:,} ≥ 上限 {cap:,}")
        self.spent, self.cap = spent, cap


def budget_exceeded(spent_tokens: int, cap: int | None) -> bool:
    """累计 token 是否已达上限。`cap is None` ⇒ 不限(不构成熔断)。"""
    return cap is not None and spent_tokens >= cap


class _Budget:
    """累计 judge 用量并判定熔断。**此前这个工具没有任何累计上限** ——
    横切原则要求的「token 预算与循环熔断」对它从未实现(2026-09-13 查证)。"""

    def __init__(self, cap: int | None = None):
        self.cap = cap
        self.spent = 0

    def add(self, usage: dict | None) -> None:
        self.spent += int((usage or {}).get("total_tokens") or 0)

    def check(self) -> None:
        if budget_exceeded(self.spent, self.cap):
            raise BudgetExceeded(self.spent, self.cap or 0)


def _run_arm(ev, make_judge, n: int, *, label: str = "", budget: "_Budget | None" = None,
             report_dir: Path | None = None, evals_path: str | None = None) -> list[float]:
    """跑 n 轮,每轮返回该轮 L2 达标率(completion)。

    ⚠️ `make_judge(i)` 必须**按轮次**产出独立的 judge。踩过的坑:若每轮都新建
    `JitterJudge(p, 同一个种子)`,n 轮就是**同一次运行的 n 份拷贝** ——
    方差恒为 0、`cohens_d` 返回 None、p 恒为 1,N 曲线彻底失去意义
    (而且表面上"跑通了",极易当成正常结果)。
    """
    rates = []
    budget = budget if budget is not None else _Budget()
    for i in range(n):
        # ⚠️ **必须传 tracer 并落盘**(2026-09-15):不传 ⇒ 这一轮只剩一个 completion 浮点,
        #    A3 要的 `sut.call`/`attempts` 到不了文件、B4 要的逐 case 答案拿不到、
        #    一次 ≈116 万 token 的运行**不可审计**(详见 `docs/plans/2026-09-15-收尾批次-实施计划.md`)。
        tr = Tracer(log_stream=io.StringIO()) if report_dir is not None else None
        res = evaluate(ev, judge=make_judge(i), tracer=tr)
        rates.append(float(res.summary["completion"]))
        budget.add(getattr(res, "judge_usage", None))     # 先累加,再报 —— 否则进度行滞后一轮
        if report_dir is not None:
            _write_round_artifacts(res, tr, report_dir, evals_path, make_judge(i))
        # 逐轮进度 —— 此前跑起来是黑盒(无 trace、无逐轮产物,只能等结束)
        print(f"[ab] {label}轮 {i + 1}/{n} · completion={rates[-1]:.4f}"
              f" · 累计 judge token={budget.spent:,}", file=sys.stderr)
        budget.check()
    return rates


def _write_round_artifacts(res, tr, report_dir: Path, evals_path: str | None, judge) -> None:
    """把一轮的**报告 + trace(+日志)**写进 `report_dir`。

    产物命名沿用主 CLI:`<run_id>.local.json` / `<run_id>.trace.jsonl` ——
    这样现成工具(`eval-gate stats`、`trace_stats`、`archive_evidence`)能直接吃。
    ⚠️ 落盘失败**不得**让 A/B 整轮崩:它是取证层,不是判据层(与 `cli.py` 的 trace
    落盘"失败不阻塞主流程"同一原则)。但**必须出声**,否则又变成静默丢证据。
    """
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        write_run(res, report_dir, evals_path or "<unknown>", _judge_label(judge))
        if tr is not None:
            tr.write_trace(report_dir / f"{res.run_id}.trace.jsonl")
            logs = tr._log_stream.getvalue()          # noqa: SLF001 —— 本仓内部工具,取回日志文本
            if logs:
                (report_dir / f"{res.run_id}.log").write_text(logs, encoding="utf-8")
    except OSError as e:
        print(f"[ab] ⚠ 第 {res.run_id} 轮产物落盘失败(**证据可能不完整**):{e}", file=sys.stderr)


def _judge_label(judge) -> str:
    try:
        return judge.label()
    except Exception:                                  # noqa: BLE001 —— 标签失败不该影响落盘
        return "unknown"


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _probes(n: int) -> list[int]:
    """N 曲线的采样点(去重、升序、≥2)。"""
    return sorted({max(2, n // 3), max(2, 2 * n // 3), n})


#: 单轮(一次完整评测集评估)的**实测** token 量级 —— 用于 live 预算提示。
#: 依据:真实链路 48 条一轮实测 **2.86–2.99 万**(见 `eval/l1_baseline.json` 与 P4-2 报告)。
#: ⚠️ 2026-09-15 修:原值 **24,000** 是早期报备口径,**比实测低 16–20%**
#: —— 而操作员是**按下百万 token 之前**读这行预告的人,低报正是"预算误解"的温床。
#: 现取实测**上界** 30,000(保守);批次跑完再用真实均值定稿。
EST_TOKENS_PER_ROUND = 30_000


def rounds_planned(n: int, repeats: int, no_curve: bool) -> int:
    """本实验将跑多少「轮」(= 多少次完整评测集评估)。**这是预算守卫的依据。**

    轮数 = 单次实验(`2N`)+ N 曲线(`2·repeats·Σprobes`)。

    ⚠️ N 曲线的放大是**乘法**的:`_probes(20)` 有 3 个采样点、平均约 13,
    `repeats` 默认 10 ⇒ N=20 时 **40 轮 → 820 轮(总倍数 20.5×)**。
    live 模式下 1 轮 ≈ **2.86–2.99 万** token(`EST_TOKENS_PER_ROUND` 取上界 3 万)
    ⇒ 不加 `--no-curve` 会从 ~120 万涨到 ~2,460 万。
    """
    base = 2 * n
    return base if no_curve else base + 2 * repeats * sum(_probes(n))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A/B 统计回归(默认离线合成抖动)")
    ap.add_argument("--evals", required=True)
    ap.add_argument("--arm-a", type=float, default=0.90, help="基线臂注入通过率(离线)")
    ap.add_argument("--arm-b", type=float, default=0.80, help="候选臂注入通过率(离线)")
    ap.add_argument("--n", type=int, default=20, help="每臂轮数 N")
    ap.add_argument("--repeats", type=int, default=10, help="整个实验重复次数(算检出率)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--live", action="store_true", help="用真实 judge(消耗 token)")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="**熔断**:累计 judge token 达此值即中止(退出码 4,并留痕)。"
                         "不传 = 不限。live 下强烈建议传(此前无任何累计上限)")
    ap.add_argument("--no-curve", action="store_true",
                    help="跳过 N 曲线,只做单次实验(= 2N 轮)。**live 下这是预算守卫**:"
                         "曲线会把轮数放大约 20.5×(N=20 时 40→820)")
    ap.add_argument("--report-dir", default=None,
                    help="**逐轮产物目录**(报告 + trace + 日志)。给 ⇒ 每轮落"
                         " `<run_id>.local.json` / `.trace.jsonl` / `.log`;"
                         "**不给 ⇒ 不落产物**(保持既有行为,供离线冒烟用)。"
                         "⚠️ `--live` 时**必填** —— 不可审计的百万 token 花销是本批次要根除的东西")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    for name, v in (("--arm-a", args.arm_a), ("--arm-b", args.arm_b)):
        if not 0.0 <= v <= 1.0:
            print(f"[ab] {name} 必须在 [0,1]:{v}", file=sys.stderr)
            return 3
    if args.n < 2:
        print("[ab] --n 至少 2(单样本无法做分布检验)", file=sys.stderr)
        return 3
    if args.repeats < 1:
        print("[ab] --repeats 至少 1", file=sys.stderr)
        return 3

    try:
        ev = load_evals(args.evals)
    except (EvalError, FileNotFoundError) as e:
        print(f"[ab] 评测集不可用: {e}", file=sys.stderr)
        return 3

    cfg = judge_config() if args.live else None
    # ⚠️ 预算提示放在**配置检查之前**:这样即使 judge 没配好,操作者也能立刻看到
    # "这一跑要多少轮/多少 token"(也让这条守卫在离线环境下**可测**)。
    if args.live:
        plan = rounds_planned(args.n, args.repeats, args.no_curve)
        where = "已加 --no-curve" if args.no_curve else "⚠️ **未加 --no-curve**"
        print(f"[ab] 计划轮数 = {plan}({where})·估算 ≈ {plan * EST_TOKENS_PER_ROUND:,} tokens",
              file=sys.stderr)
        if not args.no_curve:
            print(f"[ab] ⚠️ N 曲线把轮数从 {2 * args.n} 放大到 {plan}"
                  f"(约 {plan / (2 * args.n):.1f}×)⇒ 估算 token 同比例放大。"
                  f"若只要「N={args.n}/臂」的单次实验,请加 --no-curve。", file=sys.stderr)
    if args.live and not cfg.enabled():
        print("[ab] --live 需配置 EVAL_JUDGE_BASE_URL/API_KEY/MODEL;"
              "拒绝静默回落到合成抖动(那会冒充真实噪声)", file=sys.stderr)
        return 3

    # ⚠️ **`--live` 必须声明产物目录**(2026-09-15)—— 刻意放在 **judge 配置检查之后**:
    #    若放前面,"judge 没配好"那条测试会改走这条分支 ⇒ **因错误的原因通过**
    #    (报错文案里就看不到 EVAL_JUDGE 了)。
    #    理由:真实一轮是百万 token 量级,而**不可审计的百万 token** 正是本批次要根除的东西。
    if args.live and not args.report_dir:
        print("[ab] --live 必须显式给 --report-dir:真实一轮是百万 token 量级,"
              "没有逐轮产物就不可审计(拿不到 attempts 与逐 case 答案)", file=sys.stderr)
        return 3

    report_dir = Path(args.report_dir) if args.report_dir else None

    def arm(p: float, base_seed: int):
        """返回 `make_judge(i)`:第 i 轮用 `base_seed + i` 种子(轮间独立)。"""
        if args.live:
            return lambda i: Judge(cfg)
        return lambda i: JitterJudge(p, base_seed + i)

    t0 = time.time()
    plan = rounds_planned(args.n, args.repeats, args.no_curve)

    # ① 单次实验(N 轮/臂)→ 报告主结论
    budget = _Budget(cap=args.max_tokens)
    curve: list[dict] = []
    # ⚠️ **①② 共用一个 budget,且共用同一段 try**(2026-09-15 修):
    #    此前曲线里的 `_run_arm` **没传 budget**(各自 `_Budget()`,`cap=None`)
    #    ⇒ 漏写 `--no-curve` 时 **780 轮不受任何上限约束**(量级 2000 万),
    #    且超限会以 traceback 收场(不是契约里的 exit 4)。
    try:
        # ① 单次实验(2N 轮)→ 报告主结论
        rates_a = _run_arm(ev, arm(args.arm_a, args.seed), args.n, label="A",
                           budget=budget, report_dir=report_dir, evals_path=args.evals)
        rates_b = _run_arm(ev, arm(args.arm_b, args.seed + SEED_OFFSET_B), args.n,
                           label="B", budget=budget, report_dir=report_dir, evals_path=args.evals)

        # ② N 曲线:每个采样点重复 R 次,算「判为退化」的比例
        #    `--no-curve` 时跳过 —— live 下这是预算守卫(见 `rounds_planned`)
        if not args.no_curve:
            for n_probe in _probes(args.n):
                detected = 0
                for r in range(args.repeats):
                    sa = args.seed + 1000 * r
                    sb = sa + SEED_OFFSET_B
                    # ⚠️ 曲线**刻意不落产物**(默认 780 轮,逐轮落盘会灌出上千文件),
                    #    但**必须共用 budget** —— 否则熔断对它形同虚设。
                    ra = _run_arm(ev, arm(args.arm_a, sa), n_probe, budget=budget)
                    rb = _run_arm(ev, arm(args.arm_b, sb), n_probe, budget=budget)
                    if ab_verdict(ra, rb)["verdict"] == "regressed":
                        detected += 1
                curve.append({"n": n_probe, "detection_rate": detected / args.repeats,
                              "repeats": args.repeats})
    except BudgetExceeded as e:
        print(f"[ab] ⛔ **熔断**:累计 token {e.spent:,} ≥ 上限 {e.cap:,} —— 已中止(未跑完)",
              file=sys.stderr)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"tool": "tools/ab_regression.py", "mode": "live" if args.live else "offline-jitter",
             "warning": WARNING, "evals": {"file": args.evals, "cases": len(ev.cases)},
             # 熔断时把**已算出的部分曲线**一并留痕 —— 否则事后看不出"跑到哪一步被掐的"
             "detection_curve": curve,
             "run": {"aborted": True, "spent_tokens": budget.spent, "max_tokens": args.max_tokens,
                     "n": args.n, "no_curve": args.no_curve, "commit": _git_commit()},
             "reason": str(e)}, ensure_ascii=False, indent=1), encoding="utf-8")
        return 4
    single = ab_verdict(rates_a, rates_b)

    doc = {
        "tool": "tools/ab_regression.py",
        "mode": "live" if args.live else "offline-jitter",
        "warning": WARNING,
        "evals": {"file": args.evals, "cases": len(ev.cases)},
        "arms": {"baseline": {"p": args.arm_a, "rates": rates_a},
                 "candidate": {"p": args.arm_b, "rates": rates_b}},
        "single_experiment": single,
        "detection_curve": curve,
        "detection_rate": max((c["detection_rate"] for c in curve), default=0.0),
        "stats_summary": {
            "baseline_mean": statistics.fmean(rates_a) if rates_a else 0.0,
            "candidate_mean": statistics.fmean(rates_b) if rates_b else 0.0,
        },
        "run": {"commit": _git_commit(), "n": args.n, "repeats": args.repeats,
                "seed": args.seed, "seed_offset_b": SEED_OFFSET_B,
                # 预算守卫:轮数落盘,事后可核"这轮本该花多少"
                "no_curve": args.no_curve, "rounds_planned": plan,
                "aborted": False, "spent_tokens": budget.spent,
                "max_tokens": args.max_tokens,
                "elapsed_s": round(time.time() - t0, 2),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ab] mode={doc['mode']} N={args.n} 检出率={doc['detection_rate']:.2f} "
          f"verdict={single['verdict']} p={single['p']:.4f} "
          f"d={single['d'] if single['d'] is None else round(single['d'], 3)}")
    print(f"[ab] 报告: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
