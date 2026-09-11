"""覆盖率门防腐:覆盖率必须写进配置与 CI,且下限不低于 B 的目标(≥80%)。

依据:B `05-模块-评估与测试-v1.0.md:60`「覆盖:测试覆盖率(目标 ≥80%)」。
动机:覆盖率只写在报告里 = 会腐(阶段3 教训:纪律没有触发点 = 早晚会漏)。
本文件即那处触发点:改 pyproject / CI 都会在这里响。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "eval-gate.yml"


def test_dev_extra_declares_pytest_cov():
    """pytest-cov 必须在 dev 附加依赖里 —— 否则 CI 装不上,门形同虚设。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r"^dev\s*=\s*\[(.*?)\]", text, re.S | re.M)
    assert m, "pyproject 缺 [project.optional-dependencies] dev 数组"
    assert "pytest-cov" in m.group(1), f"dev 未声明 pytest-cov: {m.group(1)!r}"


def test_coverage_scoped_to_package_and_omits_entry_shim():
    """覆盖率只量被测包;`__main__.py` 是 `python -m` 入口 shim,omit 掉。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r"^\[tool\.coverage\.run\]", text, re.M), "缺 [tool.coverage.run] 段"
    assert re.search(r'source\s*=\s*\[\s*"eval_gate"\s*\]', text), \
        'coverage.run.source 须为 ["eval_gate"]'
    assert "__main__.py" in text, "coverage.run.omit 未排除 __main__.py(入口 shim)"


def test_ci_enforces_coverage_floor_at_least_80():
    """CI 必须显式强制覆盖率下限,且 ≥ B 的目标 80%。"""
    wf = WORKFLOW.read_text(encoding="utf-8")
    floors = re.findall(r"--cov-fail-under[=\s]+(\d+)", wf)
    assert floors, "CI 未强制覆盖率下限(缺 --cov-fail-under)"
    assert min(int(x) for x in floors) >= 80, f"覆盖率下限低于 B 目标 80%: {floors}"
