"""锚点守卫:指针/交接段里**不许写死「每次合并都会变」的值**(主要是 commit sha)。

它补的是哪个"无声"
------------------
锚点是**每会话第一个被读**的位置。写死 `main = <sha>` 之后,**下一次合并它就变成假话** ——
不报错、不变红,只是**安静地误导每一个读它的人**(2026-09-21 实测:三天里就旧了一截)。
⇒ 规矩:`CLAUDE.md` 的「当前指针」段 / `ROADMAP.md` 的「📌 交接」段,
**只放"当前为真"的断言**;sha 要现取(`git log -1 --oneline main`)。**PR 号可以写**(它不改义)。

口径边界(刻意写死,防止工具"顺手"扩大扫描面)
--------------------------------------------
- **只扫两处**:`CLAUDE.md` 的 `## 当前指针` 之后、`ROADMAP.md` 的第一个 `### 📌 交接` 之后;
- **遇到「📜 历史」横幅就停** —— 底下是过程记录,里面的 sha **是证据,不是断言**,留着是对的;
- **纯数字不算**(如 `2026091`,它多半是 run id 的一部分)—— 要求 hex 串里**至少有一个 a-f**;
- **同段相邻**(含 `main`/`当前`/`现在`/`主干` 等"当前状态"词)才算断言 ——
  `run.commit 逐字相同 3a0159c` 这类**证据陈述**,不在其列。

⚠️ 同 `test_evidence_coverage.py`:本文件**自造合成仓库**,不依赖真实文件的内容。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_anchor_no_sha.py"

_OK_CLAUDE = "# 项目\n\n## 当前指针\n\n> main 取当前值:`git log -1 --oneline main`。\n"


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root)],
                          capture_output=True, text=True)


def _mk(tmp: Path, claude: str = "", roadmap: str = "") -> Path:
    (tmp / "CLAUDE.md").write_text(claude or _OK_CLAUDE, encoding="utf-8")
    (tmp / "ROADMAP.md").write_text(roadmap or "# R\n\n### 📌 交接\n\n> 无。\n", encoding="utf-8")
    return tmp


# ── 该红的两种写法 ──────────────────────────────────────────────────────

def test_sha_equality_assertion_is_flagged(tmp_path):
    """`main = <sha>` —— 典型写法,下一次合并即过期。"""
    _mk(tmp_path, claude="# 项目\n\n## 当前指针\n\n> 已合(PR #75,main = `80b3309`)。\n")
    r = _run(tmp_path)
    assert r.returncode == 1, f"应报违规:{r.stdout}{r.stderr}"


def test_present_tense_sha_claim_is_flagged(tmp_path):
    """`main` 现在 `<sha>` —— 现在时为假。"""
    _mk(tmp_path, claude="# 项目\n\n## 当前指针\n\n> 已合;main 现在 `3e45e81`。\n")
    assert _run(tmp_path).returncode == 1


def test_roadmap_handoff_is_also_scanned(tmp_path):
    """`ROADMAP.md` 的「📌 交接」段同样在列(锚点两半)。"""
    _mk(tmp_path, roadmap="# R\n\n### 📌 交接\n\n> `main` = **`80b3309`**。\n")
    assert _run(tmp_path).returncode == 1


# ── 不该红的(防误报 —— 这是本守卫能不能活下来的关键)─────────────────

def test_recommended_phrasing_passes(tmp_path):
    """推荐写法:只写"怎么取",不写死值。"""
    assert _run(_mk(tmp_path)).returncode == 0


def test_run_id_is_not_a_sha(tmp_path):
    """run id(`20260921-212415-bfcfbd2e`)不是 sha 断言 —— 它天然自带日期,不会过期。"""
    _mk(tmp_path, claude="# 项目\n\n## 当前指针\n\n> 本轮 run `20260921-212415-bfcfbd2e` 已归档。\n")
    assert _run(tmp_path).returncode == 0


def test_sha_below_history_banner_is_exempt(tmp_path):
    """**分界之下是历史** —— 那里的 sha 是证据,不是断言(否则等于逼人删证据)。"""
    _mk(tmp_path, claude=(
        "# 项目\n\n## 当前指针\n\n> 当前无待办。\n\n"
        "> ### 📜 分界:以下全部是「历史」\n\n> 当时 main = `80b3309`,后已推进。\n"))
    assert _run(tmp_path).returncode == 0


def test_sha_without_state_word_passes(tmp_path):
    """`run.commit 逐字相同 3a0159c` —— **证据陈述**,不是对"当前状态"的断言。"""
    _mk(tmp_path, claude="# 项目\n\n## 当前指针\n\n> 两块 run.commit 逐字相同 `3a0159c`。\n")
    assert _run(tmp_path).returncode == 0


# ── 真仓自检(与 test_evidence_coverage 同款:让守卫守到自己头上)──────

def test_real_repo_is_clean():
    """本仓指针/交接段里**当前必须没有 sha 断言** —— 否则这条守卫先红了。"""
    r = _run(ROOT)
    assert r.returncode == 0, f"本仓锚点有 sha 断言:\n{r.stdout}"
