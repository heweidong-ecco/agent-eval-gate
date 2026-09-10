#!/usr/bin/env python3
"""check_pytest_report —— 校验测试报告**不是假的**。

动机(2026-09-11,业务方批准;来自对另一套 harness 的调研):
  "测试全绿"有三种常见假象,CI 只看退出码时**全都看不出来**:
    ① **一条测试都没跑**(`collected 0` / 配错 testpaths)→ 退出码 0;
    ② 有 skipped/xfail → 退出码 0,但那不是"通过";
    ③ 报告缺失或格式不符 → 被 `|| true` 之类吞掉。
  本脚本把口径写死:**总数>0 ∧ 失败=0 ∧ 错误=0 ∧ 跳过数不超过声明基线**。

用法:
    check_pytest_report.py <junit.xml> [--max-skip N]

退出码:0 = 合规;1 = 不合规(并逐条打印原因);2 = 用法错误。

注:JUnit XML 是 pytest 内置能力(`--junitxml=`),无需额外插件。
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="check_pytest_report")
    ap.add_argument("report", help="pytest --junitxml 产出的 XML")
    ap.add_argument("--max-skip", type=int, default=2,
                    help="允许的跳过数上限(默认 2,= 本仓 live_smoke 的 2 条;超了就要问为什么)")
    args = ap.parse_args(argv)

    p = Path(args.report)
    if not p.is_file():
        print(f"::error::测试报告不存在: {p}(测试可能根本没跑)")
        return 1

    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        print(f"::error::测试报告无法解析: {e}")
        return 1

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        print("::error::测试报告里没有 testsuite(没跑任何测试?)")
        return 1

    total = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)

    print(f"  测试报告: total={total} failures={failures} errors={errors} skipped={skipped}"
          f"(允许跳过 ≤{args.max_skip})")

    bad: list[str] = []
    if total <= 0:
        bad.append("一条测试都没跑(total=0)—— 退出码 0 不代表测过")
    if failures:
        bad.append(f"有 {failures} 条失败")
    if errors:
        bad.append(f"有 {errors} 条错误")
    if skipped > args.max_skip:
        bad.append(f"跳过 {skipped} 条 > 基线 {args.max_skip}"
                   f"(跳过不是通过;若确需增加基线,请显式改本检查的 --max-skip 并说明理由)")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1

    print("✅ 测试报告合规(非空、无失败/错误、跳过未超基线)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
