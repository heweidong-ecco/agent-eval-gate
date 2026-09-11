#!/usr/bin/env python3
"""门禁绕过重算 —— 从 **git 历史**重放门 1 的判据(CI 侧)。

为什么需要它
------------
门 1/门 2 是**本地** hook,`git commit --no-verify` 就能绕过;本地 `post-commit`
留痕也依赖 `core.hooksPath` 没被改。**唯一绕不过的一层是 CI 里的历史重算** ——
门 1 的判据是逐提交的(只看那次提交的文件集),所以可以从历史完整重放。

> 与 `post-commit` 的分工:post-commit 是**本机事后留痕**(带上下文,可含门 2);
> 本工具是**远端权威重算**(只判门 1,因为它不依赖本机会话状态)。

判据(与 `.githooks/commit-msg` 门 1 一致)
------------------------------------------
某提交 **同时**满足:
  ① 含实现文件(`^(app|backend|src)/.*\\.(py|ts|js)$`);
  ② 含 **0** 个测试文件(`(^|/)tests?/.*\\.(py|ts|js)$`);
  ③ 提交信息**没有**合法豁免 —— 合法 = `[no-test: <理由>]`(**必须带理由**;裸 `[no-test]` 不算)
→ 判为**绕过**。

诚实的边界
----------
1. 若本机伪造历史(base 取错/浅克隆导致算不出来),本工具**无法判定**,此时打警告并
   **exit 0**(fail-open,与门 2 的既有约定一致)—— 不假装通过,也不误炸 CI。
2. **规则是向前生效的,不是追溯的。** 2026-09-11 把覆盖范围从 `app|backend|src`
   扩到「+ 门禁/工具脚本」后,该日期**之前**的历史提交会被本工具**追溯标记**
   (当时它们改 hook 脚本确实没配测试,但那时不违规)。
   → CI 用 `pull_request.base.sha` / `event.before` 作 base,**天然把范围限定为新提交**,
     正常推送不会碰到这些遗留提交;
   → 但若 base 取到很远的过去(如长 PR、rebase),就会看到一批"历史遗留"告警。
     **这不是回归,是规则生效时点问题** —— 按需在 base 上取近点即可。

用法
----
    python tools/check_gate_bypass.py <base> [--repo DIR]

CI 里 base 通常取 `${{ github.event.pull_request.base.sha }}` 或 `github.event.before`。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 实现文件 = 应用代码 **+ 门禁/工具脚本自身**(与 .githooks/commit-msg 的 SRC、impl-guard 的路径判据三处一致)
# 注:`.githooks/` 下的 git hook **按惯例没有扩展名**(`commit-msg` / `post-commit`),故整个目录都算。
IMPL_RE = re.compile(r"^(app|backend|src)/.*\.(py|ts|js)$"
                     r"|^(\.claude/hooks|tools)/.*\.(sh|py)$"
                     r"|^\.githooks/")
TEST_RE = re.compile(r"(^|/)tests?/.*\.(py|ts|js)$")
# 合法豁免:[no-test: <非空理由>]  —— 裸 [no-test] 不算(理由必须可见,豁免才可审计)
EXEMPT_RE = re.compile(r"\[no-test:\s*[^\]]")


def _git(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="基线(sha 或 ref);检查 base..HEAD 之间的提交")
    ap.add_argument("--repo", default=".", help="仓库路径(默认当前目录)")
    a = ap.parse_args()
    repo = Path(a.repo).expanduser().resolve()

    rc, out = _git(repo, "rev-list", f"{a.base}..HEAD")
    if rc != 0:
        print(f"⚠ 无法计算 {a.base}..HEAD(浅克隆或 base 缺失)—— 本次**无法判定**,不阻断。",
              file=sys.stderr)
        return 0

    shas = [s for s in out.split() if s]
    violations: list[tuple[str, int]] = []
    for sha in shas:
        _, files = _git(repo, "show", "--name-only", "--format=", sha)
        _, msg = _git(repo, "show", "-s", "--format=%B", sha)
        changed = [f for f in files.splitlines() if f.strip()]
        n_impl = sum(1 for f in changed if IMPL_RE.match(f))
        n_test = sum(1 for f in changed if TEST_RE.match(f))
        if n_impl > 0 and n_test == 0 and not EXEMPT_RE.search(msg):
            violations.append((sha, n_impl))

    if violations:
        print("✗ 门禁绕过:以下提交**改了实现却无任何测试改动**,且没有带理由的豁免:", file=sys.stderr)
        for sha, n in violations:
            _, subject = _git(repo, "show", "-s", "--format=%s", sha)
            print(f"    {sha[:12]}  实现文件 {n} 个  {subject.strip()}", file=sys.stderr)
        print("\n  门 1 是**本地** hook,可被 `git commit --no-verify` 绕过;"
              "本检查从 git 历史重放,是绕不过的那一层。", file=sys.stderr)
        print("  二选一:① 补测试;② 提交信息写 [no-test: <理由>](必须带理由)。", file=sys.stderr)
        return 1

    print(f"✅ 绕过重算通过:{len(shas)} 个提交,无「改实现无测试且无豁免」的绕过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
