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
# ⚠️ F2 回归(2026-09-11):这两条**必须在临时仓库里跑**。
#   原先直接在项目根跑 → hook 读的是**当前工作区**的 `git diff`,于是:
#   ① 正常 TDD 中(tests/ 刚改过)它放行 → 该测试**必红**;
#   ② 还会被**并行会话**的未提交改动带偏 → 测试依赖了它不该依赖的状态。
#   → 门禁测试一律隔离(临时仓库/干净 HEAD),禁止读当前工作区。

def test_impl_guard_asks_when_editing_impl_without_tests():
    """无任何测试改动(HEAD 干净)+ 要改实现 → 必须返回 ask。"""
    d = _tmp_repo()
    try:
        _write(d, "app/report.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
        payload = json.dumps({"tool_name": "Edit",
                              "tool_input": {"file_path": str(d / "app" / "report.py")}})
        r = _run(d / ".claude" / "hooks" / "impl-guard.sh", payload, {"IMPL_GUARD": "1"}, cwd=d)
        assert r.returncode == 0
        assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_impl_guard_allows_when_tests_already_modified():
    """TDD 的正常顺序(先测试、后实现)→ **不再打扰**。这是本门的设计意图,必须守住。"""
    d = _tmp_repo()
    try:
        _write(d, "app/report.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
        _write(d, "tests/test_report.py")          # 先写测试(未提交)
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        payload = json.dumps({"tool_input": {"file_path": str(d / "app" / "report.py")}})
        r = _run(d / ".claude" / "hooks" / "impl-guard.sh", payload, {"IMPL_GUARD": "1"}, cwd=d)
        assert r.returncode == 0
        assert r.stdout.strip() == "", "已有测试改动时应放行(否则 TDD 过程中会被反复打扰)"
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
    """造一个临时 git 仓库(**仓外**,用 mkdtemp):复制 hook + 建 app/ 与 tests/。

    hook 从**自身路径**推导仓库根(`dirname $0/../..`),故复制进临时仓库即天然隔离。
    """
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="evalgate-hooktest-"))
    (d / ".githooks").mkdir(parents=True)
    (d / ".claude" / "hooks").mkdir(parents=True)
    (d / ".claude" / "traces").mkdir(parents=True)
    (d / "app").mkdir()
    (d / "tests").mkdir()
    (d / "docs").mkdir()
    shutil.copy2(GITHOOKS / "commit-msg", d / ".githooks" / "commit-msg")
    shutil.copy2(HOOKS / "impl-guard.sh", d / ".claude" / "hooks" / "impl-guard.sh")
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

def test_skill_trace_does_not_clobber_production_trace_for_unknown_session():
    """**F1 回归**(2026-09-11):未知 session_id(如测试自身)→ **不得改写生产 trace**。

    反面教材:本测试原先用假 session_id 跑真脚本,脚本**无条件覆写** `latest.json`
    为 `skill_calls:0` —— 而它正是**门 2 的判定依据**。
    后果:跑一次 `pytest` 就把证据链毁掉 → 之后所有实现类提交被误判「没调用过 skill」而拦下。
    → 断言「跑完本测试,生产 trace 内容必须一字不变」。
    """
    prod = ROOT / ".claude" / "traces" / "latest.json"
    before = prod.read_text(encoding="utf-8") if prod.is_file() else None
    r = _run(HOOKS / "skill-trace.sh",
             json.dumps({"session_id": "00000000-0000-0000-0000-000000000000"}),
             {"SKILL_TRACE": "1"})
    assert r.returncode == 0
    after = prod.read_text(encoding="utf-8") if prod.is_file() else None
    assert after == before, "未知会话改写了生产 trace —— 门 2 的证据链被测试污染(F1)"


def test_skill_trace_writes_only_when_session_transcript_found(tmp_path):
    """能定位到该会话 transcript 时才写 trace,且**写到指定目录**(不碰生产路径)。"""
    sid = "abcd1234-0000-0000-0000-000000000000"
    proj = tmp_path / ".claude" / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text(
        '{"name":"Skill","input":{"skill":"test-driven-development"}}\n'
        '{"name":"Skill","input":{"skill":"grilling"}}\n', encoding="utf-8")
    outdir = tmp_path / "traces"
    r = _run(HOOKS / "skill-trace.sh", json.dumps({"session_id": sid}),
             {"SKILL_TRACE": "1", "SKILL_TRACE_DIR": str(outdir), "HOME": str(tmp_path)})
    assert r.returncode == 0
    d = json.loads((outdir / "latest.json").read_text(encoding="utf-8"))
    assert d["session_id"] == sid
    assert d["skill_calls"] == 2, "应从 transcript 抽出 2 次 skill 调用"
    assert "test-driven-development" in d["skills"]


def test_skill_trace_writes_machine_readable_json(tmp_path):
    """写出的 trace 字段齐备(hermetic:临时 HOME + 临时输出目录,不碰生产路径)。"""
    sid = "beef0000-0000-0000-0000-000000000000"
    proj = tmp_path / ".claude" / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text(
        '{"name":"Skill","input":{"skill":"grilling"}}\n', encoding="utf-8")
    outdir = tmp_path / "traces"
    r = _run(HOOKS / "skill-trace.sh", json.dumps({"session_id": sid}),
             {"SKILL_TRACE": "1", "SKILL_TRACE_DIR": str(outdir), "HOME": str(tmp_path)})
    assert r.returncode == 0
    d = json.loads((outdir / "latest.json").read_text(encoding="utf-8"))
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
