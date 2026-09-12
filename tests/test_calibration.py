"""E7 judge 校准 · judge-人工一致率(M1 / DEC-008)。

口径(契约 `评测-judge.md:47`):judge 判定 ↔ 人工标签 → 一致率 = `judge_human_agreement`。
本文件守三件事:
① **只统计真被标注的条目**(未标注 / 「说不清」必须剔除**并单独报数**,不得当成"不一致"拉低指标);
② `judge_human_agreement` 的语义 = judge 判 pass ↔ 人工判"满足";
③ flag(存疑)单独报数 —— 它是"判分器自己也没定",与"判错"不是一回事。
"""
from eval_gate.calib import compute_agreement


def _item(rid, human, verdict):
    return {"ref_id": rid, "human": human, "judge_verdict": verdict}


# ── ① 未标注 / 说不清 的剔除 ────────────────────────────────
def test_unlabeled_items_are_excluded_not_counted_as_disagreement():
    """未标注(null)必须**剔除**,不得算进分母 —— 否则不标 = 判分器判错。"""
    out = compute_agreement([_item("a", True, "pass"), _item("b", None, "fail")])
    assert out["n_labeled"] == 1
    assert out["n_unlabeled"] == 1
    assert out["agreement"] == 1.0


def test_unsure_labels_are_excluded_and_reported_separately():
    """「说不清」是**允许的诚实答案** —— 剔除但要报出来(报出来才知道覆盖够不够)。"""
    out = compute_agreement([_item("a", True, "pass"),
                             _item("b", "unsure", "flag"),
                             _item("c", False, "fail")])
    assert out["n_unsure"] == 1
    assert out["n_labeled"] == 2
    assert out["agreement"] == 1.0


def test_no_labels_yields_no_agreement_not_zero():
    """一条都没标 ⇒ 一致率是 None(**不是 0.0**)—— 0.0 会被读成"判分器全错"。"""
    out = compute_agreement([_item("a", None, "pass")])
    assert out["agreement"] is None
    assert out["n_labeled"] == 0


# ── ② 一致率语义 ───────────────────────────────────────────
def test_agreement_is_judge_pass_equals_human_satisfied():
    out = compute_agreement([_item("a", True, "pass"),      # 一致
                             _item("b", False, "fail"),     # 一致
                             _item("c", True, "fail"),      # **误杀**:答对了却判 fail
                             _item("d", False, "pass")])    # **漏放**:答错却判 pass
    assert out["n_labeled"] == 4
    assert out["n_agree"] == 2
    assert out["agreement"] == 0.5
    assert out["n_false_negative"] == 1, "误杀条数要单独可查 —— 它比总一致率更说明问题"
    assert out["n_false_positive"] == 1


# ── ③ flag 单独报数 ────────────────────────────────────────
def test_flags_are_counted_and_secondary_agreement_excludes_them():
    """flag = 判分器自己也没定:**它不通过该条,所以"人还得看一遍"** —— 这就是它的代价。

    口径:主指标里 flag **按"非 pass"算**。于是
    - 人工也判"不满足" → 结果一致(flag 没白费);
    - 人工判"满足"   → **不一致**(明明是好的却要人再看一遍)。
    副指标 `agreement_excl_flag` 把 flag 整个剔除,用来看**纯 pass/fail 判定**的准确度。
    """
    out = compute_agreement([_item("a", True, "pass"),     # 一致
                             _item("b", False, "flag"),    # 一致(flag 没白费)
                             _item("c", True, "flag"),     # **不一致**:好的却被 flag 住
                             _item("d", False, "fail")])   # 一致
    assert out["n_flag"] == 2
    assert out["n_labeled"] == 4
    assert out["n_agree"] == 3
    assert out["agreement"] == 0.75
    assert out["agreement_excl_flag"] == 1.0           # 剔掉两条 flag 后:pass/fail 全对


def test_agreement_excl_flag_is_none_when_everything_flagged():
    out = compute_agreement([_item("a", True, "flag")])
    assert out["n_labeled"] == 1
    assert out["agreement"] == 0.0
    assert out["agreement_excl_flag"] is None


# ── 边界 ───────────────────────────────────────────────────
def test_empty_input_is_total_none_not_crash():
    out = compute_agreement([])
    assert out["n_labeled"] == 0 and out["agreement"] is None and out["agreement_excl_flag"] is None


def test_missing_or_unknown_verdict_is_treated_as_not_pass():
    """judge 没给判定(缺字段/None)⇒ 按"非 pass"计,不得静默放行。"""
    out = compute_agreement([{"ref_id": "a", "human": True, "judge_verdict": None},
                             {"ref_id": "b", "human": False, "judge_verdict": None}])
    assert out["agreement"] == 0.5


# ── CLI:`eval-gate calibrate --refs <file>` ─────────────────
import json as _json  # noqa: E402

import eval_gate.cli as cli  # noqa: E402
from eval_gate.config import JudgeConfig  # noqa: E402
from eval_gate.judge import JudgeVerdict  # noqa: E402


def _refs_file(tmp_path):
    """4 条:a 一致(都 pass)/ b 一致(都 fail)/ c 未标注 / d **不一致**(人判满足、判分器判 fail)。"""
    p = tmp_path / "refs.json"
    p.write_text(_json.dumps({"refs": [
        {"ref_id": "a", "question": "q1", "expected": {"answer_contains": ["x"]},
         "sut_answer": "含有x", "human": True},
        {"ref_id": "b", "question": "q2", "expected": {"answer_contains": ["y"]},
         "sut_answer": "答案是z", "human": False},
        {"ref_id": "c", "question": "q3", "expected": {"answer_contains": ["z"]},
         "sut_answer": "含有z", "human": None},
        {"ref_id": "d", "question": "q4", "expected": {"answer_contains": ["w"]},
         "sut_answer": "措辞不同但意思一样", "human": True},
    ]}, ensure_ascii=False), encoding="utf-8")
    return p


def _stub_judge(monkeypatch):
    """桩判分器:只认字面命中(刻意做不出语义判断 ⇒ d 会误杀)。"""
    class _J:
        usage = {"calls": 0}

        def enabled(self):
            return True

        def label(self):
            return "stub@local"

        def grade(self, item):
            exp = (item.get("expected") or {}).get("answer_contains") or []
            ok = any(t in (item.get("sut_answer") or "") for t in exp)
            return JudgeVerdict("pass" if ok else "fail", 1.0 if ok else 0.0, ["桩"])

    monkeypatch.setattr(cli, "Judge", lambda cfg: _J())
    monkeypatch.setattr(cli, "judge_config",
                        lambda: JudgeConfig(base_url="http://x", api_key="k", model="stub"))


def test_cli_calibrate_reports_agreement_with_counts(tmp_path, monkeypatch, capsys):
    _stub_judge(monkeypatch)
    rc = cli.main(["calibrate", "--refs", str(_refs_file(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "judge_human_agreement" in out
    assert "0.67" in out, "2/3 一致(3 条已标,1 条未标)"
    assert "未标注" in out and "1" in out


def test_cli_calibrate_surfaces_the_false_negative(tmp_path, monkeypatch, capsys):
    """**误杀条目必须点名** —— 总一致率会把它摊平,而它恰恰是最该看的东西。"""
    _stub_judge(monkeypatch)
    cli.main(["calibrate", "--refs", str(_refs_file(tmp_path))])
    out = capsys.readouterr().out
    assert "误杀" in out and "d" in out


def test_cli_calibrate_compares_against_threshold_min(tmp_path, monkeypatch, capsys):
    """光有数不够:要和阈值里的 min 比,才知道这根锚**够不够稳**。"""
    _stub_judge(monkeypatch)
    cli.main(["calibrate", "--refs", str(_refs_file(tmp_path))])
    out = capsys.readouterr().out
    assert "0.80" in out, "要打印阈值里的 min(judge_human_agreement.min)"


def test_cli_calibrate_without_labels_says_unlabeled_not_pass(tmp_path, monkeypatch, capsys):
    """一条都没标 ⇒ 明说"无法计算",**不许报 0**(会被读成"判分器全错")。"""
    _stub_judge(monkeypatch)
    p = tmp_path / "empty.json"
    p.write_text(_json.dumps({"refs": [
        {"ref_id": "a", "question": "q", "expected": {"answer_contains": ["x"]},
         "sut_answer": "x", "human": None}]}, ensure_ascii=False), encoding="utf-8")
    cli.main(["calibrate", "--refs", str(p)])
    out = capsys.readouterr().out
    assert "未标注" in out and "无法计算" in out
    assert "0.00" not in out


def test_cli_calibrate_rejects_malformed_refs(tmp_path, capsys):
    """缺 question/expected/sut_answer 的条目 ⇒ 报错退出,不得静默跳过(静默跳过=偷偷改分母)。"""
    p = tmp_path / "bad.json"
    p.write_text(_json.dumps({"refs": [{"ref_id": "a", "human": True}]}), encoding="utf-8")
    rc = cli.main(["calibrate", "--refs", str(p)])
    assert rc != 0
    assert "ref_id" in capsys.readouterr().err or "a" in capsys.readouterr().err


def test_case_issue_is_excluded_and_counted_separately_from_unsure():
    """「用例本身有问题」与「人说不清」是**两回事** —— 前者是在说**用例的毛病**,
    后者是在说**标注人的困难**。混在一个计数里,就会丢掉那条反馈。
    """
    out = compute_agreement([_item("a", True, "pass"),
                             {"ref_id": "b", "human": "case_issue", "judge_verdict": "fail"},
                             _item("c", "unsure", "flag"),
                             _item("d", False, "fail")])
    assert out["n_case_issue"] == 1
    assert out["n_unsure"] == 1
    assert out["n_labeled"] == 2
    assert out["agreement"] == 1.0
    # 被剔除的条 id 要报出来,否则"剔了谁"无从复核
    assert out["excluded_ids"] == ["b", "c"]


# ── 阈值接线(M1:让真值有地方落;但**不**顺手变成阻断项)──────────
from eval_gate.runner import default_thresholds, load_thresholds  # noqa: E402


def _thr_file(tmp_path, doc):
    p = tmp_path / "阈值.json"
    p.write_text(_json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_judge_agreement_threshold_is_recorded_at_top_level(tmp_path):
    """M1 判据:真值要落在**顶层**(= 被 runner 真正读到的位置),不能还躺在 `_doc_only`。"""
    p = _thr_file(tmp_path, {"l2_task_completion": {"min": 0.8}, "redteam_zero": True,
                             "judge_human_agreement": {"min": 0.8},
                             "_doc_only": {"_note": "x"}})
    thr = load_thresholds(p)
    assert thr is not None and thr["judge_human_agreement"] == {"min": 0.8}
    assert "_doc_only" not in thr, "`_` 前缀的注释块不得混进运行阈值"


def test_malformed_judge_agreement_falls_back_stricter_not_wider(tmp_path, capsys):
    """写坏了要**回落更严兜底**,不得静默忽略 —— 与其它阈值的纪律一致。"""
    p = _thr_file(tmp_path, {"judge_human_agreement": {"min": "很高"}, "redteam_zero": True})
    assert load_thresholds(p) is None
    assert "形状不合法" in capsys.readouterr().err


def test_judge_agreement_does_not_block_yet(tmp_path):
    """⚠️ **守未决项**:一致率目前**不是阻断项**(DEC-008 §5 待签核)。

    若哪天它开始阻断,这条会变红 —— 那时应该先有 DEC,而不是悄悄生效。
    """
    p = _thr_file(tmp_path, {"l2_task_completion": {"min": 0.8}, "redteam_zero": True,
                             "judge_human_agreement": {"min": 0.99}})
    thr = default_thresholds(p)
    assert thr["l2_task_completion"]["min"] == 0.8
    assert thr["judge_human_agreement"]["min"] == 0.99   # 值被读到(记录在案)
    assert set(thr) - {"l2_task_completion", "redteam_zero", "judge_human_agreement"} == set()


# ── `--fail-on-below`:可选的阻断开关(DEC-008 §5:不默认接进任何自动门)──
def test_fail_on_below_returns_nonzero_when_below_min(tmp_path, monkeypatch, capsys):
    """开了开关且低于 min ⇒ exit 1。默认**不开**;是否拦门由使用方决定。"""
    _stub_judge(monkeypatch)
    p = _refs_file(tmp_path)          # 桩判分器得 2/3 ≈ 0.67(< 0.80)
    rc = cli.main(["calibrate", "--refs", str(p), "--fail-on-below"])
    assert rc == 1
    assert "未达标" in capsys.readouterr().out


def test_fail_on_below_passes_when_at_or_above_min(tmp_path, monkeypatch):
    _stub_judge(monkeypatch)
    # 把 d(那条误杀)标成"不满足" ⇒ 3/3 = 1.00
    refs = _json.loads(_refs_file(tmp_path).read_text(encoding="utf-8"))
    refs["refs"][3]["human"] = False
    p = tmp_path / "ok.json"
    p.write_text(_json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["calibrate", "--refs", str(p), "--fail-on-below"]) == 0


def test_fail_on_below_is_fail_closed_without_labels(tmp_path, monkeypatch, capsys):
    """**算不出来 ≠ 通过** —— 与阈值读不到就回落更严同一条纪律(不放宽门)。"""
    _stub_judge(monkeypatch)
    p = tmp_path / "none.json"
    p.write_text(_json.dumps({"refs": [
        {"ref_id": "a", "question": "q", "expected": {"answer_contains": ["x"]},
         "sut_answer": "x", "human": None}]}, ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["calibrate", "--refs", str(p), "--fail-on-below"])
    assert rc == 1
    assert "无法计算" in capsys.readouterr().out


def test_without_the_flag_it_never_blocks(tmp_path, monkeypatch):
    """⚠️ 守"**默认不阻断**"这条未决决定:DEC-008 §5 只把开关做出来,不接进任何自动门。"""
    _stub_judge(monkeypatch)
    assert cli.main(["calibrate", "--refs", str(_refs_file(tmp_path))]) == 0
