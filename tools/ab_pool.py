#!/usr/bin/env python3
"""把**分块**跑出来的 A/B 产物池化成一个 N=20 的实验结果。

## 为什么需要它(2026-09-15)

`KD-11`(长任务无断点保护)业务方已定夺**不修**。而 `T4` 的真实 A/B 是
**40 轮 / ≈2 小时 / ≈116 万 token** —— 中途崩掉则**已花的 token 不可回收**。

⇒ 对策 = **分 5 块跑**,每块独立产物、独立 token 上限(崩了只丢一块),
跑完再把各块的逐轮达标率**池化**成一个 N=20 的结论。

## ⚠️ 池化最容易出的错是"拼错源"

把两次**不同 commit / 不同评测集 / 不同规模**的运行拼在一起,会得到一个
**看起来完全合理**的错数 —— 没有异常、数字漂亮、但毫无意义。
故本工具的**第一职责是拒绝异源**,第二职责才是池化。

## 口径

- **只池化 ① 单次实验的逐轮达标率**(`arms.*.rates`)。
  N 曲线的 `detection_curve` 不池化 —— 它是"在不同 N 上重复 R 次"的比例,语义不同。
- 池化的合法性来自:**每一轮都是对同一系统的独立评测**。
  块与块之间只是"中途停下再续",不是两次不同实验。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from eval_gate.stats import ab_verdict                         # noqa: E402

#: 判"同源"的字段 —— 任一不一致即拒绝(见模块 docstring)。
#: ⚠️ 每项是 **(字段路径元组, 说明)** 的**二元组**。初版写成扁平三元组、
#:    解包后 `key_path` 变成字符串 ⇒ `_dig(doc, *"run")` 去查 `'r'/'u'/'n'`
#:    ⇒ **两边都取到 None ⇒ 永远"一致"⇒ 永不拒绝**(而单块用例照样绿)。
#:    这正是"判据没在查它以为在查的东西"——本仓记住这一条。
SAME_SOURCE_KEYS = (
    (("run", "commit"), "被测/门的 commit"),
    (("evals", "file"), "评测集文件"),
    (("evals", "cases"), "评测集条数"),
    (("run", "n"), "每臂轮数 N"),
    (("run", "no_curve"), "是否跳过 N 曲线"),
)

_LIMITATIONS = (
    "分块池化 **≠** 一次连续运行:各块之间有真实的时间间隔,环境(机器负载/网络/被测状态)"
    "可能不同 ⇒ 池化把「块间差异」也计入了轮间方差。"
    "另外本产物只含 ① 单次实验的逐轮达标率;N 曲线的检出率**未被池化**(语义不同)。"
    "⚠️ 若 `detection_curve` 为空且 `detection_rate` 为 0,那是**未测**,不是检出率为零。"
)


def _dig(doc: dict, *path: str):
    cur = doc
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def load_chunks(paths: list[str]) -> tuple[list[dict], list[float], list[float]]:
    """读入各块并**校验同源**。任一项不一致 ⇒ 抛 `ValueError`(调用方转 exit 3)。"""
    docs, files = [], []
    for p in paths:
        f = Path(p)
        if not f.is_file():
            raise ValueError(f"分块产物不存在:{f}")
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise ValueError(f"分块产物不是合法 JSON:{f}({e})") from e
        files.append(f)

    for key_path, label in SAME_SOURCE_KEYS:
        vals = [_dig(d, *key_path) for d in docs]
        if any(v is None for v in vals):
            raise ValueError(f"分块缺字段「{label}」({'.'.join(key_path)})⇒ 拒绝池化")
        if len(set(map(repr, vals))) > 1:
            detail = "、".join(f"{f.name}={v!r}" for f, v in zip(files, vals))
            raise ValueError(f"分块**不同源**:{label} 不一致({detail})⇒ 拒绝池化")

    for d, f in zip(docs, files):
        if d.get("run", {}).get("aborted"):
            raise ValueError(f"分块未跑完(aborted=true):{f.name} ⇒ 拒绝池化")
        for arm in ("baseline", "candidate"):
            if not _dig(d, "arms", arm, "rates"):
                raise ValueError(f"分块缺 arms.{arm}.rates:{f.name}")

    rates_a, rates_b = [], []
    for d in docs:
        rates_a.extend(d["arms"]["baseline"]["rates"])
        rates_b.extend(d["arms"]["candidate"]["rates"])
    return docs, rates_a, rates_b


def _stats(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "mean": statistics.fmean(xs) if xs else 0.0,
        "pstdev": statistics.pstdev(xs) if len(xs) > 1 else 0.0,
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
        "saturated_rounds": sum(1 for x in xs if x >= 1.0),
    }


def build_doc(docs: list[dict], files: list[Path], rates_a: list[float], rates_b: list[float]) -> dict:
    return {
        "tool": "tools/ab_pool.py",
        "mode": docs[0].get("mode"),
        "pooled_from": [
            {"file": f.name,
             "commit": _dig(d, "run", "commit"),
             "n": _dig(d, "run", "n"),
             "rounds": 2 * (_dig(d, "run", "n") or 0),
             "spent_tokens": _dig(d, "run", "spent_tokens"),
             "elapsed_s": _dig(d, "run", "elapsed_s"),
             "baseline_mean": statistics.fmean(d["arms"]["baseline"]["rates"]),
             "candidate_mean": statistics.fmean(d["arms"]["candidate"]["rates"])}
            for d, f in zip(docs, files)
        ],
        "evals": docs[0].get("evals"),
        "arms": {"baseline": {"rates": rates_a, "stats": _stats(rates_a)},
                 "candidate": {"rates": rates_b, "stats": _stats(rates_b)}},
        # **在池化样本上重算** —— 不抄任何单块的结论
        "single_experiment": ab_verdict(rates_a, rates_b),
        "run": {
            "commit": _dig(docs[0], "run", "commit"),
            "chunks": len(docs),
            "n_per_arm": len(rates_a),
            "rounds": len(rates_a) + len(rates_b),
            "no_curve": _dig(docs[0], "run", "no_curve"),
            "spent_tokens_total": sum((_dig(d, "run", "spent_tokens") or 0) for d in docs),
            "elapsed_s_total": round(sum((_dig(d, "run", "elapsed_s") or 0.0) for d in docs), 2),
            "aborted_any": any(_dig(d, "run", "aborted") for d in docs),
        },
        "_limitations": _LIMITATIONS,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A/B 分块池化(拒绝异源)")
    ap.add_argument("--chunks", nargs="+", required=True,
                    help="各块的 `ab_regression.py --out` 产物(须同源:commit/评测集/N/no_curve 一致)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    try:
        docs, rates_a, rates_b = load_chunks(args.chunks)
    except ValueError as e:
        print(f"[pool] ⛔ {e}", file=sys.stderr)
        print("[pool] 拒绝产出 —— 拼错源会给出一个**看起来完全合理**的错数。", file=sys.stderr)
        return 3

    doc = build_doc(docs, [Path(p) for p in args.chunks], rates_a, rates_b)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    se = doc["single_experiment"]
    print(f"[pool] {len(docs)} 块 → 每臂 {doc['run']['n_per_arm']} 轮 · "
          f"verdict={se['verdict']} p={se['p']:.4f} · 累计 token={doc['run']['spent_tokens_total']:,}")
    print(f"[pool] 产物:{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
