#!/usr/bin/env python3
"""证据覆盖守卫 —— 「被引用的结论,其证据必须能重算」。

依据 `DEC-018`(MTTR **覆盖目标**;签核于收尾批次 D-24)。
上游事实:`docs/reports/P5-1/灾备演练记录.md`(2026-09-13 首次实测)。

为什么是"覆盖"而不是"MTTR 目标值"
----------------------------------
`DEC-014 §4.1` 定下的归档口径是**按需**:只有"被引用的"证据才付归档成本。
于是本仓的形状是 —— **已归档的 ≈1s 可恢复;未归档的不是"慢",是"根本恢复不了"**。
⇒ 一个**时间目标**在这种形状下无从谈:没有可优化的连续量,只有"能不能恢复"这个二值。
**可守的量是缺口数**,不是秒数。本工具守的就是它。

它补的是哪个"无声"
------------------
`eval/runs/*.trace.jsonl` 被 gitignore(`.gitignore:24`)⇒ 机器丢 = 证据丢。
但反过来也成立:**git 里看不出"少没少东西"** —— 一篇报告引用了一个从未归档的 run,
不会报错、不会变红、不会有人发现,直到真的要用它的那一天。
⇒ 本工具把"引用"与"归档"两边对上,把缺口变成一条会红的检查。

口径(刻意写死,防止后来者"顺手"放宽)
--------------------------------------
- **扫**:`*.md`(文档/报告/复盘/决策/摘要)+ `tools/*.sh`;
- **不扫**:代码文件(`*.py`)。早先的临时 grep 把代码注释里的 run id 也当引用,
  会把"实现细节里提过一嘴"变成归档义务;
- **跳过** `.git` / `.venv` / `.claude`(后者含 worktree 副本,会把同一份文档数两遍);
- **归档按需**:没被任何地方引用的 run **不必**归档 —— 不是漏洞,是 `DEC-014 §4.1` 的口径。

用法
----
    python3 tools/check_evidence_coverage.py [--root DIR]
退出码:0 = 无新增缺口且允许清单未腐烂 · 1 = 有缺口 / 允许清单有问题 · 2 = 用法错误

设计上的两条"不许静默"
----------------------
① 允许清单里的项**仍然打印**(允许 ≠ 隐藏);
② 允许清单里"其实已归档"的项判 **exit 1** —— 清单只增不减会悄悄放宽守卫。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

#: run id 形状:`20260912-171456-f5c4a6ec`(与 `eval/runs/` 的命名一致)
RUN_ID_RE = re.compile(r"\b20\d{6}-\d{6}-[0-9a-f]{8}\b")

#: 扫描时跳过的目录 —— `.claude` 里含 worktree 副本,不跳会把同一份文档数两遍
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".claude"}

ALLOWLIST_REL = Path("tools") / "evidence_coverage_allowlist.json"


class AllowlistError(Exception):
    """允许清单本身写坏了(配置错误 ⇒ exit 2,不是"有缺口" ⇒ exit 1)。"""


def reference_surface(root: Path) -> list[Path]:
    """引用面 = 结论性文字(`.md`)+ 演练脚本(`tools/*.sh`)。"""
    files: list[Path] = []
    for p in sorted(root.rglob("*.md")):
        if not SKIP_DIRS.intersection(p.relative_to(root).parts):
            files.append(p)
    files += sorted((root / "tools").glob("*.sh"))
    return files


def referenced_runs(root: Path) -> dict[str, set[str]]:
    """被引用面指名引用的 run → 引用了它的文件(相对路径)。"""
    out: dict[str, set[str]] = {}
    for p in reference_surface(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for rid in RUN_ID_RE.findall(text):
            out.setdefault(rid, set()).add(str(p.relative_to(root)))
    return out


def archived_runs(root: Path) -> set[str]:
    """**在 git 里**已归档的 run(`ls-files` 看索引 —— 与 CI 的检出语义一致)。"""
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--", "eval/runs"],
                       capture_output=True, text=True)
    out: set[str] = set()
    for line in r.stdout.splitlines():
        name = Path(line).name
        if name.endswith(".spans.jsonl"):
            out.add(name[: -len(".spans.jsonl")])
    return out


def load_allowlist(root: Path) -> tuple[dict[str, str], list[str]]:
    """读允许清单 → (可用的 {run_id: 理由}, 缺理由的 run_id 列表)。

    ⚠️ JSON 写坏时**抛出 `AllowlistError`**(由 `main` 转成 exit 2 + 可读消息):
    裸 traceback 会让人以为是**工具坏了**,而不是**清单写错了** —— 排查方向被带偏。
    (2026-09-15 实记:手工写这份清单时当场写坏过。)
    """
    p = root / ALLOWLIST_REL
    if not p.is_file():
        return {}, []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise AllowlistError(f"{ALLOWLIST_REL} 不是合法 JSON:{e}") from e
    if not isinstance(data, dict):
        raise AllowlistError(f"{ALLOWLIST_REL} 顶层必须是对象(含 unrecoverable 数组)")
    allowed: dict[str, str] = {}
    no_reason: list[str] = []
    for e in data.get("unrecoverable", []):
        rid = str(e.get("run_id") or "").strip()
        reason = str(e.get("reason") or "").strip()
        if not rid:
            continue
        if reason:
            allowed[rid] = reason
        else:
            no_reason.append(rid)
    return allowed, no_reason


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="证据覆盖守卫(DEC-018 覆盖目标)")
    ap.add_argument("--root", default=".", help="仓库根(默认当前目录)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    refs = referenced_runs(root)
    arch = archived_runs(root)
    try:
        allowed, no_reason = load_allowlist(root)
    except AllowlistError as e:
        print(f"[证据覆盖] ❌ 允许清单读不了:{e}", file=sys.stderr)
        print("           这是**配置错误**(exit 2),不是发现了缺口 —— "
              "请修好清单再跑。", file=sys.stderr)
        return 2

    gaps = sorted(rid for rid in refs if rid not in arch)
    new_gaps = [g for g in gaps if g not in allowed]
    known_gaps = [g for g in gaps if g in allowed]
    stale = sorted(rid for rid in allowed if rid in arch)

    covered = len(refs) - len(gaps)
    total = len(refs)
    pct = (100.0 * covered / total) if total else 100.0

    print(f"[证据覆盖] 引用面 {len(reference_surface(root))} 个文件 · "
          f"被引用 run {total} 个")
    print(f"           已归档 {covered}/{total} ({pct:.1f}%)")

    if refs:
        print("   ✅ 已归档:")
        for rid in sorted(refs):
            if rid in arch:
                print(f"      {rid}")

    if known_gaps:
        print(f"   ⚠️ 已知不可恢复(允许清单 —— 列出但**不算缺口**):{len(known_gaps)} 个")
        for rid in known_gaps:
            src = ",".join(sorted(refs[rid])[:2])
            print(f"      {rid}  理由:{allowed[rid]}  (引用:{src})")

    if new_gaps:
        print(f"   ❌ **缺口**:{len(new_gaps)} 个被引用但**未归档**的 run")
        for rid in new_gaps:
            src = ",".join(sorted(refs[rid])[:2])
            print(f"      {rid}  引用:{src}")
        print("      ⇒ 补救(有本地 trace 时):")
        print("         python3 tools/archive_evidence.py "
              "--trace eval/runs/<run_id>.trace.jsonl "
              "--out eval/runs/<run_id>.spans.jsonl")
        print(f"      ⇒ 本地 trace 已不存在时,写进 {ALLOWLIST_REL}(**必须带理由**);")
        print("         它只是不再拦,不会从报告里消失。")
        print("      ⇒ 若该 run 的结论已作废,应改引用它的文档,而不是往清单里加。")

    if no_reason:
        print(f"   ❌ 允许清单里有 {len(no_reason)} 条**没写理由**:{no_reason}")
        print("      ⇒ 裸条目不算 —— 与 `[no-test: <理由>]` 同一约定:理由进 git 才可审计。")

    if stale:
        print(f"   ❌ 允许清单里有 {len(stale)} 条**已归档却仍被豁免**(清单腐烂):{stale}")
        print("      ⇒ 删掉这些条目,否则守卫会被慢慢放宽。")

    bad = bool(new_gaps or no_reason or stale)
    print("   ⇒ " + ("❌ 不通过" if bad else "✅ 通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
