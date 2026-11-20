"""punishMaster 设备契约层。

当前提供：共享语义本体 + 设备契约 + 虚拟设备 + MCP 设备面。
不包含导演层/角色层；真实设备适配器实现 ``device.Device`` 即可替换虚拟设备。
"""

from .contract import CONTRACT_VERSION
from .virtual import VirtualDevice

__all__ = ["CONTRACT_VERSION", "VirtualDevice"]
