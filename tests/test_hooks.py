"""门禁防腐测试 —— 保证"门禁自己不会烂"。

动机(2026-09-11,业务方批准;来自对另一套 harness 的调研):
  那套 harness 的门禁是**坏的却没人知道**:
  · `scripts/check_harness_docs.py:1` 第一行是 markdown 代码围栏 → SyntaxError,**永不执行**;
  · 而它被 Makefile 与 CI 调用 → **`make gate` 从来没绿过**;
  · 测试里居然用 `pytest.skip` 给它兜底 → **"门禁坏了就跳过它"**。
  → 结论:**门禁自己必须被测**,否则会静默腐烂,而腐烂后无人察觉。

本文件对每个门禁脚本做三类断言:
  ① **防腐**:`sh -n` 语法通过 + 可执行位 + **已在 settings.json 注册**(没注册 = 形同不存在);
  ② **该拦的拦**:喂真实输入,断言它真的拒绝/询问;
  ③ **不该拦的不拦 + opt-in 关闭时静默**(防误伤、防噪音)。
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
GITHOOKS = ROOT / ".githooks"
SETTINGS = ROOT / ".claude" / "settings.json"

# 全部门禁脚本 + 它的 opt-in 开关(开关名必须与 settings.json 里的内联变量一致)
ALL_HOOKS = {
    "impl-guard.sh": "IMPL_GUARD",
    "kit-sentinel.sh": "KIT_SENTINEL",
    "failure-sentinel.sh": "FAILURE_SENTINEL",
    "skill-sentinel.sh": "SKILL_SENTINEL",
    "skill-trace.sh": "SKILL_TRACE",
    "session-context.sh": "SESSION_CTX",
    "kb-drift-sentinel.sh": "KB_SENTINEL",
    "commit-msg": "（git hook，无 env 开关）",
}


def _run(script: Path, stdin: str = "", env: dict | None = None, cwd: Path | None = None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(["sh", str(script)], input=stdin, capture_output=True,
                          text=True, env=e, cwd=str(cwd or ROOT), timeout=60)


def _registered_commands() -> str:
    return SETTINGS.read_text(encoding="utf-8")


# ── ① 防腐:语法 / 可执行 / 已注册 ──────────────────────────────────────────

@pytest.mark.parametrize("name", list(ALL_HOOKS))
def test_hook_script_has_valid_shell_syntax(name):
    """`sh -n` 必须通过 —— 这正是那套 harness 的病(语法错 → 永不执行 → 无人知道)。"""
    p = (GITHOOKS / name) if name == "commit-msg" else (HOOKS / name)
    assert p.is_file(), f"{name} 不存在"
    r = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name} 语法错误(会静默失效!): {r.stderr}"


@pytest.mark.parametrize("name", list(ALL_HOOKS))
def test_hook_script_is_executable(name):
    p = (GITHOOKS / name) if name == "commit-msg" else (HOOKS / name)
    assert os.access(p, os.X_OK), f"{name} 没有可执行位"


@pytest.mark.parametrize("name,switch", [(k, v) for k, v in ALL_HOOKS.items() if v.startswith(("IMPL", "KIT", "FAILURE", "SKILL", "SESSION", "KB"))])
def test_hook_is_registered_in_settings(name, switch):
    """**没注册 = 形同不存在**(脚本再对也没人调)。"""
    text = _registered_commands()
    assert name in text, f"{name} 未在 .claude/settings.json 注册"
    assert switch in text, f"{name} 的开关 {switch} 未在注册命令里内联(会永不触发)"


def test_commit_msg_hook_is_activated_by_git_config():
    """`.githooks/commit-msg` 只有 `core.hooksPath` 指过去才生效。"""
    r = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert r.stdout.strip() == ".githooks", "core.hooksPath 未指向 .githooks → 本地硬门失效"


# ── ② 该拦的拦:impl-guard(PreToolUse)──────────────────────────────────────

def test_impl_guard_asks_when_editing_impl_without_tests():
    payload = json.dumps({"tool_name": "Edit",
                          "tool_input": {"file_path": str(ROOT / "app" / "eval_gate" / "report.py")}})
    r = _run(HOOKS / "impl-guard.sh", payload, {"IMPL_GUARD": "1"})
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize("path", [
    "tests/test_cli.py",            # 改测试本身 → 放行
    "docs/部署.md",                  # 改文档 → 放行
])
def test_impl_guard_allows_non_impl_paths(path):
    payload = json.dumps({"tool_input": {"file_path": str(ROOT / path)}})
    r = _run(HOOKS / "impl-guard.sh", payload, {"IMPL_GUARD": "1"})
    assert r.stdout.strip() == "", f"{path} 不该被拦"


def test_impl_guard_silent_when_disabled():
    payload = json.dumps({"tool_input": {"file_path": str(ROOT / "app" / "x.py")}})
    r = _run(HOOKS / "impl-guard.sh", payload, {})
    assert r.stdout.strip() == ""


# ── ② 该拦的拦:commit-msg(git hook,两道门)────────────────────────────────

def _tmp_repo() -> Path:
    """造一个临时 git 仓库(**仓外**,用 mkdtemp):复制 hook + 建 app/ 与 tests/。"""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="evalgate-hooktest-"))
    (d / ".githooks").mkdir(parents=True)
    (d / ".claude" / "traces").mkdir(parents=True)
    (d / "app").mkdir()
    (d / "tests").mkdir()
    (d / "docs").mkdir()
    for f in ("commit-msg",):
        shutil.copy2(GITHOOKS / f, d / ".githooks" / f)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True, capture_output=True)
    return d


def _write(d: Path, rel: str, text: str = "x = 1\n"):
    (d / rel).write_text(text, encoding="utf-8")


def _msg(d: Path, text: str) -> Path:
    p = d / "MSG"
    p.write_text(text, encoding="utf-8")
    return p


def test_commit_msg_gate1_blocks_impl_without_tests():
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        r = _run(d / ".githooks" / "commit-msg", "", {}, cwd=d)
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"), str(_msg(d, "feat: x\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 1, "门 1 应拒绝"
        assert "门 1" in r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_gate1_allows_with_no_test_marker():
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"),
                            str(_msg(d, "refactor: x [no-test]\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_gate2_blocks_when_tdd_skill_absent():
    """门 2:改了实现 + 也改了测试,但本会话没调用过 test-driven-development → 拒。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        # 造一份"只有别的 skill"的 trace
        (d / ".claude" / "traces" / "latest.json").write_text(
            json.dumps({"session_id": "s", "skill_calls": 1, "skills": "grilling(1)"}),
            encoding="utf-8")
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"), str(_msg(d, "feat: x\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 1, "门 2 应拒绝"
        assert "门 2" in r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_gate2_allows_with_no_skill_marker():
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        (d / ".claude" / "traces" / "latest.json").write_text(
            json.dumps({"session_id": "s", "skills": "grilling(1)"}), encoding="utf-8")
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"),
                            str(_msg(d, "feat: x [no-skill]\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_ignores_docs_only_changes():
    d = _tmp_repo()
    try:
        _write(d, "docs/x.md")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"), str(_msg(d, "docs: x\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── ② 该拦的拦:skill-trace(Stop,产出机器可读事实)──────────────────────────

def test_skill_trace_writes_machine_readable_json():
    payload = json.dumps({"session_id": "00000000-0000-0000-0000-000000000000"})
    r = _run(HOOKS / "skill-trace.sh", payload, {"SKILL_TRACE": "1"})
    assert r.returncode == 0
    tr = ROOT / ".claude" / "traces" / "latest.json"
    assert tr.is_file(), "未产出 trace"
    d = json.loads(tr.read_text(encoding="utf-8"))
    assert {"session_id", "at", "skill_calls", "skills"} <= set(d)


def test_skill_trace_silent_when_disabled():
    r = _run(HOOKS / "skill-trace.sh", json.dumps({"session_id": "x"}), {})
    assert r.returncode == 0


# ── ② 该拦的拦:session-context(必须输出合法 JSON,含入口)────────────────────

def test_session_context_emits_valid_json_with_entry_trigger():
    r = _run(HOOKS / "session-context.sh", "", {"SESSION_CTX": "1"})
    assert r.returncode == 0
    d = json.loads(r.stdout)
    ctx = d["hookSpecificOutput"]["additionalContext"]
    assert d["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "using-superpowers" in ctx, "注入内容缺入口触发器"


# ── ③ 不该拦的不拦:哨兵类在开关关闭时静默 ────────────────────────────────

@pytest.mark.parametrize("name", ["kit-sentinel.sh", "failure-sentinel.sh",
                                  "skill-sentinel.sh", "kb-drift-sentinel.sh"])
def test_sentinels_silent_when_disabled(name):
    r = _run(HOOKS / name, "{}", {})
    assert r.returncode == 0 and r.stdout.strip() == ""
