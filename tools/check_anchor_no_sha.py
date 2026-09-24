#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点守卫:指针/交接段里**不许写死「每次合并都会变」的值**(主要是 commit sha)。

它补的是哪个"无声"
------------------
锚点是**每会话第一个被读**的位置。写死 `main = <sha>` 之后,**下一次合并它就变成假话** ——
不报错、不变红、不告警,只是**安静地误导每一个读它的人**。
> 2026-09-21 实测:`main = 80b3309` 写进锚点,三天后实际已是 `4161da8`;
> 同一段里还积了 7 处 9 月 10–15 日的「下一步 / 待做」,全都写成了现在时。

⇒ 规矩(`CLAUDE.md` 接续协议第 2 条):
**sha 要现取**(`git log -1 --oneline main`);**PR 号可以写**(它不随时间改义)。

口径边界(刻意写死,防止工具"顺手"扩大扫描面 —— 误报多了守卫就会被关掉)
--------------------------------------------------------------------
- **只扫两处**:`CLAUDE.md` 的 `## 当前指针` 之后 · `ROADMAP.md` 的第一个 `### 📌 交接` 之后;
- **遇到「📜」历史横幅就停** —— 底下是过程记录,那里的 sha **是证据不是断言**,留着是对的;
- **纯数字不算**(如 `2026091`)—— 它多半是 run id 的一部分;
- **不许嵌在连字符串里**(如 `20260921-212415-bfcfbd2e` 的尾巴)—— 那是 run id;
- **要与"当前状态"词同段相邻**(`main`/`主干`/`当前`/`现在`)才算断言 ——
  `run.commit 逐字相同 3a0159c` 这类**证据陈述**,不在其列。

用法:`python3 tools/check_anchor_no_sha.py [--root DIR]`;exit 0 = 干净,1 = 有违规。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 锚点的两半:CLAUDE.md 的「当前指针」段 / ROADMAP.md 的「📌 交接」段
LIVE_START = re.compile(r"^(## 当前指针|### 📌 交接)")
# 「📜 历史」横幅 —— 其下不再扫(那里是过程记录,sha 是证据)
HISTORY_BANNER = re.compile(r"📜")

# 候选 sha:7–40 位十六进制,**且不许贴在连字符/字母数字旁**(否则会切进 run id)
HEXISH = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")

# "当前状态"词 —— 只有与它相邻,那个 sha 才是"对当前仓库的断言"而不是证据
STATE_WORDS = ("main", "主干", "当前", "现在")
NEAR_WINDOW = 24

TARGETS = ("CLAUDE.md", "ROADMAP.md")


def live_region(text: str) -> str:
    """截出「当前为真」的那一段:从锚点段头起,到第一条历史横幅为止。"""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if LIVE_START.match(ln)), None)
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if HISTORY_BANNER.search(lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def violations(text: str) -> list[tuple[int, str]]:
    """返回 `(行号, 该行原文)`;行号相对传入的 text。"""
    out: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in HEXISH.finditer(line):
            tok = m.group(0)
            if not re.search(r"[a-f]", tok):        # 纯数字 ⇒ 多半是 run id 的一部分
                continue
            window = line[max(0, m.start() - NEAR_WINDOW): m.end() + NEAR_WINDOW]
            if any(w in window for w in STATE_WORDS):
                out.append((n, line.strip()))
                break
    return out


def scan(root: Path) -> list[str]:
    msgs: list[str] = []
    for name in TARGETS:
        p = root / name
        if not p.exists():
            continue
        for n, line in violations(live_region(p.read_text(encoding="utf-8"))):
            msgs.append(f"{name}:{n}  {line}")
    return msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="锚点里不许写死 commit sha")
    ap.add_argument("--root", default=".", help="仓库根(默认当前目录)")
    args = ap.parse_args(argv)

    bad = scan(Path(args.root).resolve())
    if bad:
        print("[锚点守卫] ⛔ 指针/交接段里出现了**对当前仓库的 sha 断言** —— 它下次合并就会过期:")
        for b in bad:
            print(f"  {b}")
        print("  ⇒ 改成**现取**:`git log -1 --oneline main`;或删掉这个值。")
        print("  ⇒ PR 号可以写(`#75`),它不随时间改义。")
        return 1
    print("[锚点守卫] ✅ 指针/交接段里没有 sha 断言(sha 现取;历史区豁免)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
