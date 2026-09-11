"""A/B 驱动:子进程级验证(含退出码与产物结构)。

离线、零外网、零 token。跑的是 mini 评测集(8 条,其中 6 条走 judge),
整套秒级 —— 它标定的是**统计装置**,不是模型质量。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tools" / "ab_regression.py"
EVALS = ROOT / "eval" / "mini_rag_qa.evals.json"


def _run(*args, timeout=600, env=None):
    return subprocess.run([sys.executable, str(DRIVER), *args],
                          capture_output=True, text=True, cwd=str(ROOT),
                          timeout=timeout, env=env)


def test_driver_detects_a_large_injected_difference(tmp_path):
    """两臂拉大(0.98 vs 0.55)→ 必须稳定检出;否则统计装置无效。"""
    out = tmp_path / "ab.json"
    r = _run("--evals", str(EVALS), "--arm-a", "0.98", "--arm-b", "0.55",
             "--n", "12", "--repeats", "8", "--seed", "7", "--out", str(out))
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["arms"]["baseline"]["p"] == 0.98
    assert doc["single_experiment"]["verdict"] == "regressed"
    assert doc["single_experiment"]["p"] < 0.05
    assert doc["detection_rate"] >= 0.75, doc["detection_rate"]


def test_driver_does_not_claim_difference_for_identical_arms(tmp_path):
    """同一 p 的两臂 → 检出率必须**低**(假阳性检查)。

    不为 0 是正常的:α=0.05 × repeats 次里偶发一次显著。故断言的是**上界**,
    与上一条的「下界」配对 —— 装置坏掉时两者会同时失真,单看一条证明不了什么。
    """
    out = tmp_path / "ab.json"
    r = _run("--evals", str(EVALS), "--arm-a", "0.85", "--arm-b", "0.85",
             "--n", "12", "--repeats", "8", "--seed", "7", "--out", str(out))
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["detection_rate"] <= 0.25, doc["detection_rate"]


def test_rounds_are_independent_draws_not_copies(tmp_path):
    """N 轮必须**逐轮独立抽样** —— 否则 20 轮 = 同一次运行的 20 份拷贝。

    实测踩过:每轮都用同一个种子新建 JitterJudge → 轮间方差恒为 0、
    `cohens_d` 返回 None、p 恒为 1,整条 N 曲线失去意义,而表面看"跑通了"。
    """
    out = tmp_path / "ab.json"
    r = _run("--evals", str(EVALS), "--arm-a", "0.90", "--arm-b", "0.80",
             "--n", "20", "--repeats", "2", "--seed", "7", "--out", str(out))
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(set(doc["arms"]["baseline"]["rates"])) > 1, \
        "基线臂 20 轮取值完全相同 → 轮间不是独立抽样(方差恒 0)"
    assert doc["single_experiment"]["effect_defined"] is True, \
        "有真实轮间方差时,效应量不该是「未定义」"


def test_report_declares_synthetic_variance_source(tmp_path):
    """报告必须**自陈**方差来自合成抖动 —— 不得让人误读成真实模型噪声。"""
    out = tmp_path / "ab.json"
    r = _run("--evals", str(EVALS), "--arm-a", "0.9", "--arm-b", "0.8",
             "--n", "4", "--repeats", "2", "--out", str(out))
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["mode"] == "offline-jitter"
    assert "合成" in doc["warning"] and "不代表真实模型噪声" in doc["warning"]
    assert doc["run"]["commit"] and doc["evals"]["cases"] == 8


def test_driver_rejects_out_of_range_arm_with_exit_3(tmp_path):
    r = _run("--evals", str(EVALS), "--arm-a", "1.5", "--arm-b", "0.8",
             "--n", "5", "--out", str(tmp_path / "x.json"))
    assert r.returncode == 3
    assert "arm" in (r.stderr + r.stdout).lower()


def test_driver_rejects_tiny_n_with_exit_3(tmp_path):
    r = _run("--evals", str(EVALS), "--n", "1", "--out", str(tmp_path / "x.json"))
    assert r.returncode == 3
    assert "--n" in (r.stderr + r.stdout)


def test_missing_evalset_exits_3(tmp_path):
    r = _run("--evals", str(tmp_path / "nope.json"), "--n", "4",
             "--out", str(tmp_path / "x.json"))
    assert r.returncode == 3


def test_live_mode_without_judge_config_exits_3(tmp_path):
    """`--live` 但无 judge 配置 → exit 3,**拒绝静默回落到合成抖动**。

    ⚠️ 必须 `EVAL_DOTENV=0`:否则 judge_config() 会 setdefault 把 .env 的真 key 灌回,
    这条用例就变成"真的去打线上 judge"。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("EVAL_JUDGE_") and k != "EVAL_DOTENV"}
    env["EVAL_DOTENV"] = "0"
    r = _run("--evals", str(EVALS), "--live", "--n", "4",
             "--out", str(tmp_path / "x.json"), env=env)
    assert r.returncode == 3
    assert "EVAL_JUDGE" in (r.stdout + r.stderr)
