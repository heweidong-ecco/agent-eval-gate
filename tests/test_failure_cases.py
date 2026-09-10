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
