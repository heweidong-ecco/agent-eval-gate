"""证据覆盖守卫(`DEC-018` 的「覆盖目标」)。

**覆盖目标**(取代"MTTR 目标值"):凡被**结论性产物指名引用**的 run,
必须在 git 里有 `<run_id>.spans.jsonl` 归档 —— 否则机器一丢,**那条结论永远重算不出来**。

为什么是"覆盖"而不是"时间":`docs/reports/P5-1/灾备演练记录.md §5` 实测 ——
**已归档的证据 ≈1s 可恢复;未归档的不是"慢",是"根本恢复不了"(无界)**。
时间目标在这种形状下无从谈起(没有可优化的连续量),**缺口数才是可守的量**。

⚠️ **本文件必须自造仓库,不许依赖真实 `eval/runs/`** ——
那些 `.trace.jsonl` 被 gitignore,CI 上根本不存在(同 `test_archive_evidence.py` 的教训:
初版 glob 本地 trace ⇒ 本地绿、**CI 红**)。
⇒ 因此工具必须接受 `--root`,测试全部在 `tmp_path` 里建**合成仓库**。

口径边界(刻意写死,防止工具"顺手"扩大扫描面):
- **扫**:`*.md`(文档/报告/复盘/决策/摘要)+ `tools/*.sh`;
- **不扫**:代码文件(`*.py`)—— 早先的临时 grep 把代码注释里的 id 也算作引用,
  那会把"实现细节里提过一嘴"变成归档义务。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_evidence_coverage.py"

#: 真实形状的 run id(时间戳-序号-哈希)
RID = "20260912-171456-f5c4a6ec"
RID2 = "20260910-193433-492c6fe4"


def _git(d: Path, *args):
    return subprocess.run(["git", *args], cwd=str(d), capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    """合成仓库:`git init` + 一次 `add`(`ls-files` 看的是索引,无需 commit)。"""
    d = tmp_path / "repo"
    (d / "docs").mkdir(parents=True)
    (d / "tools").mkdir()
    (d / "eval" / "runs").mkdir(parents=True)
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    return d


def _write(d: Path, rel: str, text: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _stage(d: Path):
    """把新写的文件放进索引(`ls-files` 才看得见)。"""
    _git(d, "add", "-A")


def _run(d: Path, *extra):
    return subprocess.run([sys.executable, str(TOOL), "--root", str(d), *extra],
                          capture_output=True, text=True)


def _archive(d: Path, rid: str, content: str = '{"name": "sut.call"}\n'):
    _write(d, f"eval/runs/{rid}.spans.jsonl", content)


# ── ① 覆盖齐全 ⇒ 通过 ──────────────────────────────────────────────────────

def test_all_referenced_runs_archived_exits_0(tmp_path):
    """被引用的 run 都有归档 ⇒ exit 0,并**报出覆盖率**(不是静默绿)。"""
    d = _repo(tmp_path)
    _write(d, "docs/r.md", f"本轮 run `{RID}` 取到了 exit 0。\n")
    _archive(d, RID)
    _stage(d)

    r = _run(d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"{RID}" in r.stdout, "通过的 run 也应在报告里可见"
    assert "1/1" in r.stdout or "100" in r.stdout, f"未报覆盖率:{r.stdout!r}"


# ── ② 有缺口 ⇒ 拦下并指名 ──────────────────────────────────────────────────

def test_missing_archive_exits_1_and_names_the_run(tmp_path):
    """有 run 被引用但无归档 ⇒ exit 1,**并把是哪个 run 打在脸上**。

    这是本工具存在的全部理由:缺口原本**完全无声**
    (`eval/runs/*.trace.jsonl` 被 gitignore,git 里看不出少没少东西)。
    """
    d = _repo(tmp_path)
    _write(d, "docs/r.md", f"见 run `{RID}`。\n")
    _stage(d)

    r = _run(d)
    assert r.returncode == 1, f"缺口没被拦:{r.stdout!r}"
    assert RID in r.stdout, "拦下了却没说缺哪个 run —— 等于让人自己去找"
    assert "archive_evidence" in r.stdout, "应给出补救命令(工具已存在,别让人重新发明)"


# ── ③ 允许清单:不静默,且不得腐烂 ─────────────────────────────────────────

def _allowlist(d: Path, entries):
    _write(d, "tools/evidence_coverage_allowlist.json",
           json.dumps({"unrecoverable": entries}, ensure_ascii=False))


def test_allowlisted_missing_run_is_not_a_gap_but_still_named(tmp_path):
    """允许清单里的 run 缺归档 ⇒ **不算缺口(exit 0)**,但**仍须出现在输出里**。

    ⚠️ 允许 ≠ 隐藏。若清单里的项在报告里消失,清单就变成了"遗忘"的容器 ——
    与 `DEC-014 §4.1` 要求的"写明原因、留他人可读的记录"相反。
    """
    d = _repo(tmp_path)
    _write(d, "docs/r.md", f"见 run `{RID2}`。\n")
    _allowlist(d, [{"run_id": RID2, "reason": "本地 trace 已不存在,不可恢复"}])
    _stage(d)

    r = _run(d)
    assert r.returncode == 0, f"允许清单内的缺口不该拦:{r.stdout!r}"
    assert RID2 in r.stdout, "允许清单里的项被静默隐藏了"


def test_allowlist_entry_without_reason_is_rejected(tmp_path):
    """允许清单**必须写理由** —— 裸条目不算(同 `[no-test: <理由>]` 的既有约定)。"""
    d = _repo(tmp_path)
    _write(d, "docs/r.md", f"见 run `{RID2}`。\n")
    _allowlist(d, [{"run_id": RID2}])
    _stage(d)

    r = _run(d)
    # ⚠️ 不能写成 `returncode != 0` —— 工具不存在时 python 也返回 2,那样**因错误的原因通过**。
    assert r.returncode == 1, f"无理由的允许条目未被拒:{r.stdout!r}"
    assert "理由" in r.stdout, "拒了却没说为什么拒"


def test_malformed_allowlist_fails_loudly_not_with_a_traceback(tmp_path):
    """允许清单 JSON 写坏 ⇒ exit 2 + **可读的错误**,而不是一条 traceback。

    (2026-09-15 实记:手工写这份清单时**当场把 JSON 写坏**(字符串里嵌了裸引号),
     工具抛 traceback。traceback 会让人以为是**工具坏了**,而不是**清单写错了** ——
     排查方向被带偏,正是本仓复盘里反复出现的形状。)
    """
    d = _repo(tmp_path)
    _write(d, "docs/r.md", "本文不提任何 run。\n")
    _write(d, "tools/evidence_coverage_allowlist.json", '{"unrecoverable": [ oops }')
    _stage(d)

    r = _run(d)
    assert r.returncode == 2, f"坏清单的退出码应是 2(用法/配置错误):{r.stdout!r}"
    assert "Traceback" not in (r.stdout + r.stderr), "抛了 traceback,让人以为是工具坏了"
    assert "allowlist" in (r.stdout + r.stderr).lower() or "清单" in (r.stdout + r.stderr), \
        "没说是**哪个文件**坏了"


def test_stale_allowlist_entry_exits_1(tmp_path):
    """允许清单里的 run **其实已经归档** ⇒ exit 1(逼着清理)。

    动机:允许清单只增不减 ⇒ 它会慢慢变成"没人记得为什么"的垃圾场,
    并**悄悄放宽**守卫(同 `DEC-014 §4.1` 与 2026-09-11 允许清单那次的教训)。
    """
    d = _repo(tmp_path)
    _write(d, "docs/r.md", f"见 run `{RID}`。\n")
    _archive(d, RID)                      # 已经归档了
    _allowlist(d, [{"run_id": RID, "reason": "早已不可恢复"}])
    _stage(d)

    r = _run(d)
    assert r.returncode == 1, f"腐烂的允许条目没被拦:{r.stdout!r}"
    assert RID in r.stdout


# ── ④ 口径边界:归档按需,不搞全量 ─────────────────────────────────────────

def test_run_not_referenced_anywhere_needs_no_archive(tmp_path):
    """**没被引用的 run 不必归档** —— 这是刻意口径,不是漏洞。

    `DEC-014 §4.1`:"被引用的证据"= 可恢复;"没被引用的"= 丢了就丢了。
    若改成"全部 trace 都要归档",成本会随着每次运行无限增长,而收益为零。
    """
    d = _repo(tmp_path)
    _write(d, "docs/r.md", "本文不提任何 run。\n")
    _stage(d)

    r = _run(d)
    assert r.returncode == 0, f"未被引用的 run 被算成了缺口:{r.stdout!r}"


def test_code_files_are_not_a_reference_surface(tmp_path):
    """代码文件里出现 run id **不算引用** —— 扫描面刻意不含 `*.py`。

    (早先临时 grep 把代码注释里的 id 也当引用,会把实现细节变成归档义务;
     口径写死在这里,防止后来者"顺手"放宽。)
    """
    d = _repo(tmp_path)
    _write(d, "app/eval_gate/x.py", f'"""见 run {RID}。"""\n')
    _stage(d)

    r = _run(d)
    assert r.returncode == 0, f"代码文件被当成了引用面:{r.stdout!r}"


# ── ⑤ 自校验:让守卫在 CI 里**真的会跑** ────────────────────────────────────

def test_real_repo_is_covered():
    """**本仓自身必须通过覆盖守卫** —— 否则这个守卫永远不会被执行。

    动机(本仓反复踩过):**"装了 skills ≠ 会用 skills"**、**"写了纪律 ≠ 纪律会执行"**
    (`CLAUDE.md` 引避坑库 `A2`)。一个只躺在 `tools/` 里的脚本,和一份只写在文档里的规矩
    是同一种东西 —— **没有被触发点**。这条测试就是它的触发点:
    今后任何一份报告引用了未归档的 run,CI 会红。

    ⇒ 失败时**不要改这条测试**:去 `tools/archive_evidence.py` 补归档,
      或往允许清单里加**带理由**的条目(见工具输出里的两条补救路径)。
    """
    r = subprocess.run([sys.executable, str(TOOL), "--root", str(ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "本仓有被引用却未归档的 run(证据覆盖缺口):\n" + r.stdout + r.stderr)

