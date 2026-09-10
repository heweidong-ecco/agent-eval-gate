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
import sys
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
    "subagent-guard.sh": "SUBAGENT_GUARD",
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


@pytest.mark.parametrize("name,switch", [(k, v) for k, v in ALL_HOOKS.items() if v.startswith(("IMPL", "KIT", "FAILURE", "SKILL", "SESSION", "KB", "SUBAGENT"))])
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
    shutil.copy2(GITHOOKS / "post-commit", d / ".githooks" / "post-commit")
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


def test_commit_msg_gate1_allows_with_reason_marker():
    """豁免**必须带理由**(`[no-test: <理由>]`)才放行。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"),
                            str(_msg(d, "refactor: x [no-test: 纯重命名,无行为变化]\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_gate1_rejects_bare_no_test_marker():
    """**裸 `[no-test]` 不再放行**。

    反面现状:文案写「加 [no-test] 并说明理由」,实现却只 `grep -q '[no-test]'` ——
    **理由从未被检查**,裸标记即可绕过。豁免率因此完全不可见。
    """
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"),
                            str(_msg(d, "refactor: x [no-test]\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 1, "裸标记竟被放行 —— 豁免无痕可绕"
        assert "理由" in r.stderr
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


def test_commit_msg_gate2_allows_with_reason_marker():
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        (d / ".claude" / "traces" / "latest.json").write_text(
            json.dumps({"session_id": "s", "skills": "grilling(1)"}), encoding="utf-8")
        r = subprocess.run(["sh", str(d / ".githooks" / "commit-msg"),
                            str(_msg(d, "feat: x [no-skill: 纯配置改动,无实现逻辑]\n"))],
                           cwd=d, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_commit_msg_gate2_rejects_bare_no_skill_marker():
    """裸 `[no-skill]` 不再放行(门 2 原先见它直接 exit 0,连理由都不看)。"""
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
        assert r.returncode == 1, "裸 [no-skill] 仍被放行"
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


# ── ② 该发的发:subagent-guard(SubagentStart,把纪律注入子 Agent)─────────────
# 背景:子 Agent 拿不到锚点、不触发 SessionStart/Stop hook(盲测 1/2/3 实证)。
#       `SubagentStart` 是**唯一能真正到达子 Agent** 的通道(2026-09-11 实机验证:
#       注入以 system-reminder 形式进了子 Agent 上下文,类型 `hook_additional_context`)。
# 判据只能按 `agent_type`,因为 SubagentStart **看不到任务 prompt**(GitHub #87411,
# 本机实测 stdin 字段为 agent_id/agent_type/cwd/prompt_id/session_id/transcript_path)。

SIGNATURE = "REPO-DISCIPLINE-V1"   # ASCII 锚点,供到达性探针 grep(中文签名会给 shell 添乱)


def test_subagent_guard_injects_for_writable_type():
    """可写型子 Agent → 输出合法 JSON,且 additionalContext 含版本签名。"""
    r = _run(HOOKS / "subagent-guard.sh",
             json.dumps({"agent_type": "general-purpose", "agent_id": "a1"}),
             {"SUBAGENT_GUARD": "1"})
    assert r.returncode == 0
    d = json.loads(r.stdout)
    ctx = d["hookSpecificOutput"]["additionalContext"]
    assert d["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert SIGNATURE in ctx, "注入内容缺版本签名(到达性探针的锚点)"


@pytest.mark.parametrize("atype", ["Explore", "Plan", "claude-code-guide"])
def test_subagent_guard_silent_for_readonly_types(atype):
    """只读型 → **一个字都不发**(防噪音:它不改码、不提交,发了就是打扰)。"""
    r = _run(HOOKS / "subagent-guard.sh", json.dumps({"agent_type": atype}),
             {"SUBAGENT_GUARD": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "", f"{atype} 是只读型,不该被注入"


def test_subagent_guard_unknown_type_fails_safe():
    """未知类型 → 默认**发**(fail-safe):宁可多发,不可漏发。"""
    r = _run(HOOKS / "subagent-guard.sh", json.dumps({"agent_type": "some-new-agent"}),
             {"SUBAGENT_GUARD": "1"})
    assert SIGNATURE in r.stdout


def test_subagent_guard_readonly_types_extendable():
    """只读型集合可扩展,免得自定义的只读 agent 被无谓打扰。"""
    r = _run(HOOKS / "subagent-guard.sh", json.dumps({"agent_type": "my-reader"}),
             {"SUBAGENT_GUARD": "1", "SUBAGENT_GUARD_READONLY_TYPES": "my-reader"})
    assert r.stdout.strip() == ""


def test_subagent_guard_silent_when_disabled():
    r = _run(HOOKS / "subagent-guard.sh",
             json.dumps({"agent_type": "general-purpose"}), {})
    assert r.returncode == 0 and r.stdout.strip() == ""


def _mk_subagents(tmp_path: Path, n_with_sig: int, n_without: int) -> Path:
    """造假的子 Agent transcript 目录结构,用于到达性断言的隔离测试。"""
    proj = tmp_path / "proj" / "sess-1" / "subagents"
    proj.mkdir(parents=True)
    for i in range(n_with_sig):
        (proj / f"agent-with{i}.jsonl").write_text(
            '{"content":"…REPO-DISCIPLINE-V1…"}\n', encoding="utf-8")
    for i in range(n_without):
        (proj / f"agent-without{i}.jsonl").write_text(
            '{"content":"普通子 Agent,没有任何注入"}\n', encoding="utf-8")
    return tmp_path / "proj"


# ── ② 绕过留痕:post-commit(不受 --no-verify 抑制)──────────────────────────
# 背景:门上写着"可 --no-verify 绕过但须说明",而**绕过本身没有任何痕迹**。
#      `man githooks` 明示 commit-msg 可被 --no-verify 绕过,而 `post-commit`
#      不在被抑制之列 → 它是**绕过之后的必经之路**,由它留痕。

def _commit_bypassing_hooks(d: Path, msg: str):
    """在临时仓造一个「绕过门禁」的提交(等价于 git commit --no-verify)。"""
    subprocess.run(["git", "commit", "--no-verify", "-q", "-m", msg],
                   cwd=d, check=True, capture_output=True)


def _bypass_records(d: Path) -> list:
    log = d / ".claude" / "traces" / "bypass.jsonl"
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_post_commit_logs_bypass_when_gate1_should_have_blocked():
    """本应被门 1 拦下的提交被绕过了 → 必须留痕。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        _commit_bypassing_hooks(d, "feat: 改了实现没改测试")
        r = subprocess.run(["sh", str(d / ".githooks" / "post-commit")], cwd=d,
                           capture_output=True, text=True)
        assert r.returncode == 0, "post-commit 永远不该阻断"
        recs = _bypass_records(d)
        assert any(x.get("gate") == "gate1" for x in recs), f"绕过没有留痕: {recs}"
        assert any("at" in x and "sha" in x for x in recs)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_post_commit_silent_when_commit_is_clean():
    """合规提交 → 不留痕(否则日志被噪音淹没)。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        _commit_bypassing_hooks(d, "feat: 实现 + 测试")
        subprocess.run(["sh", str(d / ".githooks" / "post-commit")], cwd=d,
                       capture_output=True, text=True)
        assert _bypass_records(d) == [], "合规提交不该被记成绕过"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_post_commit_respects_exemption_with_reason():
    """带理由的豁免是**设计意图**,不是绕过 → 不留痕。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
        _commit_bypassing_hooks(d, "refactor: x [no-test: 纯重命名,无行为变化]")
        subprocess.run(["sh", str(d / ".githooks" / "post-commit")], cwd=d,
                       capture_output=True, text=True)
        assert _bypass_records(d) == [], "合法豁免被误记成绕过"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_post_commit_always_exits_zero_even_without_commits():
    """空仓库(无 HEAD)→ 仍 exit 0,不阻断、不报错。"""
    d = _tmp_repo()
    try:
        r = subprocess.run(["sh", str(d / ".githooks" / "post-commit")], cwd=d,
                           capture_output=True, text=True)
        assert r.returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── ② 绕过重算:check_gate_bypass(CI 侧,--no-verify 绕不过)──────────────────
# post-commit 是**本机**留痕,改 core.hooksPath 就能失效;而 CI 从 git 历史**重算**
# 门 1 的判据(逐提交可重放),是 `--no-verify` 在结构上绕不过的那一层。

def _git(d: Path, *args: str):
    subprocess.run(["git", *args], cwd=d, check=True, capture_output=True)


def _commit(d: Path, msg: str):
    _git(d, "add", "-A")
    _git(d, "commit", "--no-verify", "-q", "-m", msg)


def _head(d: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True)
    return r.stdout.strip()


def _run_bypass_check(d: Path, base: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_gate_bypass.py"), base, "--repo", str(d)],
        capture_output=True, text=True)


def test_gate_bypass_check_flags_bypassed_commit():
    """历史里有「改实现无测试」的提交 → exit 1 并列出 sha。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        _commit(d, "feat: 初始实现与测试")
        base = _head(d)
        _write(d, "app/b.py")                      # 改实现,不碰测试
        _commit(d, "feat: 偷偷改实现")
        r = _run_bypass_check(d, base)
        assert r.returncode == 1, f"绕过的提交没被抓: {r.stdout}{r.stderr}"
        assert _head(d)[:7] in (r.stdout + r.stderr)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_gate_bypass_check_allows_reasoned_exemption():
    """带理由的豁免是设计意图 → 不算绕过。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        _commit(d, "feat: 初始实现与测试")
        base = _head(d)
        _write(d, "app/b.py")
        _commit(d, "refactor: x [no-test: 纯重命名,无行为变化]")
        r = _run_bypass_check(d, base)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_gate_bypass_check_rejects_bare_marker_in_history():
    """历史里的**裸** [no-test] 同样算绕过(理由从未被检查 = 等于没豁免)。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        _commit(d, "feat: 初始实现与测试")
        base = _head(d)
        _write(d, "app/b.py")
        _commit(d, "refactor: x [no-test]")
        r = _run_bypass_check(d, base)
        assert r.returncode == 1, "裸标记在历史里被当成合法豁免"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_gate_bypass_check_clean_history_passes():
    """干净历史(实现与测试同行)→ exit 0。"""
    d = _tmp_repo()
    try:
        _write(d, "app/a.py")
        _write(d, "tests/test_a.py")
        _commit(d, "feat: 初始实现与测试")
        base = _head(d)
        _write(d, "app/b.py")
        _write(d, "tests/test_b.py")
        _commit(d, "feat: 实现 + 测试")
        r = _run_bypass_check(d, base)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_check_subagent_injection_ok_when_signature_present(tmp_path):
    """有子 Agent 且含签名 → exit 0。"""
    proj = _mk_subagents(tmp_path, n_with_sig=1, n_without=1)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_subagent_injection.py"),
                        "sess-1", "--projects-dir", str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_subagent_injection_flags_missing_signature(tmp_path):
    """**结构失效**:有子 Agent transcript,却一份都不含签名 → exit 1。"""
    proj = _mk_subagents(tmp_path, n_with_sig=0, n_without=2)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_subagent_injection.py"),
                        "sess-1", "--projects-dir", str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 1, "注入没到达却没报错 —— 这正是要防的静默失效"
    assert "失效" in r.stdout or "失效" in r.stderr


def test_check_subagent_injection_noop_when_no_subagents(tmp_path):
    """本会话没派过子 Agent → 无可检,exit 0(不误报)。"""
    proj = tmp_path / "proj" / "sess-1"
    proj.mkdir(parents=True)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_subagent_injection.py"),
                        "sess-1", "--projects-dir", str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "无子 Agent" in r.stdout or "跳过" in r.stdout


def _fake_session_with_subagents(tmp_path: Path, sid: str, with_sig: bool) -> Path:
    """造 `<HOME>/.claude/projects/<sanitized-ROOT>/<sid>/subagents/` 结构。"""
    proj = tmp_path / ".claude" / "projects" / str(ROOT).replace("/", "-") / sid / "subagents"
    proj.mkdir(parents=True)
    body = "有签名 REPO-DISCIPLINE-V1" if with_sig else "这个子 Agent 没收到任何注入"
    (proj / "agent-a.jsonl").write_text(json.dumps({"content": body}) + "\n", encoding="utf-8")
    return proj


def test_skill_sentinel_warns_when_injection_missing(tmp_path):
    """到达性:派过子 Agent 却一份签名都没有 → Stop 哨兵必须出声。

    否则注入失效时**没有任何提示**,子 Agent 在无纪律工作而无人知 —— 与 F1 同型的静默失效。
    """
    _fake_session_with_subagents(tmp_path, "sess-x", with_sig=False)
    r = _run(HOOKS / "skill-sentinel.sh", json.dumps({"session_id": "sess-x"}),
             {"SKILL_SENTINEL": "1", "HOME": str(tmp_path)})
    assert "注入未到达" in r.stdout, f"注入缺失却没提醒;stdout={r.stdout!r}"


def test_skill_sentinel_silent_about_injection_when_arrived(tmp_path):
    """注入到位 → 不该就这条发声(防噪音)。"""
    _fake_session_with_subagents(tmp_path, "sess-y", with_sig=True)
    r = _run(HOOKS / "skill-sentinel.sh", json.dumps({"session_id": "sess-y"}),
             {"SKILL_SENTINEL": "1", "HOME": str(tmp_path)})
    assert "注入未到达" not in r.stdout


def test_skill_sentinel_surfaces_bypass_log():
    """**绕过留痕必须被主动暴露** —— 只写进日志没人看,等于没留。"""
    d = _tmp_repo()
    try:
        (d / ".claude" / "traces" / "bypass.jsonl").write_text(
            json.dumps({"sha": "abc1234", "gate": "gate1", "msg_head": "x",
                        "at": "2026-09-11T00:00:00Z"}) + "\n", encoding="utf-8")
        r = _run(HOOKS / "skill-sentinel.sh", "{}",
                 {"SKILL_SENTINEL": "1", "GATE_REPO": str(d)})
        assert "绕过留痕" in r.stdout, f"留痕没被暴露;stdout={r.stdout!r}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_skill_sentinel_silent_without_bypass_log():
    """没有绕过日志 → 不发声(防噪音)。"""
    d = _tmp_repo()
    try:
        r = _run(HOOKS / "skill-sentinel.sh", "{}",
                 {"SKILL_SENTINEL": "1", "GATE_REPO": str(d)})
        assert "绕过留痕" not in r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_skill_sentinel_warns_when_hookspath_tampered():
    """`core.hooksPath` 被改走 → 本地门禁(门1/门2/post-commit)全失效,必须出声。

    这是**本地门禁的单一失效点**:改一行 git config,所有 .githooks 都不再运行,
    而**不会有任何提示** —— 与 F1/F2 同型的静默失效。
    """
    d = _tmp_repo()
    try:
        subprocess.run(["git", "config", "core.hooksPath", "/dev/null"],
                       cwd=d, check=True, capture_output=True)
        r = _run(HOOKS / "skill-sentinel.sh", "{}",
                 {"SKILL_SENTINEL": "1", "GATE_REPO": str(d)})
        assert "hooksPath" in r.stdout, f"篡改没被发现;stdout={r.stdout!r}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_skill_sentinel_no_hookspath_warning_when_correct():
    """hooksPath 指向 .githooks(正常)→ 不就此发声。"""
    d = _tmp_repo()
    try:
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                       cwd=d, check=True, capture_output=True)
        r = _run(HOOKS / "skill-sentinel.sh", "{}",
                 {"SKILL_SENTINEL": "1", "GATE_REPO": str(d)})
        assert "hooksPath" not in r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── ③ 不该拦的不拦:哨兵类在开关关闭时静默 ────────────────────────────────

@pytest.mark.parametrize("name", ["kit-sentinel.sh", "failure-sentinel.sh",
                                  "skill-sentinel.sh", "kb-drift-sentinel.sh"])
def test_sentinels_silent_when_disabled(name):
    r = _run(HOOKS / name, "{}", {})
    assert r.returncode == 0 and r.stdout.strip() == ""
