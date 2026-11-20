"""VPP 拟物互动导演层（全模拟）。

本包实现一个完全虚拟的"互动场景执行器"：

- 通过标准 MCP 向 Agent 暴露工具、资源和提示词；
- 内部使用版本化的 Virtual Play Protocol（VPP）；
- 下行 CueCard：抽象的动作 / 任务 / 状态管理指令；
- 上行 StatusSignal：以文本为主的用户状态观测信道
  （可选命名指标，要求下游诚实返回 reported / unsupported / absent）；
- 所有效果均由本地模拟器（拟物道具组）执行，不连接、不扫描、不控制任何真实硬件；
- 信号采集与安全处理归下游所有，本层只采集、存储并如实呈现。

仅面向成年人的自愿互动。现实中的控制权始终属于用户。
"""

from .protocol import VPP_PROTOCOL_VERSION

__all__ = ["VPP_PROTOCOL_VERSION"]
