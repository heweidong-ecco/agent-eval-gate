"""E7 报告辅助函数测试(`app/eval_gate/report.py`)。

`format_duration` 把秒数渲染成给人读的时长串,供报告/日志展示:
秒级不加前缀(`45` → `45s`),跨分钟用 `XmYs`(`90` → `1m30s`)。
口径固定为「分+秒并存」,不做 60 的进位省略 —— 时长串要能一眼看出精度。
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
