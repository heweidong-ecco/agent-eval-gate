"""阶段门状态机测试 —— 证明它真的会拦,且真的能续跑。

动机(2026-09-11,业务方批准):`commit-msg` 是**滞后门**(只在最后提交时拦),
长任务"中途断了/做错了 = 前面全白费"。本工具把阶段门做成真状态机:
  · 进下一阶段前,前置阶段必须 **passed 且产出物现在依然存在**;
  · `resume` 从**最后一个 passed 阶段之后**继续。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "stage_gate.py"

STAGES = {"stages": [
    {"name": "分析", "evidence": ["art/01-分析.md"]},
    {"name": "编码", "evidence": ["art/02-编码.md"]},
    {"name": "验证", "evidence": ["art/03-验证.md"]},
]}


@pytest.fixture()
def sandbox(tmp_path):
    """一个独立的 STAGE_GATE_ROOT(工具用 env 覆盖 ROOT,便于测试)。"""
    (tmp_path / "art").mkdir()
    cfg = tmp_path / "stages.json"
    cfg.write_text(json.dumps(STAGES, ensure_ascii=False), encoding="utf-8")
    return tmp_path, cfg


def gate(sandbox_root, *args):
    env = dict(os.environ, STAGE_GATE_ROOT=str(sandbox_root))
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def _artifact(root: Path, rel: str, text: str = "内容\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_enter_first_stage_allowed(sandbox):
    root, cfg = sandbox
    assert gate(root, "init", "--req", "R1", "--config", str(cfg)).returncode == 0
    r = gate(root, "enter", "--req", "R1", "--stage", "分析")
    assert r.returncode == 0


def test_cannot_skip_ahead_to_later_stage(sandbox):
    """【闸 1】前置阶段没通过 → **不能**进入后面的阶段(不许跳步)。"""
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    r = gate(root, "enter", "--req", "R1", "--stage", "编码")
    assert r.returncode == 1
    assert "前置门禁未过" in r.stderr + r.stdout


def test_pass_requires_evidence_to_exist(sandbox):
    """【闸 2】产出物不存在/为空 → 该阶段**不算通过**。"""
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    gate(root, "enter", "--req", "R1", "--stage", "分析")
    r = gate(root, "pass", "--req", "R1")
    assert r.returncode == 1, "没有产出物却让它通过了"

    _artifact(root, "art/01-分析.md")
    assert gate(root, "pass", "--req", "R1").returncode == 0


def test_empty_evidence_file_does_not_count(sandbox):
    """空文件不算交付 —— 建个空文件糊弄不过去。"""
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    gate(root, "enter", "--req", "R1", "--stage", "分析")
    _artifact(root, "art/01-分析.md", "")
    assert gate(root, "pass", "--req", "R1").returncode == 1


def test_happy_path_progresses_in_order(sandbox):
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    for stage, art in [("分析", "art/01-分析.md"), ("编码", "art/02-编码.md")]:
        assert gate(root, "enter", "--req", "R1", "--stage", stage).returncode == 0
        _artifact(root, art)
        assert gate(root, "pass", "--req", "R1").returncode == 0


def test_removing_evidence_rolls_resume_back(sandbox):
    """**核心**:产出物事后被删 → resume 必须**退回**该阶段(不许假装已完成)。"""
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    for stage, art in [("分析", "art/01-分析.md"), ("编码", "art/02-编码.md")]:
        gate(root, "enter", "--req", "R1", "--stage", stage)
        _artifact(root, art)
        gate(root, "pass", "--req", "R1")

    r = gate(root, "resume", "--req", "R1")
    assert "验证" in r.stdout, "两个阶段都通过后,应指向第三阶段"

    (root / "art" / "01-分析.md").unlink()          # 把第一阶段的产出物删掉
    r = gate(root, "resume", "--req", "R1")
    assert "分析" in r.stdout, "产出物没了 → 必须退回第一阶段,而不是继续往前"


def test_status_reports_missing_evidence(sandbox):
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    gate(root, "enter", "--req", "R1", "--stage", "分析")
    _artifact(root, "art/01-分析.md")
    gate(root, "pass", "--req", "R1")
    (root / "art" / "01-分析.md").unlink()
    r = gate(root, "status", "--req", "R1")
    assert "产出物缺" in r.stdout


def test_unknown_stage_rejected(sandbox):
    root, cfg = sandbox
    gate(root, "init", "--req", "R1", "--config", str(cfg))
    r = gate(root, "enter", "--req", "R1", "--stage", "不存在")
    assert r.returncode == 2


def test_state_file_is_committed_location(sandbox):
    """状态落在 `docs/state/`(**入库**)—— 换台机器也能续跑。"""
    root, cfg = sandbox
    gate(root, "init", "--req", "REQ-X", "--config", str(cfg))
    p = root / "docs" / "state" / "REQ-X.json"
    assert p.is_file()
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["req"] == "REQ-X" and "history" in d
