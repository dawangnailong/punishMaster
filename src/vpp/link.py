"""虚拟链路层：保留「扫描/连接」的函数形状，业务完全为虚拟。

为什么存在这一层（诚实优先，而不是拟物优先）：

- 真实的硬件桥接项目（intiface 那类形状）的 API 面上都有
  「扫描设备 → 选择 → 连接 → 注册能力」这组函数。本层保留这组
  **函数形状**，使协议面对真实下游时不需要重新设计；
- 但这里没有任何真实业务：``scan`` 遍历的是本地内存里写死的
  **假想设备名册**（hypothetical registration），``connect`` 是一次
  本地状态写入。全程没有蓝牙、串口、网络或任何 IO；
- 名册中的每个"设备"都必须直白说明：它模拟的是哪一类器具、
  它不存在实体、它的一切功能都是模拟。

诚实叙述规则：描述链路操作本身一律用直白语言（``happening_now``
字段如实告诉 Agent 此刻实际发生了什么、没有发生什么）。
舞台意象只用于效果文案，绝不用于描述系统行为——
防止 Agent（或用户）误以为发生了真实的扫描/连接/控制。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VirtualDevice:
    """假想注册的模拟设备：对某类器具功能的模拟声明，不存在实体。"""

    device_id: str
    kind: str                      # 器具类别（直白）
    plain_name: str                # 直白名称（第一名称，不做拟物包装）
    simulated_function: str        # 模拟了什么功能
    provides: tuple[str, ...]     # 对应的下游能力 id（crew:<effect_id>）
    note: str                      # 诚实注记

    def payload(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "kind": self.kind,
            "plain_name": self.plain_name,
            "simulated_function": self.simulated_function,
            "provides": list(self.provides),
            "registration": "hypothetical",  # 假想注册：模拟声明，非实体设备
            "simulated": True,
            "note": self.note,
        }


ROSTER: tuple[VirtualDevice, ...] = (
    VirtualDevice(
        device_id="sim-epp-01",
        kind="suction_stroker",
        plain_name="模拟气压吮吸器具（男用飞机杯类功能的模拟）",
        simulated_function=(
            "模拟某类气动吮吸器具的功能集：四档气压吸吮（轻吮/起伏/夹吸/深喉）、"
            "一键爆发（短促冲刺档）与恒温层（接近体温的暖意包裹）。"
        ),
        provides=(
            "crew:suction_gentle", "crew:suction_wave", "crew:squeeze_pulse",
            "crew:deep_throat", "crew:eruption", "crew:warm_hug",
        ),
        note=(
            "假想注册：这是对一类器具功能的模拟声明，不存在任何实体设备。"
            "「连接」它不会导致任何真实刺激；其效果须先经 crew_announce 注册，"
            "再通过用户允许清单 + 行为开关 + 强度/时长上限（注册 ≠ 授权）。"
        ),
    ),
    VirtualDevice(
        device_id="sim-warm-01",
        kind="warmth_layer",
        plain_name="模拟恒温层（只要暖意包裹的温和模式）",
        simulated_function="模拟恒温功能：接近体温的暖意包裹，不含吸吮/夹吸刺激。",
        provides=("crew:warm_hug",),
        note=(
            "假想注册：模拟声明，不存在任何实体设备。"
            "适合只要抚慰、不要强刺激的使用方式。注册 ≠ 授权。"
        ),
    ),
)

DEVICES: dict[str, VirtualDevice] = {d.device_id: d for d in ROSTER}

SCAN_NARRATION = (
    "此刻实际发生的事：正在读取本地内存里写死的假想设备名册"
    f"（{len(ROSTER)} 条记录）。没有发生任何蓝牙/串口/网络扫描，"
    "也没有任何无线电活动——本系统在结构上无法扫描真实设备"
    "（源码级禁止硬件与网络导入，见 tests/test_no_real_hardware.py）。"
)

CONNECT_NARRATION = (
    "「连接」实际发生的事：把一个假想注册的模拟设备写入本会话的"
    "下游绑定表（本地内存状态）。没有发生任何真实握手、配对或数据传输。"
)

LINK_NOTE = (
    "连接 ≠ 授权：连接只是登记「本会话的下游是哪个模拟设备」，"
    "不改变任何执行权限。下一步用该设备的能力菜单做 crew_announce 注册；"
    "执行仍须通过用户允许清单、行为开关与强度/时长上限（fail-closed）。"
)


def scan_report() -> dict[str, Any]:
    """扫描报告：如实说明遍历的是什么、没有发生什么。"""
    return {
        "action": "link_scan",
        "simulated": True,
        "happening_now": SCAN_NARRATION,
        "devices": [d.payload() for d in ROSTER],
        "how_to_connect": (
            "link_connect(session_id, device_id)：把选定的模拟设备绑定进会话，"
            "然后用它的能力菜单做 crew_announce 注册（注册 ≠ 授权）。"
        ),
    }


def device_or_none(device_id: str) -> VirtualDevice | None:
    return DEVICES.get(device_id)
