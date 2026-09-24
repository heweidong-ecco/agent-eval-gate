#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 2 的**时序**判据(`DEC-020` 的 α,签核 **D-29**,2026-09-24)。

原来的洞
--------
门 2 原判据是 `grep -q 'test-driven-development' .claude/traces/latest.json` ——
读的是那个**会话累计**的 `skills` 字段 ⇒ **开头调一次,之后本会话所有提交永久满足**。
实测(2026-09-15 那场会话):TDD 只在早期调 1 次,之后 4 个编码任务(含改判分器输入契约的 A2)
一次没调 —— **而这道门全程一次没响过**。它退化成「**一个永远不失败的检查**」,
而它**比没有检查更坏**:让下游(锚点/复盘/签核)相信"这里有结构兜着"。

新判据
------
> 取 **`lo` = 上一次 `git commit` 的时刻**(转录里它是一条 Bash 调用);
> **通过 ⟺ 存在一次 `test-driven-development` 调用,其时刻落在 `(lo, 本次最早那次实现编辑]`**。
> 人话:**自上次提交以来、动手之前,调过 TDD。**

⚠️ **这个判据是第三版** —— 前两版都被**实跑**证伪,过程值得留:
1. **第一版**用「本会话出现过」(原实现)⇒ 开头调一次**永久满足**,门从不响;
2. **第二版**用「本次编辑之前最近的那条 `type:"user"` 行」当"本轮起点" ——
   **实测证伪**:`type:"user"` 的**行**里混着**工具结果**,而真用户消息的时间戳又与工具调用
   **互相穿插**(同一 Skill 调用 `.556` vs 用户行 `.604/.605`)⇒ 窗口被压成 **49 毫秒**
   ⇒ **一律误拦**(连那次改动自己的提交都被它拦下);
3. **第三版(本版)**改用 `git commit` 作锚。它还顺手堵了一个洞:
   用「最早那次**编辑**」会被**上一段工作的编辑**污染(同一文件跨两次提交时 → 放行);
   而 `git commit` 是"上一段工作结束"的**真实**边界。

⚠️ **判不了 ⇒ 不阻断**(打印 `undecidable`)—— `lo` 之后本会话若从未编辑过这些文件
(如文件是别处改的),拦下来就是**误拦**;而误拦是守卫被关掉的头号原因。
**代价(认下)**:这条路径**可被利用**,所以它**每次都会出声**,不当成"通过"。

⚠️ 已知边界(`D-29` 签核时预登记):**同一件工作分多次提交**时可能被拦 ⇒
用显式豁免 `[no-skill: <理由>]`(由 `commit-msg` 处理,豁免率可统计)。

⚠️ **判不了 ⇒ 不阻断**(打印 `undecidable`)—— 本会话若从未编辑过这些文件(如文件是别处改的),
拦下来就是**误拦**;而误拦是守卫被关掉的头号原因。**代价(认下)**:这条路径**可被利用**,
所以它**每次都会出声**,不当成"通过"。

⚠️ 已知边界(`D-29` 签核时预登记):**同一件工作分多次提交**时可能被拦 ⇒
用显式豁免 `[no-skill: <理由>]`(由 `commit-msg` 处理,豁免率可统计)。

用法:`check_skill_before_edit.py --transcript <sess.jsonl> --files a.py,b.py [--root DIR]`
exit 0 = 通过 / 判不了(后者会出声);1 = 拦。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

TDD_SKILL = "test-driven-development"
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
# 转录里 `git commit` 是一条 Bash 工具调用 —— 判据拿它当"上一段工作结束"的锚
COMMIT_RE = re.compile(r"\bgit\b[^\n;&|]*\bcommit\b")


def parse_ts(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def events(transcript: Path) -> list[tuple[datetime, str, str]]:
    """按时间顺序产出 `(时刻, 类别, 细节)`;类别 ∈ {user, skill, edit}。"""
    out: list[tuple[datetime, str, str]] = []
    for raw in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue          # 转录里有非 JSON 行(实测),跳过即可
        ts = parse_ts(d.get("timestamp"))
        if ts is None:
            continue
        if d.get("type") == "user":
            continue              # ⚠️ user 行**不用** —— 判据不依赖它(见模块 docstring)
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name, inp = b.get("name"), (b.get("input") or {})
            if name == "Skill":
                out.append((ts, "skill", str(inp.get("skill") or "")))
            elif name in EDIT_TOOLS:
                fp = inp.get("file_path") or inp.get("notebook_path")
                if fp:
                    out.append((ts, "edit", str(fp)))
            elif name == "Bash" and COMMIT_RE.search(str(inp.get("command") or "")):
                out.append((ts, "commit", ""))
    out.sort(key=lambda x: x[0])
    return out


def _norm(p: str, root: Path) -> str:
    """把编辑路径归一到仓库相对(容忍绝对路径 / 软链)。"""
    try:
        return str(Path(p).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return p


def judge(evs: list[tuple[datetime, str, str]], files: set[str], root: Path):
    """返回 `(verdict, 说明)`;verdict ∈ {ok, block, undecidable}。

    **取 `lo` = 上一次 `git commit` 的时刻** —— 它是"上一段工作结束"的可观测锚,
    且**不受"同一文件跨多次提交"影响**(用"最早那次编辑"会被上一段的编辑污染,已验证是洞)。
    """
    lo = max((ts for ts, k, _ in evs if k == "commit"), default=None)

    edits = [(ts, _norm(f, root)) for ts, k, f in evs if k == "edit"]
    after = [(ts, f) for ts, f in edits if lo is None or ts > lo]
    hits = [(ts, f) for ts, f in after if f in files]
    if not hits:
        return "undecidable", ("本会话**上一次提交之后**没有编辑过本次提交里的实现文件"
                               " ⇒ 判不了 ⇒ 不阻断(请人工看一眼)")

    t_first = min(ts for ts, _ in hits)
    tdd = [ts for ts, k, n in evs if k == "skill" and n == TDD_SKILL]
    window = [ts for ts in tdd if ts <= t_first and (lo is None or ts > lo)]
    if window:
        base = f";上次提交在 {lo.isoformat()}" if lo else ";本会话此前无提交"
        return "ok", f"TDD 调用于 {min(window).isoformat()},早于首次实现编辑 {t_first.isoformat()}{base}"

    if not tdd:
        why = "本会话**从没**调用过 test-driven-development"
    elif max(tdd) > t_first:
        why = (f"**先改后补** —— 最早的实现编辑在 {t_first.isoformat()},"
               f"而 TDD 那次在 {max(tdd).isoformat()}")
    else:
        why = (f"**上一次提交({lo.isoformat() if lo else '无'})之后没再调 TDD** —— "
               f"TDD 最后一次在 {max(tdd).isoformat()},而本次实现编辑在 {t_first.isoformat()}")
    return "block", why


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="门 2:实现改动之前是否调过 TDD")
    ap.add_argument("--transcript", required=True, help="本会话的 session JSONL")
    ap.add_argument("--files", required=True, help="本次提交的实现文件(逗号分隔)")
    ap.add_argument("--root", default=".", help="仓库根,用于把绝对路径归一到相对")
    args = ap.parse_args(argv)

    tr = Path(args.transcript)
    if not tr.exists():
        print("⚠ 门 2 跳过:找不到本会话转录,判不了。", file=sys.stderr)
        return 0

    files = {f.strip() for f in args.files.split(",") if f.strip()}
    verdict, why = judge(events(tr), files, Path(args.root))

    if verdict == "ok":
        return 0
    if verdict == "undecidable":
        print(f"⚠ 门 2 {verdict}:{why}", file=sys.stderr)
        return 0
    print(why, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
