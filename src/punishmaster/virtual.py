"""虚拟设备：在 MCP 视角下与未来真实设备行为等价的实现。

它不是渲染器，也不是翻译层。它实现 ``device.Device`` 契约：
能力声明、语义执行、模式/档位、状态、停止、事件、可选影像。

安全模型：
- 设备自己消费内部数据，随时准备自动停止（本实现用运行时长作为演示）；
- 停止有四个来源：agent / hardware（物理按钮）/ safety（本地策略）/ timer；
- 只在接近本地安全上限时向上游发 ``reasoning_request`` 事件；
- 原始内部数值不出现在任何上行结构中，只给语义反馈。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .contract import (
    ActionCategory,
    ActionRequest,
    DeviceActionResult,
    DeviceCapabilities,
    DeviceEvent,
    DeviceState,
    MediaItem,
    Mode,
    Realization,
    SemanticAction,
    StopResult,
)
from .ontology import CORE_ACTIONS

_SOURCE_MESSAGES = {
    "agent": "Agent 停止指令：已停止。",
    "hardware": "硬件停止按钮触发：已停止。",
    "safety": "本地安全策略：已自动停止。",
    "timer": "本次动作已到时结束。",
}


class VirtualDevice:
    """一台模拟的气压吮吸设备；接口对真实设备等价。"""

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        max_on_s: float = 1800.0,
    ) -> None:
        self._clock = clock or time.monotonic
        self._max_on_s = float(max_on_s)
        self._device_id = "sim-cup-01"
        self._level_max = 8

        self._running = False
        self._current_action: str | None = None
        self._current_mode: str | None = None
        self._level = 3
        self._feedback = "空闲；等待语义动作。"
        self._safety = "ok"
        self._fault: str | None = None
        self._started_at: float | None = None
        self._ends_at: float | None = None
        self._reasoning_requested = False

        self._events: list[DeviceEvent] = []
        self._cursor = 0

        self._caps = self._build_capabilities()
        self._actions = {a.action_id: a for a in self._caps.semantic_actions}
        self._modes = {m.mode_id: m for m in self._caps.modes}

    @property
    def device_id(self) -> str:
        return self._device_id

    # ---------------------------------------------------------------- 能力

    def _build_capabilities(self) -> DeviceCapabilities:
        def core(action_id: str, realization: Realization, **over: Any) -> SemanticAction:
            spec = CORE_ACTIONS[action_id]
            return SemanticAction(
                action_id=action_id,
                label=spec.label,
                category=ActionCategory(spec.category),
                realization=realization,
                description=over.pop("description", spec.description),
                params_schema=over.pop("params_schema", spec.params_schema),
                mapped_mode_id=over.pop("mapped_mode_id", None),
                **over,
            )

        actions = [
            core("stimulate", Realization.NATIVE),
            core("tease", Realization.MODE_MAPPING, mapped_mode_id="gentle"),
            core("hold", Realization.NATIVE),
            core("release", Realization.NATIVE),
            core(
                "check",
                Realization.UNSUPPORTED,
                description="本虚拟设备不具备检查能力；显式拒绝，不产生任何物理动作。",
                params_schema={},
            ),
            core("rest", Realization.NATIVE),
            core("stop", Realization.NATIVE),
            # 厂商扩展：核心本体之外的 action_id，仍走同一契约。
            SemanticAction(
                action_id="deep_suck",
                label="深部吮吸（厂商扩展）",
                category=ActionCategory.STIMULATE,
                realization=Realization.MODE_MAPPING,
                mapped_mode_id="deep",
                description="厂商扩展动作：映射到设备原生 deep 模式。",
            ),
        ]
        modes = [
            Mode(mode_id="gentle", label="轻吮", description="最轻档，点到即止。", level_max=4),
            Mode(mode_id="wave", label="起伏", description="节奏式一收一放。", level_max=6),
            Mode(mode_id="squeeze", label="夹吸", description="紧致包裹。", level_max=7),
            Mode(mode_id="deep", label="深部", description="最深档，仅限明确允许时使用。", level_max=8),
        ]
        return DeviceCapabilities(
            device_id=self._device_id,
            device_class="suction_cup",
            label="模拟气压吮吸器具（虚拟设备）",
            simulated=True,
            level_max=self._level_max,
            semantic_actions=actions,
            modes=modes,
            supports_media=False,
            safety={
                "local_auto_stop": True,
                "physical_stop_button": True,
                "agent_stop": True,
                "max_on_s": int(self._max_on_s),
                "raw_sensor_data_exposed": False,
                "reasoning_request": True,
            },
        )

    def capabilities(self) -> DeviceCapabilities:
        return self._caps.model_copy(deep=True)

    # ---------------------------------------------------------------- 状态

    def status(self) -> DeviceState:
        self._tick()
        remaining = 0
        if self._running and self._ends_at is not None:
            remaining = max(0, int(round(self._ends_at - self._clock())))
        return DeviceState(
            device_id=self._device_id,
            simulated=True,
            running=self._running,
            current_action=self._current_action,
            current_mode=self._current_mode,
            level=self._level,
            remaining_s=remaining,
            feedback=self._feedback,
            safety=self._safety,
            fault=self._fault,
        )

    # ---------------------------------------------------------------- 执行

    def execute(self, request: ActionRequest) -> DeviceActionResult:
        self._tick()
        action = self._actions.get(request.action_id)
        if action is None:
            return self._unsupported(request, "设备没有声明这个动作")
        if action.realization == Realization.UNSUPPORTED:
            return self._unsupported(request, "设备声明为 unsupported")
        if request.level < 1 or request.level > self._level_max:
            return self._invalid(
                "LEVEL_OUT_OF_RANGE",
                f"档位 {request.level} 超出设备范围 1..{self._level_max}",
                action.realization,
            )
        if request.duration_s > self._max_on_s:
            return self._invalid(
                "DURATION_EXCEEDED",
                f"时长 {request.duration_s}s 超出设备本地上限 {int(self._max_on_s)}s",
                action.realization,
            )

        if request.action_id in ("stop", "release"):
            result = self.stop(source="agent")
            prefix = "已停止。" if request.action_id == "stop" else "已释放/停止。"
            return DeviceActionResult(
                device_id=self._device_id,
                simulated=True,
                accepted=True,
                executed=result.executed,
                supported=True,
                realization=action.realization,
                message=f"语义动作 `{request.action_id}`：{prefix}{result.message}",
                state=result.state,
            )

        if action.realization == Realization.MODE_MAPPING:
            if not action.mapped_mode_id:
                return self._unsupported(request, "mode_mapping 未声明 mapped_mode_id")
            result = self.set_mode(
                action.mapped_mode_id, request.level, request.duration_s
            )
            if result.accepted:
                result.message = (
                    f"语义动作 `{action.action_id}` 通过模式 "
                    f"`{action.mapped_mode_id}` 执行。{result.message}"
                )
            return result

        feedback = self._feedback_for(action, request)
        self._start(action.action_id, None, request.level, request.duration_s, feedback)
        return DeviceActionResult(
            device_id=self._device_id,
            simulated=True,
            accepted=True,
            executed=True,
            supported=True,
            realization=action.realization,
            message=(
                f"已执行语义动作 `{action.action_id}`：{feedback}。"
                "本设备为模拟设备，无真实接触。"
            ),
            state=self.status(),
        )

    def set_mode(
        self, mode_id: str, level: int = 3, duration_s: int = 0
    ) -> DeviceActionResult:
        self._tick()
        mode = self._modes.get(mode_id)
        if mode is None:
            message = f"设备没有模式 `{mode_id}`（unsupported）；未发生任何物理动作。"
            return DeviceActionResult(
                device_id=self._device_id,
                simulated=True,
                accepted=False,
                executed=False,
                supported=False,
                realization=Realization.UNSUPPORTED,
                message=message,
                state=self.status(),
                error={"code": "MODE_NOT_FOUND", "message": message},
            )
        effective_max = min(mode.level_max, self._level_max)
        if level < 1 or level > effective_max:
            return self._invalid(
                "LEVEL_OUT_OF_RANGE",
                f"模式 `{mode_id}` 的档位范围是 1..{effective_max}",
                Realization.MODE_MAPPING,
            )
        if duration_s > self._max_on_s:
            return self._invalid(
                "DURATION_EXCEEDED",
                f"时长 {duration_s}s 超出设备本地上限 {int(self._max_on_s)}s",
                Realization.MODE_MAPPING,
            )
        self._start(None, mode.mode_id, level, duration_s, f"模式 {mode.label}")
        return DeviceActionResult(
            device_id=self._device_id,
            simulated=True,
            accepted=True,
            executed=True,
            supported=True,
            realization=Realization.MODE_MAPPING,
            message=(
                f"已切换到模式 `{mode.mode_id}`（{mode.label}），档位 {level}。"
                "本设备为模拟设备，无真实接触。"
            ),
            state=self.status(),
        )

    def set_level(self, level: int) -> DeviceActionResult:
        if level < 1 or level > self._level_max:
            return self._invalid(
                "LEVEL_OUT_OF_RANGE",
                f"档位 {level} 超出设备范围 1..{self._level_max}",
                Realization.NATIVE,
            )
        changed = level != self._level
        self._level = level
        if self._running:
            self._feedback = f"档位调整为 {level}"
        return DeviceActionResult(
            device_id=self._device_id,
            simulated=True,
            accepted=True,
            executed=changed,
            supported=True,
            realization=Realization.NATIVE,
            message=f"档位已调整为 {level}。本设备为模拟设备，无真实接触。",
            state=self.status(),
        )

    def stop(self, source: str = "agent") -> StopResult:
        self._tick()
        if not self._running:
            return StopResult(
                device_id=self._device_id,
                simulated=True,
                accepted=True,
                executed=False,
                source=source,  # type: ignore[arg-type]
                message="设备已是停止状态（幂等）；没有额外动作。",
                state=self.status(),
            )
        message = _SOURCE_MESSAGES.get(source, "已停止。")
        self._stop_internal(source, message)
        if source == "safety":
            self._emit("safety", "本地安全策略触发：设备已自动停止。")
        return StopResult(
            device_id=self._device_id,
            simulated=True,
            accepted=True,
            executed=True,
            source=source,  # type: ignore[arg-type]
            message=message,
            state=self.status(),
        )

    def physical_stop(self) -> StopResult:
        """模拟硬件侧物理停止按钮；不通过 MCP 暴露。"""
        return self.stop(source="hardware")

    # ---------------------------------------------------------------- 反馈

    def media(self, limit: int = 10) -> list[MediaItem]:
        # 当前虚拟设备不产出影像；真实设备可在此返回图片/视频引用。
        return []

    def poll_events(self, cursor: int = 0) -> tuple[list[DeviceEvent], int]:
        self._tick()
        events = [e for e in self._events if e.cursor > cursor][:50]
        return events, self._cursor

    # ---------------------------------------------------------------- 内部

    def _feedback_for(self, action: SemanticAction, request: ActionRequest) -> str:
        if action.action_id == "rest":
            return "暖意包裹、休息"
        if action.action_id == "hold":
            return "保持当前状态"
        bits: list[str] = []
        depth = request.params.get("depth")
        rhythm = request.params.get("rhythm")
        warmth = request.params.get("warmth")
        if depth == "deep":
            bits.append("深部")
        elif depth == "shallow":
            bits.append("浅层")
        if rhythm == "pulse":
            bits.append("节奏起伏")
        elif rhythm == "wave":
            bits.append("波浪式")
        elif rhythm == "steady":
            bits.append("稳定节奏")
        if warmth == "warm":
            bits.append("暖意")
        return "、".join(bits) if bits else action.label

    def _start(
        self,
        action_id: str | None,
        mode_id: str | None,
        level: int,
        duration_s: int,
        feedback: str,
    ) -> None:
        now = self._clock()
        self._running = True
        self._current_action = action_id
        self._current_mode = mode_id
        self._level = level
        self._feedback = feedback
        self._safety = "ok"
        self._fault = None
        self._started_at = now
        self._ends_at = (now + duration_s) if duration_s > 0 else None
        self._reasoning_requested = False

    def _stop_internal(self, source: str, message: str) -> bool:
        was_running = self._running
        self._running = False
        self._current_action = None
        self._current_mode = None
        self._started_at = None
        self._ends_at = None
        self._feedback = message
        self._safety = "safety_stop" if source == "safety" else "ok"
        return was_running

    def _tick(self) -> None:
        if not self._running or self._started_at is None:
            return
        now = self._clock()
        if self._ends_at is not None and now >= self._ends_at:
            self._stop_internal("timer", _SOURCE_MESSAGES["timer"])
            return
        elapsed = now - self._started_at
        if elapsed >= self._max_on_s:
            self._stop_internal("safety", _SOURCE_MESSAGES["safety"])
            self._emit("safety", "本地安全策略触发：设备已自动停止。")
            return
        if (
            self._max_on_s > 0
            and elapsed >= 0.9 * self._max_on_s
            and not self._reasoning_requested
        ):
            self._reasoning_requested = True
            self._emit(
                "reasoning_request",
                "接近本地安全上限；硬件请求上游协助判断是否继续或调整。",
            )

    def _invalid(
        self, code: str, message: str, realization: Realization
    ) -> DeviceActionResult:
        return DeviceActionResult(
            device_id=self._device_id,
            simulated=True,
            accepted=False,
            executed=False,
            supported=True,
            realization=realization,
            message=message,
            state=self.status(),
            error={"code": code, "message": message},
        )

    def _unsupported(self, request: ActionRequest, reason: str) -> DeviceActionResult:
        message = (
            f"本设备不支持语义动作 `{request.action_id}`（unsupported：{reason}）；"
            "未发生任何物理动作，也不会用旁白代替执行。"
        )
        return DeviceActionResult(
            device_id=self._device_id,
            simulated=True,
            accepted=False,
            executed=False,
            supported=False,
            realization=Realization.UNSUPPORTED,
            message=message,
            state=self.status(),
            error={"code": "UNSUPPORTED", "message": message},
        )

    def _emit(self, kind: str, text: str) -> DeviceEvent:
        self._cursor += 1
        event = DeviceEvent(
            event_id=f"evt_{self._cursor:04d}",
            cursor=self._cursor,
            kind=kind,  # type: ignore[arg-type]
            semantic_text=text,
        )
        self._events.append(event)
        return event
