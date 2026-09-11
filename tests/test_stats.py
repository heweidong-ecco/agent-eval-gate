"""统计原语对账:与发表临界值比、与定义式枚举比、与极限情形比。

依据:B 05-模块-评估与测试:70(统计回归:A/B 各跑 N 次,p-value + 效应量)。
"""
import pytest

from eval_gate.stats import ab_verdict, cohens_d, mannwhitney_u


# ── 与发表临界值对账(n1=n2=5,双侧)──────────────────────────
def test_published_critical_value_fully_separated():
    """完全分离(U=0):双侧 p = 2/252 ≈ 0.00794。"""
    u, p = mannwhitney_u([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
    assert u == 0.0
    assert p == pytest.approx(2 / 252, rel=1e-9)


def test_published_critical_value_one_crossing():
    """一个交叉:合并秩 = 1,2,3,4,4.5,5,6,7,8,9 → arm A 秩和 16 → U_a = 1。"""
    u, p = mannwhitney_u([1, 2, 3, 4, 5], [4.5, 6, 7, 8, 9])
    assert u == pytest.approx(1.0)
    assert p < 0.05          # 双侧 p = 4/252 ≈ 0.0159


def test_identical_samples_have_no_difference():
    xs = [1.0, 2, 3, 4, 5]
    u, p = mannwhitney_u(xs, list(xs))
    assert p == pytest.approx(1.0)
    assert u > 0


def test_all_tied_values_yield_p_one():
    """全并列(零方差且均值相同)—— p 必须是 1.0,不能 NaN/崩。"""
    _, p = mannwhitney_u([0.9] * 10, [0.9] * 10)
    assert p == pytest.approx(1.0)


def test_exact_path_matches_definitional_enumeration():
    """精确路径 = 定义式:独立枚举所有标签置换,数**单尾** U_a ≤ u_min 再乘 2。

    单尾这一点极易搞错(把两尾并起来数、外面又乘 2 = 多乘一倍),
    故另有 test_published_critical_value_fully_separated 用发表值锚定。
    """
    from itertools import combinations
    from math import comb

    a = [1.0, 4, 5, 7, 9]
    b = [2.0, 3, 6, 8, 10]
    combined = a + b
    n_a, n = len(a), len(combined)
    n_b = n - n_a

    # 独立实现:无并列,故秩 = 排序位置 + 1(不走被测的「平均秩」代码路径)
    order = sorted(range(n), key=lambda i: combined[i])
    ranks = [0.0] * n
    for pos, i in enumerate(order):
        ranks[i] = pos + 1
    u_a_obs = sum(ranks[:n_a]) - n_a * (n_a + 1) / 2
    u_min = min(u_a_obs, n_a * n_b - u_a_obs)

    total = comb(n, n_a)
    hits = 0
    for idx in combinations(range(n), n_a):
        ua = sum(ranks[i] for i in idx) - n_a * (n_a + 1) / 2
        if ua <= u_min + 1e-9:
            hits += 1
    expected = min(1.0, 2 * hits / total)

    _, p = mannwhitney_u(a, b)
    assert p == pytest.approx(expected, rel=1e-9)


def test_normal_approximation_path_above_exact_limit():
    """n=20/20 → C(40,20) 远超精确上限,走正态近似;U_min 与 p 都要合理。"""
    a = [float(i) for i in range(1, 21)]           # 均值 10.5
    b = [float(i) for i in range(11, 31)]          # 均值 20.5
    u, p = mannwhitney_u(a, b)
    assert u == pytest.approx(50.0)                # 11..20 各并列一次,秩同
    assert 0.0 <= p < 0.05


def test_p_value_is_direction_symmetric():
    a = [float(i) for i in range(20)]
    b = [float(i) + 5 for i in range(20)]
    assert mannwhitney_u(a, b)[1] == pytest.approx(mannwhitney_u(b, a)[1])


def test_empty_or_single_sample_is_guarded():
    assert mannwhitney_u([], [1.0])[1] == 1.0
    assert mannwhitney_u([1.0], [1.0])[1] == 1.0


# ── Cohen's d ───────────────────────────────────────────────
def test_cohens_d_sign_means_candidate_below_baseline():
    """符号约定:正数 = candidate 退化(回归臂均值更大)。"""
    assert cohens_d([1.0, 2, 3], [10.0, 11, 12]) < 0
    assert cohens_d([10.0, 11, 12], [1.0, 2, 3]) > 0


def test_cohens_d_known_magnitude():
    """教科书算例:d = (11-8)/2 = 1.5(两组各自方差 4 → 合并 SD = 2)。"""
    assert cohens_d([9.0, 11, 13], [6.0, 8, 10]) == pytest.approx(1.5)


def test_cohens_d_equal_samples_is_zero():
    assert cohens_d([1.0, 2, 3], [1.0, 2, 3]) == pytest.approx(0.0)


def test_cohens_d_undefined_when_both_arms_constant():
    """两组都零方差 → 合并标准差为 0,**效应量未定义**(返回 None,不是 0)。

    返回 0.0 会把「稳定的 10pp 退化」伪装成「无差异」—— 判定层必须能区分
    「效应量 = 0」与「效应量无法计算」(见 ab_verdict 的回落规则)。
    """
    assert cohens_d([5.0] * 5, [5.0] * 5) is None


def test_cohens_d_undefined_for_tiny_samples():
    assert cohens_d([1.0], [2.0, 3.0]) is None


# ── 判定口径(先定后看)────────────────────────────────────
def test_constant_arms_with_different_means_are_flagged():
    """零方差 + 均值不同 = 完全分离 → 必须判**退化**,不能被效应量闸门放过。"""
    v = ab_verdict([0.90] * 8, [0.80] * 8)
    assert v["p"] < 0.05
    assert v["d"] is None and v["effect_defined"] is False
    assert v["verdict"] == "regressed"


def test_constant_arms_with_same_means_are_no_difference():
    v = ab_verdict([0.90] * 8, [0.90] * 8)
    assert v["p"] == pytest.approx(1.0) and v["verdict"] == "no_difference"


def test_improvement_is_reported_as_improved():
    """反向同样要认:候选比基线好 → improved(不是 regressed)。"""
    assert ab_verdict([0.80] * 8, [0.90] * 8)["verdict"] == "improved"


def test_improvement_with_defined_effect_size():
    """效应量**有定义**时的 improved 分支(常数臂走的是另一条回落路径)。"""
    import random
    rng = random.Random(3)
    base = [0.70 + rng.uniform(-0.05, 0.05) for _ in range(20)]
    cand = [0.90 + rng.uniform(-0.05, 0.05) for _ in range(20)]
    v = ab_verdict(base, cand)
    assert v["d"] < -0.2 and v["verdict"] == "improved"


def test_all_tied_large_sample_uses_normal_path_and_returns_p_one():
    """n=30 全并列 → 走正态近似,且并列校正把 sigma 压到 0 → p = 1(不得除零崩)。"""
    _, p = mannwhitney_u([0.9] * 15, [0.9] * 15)
    assert p == pytest.approx(1.0)


def test_verdict_flags_regression_when_significant_and_large():
    import random
    rng = random.Random(7)
    base = [0.90 + rng.uniform(-0.05, 0.05) for _ in range(20)]
    cand = [0.70 + rng.uniform(-0.05, 0.05) for _ in range(20)]
    v = ab_verdict(base, cand)
    assert v["p"] < 0.05 and v["d"] > 0.2 and v["verdict"] == "regressed"


def test_tiny_effect_is_not_a_change_even_when_significant():
    """效应量闸门:均值差相对波动极小时不得判退化(否则大 N 下噪声会天天报警)。

    构造是**确定性的**(不用随机数):两臂各 50 点,交替 ±0.05(sd = 0.05),
    候选相对基线整体下移 0.002 → d = 0.04 < 0.2,但两臂间距极稳定 → p 很小。
    这正是闸门要拦的情形:显著 ≠ 有实际意义。
    """
    base = [0.95 if i % 2 == 0 else 0.85 for i in range(50)]
    cand = [x - 0.002 for x in base]
    v = ab_verdict(base, cand)
    assert v["p"] < 0.05, "构造应显著(否则本用例证明不了闸门)"
    assert v["d"] is not None and abs(v["d"]) < 0.2
    assert v["verdict"] == "no_difference"


def test_verdict_reports_sample_sizes():
    v = ab_verdict([1.0, 2, 3, 4], [5.0, 6, 7])
    assert v["n_a"] == 4 and v["n_b"] == 3
