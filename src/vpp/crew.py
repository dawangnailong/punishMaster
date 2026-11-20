"""拟物道具执行器（参考实现）：把抽象 CueCard 渲染成有质感的舞台文案。

设计要点（对应"Apple 式拟物风"的要求）：

1. 本模块是 CrewPort 的**参考模拟实现**（MockPropsCrew）。真实下游按
   docs/CONTRACT.zh-CN.md 自行实现自己的 Crew；本层不假设它存在。
2. 渲染产物只有文本与感官标签：一声铃、一束光、一粒沙……全部是舞台意象。
   刻意没有电机、档位、波形——本层不产生任何硬件语义。
3. 确定性：同 seed 同 cue 必得同文案（random.Random(seed) 选句），
   供 replay 与测试复现。
4. 文案上限：内置文案库整体控制在温和～中等（mild/moderate），
   即使用户配置了 explicit，本参考执行器也不会生成露骨文案。
5. 贬损称呼：即使会话配置显式允许，本参考执行器也不主动生成贬损称呼；
   导演层传来的 address 一律来自 neutral/pet/brat 层的授权称呼。
6. capabilities() 里声明 real_hardware=False——这是"全模拟"的机器可读证明。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Protocol

from .protocol import CueCard

SIM_NOTE = "〔全部为本地模拟的舞台意象：未连接任何真实设备，无任何真实效果〕"


@dataclass
class RenderContext:
    """渲染上下文：称呼、风格、露骨上限（截到 moderate）、确定性种子。"""

    address: str
    style: str = "温柔克制"
    explicitness: str = "mild"  # 已被导演层截断，不会高于 moderate
    seed: int = 0


@dataclass
class RenderedCue:
    cue_id: str
    text: str
    sensory_tags: list[str] = field(default_factory=list)
    simulated: bool = True


class CrewPort(Protocol):
    """下游契约接口：真实下游实现它，本层内置 MockPropsCrew 参考实现。"""

    def capabilities(self) -> dict[str, Any]: ...

    def render(self, cue: CueCard, ctx: RenderContext) -> RenderedCue: ...


# ---------------------------------------------------------------- 拟物文案库
# 占位符：{addr} 称呼 / {note} 导演备注（已脱敏）/ {dur} 时长描述

TEXTBANK: dict[str, dict[str, list[str]]] = {
    "chime": {
        "strike": [
            "银铃被指尖轻轻一碰，「叮——」一声荡开，在安静的房间里留下一圈微微发亮的涟漪。{addr}，这一声是给你的。{note}",
            "小银铃晃了两下，声音清而短，像有人在你耳边点头示意：做得不错。{note}",
        ],
    },
    "spotlight": {
        "hold": [
            "「啪」的一声轻响，暖黄的聚光灯光柱稳稳落在{addr}身上，把这一刻圈成只属于你的舞台。{note}",
        ],
        "fade": [
            "聚光灯缓缓收窄、变暗，最后像一次深呼吸那样松开。光斑退场，掌声留在原地。{note}",
        ],
    },
    "rose": {
        "present": [
            "一只手把纸折的玫瑰递到你面前，纸边还带着折痕的钝钝触感。{addr}，收下它。{note}",
        ],
    },
    "crown": {
        "present": [
            "纸王冠被轻轻放在{addr}的头顶，边角压出一点褶。戴着它的这一幕，由你说了算。{note}",
        ],
    },
    "badge": {
        "present": [
            "一枚小徽章「嗒」地落进掌心，先凉一下，随即被体温焐热。{addr}的徽章收藏里多了一枚。{note}",
        ],
    },
    "feather": {
        "flick": [
            "一根羽毛从舞台一侧斜斜掠过，末梢擦出一点若有似无的痒意，点到即止。{note}",
        ],
        "crescendo": [
            "羽毛的摆动慢慢加密，从一秒钟一晃到几乎连成一片柔光……节奏停在最高点之前一格。{note}",
        ],
        "fade": [
            "羽毛的摆动一格一格慢下来，最后停成一根安静悬浮的绒。{note}",
        ],
    },
    "bell_grant": {
        "strike": [
            "许可铃「叮」地一响：这一轮的「可以」，正式生效。{note}",
        ],
    },
    "dimlight": {
        "hold": [
            "角落里那盏冷光小灯亮起来，光圈很小，刚好圈出一块罚站的位置。{addr}，先在那里安静待一会儿。{note}",
        ],
        "fade": [
            "角落的冷光一格格暗下去，最后缩成一个亮点，随即熄灭。{note}",
        ],
    },
    "stamp": {
        "strike": [
            "印章在纸面「咚」地盖下去，红印洇开一点边：「本轮不合格」。盖完即止，不多说一句。{note}",
        ],
    },
    "ticket": {
        "present": [
            "一张纸罚单被撕下、拍在桌上，字迹工整得有点过分。{addr}，签收一下这一条。{note}",
        ],
    },
    "task_card": {
        "present": [
            "一张任务卡从卡组里抽出来，推到你面前，背面朝上。翻开之前，先深呼吸一次。{note}",
        ],
    },
    "badge_withdraw": {
        "withdraw": [
            "那枚徽章被轻轻拈起、收回木盒，盒盖合上时发出很小的「咔哒」。{addr}的收藏少了一枚。{note}",
        ],
    },
    "hourglass_wait": {
        "hold": [
            "大沙漏翻了个身，细沙开始一格一格往下漏。{addr}，站着看它漏完就行，别的什么都不用做。{note}",
        ],
    },
    "jester_hat": {
        "present": [
            "一顶纸糊的小丑帽被扣到{addr}头上，帽檐的小铃铛晃出两声不成调的响。{note}",
        ],
    },
    "nameplate": {
        "present": [
            "一块小桌牌「啪」地立在桌前，牌上只写一个场景内的称呼。此刻起，你是这块牌子。{note}",
        ],
    },
    "scratched_ticket": {
        "present": [
            "那张票被当面「刺啦」一声划掉，碎纸屑扫进簸箕。{addr}，这一轮作废。{note}",
        ],
    },
    "curtain_open": {
        "open": [
            "红色丝绒大幕向两侧拉开，舞台灯一排一排亮起。{addr}，戏开始了。{note}",
        ],
    },
    "curtain_close": {
        "close": [
            "丝绒大幕缓缓合拢，把舞台灯一盏一盏收进去。这一场到此为止，掌声留给下一场。{note}",
        ],
    },
    "act_shift": {
        "snap": [
            "灯光「啪」地一暗，三秒后再亮——布景已经换过，下一幕开始。{note}",
        ],
    },
    "interlude": {
        "hold": [
            "幕布半掩，场灯调到暖黄。台上安静的一小段，{addr}，喝口水也行。{note}",
        ],
    },
    "hourglass": {
        "hold": [
            "沙漏立起来了。{dur}之内，只属于等待。{note}",
        ],
    },
    "bell_call": {
        "strike": [
            "唤名铃响了一声，不高不低。{addr}，注意力请回到台上。{note}",
        ],
    },
    "freeze": {
        "snap": [
            "舞台灯光骤停，所有人保持原地。{addr}，定格。{note}",
        ],
    },
    "release": {
        "open": [
            "定格解除，场灯恢复，台上的呼吸声重新流动起来。{note}",
        ],
    },
    "observe_request": {
        "present": [
            "向下游观测侧发出请求：脉搏 / 硬度 / 湿润程度 / 呼吸 / 瞳孔。要求如实返回："
            "掌握的报 reported（附读数），不掌握的报 unsupported，当前不适用的报 absent——严禁编造。"
            "结果经 signal_report 回传。",
        ],
    },
}

# 手势级兜底（效果×手势未命中文案库时使用）
GESTURE_FALLBACK: dict[str, list[str]] = {
    "strike": ["一声短促的「嗒」落定。{note}"],
    "present": ["一件小道具被双手奉到{addr}面前。{note}"],
    "withdraw": ["道具被安静收回口袋。{note}"],
    "hold": ["道具停在半空，光圈保持不动。{note}"],
    "fade": ["光与声一层一层淡出，直到什么也不剩。{note}"],
    "crescendo": ["节奏一格一格加密，在最高点之前一格稳住。{note}"],
    "flick": ["一次轻而快的掠过，点到即止。{note}"],
    "snap": ["「啪」的一声，一切当场停住。{note}"],
    "open": ["道具展开，光面朝上。{note}"],
    "close": ["道具合上，扣好。{note}"],
}

SENSORY_TAGS: dict[str, list[str]] = {
    "chime": ["sound"],
    "spotlight": ["light"],
    "rose": ["touch"],
    "crown": ["light", "touch"],
    "badge": ["sound", "touch"],
    "feather": ["touch"],
    "bell_grant": ["sound"],
    "dimlight": ["light"],
    "stamp": ["sound"],
    "ticket": ["touch"],
    "task_card": ["touch"],
    "badge_withdraw": ["sound"],
    "hourglass_wait": ["sight"],
    "jester_hat": ["sound", "touch"],
    "nameplate": ["sight"],
    "scratched_ticket": ["sound"],
    "curtain_open": ["sight", "sound"],
    "curtain_close": ["sight", "sound"],
    "act_shift": ["light"],
    "interlude": ["light"],
    "hourglass": ["sight"],
    "bell_call": ["sound"],
    "freeze": ["light"],
    "release": ["light"],
    "observe_request": [],
}


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "片刻"
    if seconds >= 60:
        return f"约 {seconds // 60} 分钟"
    return f"{seconds} 秒"


class MockPropsCrew:
    """内置参考执行器：拟物渲染，零真实副作用，确定性输出。"""

    name = "MockPropsCrew"

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "real_hardware": False,
            "synchronous": True,
            "rendering": "skeuomorphic-text",
            "explicitness_ceiling": "moderate",
            "generates_degrading_address": False,
            "safety_policy": "none（信号采集与安全处理归下游所有）",
            "description": (
                "参考拟物执行器：把 CueCard 渲染为舞台意象文本。"
                "真实下游应实现 CrewPort 并自行负责观测与安全处理。"
            ),
        }

    def render(self, cue: CueCard, ctx: RenderContext) -> RenderedCue:
        rng = random.Random(ctx.seed)
        bank = TEXTBANK.get(cue.effect, {}).get(cue.gesture)
        if bank:
            template = rng.choice(bank)
        else:
            template = rng.choice(GESTURE_FALLBACK.get(cue.gesture, GESTURE_FALLBACK["present"]))

        note = ""
        if cue.stage_note:
            note = f"（导演备注：{cue.stage_note}）"

        text = (
            template.replace("{addr}", ctx.address)
            .replace("{note}", note)
            .replace("{dur}", _fmt_duration(cue.duration_s))
        )
        return RenderedCue(
            cue_id=cue.cue_id,
            text=text,
            sensory_tags=list(SENSORY_TAGS.get(cue.effect, [])),
            simulated=True,
        )
