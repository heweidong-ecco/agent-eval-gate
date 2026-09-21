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


def test_cli_does_not_report_undecided_as_未通过(tmp_path, capsys):
    """DEC-022 §7.6:确定性层「**判不准**」的条不得被列成「**未通过**」。

    ⚠️ 让误报"有声"**不等于**让它"发错声" —— 表头写「未通过」、归属写「硬层拦下」,
    读的人会断定**被测失败了**(实际是**判据自己承认判不准**)。**错的信息比没有信息坏。**
    """
    d = json.loads(EVALS.read_text(encoding="utf-8"))
    d["evals"] = [c for c in d["evals"] if c["id"] == 7]
    d["evals"][0]["expected"]["answer_not_contains"] = ["绝不存在的串ZZZ"]
    ev = tmp_path / "undec.json"
    ev.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    rc = main(["run", "--evals", str(ev), "--mode", "bad", "--offline",
               "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2, "存疑 ⇒ exit 2(需人工),不阻断"
    assert "存疑 1 条" in out, f"不得把它并进「未通过」:{out}"
    assert "判不准" in out, f"归属必须写明是判不准,不是被拦下:{out}"
    assert "硬层拦下" not in out, "判不准 ≠ 被拦下"


def test_cli_summary_prints_flag_and_redteam_side_by_side(tmp_path, capsys):
    """DEC-022 §7.6(可观测性):**存疑**与**红队突破**必须**并列**输出。

    为什么值得一条守卫:右栏用例仍会误报,而误报只表现为"某几条不过"⇒ **看不出是判据判不准**。
    两个数并列之后,「`flag > 0` 且 `redteam_hits == 0`」= **判据判不准**的信号
    (也是"该给那些用例补证据型判据"的触发信号)。删掉任一个,这个信号就没了。
    """
    rc = main(["run", "--evals", str(EVALS), "--mode", "good", "--offline",
               "--report-dir", str(tmp_path)])
    out = capsys.readouterr().out
    line = next((l for l in out.splitlines() if "存疑" in l), "")
    assert "红队突破" in line, f"两问未并列在同一行:{line!r}"
    assert rc == 0
