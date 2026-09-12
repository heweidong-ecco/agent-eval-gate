"""E7 judge 校准:judge-人工一致率(`judge_human_agreement`,M1 / DEC-008)。

契约 `contracts/评测-judge.md:47`:「judge 判定 ↔ golden 人工标签 → 一致率」。

**为什么需要它**:在此之前,门的结论**没有外部锚** —— 判分器判对了没有、判严了没有,
全靠门自己"觉得"。一致率是那根锚:判分器的判定与**人**的判定差多远。

三条口径(都是刻意的,不是随手定的):

1. **只统计真被标注的条目**。未标注(`human: null`)与「说不清」**整条剔除**并单独报数 ——
   尤其是「说不清」:它是**允许的诚实答案**,把它算成"不一致"等于惩罚诚实,人会开始瞎猜;
   把它算成"一致"又会把指标灌水。**剔除 + 报数**是唯一诚实的做法(报数才知道覆盖够不够)。
2. **`judge_human_agreement` = "judge 判 pass" ↔ "人工判满足"**。
3. **flag 单独计**:它既不是"判对"也不是"判错",而是"判分器自己也没定"。
   主指标里 flag 按 **非 pass** 计入 —— 它确实不让该条通过,人**还得看一遍**,这就是它的成本;
   另给一个把 flag 整个剔除的副指标 `agreement_excl_flag`,用来看**纯 pass/fail** 判得准不准。
"""
from __future__ import annotations

# 「说不清」的合法写法(中英)。标注表里允许人写中文。
_UNSURE = {"unsure", "uncertain", "说不清", "不确定", "拿不准"}
# 「用例本身有问题」= **第三种剔除理由**,与「说不清」**不能并成一类**:
# 前者在说**用例的毛病**(要回灌到评测集),后者在说**标注人的困难**。
_CASE_ISSUE = {"case_issue", "用例问题", "用例本身有问题"}


def _is_unsure(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _UNSURE


def _is_case_issue(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _CASE_ISSUE


def compute_agreement(items: list[dict]) -> dict:
    """`items` 每条形如 `{"ref_id", "human", "judge_verdict"}`。

    `human`:`True` 满足(应判 pass)/ `False` 不满足 / `None` 未标注 / `"说不清"`。
    返回各项计数与两个一致率;一条都没标 ⇒ 一致率为 `None`(**不是 0.0** ——
    0.0 会被读成"判分器全错")。
    """
    n_labeled = n_agree = n_unlabeled = n_unsure = n_case_issue = 0
    n_flag = n_false_neg = n_false_pos = 0        # 误杀 / 漏放
    n_excl = n_excl_agree = 0
    detail: list[dict] = []
    excluded_ids: list[str] = []

    for it in items:
        human = it.get("human")
        if human is None:
            n_unlabeled += 1
            continue
        if _is_case_issue(human):
            n_case_issue += 1
            excluded_ids.append(it.get("ref_id"))
            continue
        if _is_unsure(human):
            n_unsure += 1
            excluded_ids.append(it.get("ref_id"))
            continue

        verdict = it.get("judge_verdict")
        judge_pass = verdict == "pass"
        human_ok = bool(human)
        agree = judge_pass == human_ok

        n_labeled += 1
        n_agree += 1 if agree else 0
        if verdict == "flag":
            n_flag += 1
        else:
            n_excl += 1
            n_excl_agree += 1 if agree else 0
        if not agree:
            if human_ok:
                n_false_neg += 1      # 答对了却被判不通过(误杀)
            else:
                n_false_pos += 1      # 答错了却被判通过(漏放)
        detail.append({"ref_id": it.get("ref_id"), "human": human_ok,
                       "judge_verdict": verdict, "agree": agree})

    return {
        "n_total": len(items),
        "n_labeled": n_labeled,
        "n_unlabeled": n_unlabeled,
        "n_unsure": n_unsure,
        "n_case_issue": n_case_issue,
        "excluded_ids": excluded_ids,
        "n_agree": n_agree,
        "agreement": (n_agree / n_labeled) if n_labeled else None,
        "n_flag": n_flag,
        "n_excluded_from_secondary": n_flag,
        "agreement_excl_flag": (n_excl_agree / n_excl) if n_excl else None,
        "n_false_negative": n_false_neg,
        "n_false_positive": n_false_pos,
        "detail": detail,
    }
