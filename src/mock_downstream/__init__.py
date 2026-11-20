"""模拟下游（参考实现）——独立于导演层的"下游任务书"示范。

职责边界（对应 docs/CONTRACT.zh-CN.md）：

1. **拟物渲染归下游**：接收抽象 CueCard（效果/手势/强度/时长/语义注记），
   由本下游用自己的文案库渲染成有质感的舞台意象文本。
2. **观测归下游**：以文本为主形态回传用户状态；命名指标诚实三态
   （reported/unsupported/absent）——本模拟下游没有真实观测能力，
   因此除声明性演示外一律如实报 unsupported/absent。
3. **安全处理归下游**：本参考实现只做最小声明，不做阈值策略。
4. **可以主动说话**：经 initiative_text 反问/提议（如「今天要怎么奖励好呢？」），
   不构成授权、不自动执行；导演层只呈现给 Agent 与用户。

接入真实产品时，把本包当作可替换的适配器骨架：
保持 CueCard → 渲染、观测 → StatusSignal 两个方向即可。
"""

from .mock import MockDownstream, ObserveContext, capabilities_menu_payload

__all__ = ["MockDownstream", "ObserveContext", "capabilities_menu_payload"]
