"""设备侧协议。

真实设备适配器与虚拟设备实现同一个协议；MCP 设备面只依赖本协议，
不关心背后是电机、气泵还是纯模拟。
"""

from __future__ import annotations

from typing import Protocol

from .contract import (
    ActionRequest,
    DeviceActionResult,
    DeviceCapabilities,
    DeviceEvent,
    DeviceState,
    MediaItem,
    StopResult,
)


class Device(Protocol):
    @property
    def device_id(self) -> str: ...

    def capabilities(self) -> DeviceCapabilities: ...

    def status(self) -> DeviceState: ...

    def execute(self, request: ActionRequest) -> DeviceActionResult: ...

    def set_mode(self, mode_id: str, level: int, duration_s: int) -> DeviceActionResult: ...

    def set_level(self, level: int) -> DeviceActionResult: ...

    def stop(
        self, source: str = "agent"
    ) -> StopResult: ...

    def media(self, limit: int = 10) -> list[MediaItem]: ...

    def poll_events(self, cursor: int = 0) -> tuple[list[DeviceEvent], int]: ...
