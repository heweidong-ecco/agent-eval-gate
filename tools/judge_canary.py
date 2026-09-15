#!/usr/bin/env python3
"""judge 金丝雀 —— "**该拦的拦**"的证据(收尾批次 PR-5 / A2 的验收②)。

## 为什么需要它

A2(`DEC-015` 方案 B1)把 `deterministic` 从**判分器输入**里拿掉了 ⇒ 改变了判分器看到的东西。
按本仓纪律,改判分器输入必须跑真实回归 —— 但**一轮回归只能证明"分数没变"**,
而全部轮次都在天花板上(16/16 轮 1.0)⇒ 那一轮**证明不了"判分器没变松"**。

金丝雀补的正是这一块:**若干条"必须被拦"的构造答案**,断言 **0 条 pass**。
**没有它,"去掉一个字段没让判分器变松"这件事没有任何证据。**

## ⚠️ 它不是判分器的准确率测试

它只有**一个方向**:`该拦的拦`。它**不测**"该放过的有没有放过" ——
后者要参照集(`eval-gate calibrate`),是另一件事。
⇒ **本工具绿,不等于判分器好**;它只等于**没变松到连这些明显的坏答案都放行**。

## 成本与运行时机(**不进 CI**)

每次运行 = `len(cases)` 次真实 judge 调用(默认 8 条 ⇒ 约 1 万 token)。
⇒ **归"改判分器输入/提示词"时的回归清单**,不放进每次 PR 的 CI(那会天天烧钱)。

## 用法

    python3 tools/judge_canary.py [--fixtures tools/judge_canary_cases.json] [--json]

退出码:0 = **无人通过**(全被拦/交人复核)· 1 = **有构造答案被判 pass** · 2 = 用法/配置错误

> `flag` 算**被拦**(交人复核),**不算 pass** —— 把它算成放过会让金丝雀虚绿。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

DEFAULT_FIXTURES = ROOT / "tools" / "judge_canary_cases.json"


class FixtureError(Exception):
    """fixture 本身有问题(配置错误 ⇒ exit 2,不是"有东西没被拦" ⇒ exit 1)。"""


def load_cases(path: Path) -> list[dict]:
    if not path.is_file():
        raise FixtureError(f"fixture 不存在:{path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise FixtureError(f"{path} 不是合法 JSON:{e}") from e
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list) or not cases:
        raise FixtureError(f"{path} 里没有 cases 数组")
    return cases


def run(cases: list[dict], judge) -> tuple[int, dict]:
    """逐条送判分器 → (退出码, 报告)。

    判分器入参经 `build_item` 构造 —— **这是刻意的**:金丝雀是"新调用点"的活样本,
    它必须走**与生产同一条构造路径**,否则它测的就不是生产契约。
    """
    from eval_gate.judge import build_item

    items = []
    for c in cases:
        item = build_item(c["id"], c["question"], c["expected"], c["sut_answer"])
        jv = judge.grade(item)
        verdict = getattr(jv, "verdict", None) or str(jv)
        items.append({
            "id": c["id"], "kind": c.get("kind", ""), "verdict": verdict,
            "score": getattr(jv, "score", None),
            "why": c.get("why", ""),
            "reasons": list(getattr(jv, "reasons", []) or []),
        })

    passed = [i for i in items if i["verdict"] == "pass"]
    report = {
        "judge": getattr(judge, "label", lambda: "unknown")(),
        "total": len(items),
        "passed_count": len(passed),
        "passed_ids": [i["id"] for i in passed],
        "items": items,
    }
    return (1 if passed else 0), report


def render(report: dict) -> str:
    lines = [f"[canary] judge={report['judge']} · {report['total']} 条构造答案(全部**必须被拦**)",
             ""]
    for i in report["items"]:
        mark = "❌ **放过了**" if i["verdict"] == "pass" else "✅"
        lines.append(f"  {mark} id={i['id']:<3} kind={i['kind']:<28} verdict={i['verdict']}")
        if i["verdict"] == "pass":
            lines.append(f"        它**本不该**通过 —— {i['why']}")
    lines.append("")
    if report["passed_count"]:
        lines.append(f"⇒ ❌ **{report['passed_count']}/{report['total']} 条被放过**"
                     f"(id={report['passed_ids']})—— 判分器在去掉 deterministic 后**变松了**,")
        lines.append("   或者这些构造答案本身就是判分器抓不到的类型。**两种情况都要人看。**")
    else:
        lines.append(f"⇒ ✅ **0/{report['total']} 条通过** —— 该拦的都拦住了")
        lines.append("   ⚠️ 这只说明**没变松到连明显的坏答案都放行**;")
        lines.append("      它**不测**「该放过的有没有放过」(那要参照集,见 `eval-gate calibrate`)。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="judge 金丝雀(该拦的拦)")
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--json", action="store_true", help="机读产物")
    a = ap.parse_args(argv)

    try:
        cases = load_cases(Path(a.fixtures))
    except FixtureError as e:
        print(f"[canary] ❌ {e}", file=sys.stderr)
        print("        这是**配置错误**(exit 2),不是发现了放过。", file=sys.stderr)
        return 2

    from eval_gate.judge import Judge

    judge = Judge()
    rc, report = run(cases, judge)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    # 成本留痕 —— 这是"金丝雀不便宜"这件事的**当场证据**(约 1 万 token/次)
    usage = getattr(judge, "usage", None)
    if usage:
        report["judge_usage"] = usage
        print(f"[canary] judge 用量:{usage}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
