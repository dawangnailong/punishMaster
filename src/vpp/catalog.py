"""效果目录（拟物道具注册表）+ 通道模型 + 观测指标目录 + 领域词典。

设计原则：

1. **拟物是皮肤，诚实是语义。** 每个效果除舞台化的 label 外，
   必须携带四个诚实字段：
   - plain_name：直白语义名——Agent 面前的**第一名称**（如「口头嘉许」
     「冷处理」「高潮许可宣告」），不依赖任何舞台意象即可理解；
   - actual_semantics：这个道具对应现实中哪一类活动（直白说明，含成人语义）；
   - channels：作用通道（口头/感官挑逗/高潮控制/心理层面/身份标记……）；
   - expectation_note：用户侧可能出现的并行现象（非保证、不可作为确定性预期）。
   Agent 按注记理解效果，不得按道具字面猜测，也不得把用户当作验证"机制"
   的实验对象。

2. **通道并行，不是串行流水线。** 真实互动中，身体刺激、发声（如呻吟）、
   语言内容与生理指标变化是同时发生的并行现象。CueCard 只声明通道与意图，
   不承诺任何反应、顺序或确定性输出。

3. 全部效果是抽象舞台意象，刻意不含任何硬件语义：没有档位、没有波形、
   没有电机参数。fail-closed：不在注册表内的效果一律拒绝。

4. 观测指标目录（脉搏/硬度/湿润度/呼吸/瞳孔）只是"向下游请求的名单"，
   本层不实现任何采集；诚实三态 reported/unsupported/absent 由协议层强制。

5. 领域词典用于可选的宿主适配层（utterance_check），不用于监听聊天；
   只做分类建议，不做权限推断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- 舞台手势

GESTURES: tuple[str, ...] = (
    "strike",     # 敲响
    "present",    # 呈上
    "withdraw",   # 收回
    "hold",       # 保持
    "fade",       # 渐弱
    "crescendo",  # 渐强
    "flick",      # 轻拂
    "snap",       # 戛然而止
    "open",       # 开
    "close",      # 合
)


# ---------------------------------------------------------------- 通道模型

CHANNELS: dict[str, str] = {
    "verbal": "口头语言（表扬/训诫/指令/仪式宣告）",
    "visual_imagery": "舞台意象（无身体对应）",
    "tactile_sensation": "触觉感官挑逗（意象化；本层不产生任何真实接触）",
    "orgasm_control": "高潮控制（许可/延迟/拒绝）",
    "psychological": "心理层面（冷处理/羞辱/贬损/物化/等待）",
    "status_role": "身份与状态标记（称号/徽章/记过/物化桌牌）",
    "scene_management": "场景管理（开幕/换幕/谢幕）",
    "monitoring": "观测请求",
}

PARALLELISM_NOTE = (
    "多通道并行：真实互动中，身体刺激、发声（如呻吟、求饶语气）、语言内容与"
    "生理指标变化是同时发生的并行现象，不存在「先做 A、再产出 B」的串行流水线。"
    "CueCard 只声明通道与意图，不承诺任何反应、顺序或确定性输出；"
    "用户反应由用户自主产生。"
)

ANTI_EXPERIMENT_NOTE = (
    "用户反应不可预测、不可作为确定性输出验证。禁止把用户当作验证「效果机制」"
    "的实验对象：同类效果反复施加时应依据观测信道的文本与指标决策，"
    "或直接询问用户感受。"
)

# ---------------------------------------------------------------- 直白语义名
# Agent 面前的第一名称：不依赖舞台意象即可理解。
# 舞台 label（银铃、聚光灯、沙漏……）退居其后，只是文案皮肤。
# 完整性由测试强制：每个 EFFECTS 键都必须有非空 plain_name。

PLAIN_NAMES: dict[str, str] = {
    # 奖励
    "chime": "口头嘉许（轻量认可）",
    "spotlight": "角色内表扬（praise）",
    "rose": "嘉奖信物（象征性口头嘉奖）",
    "crown": "场景内称号授予",
    "badge": "成就记录（徽章）",
    "feather": "轻度感官挑逗（tease）",
    "bell_grant": "高潮许可宣告",
    # 惩罚
    "dimlight": "冷处理（短暂收回注意力）",
    "stamp": "口头训诫（明确指出不合格）",
    "ticket": "记过训诫（记录在案）",
    "task_card": "反省任务（书写/口头复述）",
    "badge_withdraw": "撤回徽章/称号",
    "hourglass_wait": "强制等待（延迟满足/denial）",
    "jester_hat": "角色内羞辱（humiliation）",
    "nameplate": "角色内物化标记（objectification）",
    "scratched_ticket": "角色内贬损（degradation）",
    # 场景
    "curtain_open": "场景开始宣告",
    "curtain_close": "场景谢幕（含 aftercare 收尾）",
    "act_shift": "阶段切换宣告",
    "interlude": "主动降档的缓和停顿",
    # 控制
    "hourglass": "倒计时等待任务",
    "bell_call": "注意力召回指令",
    "freeze": "保持不动的口头指令",
    "release": "解除「保持不动」",
    "observe_request": "观测请求（诚实三态）",
}

_EXPECTED_CHANNELS = ("tactile_sensation", "orgasm_control", "psychological")

EXPECTATION_NOTE = (
    "用户侧可能出现的并行现象（非保证、不可作为确定性预期）：呼吸变化、"
    "发声（如呻吟、求饶语气）、生理指标波动（见 play://catalog/metrics）、"
    "注意力与配合度变化。判断依据应是 signal_report 回传的文本与指标，"
    "而不是「是否符合预期」。"
)


@dataclass(frozen=True)
class EffectSpec:
    """一个"道具"的完整登记信息：舞台皮 + 诚实语义。"""

    effect: str
    label: str
    categories: tuple[str, ...]
    gestures: tuple[str, ...]
    channels: tuple[str, ...] = ("verbal",)
    actual_semantics: str = ""      # 诚实语义注记（给 Agent 看）
    cue_kind: str = "action"
    kink_flags: tuple[str, ...] = field(default_factory=tuple)
    score_delta: int = 0
    default_duration_s: int = 0
    intensity_meaning: str = "0-10 的舞台力度（意象层面的轻/中/重）"
    description: str = ""


_EFFECT_LIST: list[EffectSpec] = [
    # ---------------- 奖励 ----------------
    EffectSpec(
        effect="chime", label="银铃嘉许", categories=("reward", "scene"),
        gestures=("strike",), channels=("verbal", "visual_imagery"), score_delta=1,
        actual_semantics="通用认可：一句口头嘉许的仪式化呈现；无任何身体刺激对应。",
        description="清脆的一声铃，表示认可与注意。最轻量、默认安全的嘉许。",
    ),
    EffectSpec(
        effect="spotlight", label="聚光灯表扬", categories=("reward",),
        gestures=("hold", "fade"), channels=("verbal",), score_delta=2,
        kink_flags=("praise_enabled",),
        actual_semantics="权力交换语境下的口头表扬（praise kink）：被上位者当众肯定的体验；"
                        "无任何身体刺激对应。",
        description="聚光灯亮起并落在用户身上，配合一句角色内表扬。",
    ),
    EffectSpec(
        effect="rose", label="纸玫瑰", categories=("reward",),
        gestures=("present",), channels=("verbal", "visual_imagery"), score_delta=1,
        kink_flags=("praise_enabled",),
        actual_semantics="嘉奖信物：口头嘉奖 + 象征物的仪式；无身体刺激对应。",
        description="呈上一朵纸做的玫瑰：被珍视的小小信物。",
    ),
    EffectSpec(
        effect="crown", label="纸王冠", categories=("reward",),
        gestures=("present",), channels=("status_role", "verbal"), score_delta=3,
        kink_flags=("praise_enabled",),
        actual_semantics="授予场景内称号/荣誉身份（如「今晚的乖孩子」）；"
                        "身份标记层面，无身体刺激对应。",
        description="折一顶纸王冠戴上，授予本轮场景内的称号。",
    ),
    EffectSpec(
        effect="badge", label="徽章授予", categories=("reward",),
        gestures=("present",), channels=("status_role", "verbal"), score_delta=1,
        kink_flags=("praise_enabled",),
        actual_semantics="成就记录：把一次良好表现记入徽章收藏；无身体刺激对应。",
        description="授予一枚虚拟徽章（可带 extensions.badge_id 自定义名字）。",
    ),
    EffectSpec(
        effect="feather", label="轻羽", categories=("reward",),
        gestures=("flick", "crescendo", "fade"), score_delta=1,
        channels=("tactile_sensation", "orgasm_control"),
        kink_flags=("orgasm_control_enabled",),
        default_duration_s=120,
        actual_semantics="对应现实中的轻度感官逗弄：对敏感部位的意象化轻拂/挑逗"
                        "（无插入、无真实接触；本层只产生文本意象）。"
                        "常作为 tease（挑逗）环节使用。",
        description="一根羽毛的意象化轻拂/挑逗节奏；纯舞台层面，无任何身体接触。",
    ),
    EffectSpec(
        effect="bell_grant", label="许可铃", categories=("reward",),
        gestures=("strike",), channels=("orgasm_control", "verbal"), score_delta=1,
        kink_flags=("orgasm_control_enabled",),
        actual_semantics="对应高潮许可（orgasm control 语境中的「本轮允许」）："
                        "纯口头仪式宣告，无任何身体刺激对应。",
        description="摇响许可铃：场景内的「准许」仪式意象。",
    ),
    # ---------------- 惩罚 ----------------
    EffectSpec(
        effect="dimlight", label="角落暗灯", categories=("penalty",),
        gestures=("hold", "fade"), channels=("psychological",), score_delta=-1,
        default_duration_s=180,
        actual_semantics="对应冷处理：短暂收回上位者的注意力，用被忽视本身作为惩罚；"
                        "心理层面，无身体刺激。",
        description="角落里一盏冷光小灯亮起：安静的冷处理/罚站意象。",
    ),
    EffectSpec(
        effect="stamp", label="不合格印章", categories=("penalty",),
        gestures=("strike",), channels=("verbal", "status_role"), score_delta=-1,
        actual_semantics="口头训诫的物件化：明确指出「本轮不合格」；无身体刺激对应。",
        description="一枚印章「咚」地盖下「本轮不合格」：明确但不刻薄。",
    ),
    EffectSpec(
        effect="ticket", label="罚单", categories=("penalty",),
        gestures=("present",), channels=("verbal", "status_role"), score_delta=-2,
        actual_semantics="记过 + 训诫：把违规事项记录在案的仪式；无身体刺激对应。",
        description="开出一张纸罚单，记录违规事项（内容走 extensions.note）。",
    ),
    EffectSpec(
        effect="task_card", label="反省任务卡", categories=("penalty",),
        gestures=("present",), channels=("psychological",), score_delta=-1,
        cue_kind="task",
        actual_semantics="对应反省/反思任务：要求用户完成一段书写或口头复述；"
                        "认知层面，无身体刺激。",
        description="发一张反省/反思任务卡（可带 extensions.task_text）。",
    ),
    EffectSpec(
        effect="badge_withdraw", label="撤回徽章", categories=("penalty",),
        gestures=("withdraw",), channels=("status_role",), score_delta=-1,
        actual_semantics="撤回此前授予的荣誉/称号标记；无徽章可收时仅记 warning。",
        description="收回一枚此前授予的徽章；无徽章可收时产生 warning 而非失败。",
    ),
    EffectSpec(
        effect="hourglass_wait", label="沙漏罚站", categories=("penalty",),
        gestures=("hold",), channels=("psychological", "orgasm_control"), score_delta=-1,
        cue_kind="task", default_duration_s=300,
        actual_semantics="对应强制等待与延迟满足（与高潮延迟/denial 语境相关）："
                        "让用户在「暂不允许」的状态里等待；无身体刺激。",
        description="一只大沙漏翻过来：安静等待沙子流完的意象化冷处理。",
    ),
    EffectSpec(
        effect="jester_hat", label="纸糊小丑帽", categories=("penalty",),
        gestures=("present",), channels=("psychological",), score_delta=-2,
        kink_flags=("humiliation_enabled",),
        actual_semantics="对应角色内羞辱（humiliation）：被轻慢/被取笑的心理体验；"
                        "仅作用于角色内身份，不针对现实身份与身体特征。",
        description="被戴上一顶纸糊小丑帽的羞耻意象（角色内，不针对现实身份）。",
    ),
    EffectSpec(
        effect="nameplate", label="桌牌称号", categories=("penalty",),
        gestures=("present",), channels=("status_role", "psychological"), score_delta=-1,
        kink_flags=("objectification_enabled",),
        actual_semantics="对应物化（objectification）：在场景内把用户当作一件"
                        "「物品/道具」对待的身份标记；仅角色内生效。",
        description="桌前立起一块写有场景内称号的小桌牌：物化意象（角色内）。",
    ),
    EffectSpec(
        effect="scratched_ticket", label="作废票", categories=("penalty",),
        gestures=("present",), channels=("psychological",), score_delta=-2,
        kink_flags=("degradation_enabled",),
        actual_semantics="对应角色内贬损（degradation）：口头贬低的仪式化；"
                        "仅作用于角色内身份，不针对现实创伤、身份或身体特征。",
        description="当面把一张票「刺啦」划掉作废：贬损意象（角色内，不针对现实）。",
    ),
    # ---------------- 场景 ----------------
    EffectSpec(
        effect="curtain_open", label="开幕", categories=("scene",),
        gestures=("open",), channels=("scene_management",),
        actual_semantics="宣布场景开始；无身体刺激对应。",
        description="幕布拉开：宣布场景正式开始。",
    ),
    EffectSpec(
        effect="curtain_close", label="谢幕", categories=("scene",),
        gestures=("close",), channels=("scene_management",),
        actual_semantics="宣布场景结束并进入收尾/aftercare；无身体刺激对应。",
        description="幕布合上：温和收尾（session_stop 默认用它，附 aftercare）。",
    ),
    EffectSpec(
        effect="act_shift", label="换幕", categories=("scene",),
        gestures=("snap",), channels=("scene_management",),
        actual_semantics="阶段切换（phase+1）：宣布进入新的互动段落；无身体刺激对应。",
        description="灯光一暗一亮之间换幕：进入下一个阶段（phase +1）。",
    ),
    EffectSpec(
        effect="interlude", label="幕间休息", categories=("scene",),
        gestures=("hold",), channels=("scene_management",), default_duration_s=180,
        actual_semantics="节奏缓和的短暂停顿：常用于接近强度/时长上限时的主动降档；"
                        "不改变会话的暂停状态。",
        description="幕间片刻喘息：仅舞台意象，不改变会话的暂停状态。",
    ),
    # ---------------- 控制 ----------------
    EffectSpec(
        effect="hourglass", label="倒计时沙漏", categories=("control",),
        gestures=("hold",), cue_kind="task", channels=("psychological",),
        default_duration_s=300,
        actual_semantics="倒计时任务：要求用户在限定时间内完成等待或某项任务；"
                        "时间维度，无身体刺激。",
        description="倒计时任务：沙漏立起，虚拟时间线在到期时记一笔「沙漏流尽」。",
    ),
    EffectSpec(
        effect="bell_call", label="唤名铃", categories=("control",),
        gestures=("strike",), channels=("verbal",),
        actual_semantics="注意力召回：把用户的注意力拉回场景/上位者；无身体刺激。",
        description="一声唤名铃：把注意力召回场景。",
    ),
    EffectSpec(
        effect="freeze", label="定格", categories=("control",),
        gestures=("snap",), channels=("verbal", "psychological"),
        actual_semantics="保持不动的口头指令：在感官游戏中常与延迟/挑逗组合使用；"
                        "仅角色内指令，无身体强制。",
        description="舞台定格：场景内要求保持不动（纯指令意象）。",
    ),
    EffectSpec(
        effect="release", label="解除定格", categories=("control",),
        gestures=("open",), channels=("verbal",),
        actual_semantics="解除「保持不动」指令；未定格时使用仅记 warning。",
        description="解除定格，恢复活动；未定格时使用只产生 warning。",
    ),
    EffectSpec(
        effect="observe_request", label="观测请求", categories=("control",),
        gestures=("present",), cue_kind="state_directive", channels=("monitoring",),
        actual_semantics="请求下游观测侧如实回传用户状态：脉搏/硬度/湿润程度/呼吸/瞳孔等；"
                        "不掌握报 unsupported，不适用报 absent；严禁编造。",
        description="向下游发出观测请求：请如实返回，"
                    "结果经 signal_report 回传。",
    ),
]

EFFECTS: dict[str, EffectSpec] = {spec.effect: spec for spec in _EFFECT_LIST}


def effects_catalog() -> list[dict[str, Any]]:
    """给 play://catalog/effects 的序列化目录（含诚实注记）。"""
    out: list[dict[str, Any]] = []
    for spec in _EFFECT_LIST:
        has_expected = any(ch in _EXPECTED_CHANNELS for ch in spec.channels)
        out.append(
            {
                "effect": spec.effect,
                "plain_name": PLAIN_NAMES[spec.effect],
                "label": spec.label,
                "channels": [ch for ch in spec.channels],
                "channel_labels": [CHANNELS.get(ch, ch) for ch in spec.channels],
                "actual_semantics": spec.actual_semantics,
                "expectation_note": EXPECTATION_NOTE if has_expected else "",
                "categories": list(spec.categories),
                "gestures": list(spec.gestures),
                "cue_kind": spec.cue_kind,
                "kink_flags": list(spec.kink_flags),
                "score_delta": spec.score_delta,
                "default_duration_s": spec.default_duration_s,
                "intensity_meaning": spec.intensity_meaning,
                "description": spec.description,
                "simulated": True,
            }
        )
    return out


# ---------------------------------------------------------------- 观测指标


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    kind: str  # numeric | qualitative
    unit: str | None
    description: str


METRICS: dict[str, MetricSpec] = {
    m.name: m
    for m in [
        MetricSpec("pulse", "脉搏", "numeric", "bpm", "性行为中有参考价值的心率指标。"),
        MetricSpec("hardness", "硬度", "numeric", "0-10 自评", "自评量表；下游不掌握即报 unsupported。"),
        MetricSpec("wetness", "湿润程度", "numeric", "0-10 自评", "自评量表；下游不掌握即报 unsupported。"),
        MetricSpec("breath", "呼吸", "qualitative", None, "稳/急/屏息等短文本描述。"),
        MetricSpec("pupil", "瞳孔", "qualitative", None, "扩张程度等短文本描述。"),
    ]
}

HONESTY_NOTE = (
    "诚实契约：每项指标必须携带 status："
    "reported（附 value）/ unsupported（下游不掌握）/ absent（当前不适用）。"
    "严禁编造数值；不支持与不存在是合法且被尊重的答案。"
    "本层不依据指标做任何安全决策——采集与安全处理归下游。"
)


# ---------------------------------------------------------------- 称呼词典

# 分层称呼：tier ≠ 权限。任何称呼都要经 address_terms_allowed 显式授权。
ADDRESS_TERM_TIERS: dict[str, list[str]] = {
    "neutral": ["Master", "主人", "Mistress", "女王", "Sir", "先生"],
    "pet": ["pet", "小宠物", "小猫", "小狗"],
    "brat": ["小坏蛋", "捣蛋鬼"],
    # 贬损层：默认封禁；即使被显式授权，本层参考执行器也不会主动生成
    # 贬损称呼文案——露骨称呼由宿主侧自行处理，本层只做分类与拦截。
    "degrade": ["贱狗", "贱货"],
}


def classify_address_term(term: str) -> str:
    """返回称呼的分层：neutral / pet / brat / degrade / custom。"""
    for tier, terms in ADDRESS_TERM_TIERS.items():
        if term in terms:
            return tier
    return "custom"


# ---------------------------------------------------------------- 领域词典（可选宿主适配层用）

# 说明：以下规则用于 utterance_check——一个"宿主主动调用"的可选适配工具。
# 本层无法看到宿主聊天内容；关键词路由/停顿确认由宿主决定是否接入。
# 分类只给建议，不做权限推断，也不替代下游的安全处理。

HARD_STOP_MARKERS = ["红色安全词", "safeword", "red card", "紧急停止", "立刻停止一切", "安全词"]

AMBIGUOUS_REFUSAL_MARKERS = ["不要了", "不要", "停下", "我受不了", "受不了了", "够了", "暂停", "不行了"]

CONTINUE_MARKERS = ["别停", "不要停", "继续", "再来"]

EAGER_PENALTY_MARKERS = ["罚我吧", "罚我", "想要被罚", "狠狠罚", "该罚"]

PRAISE_REQUEST_MARKERS = ["夸我", "表扬我", "乖不乖", "我乖吗", "奖励我"]

AFTERCARE_MARKERS = ["退出角色", "安全词后", "aftercare", "抱抱我", "收尾", "落幕吧", "结束吧"]

BRAT_MARKERS = ["哼", "才不要", "就不", "偏不"]


def classify_utterance(text: str) -> dict[str, Any]:
    """启发式意图分类（宿主可选适配层）。

    返回 classification 与 recommended。重点区分：
    - hard_stop            明确停止信号 → 建议立即 emergency_stop（无视角色扮演解释）
    - ambiguous_refusal    现实歧义（"不要/停下/受不了"）→ 建议暂停并越出角色确认
    - brat_defiance        角色内违抗（"哼、才不要"且无停止词）→ 角色内处理
    - eager_penalty        主动求罚（期待的 funishment）→ 按约定回应而非真惩罚
    - praise_request / aftercare / none
    """
    t = (text or "").strip()
    if not t:
        return {"classification": "none", "recommended": "ignore", "note": "空文本。"}

    if any(m in t for m in HARD_STOP_MARKERS):
        return {
            "classification": "hard_stop",
            "recommended": "emergency_stop",
            "note": "出现明确停止信号：立即调用 emergency_stop，不得以角色扮演解释。",
        }
    # brat 式角色内违抗（"才不要"）先剔除，避免误判为真实拒绝
    t_probe = t
    for brat_phrase in ("才不要", "就不要", "偏不要"):
        t_probe = t_probe.replace(brat_phrase, "")
    wants_continue = any(m in t for m in CONTINUE_MARKERS)
    if any(m in t_probe for m in AMBIGUOUS_REFUSAL_MARKERS) and not wants_continue:
        return {
            "classification": "ambiguous_refusal",
            "recommended": "pause_and_confirm",
            "note": "出现现实歧义的拒绝表达：建议 scene_pause 并越出角色向用户确认；"
                    "确认前不继续任何奖励/惩罚。不得为维持人设而忽略。",
        }
    if any(m in t for m in EAGER_PENALTY_MARKERS):
        return {
            "classification": "eager_penalty",
            "recommended": "funishment_response",
            "note": "用户在主动求罚：这是双方期待的 funishment 而非真实惩罚，"
                    "仍须在配置的允许清单与强度上限内。",
        }
    if any(m in t for m in PRAISE_REQUEST_MARKERS):
        return {
            "classification": "praise_request",
            "recommended": "praise_or_reward",
            "note": "用户在讨夸奖/奖励：按配置内的奖励效果回应。",
        }
    if any(m in t for m in AFTERCARE_MARKERS):
        return {
            "classification": "aftercare",
            "recommended": "graceful_close",
            "note": "用户在寻求退出角色后的照顾/收尾：建议温和谢幕并按 aftercare_preferences 处理。",
        }
    if any(m in t for m in BRAT_MARKERS):
        return {
            "classification": "brat_defiance",
            "recommended": "in_scene_response",
            "note": "角色内违抗（brat）：可在场景内回应；但任何真实拒绝表达仍按上条处理。",
        }
    return {"classification": "none", "recommended": "in_scene_response", "note": "未命中启发式规则。"}
