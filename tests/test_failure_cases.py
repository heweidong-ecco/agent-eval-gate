"""失败集完整性(「失败即补 case」的结构守卫)。

依据:Kit `eval/README.md:13,25` + 本仓 `eval/cases/README.md`。
动机:2026-09-10 复盘发现该纪律**整个阶段3 零执行** —— 因为它只有文字、没有结构。
本测试即那处结构:任何进入 `eval/cases/` 的失败条目**必须能装载、且必须带根因**。

放在 pytest 里(而非只在 CI yaml)是为了**本地也能跑** —— 漏了当场就知道。
"""
import json
from pathlib import Path

import pytest

from eval_gate.schema import EvalError, load_evals

CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
REQUIRED_REGRESSION_FIELDS = ("from_run", "observed", "root_cause", "status")
VALID_STATUS = {"open", "fixed", "accepted"}
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "eval-gate.yml"


def test_ci_evalset_trace_guard_accepts_all_three_legitimate_paths():
    """CI 的「改评测集/阈值须同步留痕」必须认得**三条**合法路径。

    动机(2026-09-12,DEC-005):该守卫原先只认 `eval/cases/` 与 `docs/复盘/` ——
    即只建模了**失败驱动**的改动。而**决策驱动**的改动(转档 / 扩充 / 调阈值,
    如 R2a 与本次 boundary 扩充)**没有合法留痕路径** ⇒ 只能二选一:绕过守卫,或伪造一条复盘。

    本测试把三条路径钉住,防止清单被静默收窄(收窄 = 又回到"改动无路可走")。
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = [ln for ln in text.splitlines() if ln.strip().startswith("if ! echo \"$CHANGED\"")]
    assert guard, "未找到评测集/阈值留痕守卫(工作流被改动?)"
    line = guard[0]
    for path in ("eval/cases/", "docs/复盘/", "docs/decisions/"):
        assert path in line, f"留痕守卫未接受合法路径 {path!r}(清单被收窄了?)"


def test_ci_evalset_trace_guard_reads_unquoted_paths():
    """取改动清单时必须 `-c core.quotePath=false`。

    **动机(2026-09-12 CI 实测,不是防御性臆想)**:`git diff --name-only` 默认对**非 ASCII 路径**
    做 C-quoting ⇒ 输出 `"docs/decisions/DEC-005-golden\\351\\233\\206…"`(行首是双引号),
    `^…` 正则**永远匹配不上**。后果:本仓的 `docs/复盘/`(全中文名)**从来没生效过** ——
    是死代码;直到新增 `docs/decisions/` 才把潜伏 bug 引爆。

    ⚠️ 本仓**中文文件名的目录**(`docs/复盘/`、`docs/decisions/`)正是这条路径的主要使用者,
    所以这个 flag 不能删。
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    diff_lines = [ln for ln in text.splitlines() if "diff --name-only" in ln]
    assert diff_lines, "未找到取改动清单的命令(工作流被改动?)"
    for ln in diff_lines:
        assert "core.quotePath=false" in ln, (
            "取改动清单未关掉 quotePath ⇒ 中文路径会被 C-quoting,"
            f"留痕守卫将永远匹配不上:{ln.strip()!r}")


def _case_files():
    return sorted(CASES_DIR.glob("*.json"))


def test_cases_dir_exists_with_readme():
    """「失败即补 case」的落地点必须存在 —— 目录不在,纪律就会漏(2026-09-10 教训)。"""
    assert CASES_DIR.is_dir(), "eval/cases/ 不存在:失败集无处可落"
    assert (CASES_DIR / "README.md").is_file(), "eval/cases/README.md 缺失(格式无据可依)"


@pytest.mark.parametrize("path", _case_files(), ids=lambda p: p.name)
def test_case_file_is_loadable(path):
    """必须是合法评测集(可直接被 load_evals 装载)——避免失败集本身是坏的。"""
    try:
        ev = load_evals(path)
    except EvalError as e:
        pytest.fail(f"{path.name} 装载失败: {e}")
    assert ev.cases, f"{path.name} 无条目"


@pytest.mark.parametrize("path", _case_files(), ids=lambda p: p.name)
def test_every_case_has_root_cause(path):
    """每条失败必须带根因 —— 没有根因的记录等于没记(不许空着,写「待查」也算)。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    missing = []
    for c in raw.get("evals", []):
        r = c.get("regression") or {}
        for k in REQUIRED_REGRESSION_FIELDS:
            if not r.get(k):
                missing.append(f"id={c.get('id')} 缺 regression.{k}")
        if r.get("status") and r["status"] not in VALID_STATUS:
            missing.append(f"id={c.get('id')} regression.status={r['status']!r} 非法(须 ∈ {sorted(VALID_STATUS)})")
    assert not missing, f"{path.name} 失败集不完整: " + "; ".join(missing)


def test_cases_are_documented_in_readme_format():
    """README 必须写明格式与纪律(否则下一个人不知道怎么补)。"""
    text = (CASES_DIR / "README.md").read_text(encoding="utf-8")
    for kw in ("regression", "root_cause", "status", "失败即补 case"):
        assert kw in text, f"eval/cases/README.md 未说明 {kw!r}"
