"""模拟下游实现：拟物渲染 + 诚实观测 + 主动话语。

与层内 vpp.crew.MockPropsCrew 的区别：

- MockPropsCrew 是导演层自带的“开箱兜底渲染器”（保证不接下游也能演示）；
- MockDownstream 是**独立下游**的参考实现：拥有自己的道具文案库、
  自己的观测模拟（诚实三态）与主动话语能力，通过 CrewPort 与
  StatusSignal 两条契约与导演层对话。

确定性：所有随机都由 (session_seed, 序号) 种子驱动，可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from vpp.crew import GESTURE_FALLBACK, SENSORY_TAGS, RenderContext, RenderedCue
from vpp.protocol import (
    CapabilitiesDeclaration,
    CapabilitySpec,
    CueCard,
    MetricReading,
    StatusSignal,
)
from vpp.catalog import METRICS


# ---------------------------------------------------------------- 能力菜单
# 模拟下游按其参考产品（Jissbon E-Pneumatic Pro：温感吮吸气动加热飞机杯）
# 的公开功能描述登记能力菜单。产品卖点：真空气动深喉、负压 max 超强深喉夹吸
# （旋转抽空技术，从浅到深）、四种气压吸吮、一键爆发（One-Click Burst）、
# 智能体温感加热、低于耳语级静音、极致柔软纹理。
# 注意：这是对产品功能集的**模拟**，与该品牌无任何关联，不含任何真实控制路径。
# 注册 ≠ 授权：执行仍须通过用户允许清单 + 行为开关 + 强度/时长上限。

EPP_MENU: list[CapabilitySpec] = [
    CapabilitySpec(
        effect_id="suction_gentle", label="气压轻吮·一档", category="reward",
        channels=["tactile_sensation"], kink_flags=["orgasm_control_enabled"],
        intensity_max=4, duration_min_s=30, duration_max_s=1800, score_delta=1,
        description="产品功能：最轻档气压吸吮，对应「从轻柔逗弄开始」的使用节奏。",
        actual_semantics="对应轻度感官刺激（最低档吮吸）：现实的轻抚/浅吮类感官游戏；"
                        "本模拟下游无真实接触，仅产生文本意象。",
    ),
    CapabilitySpec(
        effect_id="suction_wave", label="起伏吸吮·二档", category="reward",
        channels=["tactile_sensation"], kink_flags=["orgasm_control_enabled"],
        intensity_max=6, duration_min_s=30, duration_max_s=1800, score_delta=1,
        description="产品功能：中档起伏式气压吸吮，旋转抽空带节奏地一收一放。",
        actual_semantics="对应中等感官刺激（起伏节奏吮吸）：tease/节奏挑逗类感官游戏；"
                        "本模拟下游无真实接触，仅产生文本意象。",
    ),
    CapabilitySpec(
        effect_id="squeeze_pulse", label="紧致夹吸·三档", category="reward",
        channels=["tactile_sensation"], kink_flags=["orgasm_control_enabled"],
        intensity_max=7, duration_min_s=30, duration_max_s=1800, score_delta=1,
        description="产品功能：较高档气压夹吸，极致柔软的纹理提供紧致包裹感。",
        actual_semantics="对应较强感官刺激（紧致收缩/挤压节奏）：须用户明确允许的中高强度感官游戏；"
                        "本模拟下游无真实接触，仅产生文本意象。",
    ),
    CapabilitySpec(
        effect_id="deep_throat", label="深喉夹吸·四档", category="reward",
        channels=["tactile_sensation"], kink_flags=["orgasm_control_enabled"],
        intensity_max=8, duration_min_s=30, duration_max_s=1200, score_delta=2,
        description="产品功能：负压 max 超强深喉夹吸——旋转抽空技术，从浅到深的最强一档。",
        actual_semantics="对应强感官刺激：模拟口腔深部吸附的最深档模式；"
                        "属强感官/高潮控制类，须用户明确允许且强度受会话上限约束；"
                        "本模拟下游无真实接触，仅产生文本意象。",
    ),
    CapabilitySpec(
        effect_id="eruption", label="一键爆发", category="reward",
        channels=["tactile_sensation"], kink_flags=["orgasm_control_enabled"],
        intensity_max=8, duration_min_s=10, duration_max_s=300, score_delta=2,
        description="产品功能：One-Click Burst——一键触发，负压瞬间拉满的短促冲刺，随即回落。",
        actual_semantics="对应短时高强度的冲刺式刺激（爆发档）：属强感官/高潮控制类，"
                        "须用户明确允许且强度受会话上限约束；时长刻意很短；"
                        "本模拟下游无真实接触，仅产生文本意象。",
    ),
    CapabilitySpec(
        effect_id="warm_hug", label="恒温层", category="reward",
        channels=["tactile_sensation"], kink_flags=[],
        intensity_max=3, duration_min_s=60, duration_max_s=3600, score_delta=0,
        description="产品功能：智能体温感加热，接近体温的暖意先行铺开。",
        actual_semantics="对应暖意包裹的感官抚慰（恒温层意象）；无需成人行为开关即可允许，"
                        "仍须出现在用户允许清单内；本模拟下游无真实接触。",
    ),
]

# ---------------------------------------------------------------- 道具箱文案库
# 模拟下游自带的风格：更口语、更“贴身服务”的拟物感。
# （待接入具体产品后，可整体替换为对齐该产品风格的文案库。）

DOWNSTREAM_TEXTBANK: dict[str, dict[str, list[str]]] = {
    "chime": {
        "strike": [
            "道具箱里的小银铃被托到台口，用指腹轻轻一磕，「叮」——这一声清亮，是{addr}应得的。{note}",
        ],
    },
    "spotlight": {
        "hold": [
            "舞台技师把主灯缓缓推亮，暖黄的光稳稳罩住{addr}。这一束光不是照给别人看的，是给你一个人的。{note}",
        ],
        "fade": [
            "主灯慢慢收暗，光斑像一杯温着的水渐渐降温。夸奖说完了，但暖意还留着。{note}",
        ],
    },
    "rose": {
        "present": [
            "后勤从后台快步走上来，双手把一朵纸玫瑰别在{addr}手边。花瓣有点软，却折不坏。{note}",
        ],
    },
    "crown": {
        "present": [
            "一顶折得方方正正的纸王冠落在{addr}头顶，帽檐压出小小的褶。今晚这一场，你是主角。{note}",
        ],
    },
    "badge": {
        "present": [
            "道具组送来一枚小徽章，「嗒」地放进{addr}掌心。先凉一下，然后被体温焐热。{note}",
        ],
    },
    "feather": {
        "flick": [
            "一根羽毛从侧幕斜斜飘进来，末梢在{addr}身侧若有似无地擦了一下，点到即止。{note}",
        ],
        "crescendo": [
            "羽毛的摆幅一格一格加大，节奏慢慢变密……在最高点之前一格，稳稳停住。{note}",
        ],
        "fade": [
            "羽毛慢下来，慢下来，最后停成一根安静的绒，悬在{addr}面前。{note}",
        ],
    },
    "bell_grant": {
        "strike": [
            "道具组把许可铃摇响一声：「叮——」。这一轮的「可以」，正式生效。{note}",
        ],
    },
    "dimlight": {
        "hold": [
            "舞台一侧的冷光小灯亮起，光圈刚好圈出一小块角落。{addr}，去那里安静待一会儿，光不会盯着你。{note}",
        ],
        "fade": [
            "角落那盏冷光一格一格暗下去，最后熄了。冷处理结束，场灯照旧。{note}",
        ],
    },
    "stamp": {
        "strike": [
            "道具组把大印「咚」地按在记录本上，红印洇开一点边：本轮不合格。盖完就翻页，不追加一句。{note}",
        ],
    },
    "ticket": {
        "present": [
            "一张罚单撕下来，双手递到{addr}面前——字迹工整，句句有据。签收一下。{note}",
        ],
    },
    "task_card": {
        "present": [
            "任务卡从卡组里抽出来，推到{addr}面前，背面朝上。翻开之前，先深呼吸一次。{note}",
        ],
    },
    "badge_withdraw": {
        "withdraw": [
            "道具组把那枚徽章拈起来，收回木盒，盒盖「咔哒」合上。{addr}的收藏，暂时少一枚。{note}",
        ],
    },
    "hourglass_wait": {
        "hold": [
            "大沙漏被翻了个身，细沙一格一格往下漏。{addr}，看着它就好，其余的都不用做。{note}",
        ],
    },
    "jester_hat": {
        "present": [
            "纸糊的小丑帽被扣到{addr}头上，帽铃铛晃出两声不成调的响。台下没人笑——这是戏，不是你。{note}",
        ],
    },
    "nameplate": {
        "present": [
            "一块小桌牌「啪」地立在{addr}桌前，牌上只写一个场景内的称呼。此刻起，你是这块牌子。{note}",
        ],
    },
    "scratched_ticket": {
        "present": [
            "那张票被当面「刺啦」划掉，纸屑扫进簸箕。{addr}，这一轮作废——下一轮重新来。{note}",
        ],
    },
    "curtain_open": {
        "open": [
            "丝绒大幕拉开，场灯一排一排亮起，侧幕有人小声说：来了来了。{addr}，戏开始了。{note}",
        ],
    },
    "curtain_close": {
        "close": [
            "大幕合拢，场灯收到只剩观众席的安全出口灯。这一场到这里，掌声先欠着，下一场补。{note}",
        ],
    },
    "act_shift": {
        "snap": [
            "场灯「啪」地一暗，三秒后再亮——布景已经换过了。下一幕，从这一秒开始。{note}",
        ],
    },
    "interlude": {
        "hold": [
            "幕布半掩，场灯调成暖黄。幕间这一小段属于{addr}自己：喝口水，动动肩。{note}",
        ],
    },
    "hourglass": {
        "hold": [
            "沙漏立起来了。接下来的{dur}，只属于等待。{note}",
        ],
    },
    "bell_call": {
        "strike": [
            "唤名铃响了一声，不高不低。{addr}，请把注意力放回台上。{note}",
        ],
    },
    "freeze": {
        "snap": [
            "场控喊了一声「定格」，全场灯光骤停。{addr}，保持这个姿势，一动不动。{note}",
        ],
    },
    "release": {
        "open": [
            "场控喊「解除」，场灯恢复，台上的呼吸声重新流动起来。{note}",
        ],
    },
    "observe_request": {
        "present": [
            "（模拟下游）收到观测请求：将如实回传——本下游没有真实观测能力，"
            "除声明性演示外一律报 unsupported/absent；不编造数值。"
            "结果经 signal_report 回传。",
        ],
    },
}

# 下游自带的能力渲染文案（crew:<effect_id> 寻址）。
# 风格对齐参考产品的文案体系：真空气动、负压、旋转抽空、深喉夹吸、
# 从浅到深、极致柔软纹理、智能体温感加热、耳语级静音——词汇直白，
# 描述保持温和～中等，每条都保留 {note} 诚实注记。
CREW_TEXTBANK: dict[str, dict[str, list[str]]] = {
    "suction_gentle": {
        "hold": [
            "气路先做一次很浅的抽空：负压像一层软膜轻轻贴上来，又慢慢松开——一档只在逗弄的范围里。{note}",
        ],
        "fade": [
            "一档的负压一点一点泄掉，气流放平，最后只剩柔软贴着的安静。{note}",
        ],
    },
    "suction_wave": {
        "hold": [
            "二档开启：旋转抽空开始走节奏，一阵收紧、一阵放开，像潮水从浅处往深处试探。{note}",
        ],
        "crescendo": [
            "二档的潮汐一格一格变密，收紧停留得更久、放开得更慢——在再进一档之前稳稳收住。{note}",
        ],
        "fade": ["潮水退成涟漪，涟漪退成平缓的气流。{note}"],
    },
    "squeeze_pulse": {
        "hold": [
            "三档：极致柔软的纹理随负压一节一节收拢，裹得很紧、也裹得很软——夹吸从这里开始变得实在。{note}",
        ],
        "crescendo": [
            "三档的夹吸一节密过一节，紧致的峰叠着上一节的余温，仍稳在会话上限之内。{note}",
        ],
        "fade": ["夹吸慢下来，负压松开，纹理最后只是安安稳稳地贴着。{note}"],
    },
    "deep_throat": {
        "hold": [
            "四档：负压拉到最深——旋转抽空整段收紧，从浅到深完成一次完整而缓慢的探入与吸附，"
            "静得只有接近耳语的气流声。{note}",
        ],
        "crescendo": [
            "四档的深喉夹吸开始加密：深、退、再深，每一次都探到上一口的余深处，"
            "负压 max 的一格仍稳在会话上限之内。{note}",
        ],
        "fade": [
            "深处的负压一寸一寸松开，从最深处退回浅处，收成一段温软的静。{note}",
        ],
    },
    "eruption": {
        "burst": [
            "一键按下：负压瞬间拉满——短促、整段、不打商量的一次冲刺，把四档最深的一口压进几秒之内，随即回落。{note}",
        ],
        "hold": [
            "爆发档进入短促的高位保持：负压顶满、纹理全收，只在会话上限允许的这几秒里。{note}",
        ],
        "fade": [
            "冲刺结束，负压应声回落，气流平下来，像长跑后的第一口匀呼吸。{note}",
        ],
    },
    "warm_hug": {
        "hold": [
            "智能体温感加热先铺开：暖意从腔壁一层一层透出来，接近体温——像有人先替你焐热了手心。{note}",
        ],
        "fade": ["加热一层层收回，余温留在原处。{note}"],
    },
}


# 主动话语模板（下游“开口”的几种姿态），口吻对齐产品菜单：一档到四档、
# 一键爆发、恒温层——只提议，不执行，不构成授权。
INITIATIVE_TEMPLATES: list[str] = [
    "今天想怎么被奖励呢？{addr}状态看着不错，菜单上有一档到四档，也有恒温层。",
    "接下来想被怎么对待？从轻到深的四档气压都在，一键爆发也可以点，但只有几秒。",
    "刚才那一下，{addr}的反应好像不错。要不要升一档，还是换旋转抽空的节奏？",
    "我看今天适合慢一点。你说了算：继续、降一档，还是先焐进恒温层歇一会儿？",
]


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "片刻"
    if seconds >= 60:
        return f"约 {seconds // 60} 分钟"
    return f"{seconds} 秒"


# crew 能力的感官标签（本下游自有通道标注，不依赖导演层的道具标签表）
CREW_SENSORY_TAGS: dict[str, list[str]] = {
    "suction_gentle": ["tactile_sensation"],
    "suction_wave": ["tactile_sensation"],
    "squeeze_pulse": ["tactile_sensation"],
    "deep_throat": ["tactile_sensation"],
    "eruption": ["tactile_sensation"],
    "warm_hug": ["tactile_sensation", "temperature"],
}


def capabilities_menu_payload() -> list[dict[str, Any]]:
    """给 MCP crew_announce 工具直接可用的能力菜单 JSON（host 侧调用示例）。"""
    return [spec.model_dump(mode="json") for spec in EPP_MENU]


@dataclass
class ObserveContext:
    """观测上下文：观测的确定性种子与称呼。"""

    session_id: str | None = None
    seed: int = 0
    address: str = "你"


class MockDownstream:
    """模拟下游：渲染 + 诚实观测 + 主动话语；零真实硬件。"""

    name = "MockDownstream"

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "real_hardware": False,
            "owns_rendering": True,
            "owns_observation": True,
            "owns_safety": "minimal（安全处理归下游——本参考实现仅做声明）",
            "honest_metrics": True,
            "initiative_channel": True,
            "capability_menu": "E-Pneumatic-Pro（模拟）：4 档气压吸吮（负压 max 深喉夹吸）+ 一键爆发 + 智能体温感恒温",
            "synchronous": True,
            "description": (
                "独立模拟下游的参考实现：连接后经 crew_announce 注册能力菜单，"
                "消费 CueCard 渲染拟物文案，回传诚实三态指标与文本状态，"
                "并可主动反问/提议。与任何真实品牌/产品无关联。"
            ),
        }

    # ------------------------------------------------------------ 能力菜单注册

    def capabilities_declaration(self, session_id: str | None = None) -> CapabilitiesDeclaration:
        """连接握手：向导演层注册本下游实际支持的能力菜单。"""
        return CapabilitiesDeclaration(
            crew_name="E-Pneumatic-Pro 模拟器（非真实产品，无任何硬件控制）",
            session_id=session_id,
            effects=list(EPP_MENU),
            notes=(
                "参考产品功能集的模拟：四种气压吸吮（旋转抽空、负压 max 深喉夹吸、从浅到深）"
                "+ 一键爆发（One-Click Burst）+ 智能体温感恒温，低于耳语级静音。"
                "注册 ≠ 授权：每项能力仍须通过用户的允许清单、行为开关与强度/时长上限。"
            ),
        )

    # ------------------------------------------------------------ 下行消费

    def render(self, cue: CueCard, ctx: RenderContext) -> RenderedCue:
        rng = random.Random(ctx.seed)
        effect_key = cue.effect.removeprefix("crew:")
        bank = (
            CREW_TEXTBANK.get(effect_key, {}).get(cue.gesture)
            or DOWNSTREAM_TEXTBANK.get(cue.effect, {}).get(cue.gesture)
        )
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
            text=text + "〔模拟下游渲染〕",
            sensory_tags=list(CREW_SENSORY_TAGS.get(effect_key, SENSORY_TAGS.get(cue.effect, []))),
            simulated=True,
        )

    # ------------------------------------------------------------ 上行观测

    def observe(self, ctx: ObserveContext) -> StatusSignal:
        """模拟一次用户状态观测。

        诚实三态示范：脉搏做声明性模拟（reported，并明示是模拟值）；
        呼吸以短文本报 reported；硬度本下游不掌握 → unsupported；
        湿润程度当前场景不适用 → absent；瞳孔不掌握 → unsupported。
        """
        rng = random.Random(ctx.seed)
        pulse = rng.randint(72, 108)
        breath = rng.choice(["平稳", "略快而稳", "轻浅"])
        return StatusSignal(
            session_id=ctx.session_id,
            source="downstream",
            state_text=(
                f"（模拟观测，非真实读数）呼吸{breath}；用户自述投入、无不适表达；"
                "如需真实生理指标请接入具备观测能力的下游。"
            ),
            state_text_format="plain",
            metrics=[
                MetricReading(name="pulse", status="reported", value=pulse, unit="bpm",
                              note="声明性模拟值，非真实采集"),
                MetricReading(name="breath", status="reported", value=breath),
                MetricReading(name="hardness", status="unsupported",
                              note="本模拟下游不掌握该观测能力，如实上报"),
                MetricReading(name="pupil", status="unsupported",
                              note="本模拟下游不掌握该观测能力，如实上报"),
                MetricReading(name="wetness", status="absent",
                              note="当前场景不适用，如实上报"),
            ],
            extensions={"requested": list(METRICS)},
        )

    # ------------------------------------------------------------ 主动话语

    def initiative(
        self,
        ctx: ObserveContext,
        proposals: list[str] | None = None,
        index: int = 0,
    ) -> StatusSignal:
        """下游主动反问/提议：如「今天要怎么奖励好呢？」。

        仅呈现给 Agent 与用户；不构成授权，不自动执行。
        """
        rng = random.Random(ctx.seed + index)
        text = rng.choice(INITIATIVE_TEMPLATES).replace("{addr}", ctx.address)
        return StatusSignal(
            session_id=ctx.session_id,
            source="downstream",
            state_text="（主动话语）等待用户点单。",
            initiative_text=text,
            proposals=proposals or [
                "crew:suction_gentle", "crew:deep_throat", "crew:eruption", "crew:warm_hug",
            ],
        )
