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


# ── 预算守卫:--no-curve(2026-09-13 加)───────────────────────────
def test_no_curve_skips_detection_curve_and_reports_round_count(tmp_path):
    """`--no-curve`:只跑单次实验(`2N` 轮),不做 N 曲线。

    ⚠️ 动机:M2 只需要「N=20/臂」的单次实验,而 N 曲线会把**轮数**放大到
    `2N + 2·repeats·Σprobes`(N=20 时 **40 → 820 轮**,约 19.5×)。
    这个开关此前**不存在** —— 照文档直接跑 `--n 20 --live` 会超预算约 20 倍。
    """
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--n", "4", "--repeats", "2",
             "--no-curve", "--out", str(out))
    assert p.returncode == 0, p.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["detection_curve"] == []
    assert d["run"]["no_curve"] is True
    assert d["run"]["rounds_planned"] == 8          # 2N = 8


def test_rounds_planned_exposes_the_curve_multiplier(tmp_path):
    """不开 `--no-curve` 时也要能算清总轮数 —— 这就是预算守卫的依据。"""
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--n", "4", "--repeats", "2", "--out", str(out))
    assert p.returncode == 0, p.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    # probes(4) = [2, 4];曲线 = 2·2·(2+4) = 24;合计 8 + 24 = 32
    assert d["run"]["no_curve"] is False
    assert d["run"]["rounds_planned"] == 32


def test_live_warns_about_curve_multiplier_before_judge_config_check(tmp_path):
    """`--live` 未加 `--no-curve` 时,**即使 judge 没配好也要先报出轮数与倍数**。

    动机:这条警告是**预算守卫**。若它印在配置检查之后,操作者看不到成本就先退出了。
    """
    env = dict(os.environ, EVAL_DOTENV="0")
    for k in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL"):
        env.pop(k, None)
    p = _run("--evals", str(EVALS), "--n", "20", "--repeats", "10", "--live",
             "--out", str(tmp_path / "x.json"), env=env)
    assert p.returncode == 3                       # 没配 judge ⇒ 拒绝跑(不静默冒充)
    assert "计划轮数 = 820" in p.stderr
    assert "--no-curve" in p.stderr                # 并把放大的原因说清


def test_live_with_no_curve_reports_single_experiment_cost(tmp_path):
    env = dict(os.environ, EVAL_DOTENV="0")
    for k in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL"):
        env.pop(k, None)
    p = _run("--evals", str(EVALS), "--n", "20", "--repeats", "10", "--live", "--no-curve",
             "--out", str(tmp_path / "x.json"), env=env)
    assert p.returncode == 3
    assert "计划轮数 = 40" in p.stderr
    assert "已加 --no-curve" in p.stderr


# ── 熔断与可见性(2026-09-13 补:业务方问起时查证,此前**两者都没有**)──
def test_max_tokens_zero_trips_the_breaker(tmp_path):
    """`--max-tokens 0` ⇒ 第一轮后立刻中止。

    动机:本工具此前**没有任何累计 token 上限**。横切原则要求的
    「token 预算与循环熔断」对它从未实现 —— 一次 N=20 live 跑的最坏上界
    按算约 1440 万 token,而中途**看不到也拦不住**。
    """
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--n", "6", "--repeats", "1", "--no-curve",
             "--max-tokens", "0", "--out", str(out))
    assert p.returncode != 0, "熔断必须让退出码非 0"
    assert "熔断" in (p.stderr + p.stdout)
    d = json.loads(out.read_text(encoding="utf-8"))     # 但**要留下痕迹**
    assert d["run"]["aborted"] is True
    assert d["run"]["spent_tokens"] == 0


def test_generous_max_tokens_lets_run_finish(tmp_path):
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--n", "2", "--repeats", "1", "--no-curve",
             "--max-tokens", "1000000", "--out", str(out))
    assert p.returncode == 0, p.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["run"]["aborted"] is False


def test_round_progress_is_printed_for_visibility(tmp_path):
    """逐轮打印进度 —— 此前 A/B 跑起来是个黑盒(无 trace、无逐轮产物)。"""
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--n", "2", "--repeats", "1", "--no-curve",
             "--out", str(out))
    assert p.returncode == 0, p.stderr
    assert "轮 1/" in (p.stderr + p.stdout)
