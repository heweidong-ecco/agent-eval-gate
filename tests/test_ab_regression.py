"""A/B 驱动:子进程级验证(含退出码与产物结构)。

离线、零外网、零 token。跑的是 mini 评测集(8 条,其中 6 条走 judge),
整套秒级 —— 它标定的是**统计装置**,不是模型质量。
"""
import importlib.util
import json
import os
import re
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
    `2N + 2·repeats·Σprobes`(N=20 时 **40 → 820 轮**,总倍数 20.5×)。
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


# ── 逐轮取证:让每一轮**落独立产物**(2026-09-15)─────────────────────────────
#
# 动机:`_run_arm` 原本是 `evaluate(ev, judge=make_judge(i))` —— **不传 tracer**,
# 一圈跑完只留一个 completion 浮点。后果三条,每一条都致命:
#   ① A3(轮间延迟取证)要的 `sut.call` / `attempts` **一个字节都到不了文件**
#      —— 字段加了也白加(本仓前科:重试只写 stderr、不落盘);
#   ② B4(judge 校准)要的**逐 case 答案**拿不到 ⇒ 凑不出新参照集;
#   ③ 一次 ≈116 万 token 的运行**不可审计** —— 只有两个浮点数组。
# ⇒ 这是本批次**唯一挡在 116 万前面的东西**。

def _artifact_names(d: Path, suffix: str) -> set[str]:
    return {p.name.split(".")[0] for p in d.glob(f"*{suffix}")}


def test_every_round_writes_its_own_run_artifacts(tmp_path):
    """2 轮 × 2 臂 ⇒ **4 份 trace + 4 份报告**,且 run_id 一一对应。"""
    rd = tmp_path / "runs"
    out = tmp_path / "ab.json"
    p = _run("--evals", str(EVALS), "--arm-a", "0.9", "--arm-b", "0.8",
             "--n", "2", "--repeats", "1", "--no-curve",
             "--report-dir", str(rd), "--out", str(out))
    assert p.returncode == 0, p.stderr
    traces = sorted(rd.glob("*.trace.jsonl"))
    reports = sorted(rd.glob("*.local.json"))
    assert len(traces) == 4, \
        f"2 轮 × 2 臂应各留一份 trace,实得 {len(traces)}: {[q.name for q in traces]}"
    assert len(reports) == 4, f"报告数不对: {[q.name for q in reports]}"
    assert _artifact_names(rd, ".trace.jsonl") == _artifact_names(rd, ".local.json"), \
        "trace 与报告 run_id 对不上 ⇒ 事后无法把落盘证据配成一轮"
    # ⚠️ **光有文件不够**:若 `evaluate()` 没拿到 tracer,trace 会是**空文件** ——
    #    文件数照样对,但里面一个 span 都没有(= 什么都没记)。
    #    (突变验证时实测到:只数文件条数抓不住这种"空壳"。)
    for q in traces:
        spans = [json.loads(l) for l in q.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert any(s["name"] == "run.evaluate" for s in spans), \
            f"{q.name} 是空壳 trace(没有 run.evaluate span)⇒ 这一轮实际没有取证"


def test_written_trace_carries_retry_visibility_fields(tmp_path):
    """**端到端**:`attempts` 必须真的写进 `.trace.jsonl`(不是只进内存)。

    落盘是唯一能"跑完之后还查得到"的地方 —— 若这里取不到,A3 的取证
    ("是不是重试吃掉的")就无从下手。
    """
    rd = tmp_path / "runs"
    p = _run("--evals", str(EVALS), "--arm-a", "0.9", "--arm-b", "0.8",
             "--n", "2", "--repeats", "1", "--no-curve",
             "--report-dir", str(rd), "--out", str(tmp_path / "ab.json"))
    assert p.returncode == 0, p.stderr          # 驱动要求 --n ≥ 2
    tr = sorted(rd.glob("*.trace.jsonl"))[0]
    spans = [json.loads(l) for l in tr.read_text(encoding="utf-8").splitlines() if l.strip()]
    sut_spans = [s for s in spans if s["name"] == "sut.call"]
    assert sut_spans, "trace 里没有 sut.call span ⇒ 这轮没有逐 case 证据"
    assert all("attempts" in s["attributes"] for s in sut_spans), \
        "sut.call span 缺 attempts ⇒ A3 将无从判断'是不是重试吃掉的'"


def test_without_report_dir_no_artifacts_are_written(tmp_path):
    """不传 `--report-dir` ⇒ **不落产物**(保持既有行为)。

    这一条是**给测试与本地冒烟用的**:否则每次离线冒烟都会往 `eval/runs/` 里灌文件。
    真实批次**必须显式声明目录** —— 见下面的守卫用例。
    """
    rd = tmp_path / "runs"
    rd.mkdir()
    p = _run("--evals", str(EVALS), "--n", "2", "--repeats", "1", "--no-curve",
             "--out", str(tmp_path / "ab.json"))
    assert p.returncode == 0, p.stderr          # 驱动要求 --n ≥ 2
    assert not list(rd.glob("*.trace.jsonl"))


# ── 工具卫生三修(2026-09-15,PR-2)────────────────────────────────────────

def _load_driver():
    """把驱动当模块载入(用于对 `main()` 做**单元级**断言)。

    子进程级测不了"曲线段也受熔断约束" —— 离线判分器不上报 token,`spent` 恒为 0,
    上限永远触发不了。⇒ 必须把 `evaluate` 换成会上报用量的桩。
    """
    spec = importlib.util.spec_from_file_location("ab_regression_mod", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_live_estimate_uses_the_measured_per_round_cost(tmp_path):
    """live 预算预告必须用**实测**每轮成本(**2.86–2.99 万**),不是旧的内置估值 2.4 万。

    为什么较真:操作员是**按下 116 万之前**读这一行的人。低报 16–20% 正是"预算误解"的温床
    —— 而本批次已经因为这类的口径漂移翻过一次车(`ROADMAP` 的 T4 行)。
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("EVAL_JUDGE_")}
    env["EVAL_DOTENV"] = "0"
    p = _run("--evals", str(EVALS), "--live", "--n", "20", "--no-curve",
             "--report-dir", str(tmp_path / "runs"), "--out", str(tmp_path / "x.json"), env=env)
    assert p.returncode == 3, f"无 judge 配置应 exit 3;实得 {p.returncode}\n{p.stderr}"
    m = re.search(r"估算 ≈ ([\d,]+) tokens", p.stderr)
    assert m, f"预告行没打印估算:\n{p.stderr}"
    est = int(m.group(1).replace(",", ""))
    low = 40 * 28_600          # 40 轮 × 实测下界 2.86 万
    assert est >= low, \
        f"live 预告低估:报 {est:,},而实测每轮 2.86–2.99 万 ⇒ 40 轮应 ≥ {low:,}"


def test_curve_is_covered_by_the_token_breaker(tmp_path, monkeypatch):
    """**N 曲线也必须受 `--max-tokens` 约束** —— 这是本批次唯一带"失控花钱"失败模式的缺陷。

    实测:`_run_arm` 在曲线里**没拿到 budget**(`cap=None`)⇒ 漏写 `--no-curve` 时
    780 轮**不受任何上限约束**,量级 **2000 万**。本批始终用 `--no-curve`(敞口被封住),
    但修它只需 1 行 + 1 个突变测试 —— 用近乎为零的成本消掉一个 2000 万级事故。
    """
    mod = _load_driver()
    calls = {"n": 0}

    class _Res:
        run_id = "deadbeef"
        summary = {"completion": 1.0}
        judge_usage = {"total_tokens": 10}

    def fake_evaluate(ev, quality="faithful", judge=None, thresholds=None,
                      quality_by_sut=None, tracer=None):
        calls["n"] += 1
        return _Res()

    monkeypatch.setattr(mod, "evaluate", fake_evaluate)
    # `--n 2 --repeats 1` ⇒ 计划 = 主实验 4 轮 + 曲线 4 轮 = 8 轮;每轮 10 token
    # 上限 60:主实验(40)过得去,曲线到第 2 轮就超 ⇒ 必须熔断
    rc = mod.main(["--evals", str(EVALS), "--n", "2", "--repeats", "1",
                   "--max-tokens", "60", "--out", str(tmp_path / "ab.json")])
    assert rc == 4, f"曲线段超上限必须熔断(exit 4),而不是无声跑完;实得 {rc}"
    assert calls["n"] < 8, f"熔断后不该把全部轮跑完(实跑 {calls['n']} 轮)"
    d = json.loads((tmp_path / "ab.json").read_text(encoding="utf-8"))
    assert d["run"]["aborted"] is True


def test_help_quotes_the_true_amplification_factor():
    """help 里的放大倍数必须与 `rounds_planned` **算出来的一致**。

    实测:代码 stderr 打的是**总倍数** `820/40 = 20.5×`,而 docstring/help/测试注释写**19.5×**
    (那是**曲线增量** `780/40`)⇒ **代码是对的,文档写错了**。
    把已知错的数字留在"预算纪律"议题旁边,是最廉价的信誉流失。
    """
    mod = _load_driver()
    true_x = mod.rounds_planned(20, 10, False) / (2 * 20)          # 820/40 = 20.5
    r = subprocess.run([sys.executable, str(DRIVER), "--help"],
                       capture_output=True, text=True)
    text = r.stdout + r.stderr
    assert f"{true_x:.1f}×" in text, \
        f"--help 未写出真实倍数 {true_x:.1f}×;含 × 的行:{[l for l in text.splitlines() if '×' in l]}"
    assert "19.5×" not in text, "19.5× 是**曲线增量**倍数,不是操作员要看的**总**倍数"


def test_live_without_report_dir_is_refused(tmp_path):
    """`--live` 却不声明产物目录 ⇒ **exit 3 拒启动**。

    理由:一次真实运行的成本量级是 100 万 token,而**不可审计的百万 token 花销**
    正是本批次要根除的东西。离线冒烟不受此限(不让测试往仓里灌文件)。

    ⚠️ judge 配置**必须给假的非空值**:若留空,这条会因"judge 未配置"就 exit 3
    —— **因为错误的原因通过**(报错文案里根本没有 report-dir)。
    下面的 `assert "report-dir"` 就是防这个的。指向 `127.0.0.1:1` 且**在校验后才可能发请求**,
    而校验在发请求之前 ⇒ 不会真的外联。
    """
    out = tmp_path / "ab.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("EVAL_JUDGE_")}
    env.update({"EVAL_DOTENV": "0", "EVAL_JUDGE_BASE_URL": "http://127.0.0.1:1/v1",
                "EVAL_JUDGE_API_KEY": "dummy-not-used", "EVAL_JUDGE_MODEL": "dummy"})
    p = _run("--evals", str(EVALS), "--live", "--n", "2", "--repeats", "1",
             "--no-curve", "--out", str(out), env=env)
    assert p.returncode == 3, f"应拒启动,实得 {p.returncode}:\n{p.stderr}"
    assert "report-dir" in (p.stderr + p.stdout).lower(), \
        f"拒绝的理由必须是缺产物目录,不是别的:\n{p.stdout}\n{p.stderr}"
