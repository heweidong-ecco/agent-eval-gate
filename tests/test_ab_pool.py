"""A/B **分块池化**(`tools/ab_pool.py`)。

**为什么需要它**(2026-09-15):`KD-11`(长任务无断点)业务方已定夺**不修**。
⇒ 一次 40 轮 / ≈2 小时 / ≈116 万 token 的运行,中途崩掉就全废。
⇒ 对策 = **分 5 块跑,每块独立产物与独立 token 上限**(崩了只丢一块),
跑完再把各块的逐轮达标率**池化**成一个 N=20 的实验结论。

⚠️ **池化最容易出的错是"拼错源"**:把两轮不同 commit / 不同评测集的产物拼在一起,
会得到一个**看起来完全合理**的错数。故本工具的第一职责是**拒绝异源**。

⚠️ 本文件**自造 chunk**,不依赖 `eval/runs/` 的真实产物(那些被 gitignore,CI 上不存在)
—— 与 `tests/test_archive_evidence.py` 同一纪律。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ab_pool.py"


def _chunk(path: Path, *, commit="abc1234", evals="eval/fastapi_rag_golden.evals.json",
           cases=48, n=4, rates_a=None, rates_b=None, spent=230000, no_curve=True) -> Path:
    doc = {
        "tool": "tools/ab_regression.py",
        "mode": "live",
        "evals": {"file": evals, "cases": cases},
        "arms": {"baseline": {"p": 0.9, "rates": rates_a if rates_a is not None else [1.0] * n},
                 "candidate": {"p": 0.8, "rates": rates_b if rates_b is not None else [1.0] * n}},
        "single_experiment": {"verdict": "no_difference", "p": 1.0, "d": 0.0},
        "detection_curve": [],
        "detection_rate": 0.0,
        "run": {"commit": commit, "n": n, "repeats": 10, "no_curve": no_curve,
                "rounds_planned": 2 * n, "aborted": False, "spent_tokens": spent,
                "max_tokens": 320000, "elapsed_s": 1380.0},
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_pools_rates_across_chunks(tmp_path):
    """3 块 × n=4 ⇒ 池化后**每臂 12 轮**,且结论在新样本上**重算**(不是取某一块的)。"""
    c1 = _chunk(tmp_path / "c1.json", rates_a=[1.0, 1.0, 0.9, 1.0], rates_b=[1.0, 1.0, 1.0, 1.0])
    c2 = _chunk(tmp_path / "c2.json", rates_a=[1.0, 0.8, 1.0, 1.0], rates_b=[1.0, 1.0, 1.0, 1.0])
    c3 = _chunk(tmp_path / "c3.json", rates_a=[1.0, 1.0, 1.0, 0.7], rates_b=[1.0, 1.0, 1.0, 1.0])
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(c1), str(c2), str(c3), "--out", str(out))
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert len(d["arms"]["baseline"]["rates"]) == 12, "基线臂应为 4×3=12 轮"
    assert len(d["arms"]["candidate"]["rates"]) == 12
    assert d["run"]["n_per_arm"] == 12
    assert d["run"]["rounds"] == 24
    assert d["run"]["spent_tokens_total"] == 230000 * 3
    # 结论必须是**在 12+12 上重算**的,而不是抄某一块的
    assert "single_experiment" in d and "p" in d["single_experiment"]
    assert len(d["pooled_from"]) == 3


def test_rejects_chunks_from_different_commits(tmp_path):
    """**异源必须拒绝** —— 拼错源会给出一个看起来完全合理的错数。"""
    c1 = _chunk(tmp_path / "c1.json", commit="aaa1111")
    c2 = _chunk(tmp_path / "c2.json", commit="bbb2222")
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(c1), str(c2), "--out", str(out))
    assert r.returncode == 3, f"应拒绝,实得 {r.returncode}"
    assert "commit" in (r.stdout + r.stderr)
    assert not out.exists(), "拒绝时**不得**产出半成品"


def test_rejects_chunks_from_different_evalsets(tmp_path):
    c1 = _chunk(tmp_path / "c1.json", evals="eval/a.evals.json", cases=48)
    c2 = _chunk(tmp_path / "c2.json", evals="eval/b.evals.json", cases=48)
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(c1), str(c2), "--out", str(out))
    assert r.returncode == 3
    assert not out.exists()


def test_rejects_chunks_with_different_n(tmp_path):
    """`--n` 不同 ⇒ 拒绝(本批次的各块必须同规模,否则"池化"的语义就变了)。"""
    c1 = _chunk(tmp_path / "c1.json", n=4)
    c2 = _chunk(tmp_path / "c2.json", n=5, rates_a=[1.0] * 5, rates_b=[1.0] * 5)
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(c1), str(c2), "--out", str(out))
    assert r.returncode == 3
    assert not out.exists()


def test_single_chunk_is_allowed(tmp_path):
    """单块也合法(退化为原样)—— 分块是手段,不是目的。"""
    c1 = _chunk(tmp_path / "c1.json")
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(c1), "--out", str(out))
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["run"]["n_per_arm"] == 4


def test_missing_chunk_returns_3(tmp_path):
    out = tmp_path / "pooled.json"
    r = _run("--chunks", str(tmp_path / "nope.json"), "--out", str(out))
    assert r.returncode == 3
    assert not out.exists()


def test_pooled_doc_says_what_it_cannot_prove(tmp_path):
    """池化产物必须自带**局限说明** —— 本仓每份产物都要能回答"不能证明什么"。"""
    c1 = _chunk(tmp_path / "c1.json")
    out = tmp_path / "pooled.json"
    assert _run("--chunks", str(c1), "--out", str(out)).returncode == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    lim = d.get("_limitations", "")
    assert "分块" in lim and ("≠" in lim or "不等" in lim or "不可" in lim), \
        "必须写明:分块池化 ≠ 一次连续运行(块间环境可能不同)"
