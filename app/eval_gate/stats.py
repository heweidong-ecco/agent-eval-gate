"""A/B 统计回归原语(Mann-Whitney U + Cohen's d)。**纯标准库,零依赖。**

依据:B `05-独立模块工作流/05-模块-评估与测试-v1.0.md:70`「统计回归测试:A/B 各跑 N 次,
用 p-value(Mann-Whitney U)与效应量(Cohen's d)判变化」+ 本仓 `eval/README.md:24`。

口径(先定后看,不得事后调整):
- **U 取 min(U_a, U_b)**(对称分布下双向检验用),p 为**双侧**;
- 组合数 `C(n_a+n_b, n_a) ≤ EXACT_LIMIT` → **精确枚举**(定义式,含并列);
  否则 → **正态近似**(连续性校正 + 并列校正);
- **符号约定**:`cohens_d(baseline, candidate) > 0` 表示 **candidate 低于 baseline = 退化**;
- 判定要**同时**满足 `p < alpha` 与 `|d| ≥ min_effect` —— 大 N 下微小差异也会显著,
  只看 p 会把噪声判成退化;
- **零方差特例**(离线确定性跑批的常态):两组各自恒定 → 合并标准差为 0 → 效应量
  **未定义**(返回 `None`,**不是 0**)。返回 0 会把「稳定的 10pp 退化」伪装成「无差异」;
  此时判定回落到「显著 + 均值差方向」(见 `ab_verdict`)。

不引入 scipy:运行时零依赖是本仓红线(`app/eval_gate/judge.py` 同一原则)。
"""
from __future__ import annotations

from itertools import combinations
from math import comb, erf, sqrt
from typing import Sequence

# 精确枚举的组合数上限(≈0.5M 次纯 Python 循环,秒级)
EXACT_LIMIT = 500_000

# 合并标准差 ≤ 此**相对**阈值 → 视为零方差。浮点下「十个 0.90」的方差不是 0 而是 ~1e-32,
# 直接判 `sp2 <= 0` 会漏掉,于是 d 炸成 1e15 而不是「未定义」。真实 A/B 的 sd 远大于此。
_ZERO_SD_REL = 1e-9


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _ranks(values: Sequence[float]) -> list[float]:
    """平均秩(并列取平均)。返回与 values 同序的秩列表。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _u_a_perm(ranks: Sequence[float], idx: tuple[int, ...], n_a: int) -> float:
    """给定 arm A 的下标组合,算 U_a(精确枚举用)。

    ⚠️ 必须算**单尾**统计量 U_a,不能算 `min(U_a, U_b)` —— 精确 p 的公式是
    `2 × P(U_a ≤ u_min)`,其中 `u_min = min(U_a观察, U_b观察)`。
    若枚举时已把两尾并起来计数、外面再乘 2,就**多乘了一倍**
    (发表临界值 n=5/5、U=0 应为 `2/252`;错法会给出 `4/252`)。
    """
    return sum(ranks[i] for i in idx) - n_a * (n_a + 1) / 2


def _u_min(ranks: Sequence[float], n_a: int) -> float:
    """由 arm A 的秩和算 U_a 与 U_b,取较小者(ranks 前 n_a 项属于 arm A)。"""
    n_b = len(ranks) - n_a
    u_a = sum(ranks[:n_a]) - n_a * (n_a + 1) / 2
    return min(u_a, n_a * n_b - u_a)


def _phi(z: float) -> float:
    """标准正态 CDF。"""
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def _tie_corrected_sigma2(ranks: Sequence[float], n_a: int) -> float:
    """并列校正后的 U 方差(无并列时退化为 n_a*n_b*(n+1)/12)。"""
    n = len(ranks)
    if n < 2:
        return 0.0
    tie_sum = 0.0
    srt = sorted(ranks)
    i = 0
    while i < len(srt):
        j = i
        while j + 1 < len(srt) and srt[j + 1] == srt[i]:
            j += 1
        t = j - i + 1
        tie_sum += t ** 3 - t
        i = j + 1
    n_b = n - n_a
    return (n_a * n_b / 12.0) * ((n + 1) - tie_sum / (n * (n - 1)))


def mannwhitney_u(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """返回 `(U_min, p_two_sided)`。任一组样本数 < 2 → `(0.0, 1.0)`(无证据即无差异)。"""
    a, b = list(a), list(b)
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0
    ranks = _ranks(a + b)
    u = _u_min(ranks, n_a)
    n = n_a + n_b

    if comb(n, n_a) <= EXACT_LIMIT:
        hits = 0
        for idx in combinations(range(n), n_a):
            if _u_a_perm(ranks, idx, n_a) <= u + 1e-9:
                hits += 1
        # 单尾计数 × 2 = 双侧(分布对称;u 已取 min,故上尾等价于下尾)
        return u, min(1.0, 2.0 * hits / comb(n, n_a))

    sigma2 = _tie_corrected_sigma2(ranks, n_a)
    if sigma2 <= 0:
        return u, 1.0
    z = (u + 0.5 - n_a * n_b / 2.0) / sqrt(sigma2)   # 连续性校正
    return u, min(1.0, 2.0 * _phi(z))


def cohens_d(baseline: Sequence[float], candidate: Sequence[float]) -> float | None:
    """合并标准差效应量。**正数 = candidate 低于 baseline(退化)**。

    **返回 None 表示效应量未定义**:任一组样本数 < 2,或合并标准差为 0
    (两组各自恒定)。此时不能假装 d = 0 —— 那会把稳定的差异伪装成「无差异」。
    """
    a, b = list(baseline), list(candidate)
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return None
    va = sum((x - _mean(a)) ** 2 for x in a) / (n_a - 1)
    vb = sum((x - _mean(b)) ** 2 for x in b) / (n_b - 1)
    sp2 = ((n_a - 1) * va + (n_b - 1) * vb) / (n_a + n_b - 2)
    ma, mb = _mean(a), _mean(b)
    scale = max(abs(ma), abs(mb), 1e-12)
    if sp2 <= 0 or sqrt(sp2) <= _ZERO_SD_REL * scale:
        return None
    return (ma - mb) / sqrt(sp2)


def ab_verdict(a: Sequence[float], b: Sequence[float],
               alpha: float = 0.05, min_effect: float = 0.2) -> dict:
    """A/B 判定:`a` = 基线臂,`b` = 候选臂。

    返回 `{"u","p","d","verdict","n_a","n_b","effect_defined"}`;
    `verdict ∈ {regressed, improved, no_difference}`。

    - 效应量**有定义**时:需 `p < alpha` **且** `|d| ≥ min_effect` 才判变化;
    - 效应量**未定义**时(两组都零方差):回落到「`p < alpha` **且均值不同**」,
      按均值差方向判 —— 完全分离的两臂必须被判出来,不能被闸门放过。
    """
    a, b = list(a), list(b)
    u, p = mannwhitney_u(a, b)
    d = cohens_d(a, b)
    ma = _mean(a) if a else 0.0
    mb = _mean(b) if b else 0.0

    if d is None:
        effect_defined = False
        if p < alpha and ma != mb:
            verdict = "regressed" if ma > mb else "improved"
        else:
            verdict = "no_difference"
    else:
        effect_defined = True
        if p < alpha and d >= min_effect:
            verdict = "regressed"
        elif p < alpha and d <= -min_effect:
            verdict = "improved"
        else:
            verdict = "no_difference"

    return {"u": u, "p": p, "d": d, "verdict": verdict,
            "n_a": len(a), "n_b": len(b), "effect_defined": effect_defined}
