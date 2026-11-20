"""设备契约：MCP 设备面与设备实现之间的唯一边界。

设计原则（对应 2026-11-20 的重置决定）：

1. **设备是黑盒。** 上层只看到语义动作、模式、档位/强度、状态、停止与
   语义反馈；电机、波形、寄存器不属于本契约。
2. **语义动作优先。** 设备必须为每个核心动作声明 realization：
   ``native``（原生执行）/ ``mode_mapping``（映射到模式）/ ``unsupported``。
   不支持就是 unsupported，显式拒绝；不得用旁白冒充物理动作。
3. **强度/档位保留。** 档位是体验级参数，不是电机参数。
4. **原始传感器数值不进入本契约。** 反馈只有语义文本与可选影像；
   硬件自己消费原始数据用于本地安全。
5. **simulated 诚实标注。** 虚拟设备与真实设备接口等价、可替换，
   但不会假装有硬件。

所有跨层消息都带 ``contract_version``；未知字段保留（extra=allow）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "0.1"


class Realization(str, Enum):
    """设备对某个语义动作的实现方式。"""

    NATIVE = "native"
    MODE_MAPPING = "mode_mapping"
    UNSUPPORTED = "unsupported"


class ActionCategory(str, Enum):
    STIMULATE = "stimulate"
    TEASE = "tease"
    HOLD = "hold"
    RELEASE = "release"
    CHECK = "check"
    REST = "rest"
    STOP = "stop"


class SemanticAction(BaseModel):
    """能力菜单中的一项语义动作。

    ``params_schema`` 只描述语义参数（深度/节奏/温度……），
    不描述硬件参数。厂商扩展动作使用自己的 action_id，
    但仍须声明 realization。
    """

    model_config = ConfigDict(extra="allow")

    action_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    label: str = Field(max_length=60)
    category: ActionCategory
    realization: Realization
    mapped_mode_id: str | None = Field(
        default=None,
        description="realization=mode_mapping 时，实际执行的设备模式 id",
    )
    description: str = Field(default="", max_length=400)
    params_schema: dict[str, Any] = Field(default_factory=dict)
    requires_consent: bool = True


class Mode(BaseModel):
    """设备原生模式（当前产品直接提供的档位/模式）。"""

    model_config = ConfigDict(extra="allow")

    mode_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    label: str = Field(max_length=60)
    description: str = Field(default="", max_length=300)
    level_max: int = Field(default=8, ge=1, le=10)


class DeviceCapabilities(BaseModel):
    """设备能力菜单：语义动作 + 模式 + 档位 + 安全声明。"""

    model_config = ConfigDict(extra="allow")

    contract_version: str = CONTRACT_VERSION
    device_id: str
    device_class: str
    label: str
    simulated: bool = Field(default=True, description="虚拟设备恒为 true；真实设备由适配器如实填写")
    level_max: int = Field(default=8, ge=1, le=10)
    semantic_actions: list[SemanticAction] = Field(default_factory=list)
    modes: list[Mode] = Field(default_factory=list)
    supports_media: bool = False
    safety: dict[str, Any] = Field(
        default_factory=dict,
        description="安全声明（语义级）：本地自动停止、物理停止按钮、是否向上游请求推理等",
    )


class ActionRequest(BaseModel):
    """一次语义执行请求。"""

    model_config = ConfigDict(extra="allow")

    action_id: str
    intent: str = Field(
        default="",
        max_length=500,
        description="自然语言意图（可选，用于记录与审计；不会自动映射到动作）",
    )
    level: int = Field(default=3, ge=1, le=10, description="体验级档位/强度")
    duration_s: int = Field(default=0, ge=0, description="0 = 持续到显式停止")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="语义参数，如 depth=deep / rhythm=pulse / warmth=warm",
    )


class DeviceState(BaseModel):
    """设备状态：只包含语义信息，不含原始传感器数值。"""

    model_config = ConfigDict(extra="allow")

    device_id: str
    simulated: bool = True
    running: bool = False
    current_action: str | None = None
    current_mode: str | None = None
    level: int = 0
    remaining_s: int = 0
    feedback: str = Field(default="", description="语义级反馈，例如「深部、节奏起伏」")
    safety: str = Field(default="ok", description="语义安全状态，例如 ok / safety_stop")
    fault: str | None = None


class MediaItem(BaseModel):
    """可选影像反馈。原始传感器数值不走这个通道。"""

    model_config = ConfigDict(extra="allow")

    media_id: str
    kind: Literal["image", "video"]
    uri: str
    caption: str = ""


class DeviceEvent(BaseModel):
    """设备主动事件：安全事件、请求上游推理、状态/影像通知。"""

    model_config = ConfigDict(extra="allow")

    event_id: str
    cursor: int
    kind: Literal["safety", "reasoning_request", "state", "media"]
    semantic_text: str
    data: dict[str, Any] = Field(default_factory=dict)


class DeviceActionResult(BaseModel):
    """统一执行结果。

    ``supported=False`` 表示设备没有这个语义动作或明确不支持；
    此时 ``executed`` 必须为 False，且不得用旁白代替物理执行。
    """

    model_config = ConfigDict(extra="allow")

    contract_version: str = CONTRACT_VERSION
    device_id: str
    simulated: bool = True
    accepted: bool
    executed: bool
    supported: bool
    realization: Realization
    message: str = ""
    state: DeviceState
    error: dict[str, Any] | None = None


class StopResult(BaseModel):
    """停止结果。agent / hardware / safety / timer 四个来源共用一条停止路径。"""

    model_config = ConfigDict(extra="allow")

    contract_version: str = CONTRACT_VERSION
    device_id: str
    simulated: bool = True
    accepted: bool = True
    executed: bool
    source: Literal["agent", "hardware", "safety", "timer"]
    message: str
    state: DeviceState
