"""CLI 异常路径:坏输入一律 exit 3(配置/运行错误),绝不与 1(阻断发布)混淆。

另含 `.env` 加载开关(`EVAL_DOTENV=0`)—— 没有它,"未配置 judge" 的用例会被
`_load_dotenv` 用 `setdefault` 把 .env 里的**真 key 灌回**,测试会真的打到线上 judge。
"""
import json
import os
from pathlib import Path

from eval_gate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "eval" / "mini_rag_qa.evals.json"


# ── .env 加载开关(驱动本任务唯一的生产改动)──────────────────
def test_dotenv_loading_can_be_disabled(monkeypatch, tmp_path):
    """`EVAL_DOTENV=0` 时不得读 .env —— 否则测试无法构造「未配置」的环境。

    末尾带**反证**:不设开关时确实会读入 —— 证明本断言不是恒真。
    """
    from eval_gate import config as cfg_mod

    env_file = tmp_path / ".env"
    env_file.write_text("EVAL_JUDGE_MODEL=leaked\n", encoding="utf-8")
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)

    monkeypatch.setenv("EVAL_DOTENV", "0")
    cfg_mod._load_dotenv(env_file)
    assert "EVAL_JUDGE_MODEL" not in os.environ, "EVAL_DOTENV=0 但 .env 仍被读入"

    monkeypatch.delenv("EVAL_DOTENV")
    cfg_mod._load_dotenv(env_file)
    assert os.environ["EVAL_JUDGE_MODEL"] == "leaked", "反证失败:默认本应读入 .env"
    monkeypatch.delenv("EVAL_JUDGE_MODEL")


# ── 阈值文件 ────────────────────────────────────────────────
def test_structurally_broken_threshold_file_returns_3(tmp_path, capsys):
    """合法 JSON 但顶层是数组 → 结构不对,同属配置错误(不许 traceback 顶成 1)。"""
    bad = tmp_path / "thr.json"
    bad.write_text("[1,2,3]", encoding="utf-8")
    rc = main(["run", "--evals", str(EVALS), "--offline", "--threshold", str(bad),
               "--report-dir", str(tmp_path)])
    assert rc == 3
    assert "阈值文件不可读/结构不对" in capsys.readouterr().out


def test_unreadable_threshold_path_returns_3(tmp_path):
    rc = main(["run", "--evals", str(EVALS), "--offline",
               "--threshold", str(tmp_path / "nope.json"), "--report-dir", str(tmp_path)])
    assert rc == 3


# ── judge 缺配置(须真隔离 .env)────────────────────────────
def test_unconfigured_judge_falls_back_to_fake_with_notice(tmp_path, monkeypatch, capsys):
    """未配 EVAL_JUDGE_* → 用 FakeJudge 并**明说**(不静默降级)。"""
    monkeypatch.setenv("EVAL_DOTENV", "0")
    for k in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL"):
        monkeypatch.delenv(k, raising=False)
    rc = main(["run", "--evals", str(EVALS), "--mode", "good",
               "--report-dir", str(tmp_path)])
    assert rc == 0
    assert "用 FakeJudge 离线自证" in capsys.readouterr().out


# ── trace 子命令 ────────────────────────────────────────────
def test_trace_for_unknown_run_returns_3(tmp_path, capsys):
    assert main(["trace", "--run", "nope", "--trace-dir", str(tmp_path)]) == 3
    assert "trace 文件不存在" in capsys.readouterr().out


def test_trace_with_empty_dir_returns_3(tmp_path, capsys):
    assert main(["trace", "--trace-dir", str(tmp_path)]) == 3
    assert "未找到 trace 文件" in capsys.readouterr().out


# ── 投毒评测集的**门级**断言(红队靶子④)────────────────────
def test_poisoned_evalset_fails_before_any_model_call(tmp_path, monkeypatch, capsys):
    """投毒评测集 → exit 3,且全程**零 judge 构造**。

    「零模型调用即失败」在门上的落点 = `_cmd_run` 顺序:先 load_evals,后建 judge。
    用 Tripwire 记构造次数,证明坏配置**走不到**建 judge 那一步。
    """
    from eval_gate import cli as cli_mod
    import eval_gate.judge as judge_mod

    built = []

    class Tripwire(judge_mod.Judge):
        def __init__(self, *a, **k):
            built.append(1)
            super().__init__(*a, **k)

    monkeypatch.setattr(cli_mod, "Judge", Tripwire)
    # 让 judge「看起来已配置」—— 否则 FakeJudge 分支会让本断言失去意义
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "m")

    poison = tmp_path / "poisoned.json"
    poison.write_text(json.dumps({
        "version": 1, "threshold_ref": "eval/阈值.md",
        "evals": [{"id": 1, "module": "nope",           # module 非法 → 装载即失败
                   "input": {"question": "q"},
                   "expected": {"answer_contains": ["a"]}}]}), encoding="utf-8")

    rc = cli_mod.main(["run", "--evals", str(poison), "--report-dir", str(tmp_path)])
    assert rc == 3
    assert "评测集错误" in capsys.readouterr().out
    assert built == [], "投毒评测集在装载阶段就构造了 judge(违反「零模型调用即失败」)"


# ── 整批 aborted(degraded)─────────────────────────────────
def test_degraded_run_prints_notice(tmp_path, capsys, monkeypatch):
    """整批 aborted(exit 3)→ 必须印 DEGRADED 提示,不许静默当全绿。"""
    from eval_gate import cli as cli_mod
    from eval_gate.runner import RunResult

    fake = RunResult(
        run_id="x",
        summary={"total": 0, "passed": 0, "failed": 0, "flag": 0,
                 "skipped": 0, "redteam_hits": 0, "completion": 0.0},
        cases=[], exit_code=3, blockers=[], applied_thresholds={},
        degraded=True, degraded_reason="E_SUT_QUOTA: 额度耗尽")
    monkeypatch.setattr(cli_mod, "evaluate", lambda *a, **k: fake)
    rc = cli_mod.main(["run", "--evals", str(EVALS), "--offline",
                       "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 3 and "DEGRADED" in out
    assert "整批 aborted" in out
