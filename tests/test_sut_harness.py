"""被测运行脚手架(`tools/sut-harness/`)的离线守卫。

只测**不需要 Docker / 不需要被测仓**的部分 —— 前置校验与文档承诺。
真正起容器的那条路只能在真机上跑(README 已写明),不在离线套件里假装覆盖。

动机:脚手架此前散在 `/tmp`,**重启丢过两次**;固化后若无守卫,它会再次悄悄漂移
(这正是本仓「门禁需要门禁」的一贯做法,见 tests/test_hooks.py / test_coverage_gate.py)。
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "sut-harness"
RUN_SUT = HARNESS / "run_sut.sh"
README = HARNESS / "README.md"


def test_harness_files_exist():
    for f in (RUN_SUT, HARNESS / "sut_run.py", HARNESS / "sitecustomize.py", README):
        assert f.is_file(), f"脚手架缺文件: {f.name}"


def test_run_sut_is_executable_and_syntactically_valid():
    assert RUN_SUT.stat().st_mode & 0o111, "run_sut.sh 不可执行(chmod +x)"
    r = subprocess.run(["bash", "-n", str(RUN_SUT)], capture_output=True, text=True)
    assert r.returncode == 0, f"run_sut.sh 语法错误: {r.stderr}"


def _run_with_env(**over):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())}
    env.update(over)
    return subprocess.run(["bash", str(RUN_SUT)], capture_output=True, text=True, env=env, timeout=60)


def test_rejects_missing_sut_repo_before_touching_docker(tmp_path):
    """路径不对必须**在碰 Docker 之前**就报错退出 —— 否则会在无关环境里乱起容器。"""
    r = _run_with_env(EVAL_SUT_REPO=str(tmp_path / "nope"))
    assert r.returncode == 1
    assert "被测仓路径不对" in r.stderr
    assert "Docker" not in r.stdout  # 未走到 Docker 分支


def test_rejects_sut_repo_without_env_file(tmp_path):
    """有 api/ 但缺 .env(容器要用它做 env-file)→ 同样前置失败。"""
    (tmp_path / "api").mkdir()
    r = _run_with_env(EVAL_SUT_REPO=str(tmp_path))
    assert r.returncode == 1
    assert ".env" in r.stderr


def test_script_takes_sut_path_from_env_not_hardcoded():
    """被测路径必须可注入 —— 本仓不得硬编码外部绝对路径(跨机器/换目录即失效)。"""
    text = RUN_SUT.read_text(encoding="utf-8")
    assert "EVAL_SUT_REPO" in text
    assert re.search(r'SUT_REPO="\$\{EVAL_SUT_REPO:-', text), "EVAL_SUT_REPO 未作为默认值来源"


def test_does_not_modify_the_sut_repo():
    """脚手架必须**只读挂载**被测仓 —— 这是「评测门不改被测」的结构保证。"""
    text = RUN_SUT.read_text(encoding="utf-8")
    assert "-v \"$SUT_REPO/api:/app:ro\"" in text, "被测 api/ 未以只读方式挂载"


def test_readme_documents_retirement_condition_and_capability_probe():
    """README 必须写明**退出条件**与**能力探针的必要性** —— 否则这层会变成永久负债。"""
    text = README.read_text(encoding="utf-8")
    assert "退出条件" in text, "README 未写退出条件(本层定位是过渡/兜底)"
    assert "能力探针" in text, "README 未写能力探针"
    assert "不剥离行内" in text or "不剥离" in text, "README 未写 --env-file 不剥注释的坑"
