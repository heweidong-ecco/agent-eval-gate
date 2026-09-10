#!/usr/bin/env python3
"""从子 Agent 的 transcript(JSONL)抽取**紧凑的工具调用时间线**,用于盲测取证。

为什么要它:
  子 Agent 的 transcript 是完整 JSONL(动辄几 MB),`cat` 会撑爆上下文。
  盲测要的是「客观过程」——它**依次调用了什么工具、带了什么参数**,
  而不是它对结果的**自述**(自述不可采信)。

用法:
  python tools/subagent_trace.py <transcript.jsonl> [--limit N] [--full]

输出:
  - 逐条时间线:<序号> <工具名> <关键参数摘要>
  - 末尾:工具直方图 + Skill 调用清单
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# 每个工具只展示最有信息量的那个字段(避免把大段内容刷屏)
KEY_ARG = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Bash": "command",
    "Skill": "skill",
    "Glob": "pattern",
    "Grep": "pattern",
    "Task": "description",
    "WebFetch": "url",
}
MAXLEN = 110


def _brief(v, full: bool) -> str:
    s = str(v)
    s = " ".join(s.split())          # 压掉换行,保持单行
    if full or len(s) <= MAXLEN:
        return s
    return s[:MAXLEN] + " …"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"✗ 找不到 transcript: {path}", file=sys.stderr)
        return 2
    full = "--full" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            limit = 0

    timeline: list[str] = []
    tools: Counter[str] = Counter()
    skills: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            content = d.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "?")
                args = block.get("input", {}) or {}
                tools[name] += 1
                key = KEY_ARG.get(name)
                arg = args.get(key, "") if key else ""
                if name == "Skill":
                    skills.append(str(args.get("skill", "")))
                    extra = f' args="{_brief(args.get("args", ""), full)}"'
                else:
                    extra = ""
                timeline.append(f"{len(timeline)+1:3d}. {name:<10} {_brief(arg, full)}{extra}")

    shown = timeline[:limit] if limit else timeline
    print("\n".join(shown))
    if limit and len(timeline) > limit:
        print(f"     … 另有 {len(timeline)-limit} 次调用(用 --limit 0 看全部)")

    print("\n" + "─" * 60)
    print(f"工具调用总数: {len(timeline)}")
    print("直方图: " + ", ".join(f"{k}={v}" for k, v in tools.most_common()))
    if skills:
        print("Skill 调用: " + ", ".join(skills))
    else:
        print("Skill 调用: **0 次**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
