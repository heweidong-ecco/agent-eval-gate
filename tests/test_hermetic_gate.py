"""`tools/check_hermetic.sh` 自身的防腐测试。

**为什么这个测试非有不可**:该脚本声称"能判出测试是否依赖本地产物"。
按项目教义(`A5`):**"验证不是'我做了验证动作',而是'这个验证动作真的能失败'"** ——
所以必须证明它**在真的有问题时会红**,而不是一个"从来没红过"的检查。

做法:造一个**临时 git 仓**(带一条**故意依赖被忽略产物**的测试),对它跑自检,断言其退出码。
⚠️ 本测试**自造全部输入**(不依赖任何本地产物)—— 否则它自己就成了它要抓的那类测试。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_hermetic.sh"

PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
GOOD_TEST = "def test_ok():\n    assert 1 + 1 == 2\n"
# ⚠️ 故意依赖**被 .gitignore 的**本地产物 —— 在"只含跟踪文件"的树里必红
BAD_TEST = ("from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[1]\n"
            "def test_depends_on_ignored_artifact():\n"
            "    assert list((ROOT / 'runs').glob('*.jsonl')), '本地没有产物 ⇒ 必红'\n")


def _mk_repo(tmp_path: Path, bad: bool, extra_test: str | None = None) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "app" / "eval_gate").mkdir(parents=True)     # ③ 自证步骤要能 import 到它
    (repo / "app" / "eval_gate" / "__init__.py").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("runs/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "tests" / "test_ok.py").write_text(GOOD_TEST, encoding="utf-8")
    if bad:
        (repo / "tests" / "test_bad.py").write_text(BAD_TEST, encoding="utf-8")
    if extra_test:
        (repo / "tests" / "test_extra.py").write_text(extra_test, encoding="utf-8")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "commit", "-q", "-m", "init", "--no-verify"]):
        subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True, env=env)
    return repo


def _run_checker(repo: Path):
    env = dict(os.environ, GATE_REPO=str(repo), GATE_PY=sys.executable)
    return subprocess.run(["sh", str(CHECKER)], capture_output=True, text=True, env=env)


def test_checker_goes_red_when_a_test_depends_on_local_artifacts(tmp_path):
    """**突变验证**:注入一条依赖本地产物的测试 ⇒ 自检必须**变红且退出码 1**。"""
    repo = _mk_repo(tmp_path, bad=True)
    (repo / "runs").mkdir()                       # 本地产物**存在**(已 gitignore)
    (repo / "runs" / "x.jsonl").write_text("{}\n", encoding="utf-8")
    r = _run_checker(repo)
    assert r.returncode == 1, f"应判不密闭;stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "不密闭" in r.stdout


def test_checker_green_when_all_tests_are_hermetic(tmp_path):
    """对照:全部测试自足 ⇒ 退出码 0(否则它就是个永远红的检查)。"""
    repo = _mk_repo(tmp_path, bad=False)
    r = _run_checker(repo)
    assert r.returncode == 0, f"应判密闭;stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "密闭" in r.stdout


def test_checker_self_verifies_which_tree_it_imported(tmp_path):
    """它必须**自证** import 的是临时树里的代码 —— 否则它可能在检错对象(静默)。

    这条守的是脚本第 ③ 步:若那条自证被去掉或写坏,本测试应能察觉。
    """
    repo = _mk_repo(tmp_path, bad=False)
    r = _run_checker(repo)
    assert "自证" in r.stdout and "✅ 用的是" in r.stdout, \
        f"自证步骤缺失或未通过;stdout={r.stdout!r}"
    # ⚠️ 断言它**导入的不是本仓那份代码** —— 这才是"自证"要保证的性质。
    #    (初版断言"路径含 fixture 仓"是错的:检查器解到**它自己 mktemp 的树**里,与 fixture 无关;
    #     而它当时在 macOS 上能过,是因为我加了 `or "/private" in line` 的兜底 —— **因错而绿**,
    #     被 CI(Linux)当场抓出。教训同本篇:`没报错`/`本地过` 都不等于 `对了`。)
    line = next(ln for ln in r.stdout.splitlines() if "✅ 用的是" in ln)
    assert str(ROOT / "app") not in line, f"它导入了本仓的代码 ⇒ 自证无效:{line}"
    assert "/app/eval_gate/__init__.py" in line, line


# ── 临时树必须**像真 clone 一样有索引**(2026-09-15 实证)──────────────────────
# 缘起:`git archive HEAD | tar -x` + `git init` **不会**填充索引 ⇒
# 任何用 `git ls-files` 判断"文件在不在 git 里"的检查,在临时树里都看到**空仓**。
# 而 CI 是**真 clone**,索引是满的 ⇒ 这类检查**CI 绿、自检红**,自检在**假报不密闭**。
#
# ⚠️ 这不是"某条测试太依赖环境",而是**自检脚本与它自己声明的目标不符**:
#    脚本第 39 行写"对齐 CI 的 clone",而真 clone 的索引是满的。
# 判据:一个**只用 git 跟踪文件**的测试,在自检里必须**通过**。

INDEX_TEST = (
    "import subprocess\n"
    "from pathlib import Path\n"
    "ROOT = Path(__file__).resolve().parents[1]\n"
    "def test_index_is_populated_like_a_clone():\n"
    "    out = subprocess.run(['git', 'ls-files'], cwd=str(ROOT),\n"
    "                         capture_output=True, text=True)\n"
    "    assert out.stdout.strip(), '临时树里 git 索引是空的 —— 那不像 CI 的 clone'\n"
    "    assert 'pyproject.toml' in out.stdout\n"
)


def test_temp_tree_has_a_populated_index_like_a_real_clone(tmp_path):
    """临时树的索引必须**非空** —— 否则用 `git ls-files` 的检查会被它误判。"""
    repo = _mk_repo(tmp_path, bad=False, extra_test=INDEX_TEST)
    r = _run_checker(repo)
    assert r.returncode == 0, (
        "自检把「索引为空的临时树」当成了真实环境 ⇒ 假报不密闭\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}")
