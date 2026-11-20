"""MCP 设备面。

只暴露设备操作，不包含导演层/角色层：
能力查询、语义执行、模式、档位、状态、停止、影像、事件。

原则：
- 语义动作优先；设备返回 unsupported 时就是没有物理执行。
- 档位/强度保留，作为体验级参数。
- 原始传感器数值不暴露；反馈只有语义文本与可选影像。
- simulated=true 对 Agent 可见。
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import Field

from .contract import ActionRequest, DeviceActionResult, StopResult
from .device import Device
from .virtual import VirtualDevice

try:
    from mcp.server import MCPServer
except ImportError:  # pragma: no cover
    raise

INSTRUCTIONS = (
    "你是设备操作端的 Agent：通过 MCP 操作一台设备。"
    "设备只暴露语义动作、模式、体验级档位、状态、停止与语义反馈；"
    "不暴露电机、波形、寄存器，也不提供原始传感器数值。"
    "优先使用 device_do 执行语义动作（如 stimulate 配合 depth=deep/rhythm=pulse/warmth=warm）；"
    "设备返回 supported=false 时，就是没有发生任何物理执行——"
    "不得用旁白代替，也不得声称设备执行了它。"
    "档位/强度用 level（1 到设备上限）；device_set_level 可在运行中调整。"
    "device_stop 永远可用、幂等；硬件另有本地安全与物理停止权，本服务的停止不是唯一保障。"
    "设备在接近本地安全上限时会通过 device_events 发 reasoning_request，"
    "硬件请求上游协助判断——这只是建议，不能覆盖硬件的本地停止权。"
    "simulated=true 表示这是虚拟设备：接口与真实设备等价，但不产生真实接触。"
    "反馈只有语义文本与可选影像；不要向用户伪造数值型生理数据。"
)


def _dump_model(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def build_mcp(device: Device | None = None) -> MCPServer:
    dev: Device = device or VirtualDevice()
    mcp = MCPServer("punishMaster Device Server", instructions=INSTRUCTIONS)

    # ---------------------------------------------------------------- 工具

    @mcp.tool()
    async def device_capabilities() -> dict[str, Any]:
        """读取设备能力菜单：语义动作、模式、档位范围、realization 与安全声明。

        每个语义动作声明 realization：
        native（设备原生执行）/ mode_mapping（映射到模式）/ unsupported（明确不支持）。
        """
        return _dump_model(dev.capabilities())

    @mcp.tool()
    async def device_status() -> dict[str, Any]:
        """读取设备当前状态：是否运行、当前动作/模式、档位、剩余时长、语义反馈。

        只返回语义信息，不含原始传感器数值。
        """
        return _dump_model(dev.status())

    @mcp.tool()
    async def device_do(
        action_id: Annotated[
            str,
            Field(
                description=(
                    "语义动作 id，见 device_capabilities。核心动作：stimulate（刺激）、"
                    "tease（挑逗）、hold（保持）、release（释放）、check（检查）、"
                    "rest（休息）、stop（停止）；厂商可扩展自定义 id。"
                )
            ),
        ],
        level: Annotated[
            int, Field(description="体验级档位/强度 1..设备上限", ge=1, le=10)
        ] = 3,
        duration_s: Annotated[
            int, Field(description="持续秒数；0 = 持续到 device_stop", ge=0)
        ] = 0,
        intent: Annotated[
            str,
            Field(
                description="自然语言意图（可选，用于记录；不会自动映射为动作）",
                max_length=500,
            ),
        ] = "",
        params: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "语义参数，如 depth=shallow|deep、rhythm=steady|pulse|wave、"
                    "warmth=none|warm；具体以设备 capabilities 的 params_schema 为准"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """执行一个语义动作（语义级调节与执行的首选入口）。

        设备不支持该动作时返回 supported=false、executed=false：
        这表示没有物理执行，不得用旁白代替或声称已发生。
        """
        request = ActionRequest(
            action_id=action_id,
            intent=intent,
            level=level,
            duration_s=duration_s,
            params=params or {},
        )
        return _dump_model(dev.execute(request))

    @mcp.tool()
    async def device_set_mode(
        mode_id: Annotated[str, Field(description="设备模式 id，见 device_capabilities 的 modes")],
        level: Annotated[int, Field(description="该模式下的档位 1..模式上限", ge=1, le=10)] = 3,
        duration_s: Annotated[int, Field(description="持续秒数；0 = 持续到 device_stop", ge=0)] = 0,
    ) -> dict[str, Any]:
        """直接使用设备原生模式（当前产品已有模式的回退入口）。"""
        return _dump_model(dev.set_mode(mode_id, level, duration_s))

    @mcp.tool()
    async def device_set_level(
        level: Annotated[int, Field(description="新的体验级档位 1..设备上限", ge=1, le=10)],
    ) -> dict[str, Any]:
        """调整档位/强度；运行中调整不重启当前动作。"""
        return _dump_model(dev.set_level(level))

    @mcp.tool()
    async def device_stop() -> dict[str, Any]:
        """立即停止设备。永远可用、幂等；与硬件物理停止按钮共用同一停止路径。"""
        return _dump_model(dev.stop(source="agent"))

    @mcp.tool()
    async def device_media(
        limit: Annotated[int, Field(description="最多返回条数", ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """读取设备提供的影像反馈（图片/视频）。没有影像时返回空列表；不返回原始数值。"""
        items = dev.media(limit)
        return {
            "device_id": dev.device_id,
            "simulated": True,
            "supports_media": dev.capabilities().supports_media,
            "items": [_dump_model(item) for item in items],
        }

    @mcp.tool()
    async def device_events(
        cursor: Annotated[int, Field(description="上次返回的 next_cursor；首次为 0", ge=0)] = 0,
    ) -> dict[str, Any]:
        """轮询设备主动事件：safety（本地安全停止）、reasoning_request（硬件请求上游推理）、
        state/media。事件只有语义文本，不含原始传感器数值。
        """
        events, next_cursor = dev.poll_events(cursor)
        return {
            "device_id": dev.device_id,
            "simulated": True,
            "events": [_dump_model(e) for e in events],
            "next_cursor": next_cursor,
        }

    # ---------------------------------------------------------------- 资源

    @mcp.resource("device://capabilities")
    def res_capabilities() -> str:
        return json.dumps(_dump_model(dev.capabilities()), ensure_ascii=False, indent=1)

    @mcp.resource("device://state")
    def res_state() -> str:
        return json.dumps(_dump_model(dev.status()), ensure_ascii=False, indent=1)

    return mcp


mcp = build_mcp()


def main() -> None:
    """stdio 运行入口（MCP 默认传输）。"""
    mcp.run()


if __name__ == "__main__":
    main()
