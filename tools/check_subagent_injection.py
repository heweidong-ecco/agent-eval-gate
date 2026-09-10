#!/usr/bin/env python3
"""到达性断言 —— 检查「仓库纪律注入」是否**真的到达了子 Agent**。

为什么需要它
------------
`subagent-guard.sh`(SubagentStart)把纪律注入子 Agent 上下文。但**注入会发生什么,
没人知道** —— 如果某天它静默失效了(事件没触发 / JSON 非法 / 被 harness 丢掉),
**不会有任何东西变红**:子 Agent 照常工作,只是没人告诉它纪律。

> 这与本仓踩过的 F1(门 2 的证据链被自己的测试写坏)是同一类:**机制的失效必须可被察觉**。

判据(客观、可复核)
------------------
- 本会话**没派过**子 Agent → 无可检,`exit 0`(不误报);
- 派过,但**一份 transcript 都不含签名** → `exit 1`(**结构失效**);
- 至少一份含签名 → `exit 0`。

只读:不写任何生产路径(F1 纪律)。

用法
----
    python tools/check_subagent_injection.py <session_id> [--projects-dir DIR]

`--projects-dir` 默认 `~/.claude/projects/<sanitized-cwd>`(测试用临时目录覆盖)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SIGNATURE = "REPO-DISCIPLINE-V1"


def sanitized_cwd(cwd: Path | None = None) -> str:
    """Claude Code 把会话目录按 cwd 消毒:`/` → `-`。"""
    return str(cwd or Path.cwd()).replace("/", "-")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_id")
    ap.add_argument("--projects-dir", default=None,
                    help="默认 ~/.claude/projects/<sanitized-cwd>")
    a = ap.parse_args()

    base = Path(a.projects_dir).expanduser() if a.projects_dir else \
        Path.home() / ".claude" / "projects" / sanitized_cwd()
    sub_dir = base / a.session_id / "subagents"

    files = sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []
    if not files:
        print(f"✅ 到达性检查跳过:本会话无子 Agent transcript({sub_dir})")
        return 0

    hit = 0
    for f in files:
        try:
            if SIGNATURE in f.read_text(encoding="utf-8", errors="replace"):
                hit += 1
        except OSError:
            continue

    if hit == 0:
        print(f"✗ 注入失效:本会话有 {len(files)} 份子 Agent transcript,"
              f"但**没有任何一份**含签名 `{SIGNATURE}`。", file=sys.stderr)
        print("  可能原因:SubagentStart 未触发 / subagent-guard.sh 输出非法 JSON / "
              "未在 settings.json 注册 / 本次改动后未重启会话。", file=sys.stderr)
        print("  → 子 Agent 此刻在**无纪律**工作,而此前不会有任何提示。", file=sys.stderr)
        return 1

    print(f"✅ 到达性检查通过:{hit}/{len(files)} 份子 Agent transcript 含纪律注入签名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
