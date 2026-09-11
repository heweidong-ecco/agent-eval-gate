"""E7 报告辅助函数测试(`app/eval_gate/report.py`)。

`format_duration` 把秒数渲染成给人读的时长串,供报告/日志展示:
秒级不加前缀(`45` → `45s`),跨分钟用 `XmYs`(`90` → `1m30s`)。
口径固定为「分+秒并存」,不做 60 的进位省略 —— 时长串要能一眼看出精度。

`format_ratio` 把 0..1 的比率渲染成百分比串(`0.85` → `85%`)。
口径:整数百分比不带小数点;真有小数的比率保留小数(不四舍五入成整数);
浮点乘 100 的噪声要吃掉(`0.07` → `7%`,不是 `7.000000000000001%`)。
"""
from eval_gate import report


def test_format_duration_under_a_minute_stays_in_seconds():
    assert report.format_duration(45) == "45s"
    assert report.format_duration(59) == "59s"
    assert report.format_duration(0) == "0s"


def test_format_duration_at_or_over_a_minute_uses_minutes_and_seconds():
    assert report.format_duration(60) == "1m0s"   # 边界:恰好一分钟,秒位仍显式补 0
    assert report.format_duration(90) == "1m30s"
    assert report.format_duration(125) == "2m5s"


def test_format_ratio_renders_whole_percents_without_decimal_point():
    assert report.format_ratio(0.85) == "85%"
    assert report.format_ratio(0.5) == "50%"
    assert report.format_ratio(0.0) == "0%"
    assert report.format_ratio(1.0) == "100%"   # 边界:上界不该渲染成 "1%"


def test_format_ratio_does_not_leak_binary_float_noise():
    # 0.07 * 100 在二进制浮点下是 7.000000000000001,不能漏进展示串
    assert report.format_ratio(0.07) == "7%"
    assert report.format_ratio(0.29) == "29%"


def test_format_ratio_keeps_fractional_percents():
    assert report.format_ratio(0.855) == "85.5%"   # 真小数保留,不退化成整数
