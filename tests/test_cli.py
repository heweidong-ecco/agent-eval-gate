"""CLI run:--mode good→exit0 / bad→exit1;离线 --offline 用 FakeJudge;产出报告文件。"""
import json
from pathlib import Path

from eval_gate.cli import main

EVALS = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"


def test_cli_good_mode_exit_zero(tmp_path):
    rc = main(["run", "--evals", str(EVALS), "--mode", "good", "--offline",
               "--report-dir", str(tmp_path)])
    assert rc == 0
    runs = list(tmp_path.glob("*.local.json"))
    assert runs and json.loads(runs[0].read_text(encoding="utf-8"))["exit_code"] == 0


def test_cli_bad_mode_exit_one(tmp_path):
    rc = main(["run", "--evals", str(EVALS), "--mode", "bad", "--offline",
               "--report-dir", str(tmp_path)])
    assert rc == 1


def test_cli_missing_evals_is_usage_error(tmp_path):
    rc = main(["run", "--evals", str(tmp_path / "nope.json"), "--offline",
               "--report-dir", str(tmp_path)])
    assert rc == 3
