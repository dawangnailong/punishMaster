"""共享核心语义本体。

设备可以只实现其中一部分；每个动作的 realization 由设备自己声明。
厂商扩展动作使用自己的 action_id，但必须落回同一套契约。

核心动作只描述「对用户做什么」，不描述电机/波形/寄存器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CoreAction:
    action_id: str
    label: str
    category: str
    intent_examples: tuple[str, ...]
    description: str
    params_schema: dict[str, Any] = field(default_factory=dict)


CORE_ACTIONS: dict[str, CoreAction] = {
    "stimulate": CoreAction(
        action_id="stimulate",
        label="刺激",
        category="stimulate",
        intent_examples=(
            "奖励主人尝一下自己最里面",
            "给我一点刺激",
            "深一点，慢一点",
        ),
        description=(
            "对用户施加刺激。深度、节奏、温度等由语义参数表达；"
            "设备若不支持某种参数组合，应如实拒绝或降级并说明。"
        ),
        params_schema={
            "depth": {"enum": ["shallow", "deep"], "default": "shallow"},
            "rhythm": {"enum": ["steady", "pulse", "wave"], "default": "steady"},
            "warmth": {"enum": ["none", "warm"], "default": "none"},
        },
    ),
    "tease": CoreAction(
        action_id="tease",
        label="挑逗",
        category="tease",
        intent_examples=("先逗一逗，别让我太快", "只给一点点"),
        description="轻度、点到即止的挑逗；通常映射到设备的轻档模式。",
    ),
    "hold": CoreAction(
        action_id="hold",
        label="保持",
        category="hold",
        intent_examples=("保持住，不许动", "就这样别变"),
        description="维持当前动作与档位。",
    ),
    "release": CoreAction(
        action_id="release",
        label="释放",
        category="release",
        intent_examples=("可以了，放开", "结束这一段"),
        description="结束当前保持/动作；与停止共用同一条停止路径。",
    ),
    "check": CoreAction(
        action_id="check",
        label="检查",
        category="check",
        intent_examples=(
            "先用指腹检查下肛周今天有没有偷吃，再决定下一步",
            "让我看看现在是什么状态",
        ),
        description=(
            "检查/观察。不是所有设备都具备该能力；不支持时必须显式返回 "
            "unsupported，不得用旁白冒充物理检查。"
        ),
    ),
    "rest": CoreAction(
        action_id="rest",
        label="休息",
        category="rest",
        intent_examples=("先暖一暖，休息一下", "缓一缓"),
        description="低强度安抚/暖意，不追求刺激。",
    ),
    "stop": CoreAction(
        action_id="stop",
        label="停止",
        category="stop",
        intent_examples=("停下", "立刻停"),
        description="立即停止；与 device_stop 走同一条路径，幂等。",
    ),
}


def core_action_ids() -> tuple[str, ...]:
    return tuple(CORE_ACTIONS)
