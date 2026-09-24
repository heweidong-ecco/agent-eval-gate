"""门 2 的**时序**判据(`DEC-020` 的 α,签核 **D-29**,2026-09-24)。

原来的洞
--------
门 2 原判据是 `grep -q 'test-driven-development' latest.json` —— 读的是 `.claude/traces/latest.json`
里那个**会话累计**的 `skills` 字段 ⇒ **开头调一次,之后本会话所有提交永久满足**。
实测(2026-09-15 那场会话):TDD 只在早期调 1 次,之后 4 个编码任务(含改判分器输入契约的 A2)
一次没调 —— **而这道门全程一次没响过**。它成了「**一个永远不失败的检查**」。

新判据(α)
----------
> 门 2 通过 ⟺ 存在一次 `test-driven-development` 调用,其时刻落在
> **`[本轮起点, 本次提交里最早那次实现文件编辑]`** 之间。
> 「本轮起点」= 该最早编辑**之前最近的那条 user 消息**的时刻。
> 人话:**在这一轮里、动实现之前,调过 TDD。**

⚠️ **判不了时不阻断**(记 `undecidable` 并出声)—— 本会话若从未编辑过这些文件
(如文件是别处改的),拦下来就是**误拦**;而误拦是守卫被关掉的头号原因。

⚠️ 同族:`test_evidence_coverage.py` —— 本文件**自造转录**,不依赖真实 session。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_skill_before_edit.py"

IMPL = "app/eval_gate/rules.py"


def _line(kind: str, ts: str, **kw) -> dict:
    """造一条最小转录行(形态与真实 session JSONL 一致)。"""
    if kind == "user":
        return {"type": "user", "timestamp": ts, "message": {"content": kw["text"]}}
    block = {"type": "tool_use", "name": kw["name"], "input": kw["input"]}
    return {"type": "assistant", "timestamp": ts, "message": {"content": [block]}}


def _transcript(tmp: Path, lines: list[dict]) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    p = tmp / "sess.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    return p


def _run(transcript: Path, files: str = IMPL) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), "--transcript", str(transcript), "--files", files],
        capture_output=True, text=True)


def _tdd(ts):
    return _line("asst", ts, name="Skill", input={"skill": "test-driven-development"})


def _edit(ts, path=IMPL):
    return _line("asst", ts, name="Edit", input={"file_path": path})


def _commit(ts):
    """转录里 `git commit` 是一条 **Bash 工具调用** —— 判据拿它当"上一段工作的结束"。"""
    return _line("asst", ts, name="Bash", input={"command": "git commit -m 'x'"})


T = "2026-09-24T10:{:02d}:00.000Z"


# ── 该通过 ────────────────────────────────────────────────────────────

def test_tdd_before_first_impl_edit_passes(tmp_path):
    """本轮先调 TDD、再动实现 ⇒ 通过(这正是 TDD 要求的顺序)。"""
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="实现 X"),
        _tdd(T.format(1)),
        _edit(T.format(2)),
    ])
    assert _run(tr).returncode == 0


# ── 该拦(原判据会放过的三种) ─────────────────────────────────────────

def test_tdd_after_the_edit_is_blocked(tmp_path):
    """**先动实现、后调 TDD** ⇒ 拦 —— 这是「走后门补的 TDD」,不是 TDD。"""
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="实现 X"),
        _edit(T.format(1)),
        _tdd(T.format(2)),
    ])
    assert _run(tr).returncode == 1


def test_tdd_before_the_last_commit_is_blocked(tmp_path):
    """**上次提交之后没再调 TDD** ⇒ 拦 —— 这就是原来那个洞(一次调用永久满足)。

    ⚠️ 本判据**不看"回合"**(转录里 `type:"user"` 的行不可靠:混着**工具结果**,
    且真用户消息的时间戳与工具调用互相穿插 —— 实测窗口被压成 49ms ⇒ 一律误拦)。
    锚改用**「上一次 `git commit`」**:它在转录里是可见的 Bash 调用,且语义就是"上一段工作结束"。
    """
    tr = _transcript(tmp_path, [
        _tdd(T.format(0)),
        _edit(T.format(1)),
        _commit(T.format(2)),           # 上次提交
        _edit(T.format(30)),            # 新一轮动手 —— 中间没再调 TDD
    ])
    assert _run(tr).returncode == 1


def test_same_file_across_commits_is_still_blocked(tmp_path):
    """⚠️ **同一个文件跨两次提交**也要拦 —— 这正是"最早那次编辑"取法的洞。"""
    tr = _transcript(tmp_path, [
        _tdd(T.format(0)),
        _edit(T.format(1)),             # 第一次改这个文件(有 TDD)
        _commit(T.format(2)),
        _edit(T.format(30)),            # 又改同一个文件(没 TDD)
    ])
    assert _run(tr).returncode == 1


def test_tdd_after_the_last_commit_passes(tmp_path):
    """**上次提交之后又调了一次 TDD** ⇒ 通过(即使同一个文件改了很多次)。"""
    tr = _transcript(tmp_path, [
        _tdd(T.format(0)),
        _edit(T.format(1)),
        _commit(T.format(2)),
        _tdd(T.format(20)),             # 新一轮动手前又调了
        _edit(T.format(30)),
        _edit(T.format(31)),
    ])
    assert _run(tr).returncode == 0


def test_no_tdd_at_all_is_blocked(tmp_path):
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="实现 X"),
        _edit(T.format(1)),
    ])
    assert _run(tr).returncode == 1


# ── 不误拦(守卫活下来的关键) ─────────────────────────────────────────

def test_undecidable_when_file_never_edited_in_session(tmp_path):
    """本会话从没编辑过这个文件(如文件是别处改的)⇒ **判不了,不阻断**,但要说清。"""
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="只是提交已有改动"),
        _tdd(T.format(1)),
    ])
    r = _run(tr)
    assert r.returncode == 0, "判不了就拦 = 误拦 ⇒ 守卫会被关掉"
    assert "判不了" in r.stderr + r.stdout


def test_rule_does_not_depend_on_user_lines(tmp_path):
    """⚠️ 判据**不得依赖 user 行** —— 转录里那串时间戳不可靠。

    2026-09-24 实测:`type:"user"` 的行里**混着工具结果**,而真用户消息的时间戳又与
    工具调用**互相穿插**(同一个 Skill 调用 .556、用户行 .604/.605 —— 顺序都乱)。
    据此定"本轮起点",窗口会被压成 **49 毫秒** ⇒ **一律误拦**(连我自己那次提交都被拦下)。
    ⇒ 本判据只看**实现编辑的时间序**;故**整份转录没有 user 行,也必须判得对**。
    """
    tr = _transcript(tmp_path, [_tdd(T.format(1)), _edit(T.format(2))])
    assert _run(tr).returncode == 0, "没有 user 行也要能判:先调 TDD 再动手 ⇒ 通过"

    tr2 = _transcript(tmp_path / "b", [_edit(T.format(1)), _tdd(T.format(2))])
    assert _run(tr2).returncode == 1, "没有 user 行也要能判:先动手后补 ⇒ 拦"


def test_other_skills_do_not_satisfy_the_gate(tmp_path):
    """只有 `test-driven-development` 算数 —— 别的 skill 调再多也不行。"""
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="实现 X"),
        _line("asst", T.format(1), name="Skill", input={"skill": "grilling"}),
        _edit(T.format(2)),
    ])
    assert _run(tr).returncode == 1


def test_tdd_in_the_same_turn_but_before_edit_of_a_partially_staged_file(tmp_path):
    """**多条实现文件**:TDD 须早于**最早**那次实现编辑(不是最晚)。"""
    tr = _transcript(tmp_path, [
        _line("user", T.format(0), text="两件事"),
        _edit(T.format(1), "app/eval_gate/judge.py"),   # 先改了 A
        _tdd(T.format(2)),                              # 才补 TDD
        _edit(T.format(3), IMPL),                       # 再改 B
    ])
    assert _run(tr, files=f"{IMPL},app/eval_gate/judge.py").returncode == 1, \
        "A 是在 TDD 之前改的 ⇒ 整体应拦"
