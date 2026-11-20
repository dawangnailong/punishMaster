"""可注入时钟。

所有"计时"都是虚拟时间：沙漏、幕间休息、会话过期都基于注入的 Clock 惰性求值，
不存在任何真实后台线程或定时器。这保证了：

1. 停止/紧急停止后不存在继续触发的后台任务（结构上不可能存在）；
2. 测试可以用 FakeClock 快进，replay 可以完全确定地重现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """时钟抽象：导演层唯一的时间来源。"""

    def now(self) -> datetime: ...


class SystemClock:
    """真实系统时钟（生产默认）。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """可任意快进的假时钟（测试 / 演示用）。"""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)
