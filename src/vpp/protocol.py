"""VPP（Virtual Play Protocol）核心类型。

分层说明：本模块只定义协议数据结构，不含任何业务规则。
业务校验在 director.py，模拟渲染在 crew.py，MCP 暴露在 server.py。

两类跨层消息：

- CueCard      下行「剧目卡」：导演 → 下游。抽象的动作 / 任务 / 状态管理指令。
- StatusSignal 上行「观测信号」：下游 → 导演。以文本为主的用户状态描述，
                可选命名指标（脉搏 / 硬度 / 湿润度 / 呼吸 / 瞳孔……），
                每项必须诚实携带 status: reported | unsupported | absent。

所有消息都带 protocol_version 与 extensions，未知扩展字段不破坏核心协议。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VPP_PROTOCOL_VERSION = "1.0"

Category = Literal["reward", "penalty", "scene", "control"]
CueKind = Literal["action", "task", "state_directive"]


# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha1_short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------- 标准错误


class ErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    EXPIRED = "EXPIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_HINTS: dict[ErrorCode, str] = {
    ErrorCode.INVALID_ARGUMENT: "参数缺失或取值非法，Agent 可修正后重试。",
    ErrorCode.SESSION_NOT_FOUND: "会话不存在。请先用 session_create 创建。",
    ErrorCode.INVALID_STATE: "当前会话状态不允许此操作。查看 state 字段与 play://safety/policy。",
    ErrorCode.CONSENT_REQUIRED: "需要用户授权：先 session_configure 明确允许项，再 session_authorize。",
    ErrorCode.LIMIT_EXCEEDED: "超出用户配置的强度/时长上限。不可通过 Agent 请求突破。",
    ErrorCode.ACTION_NOT_ALLOWED: "该效果不在用户允许清单内（fail-closed 拒绝）。",
    ErrorCode.EXPIRED: "会话已按最长时长过期。",
    ErrorCode.INTERNAL_ERROR: "内部错误（不应出现；出现即为缺陷）。",
}


class VPPError(Exception):
    """协议级错误。导演层抛出，工具层转为 in-band ActionResult。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "hint": ERROR_HINTS.get(self.code, ""),
        }
        if self.detail:
            out["detail"] = self.detail
        return out


# ---------------------------------------------------------------- 下行信封


class ActionEnvelope(BaseModel):
    """统一的 Action Envelope（导演层内部 + 下发的动作描述）。

    未知字段一律保留（extra="allow"），不破坏核心协议。
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str = Field(default=VPP_PROTOCOL_VERSION)
    request_id: str = Field(description="幂等键：同一 request_id 的重复提交不会重复执行")
    session_id: str
    action_type: str = Field(
        default="issue_action",
        description="issue_reward / issue_penalty / scene / control",
    )
    category: Category
    effect: str = Field(description="效果（道具）id，全集见 play://catalog/effects")
    intensity: int = Field(default=3, ge=0, le=10, description="0-10；受会话配置上限硬性约束")
    duration_s: int = Field(default=0, ge=0, description="虚拟持续时间（秒），0 表示瞬时")
    reason: str = Field(default="", max_length=200, description="导演备注；审计中只保留脱敏摘要")
    dry_run: bool = Field(default=False, description="预演：完整校验但不改变任何业务状态")
    created_at: str = Field(default_factory=now_iso)
    extensions: dict[str, Any] = Field(default_factory=dict)

    def digest(self) -> str:
        payload = (
            f"{self.session_id}:{self.request_id}:{self.category}:"
            f"{self.effect}:{self.intensity}:{self.duration_s}"
        )
        return sha1_short(payload)


# ---------------------------------------------------------------- 下行剧目卡


class CueCard(BaseModel):
    """CueCard：下发给下游的抽象指令。

    kind 三类（下游任务书，见 docs/CONTRACT.zh-CN.md）：
    - action         一次抽象动作（银铃敲响、聚光灯亮起……纯舞台意象）
    - task           一段任务/等待（沙漏、反省任务卡……）
    - state_directive 状态管理指令（开场、换幕、观测请求……）

    刻意不含任何硬件语义（无档位、无波形、无电机参数）。
    """

    model_config = ConfigDict(extra="allow")

    cue_id: str
    protocol_version: str = Field(default=VPP_PROTOCOL_VERSION)
    session_id: str
    request_id: str
    kind: CueKind = "action"
    category: Category = "reward"
    effect: str
    gesture: str = Field(
        description="舞台手势：strike/present/withdraw/hold/fade/crescendo/flick/snap/open/close"
    )
    intensity: int = 0
    duration_s: int = 0
    stage_note: str = Field(default="", description="导演备注（已脱敏）")
    semantics_gloss: str = Field(
        default="",
        description="诚实语义注记：这个道具对应现实中哪一类活动（防止下游/Agent 按字面猜测）",
    )
    issued_at: str = Field(default_factory=now_iso)
    simulated: bool = Field(default=True, description="恒为 true：本层只产生模拟效果")
    extensions: dict[str, Any] = Field(default_factory=dict)


class ScheduledCue(BaseModel):
    """虚拟时间线上的待执行剧目卡（惰性求值，无真实定时器）。"""

    cue_id: str
    due_offset_s: float = Field(description="相对场景虚拟时钟的到期偏移（秒）")
    cue: CueCard
    rendered: bool = False


# ---------------------------------------------------------------- 上行观测信号


class MetricReading(BaseModel):
    """单条命名指标读数。

    诚实契约（本层的核心要求之一）：
    - status="reported"    必须携带 value（数值或短文本）；
    - status="unsupported" 下游不掌握该观测能力，如实上报即可；
    - status="absent"      该指标在当前场景不存在/不适用；
    - 严禁编造数值。不支持与不存在是合法且被尊重的答案。
    """

    name: str = Field(description="pulse / hardness / wetness / breath / pupil 或自定义名")
    status: Literal["reported", "unsupported", "absent"]
    value: float | str | None = None
    unit: str | None = None
    note: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _check_honesty(self) -> "MetricReading":
        if self.status == "reported" and self.value is None:
            raise ValueError(
                "诚实契约：status=reported 必须携带 value；"
                "不掌握请报 unsupported，不适用请报 absent，不得编造。"
            )
        return self


class StatusSignal(BaseModel):
    """StatusSignal：下游 → 导演的用户状态观测信号。

    主形态是 state_text：用户状态的自然语言或格式化文本描述。
    命名指标是可选补充；两种来源：
    - downstream  下游观测侧（设备/宿主观测适配器）
    - host_chat    用户与 MCP Agent 对话中的自述反馈

    本层不依据本信号做任何安全决策——信号采集与安全处理归下游与 Agent。
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str = Field(default=VPP_PROTOCOL_VERSION)
    signal_id: str = Field(default_factory=lambda: new_id("sig"))
    session_id: str | None = None
    source: Literal["downstream", "host_chat"]
    observed_at: str = Field(default_factory=now_iso)
    state_text: str = Field(description="用户状态描述（自然语言或格式化文本）")
    state_text_format: Literal["plain", "structured"] = Field(default="plain")
    metrics: list[MetricReading] = Field(default_factory=list)
    advisory_tags: list[str] = Field(default_factory=list, description="可选建议性标签，仅呈现不做策略")
    initiative_text: str = Field(
        default="",
        max_length=500,
        description=(
            "下游主动话语/反问（如「今天要怎么奖励好呢？」）："
            "仅呈现给 Agent 与用户，不构成授权，不自动执行"
        ),
    )
    proposals: list[str] = Field(
        default_factory=list,
        description="下游提议的效果 id（仅供参考；执行仍须通过全部校验与用户边界）",
    )
    extensions: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- 下游能力注册


class CapabilitySpec(BaseModel):
    """能力菜单中的一项：下游实际支持的具体效果。

    注册 ≠ 授权：声明只让效果变得"可寻址"（crew:<effect_id>），
    能否执行仍由用户边界决定（允许清单 + 行为开关 + 强度/时长上限）。
    """

    model_config = ConfigDict(extra="allow")

    effect_id: str = Field(
        description="下游本地能力 id（小写字母/数字/下划线）；接入后以 crew:<effect_id> 寻址",
        pattern=r"^[a-z0-9_]{1,40}$",
    )
    label: str = Field(max_length=60)
    category: Category = Field(default="reward")
    channels: list[str] = Field(default_factory=lambda: ["tactile_sensation"])
    kink_flags: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=300)
    actual_semantics: str = Field(
        default="",
        max_length=400,
        description="诚实语义注记：这个能力对应现实中哪一类活动（必填，不许只给营销词）",
    )
    intensity_max: int = Field(default=8, ge=1, le=8)
    duration_min_s: int = Field(default=0, ge=0)
    duration_max_s: int = Field(default=3600, ge=0)
    score_delta: int = Field(default=0)
    gestures: list[str] = Field(default_factory=lambda: ["hold", "fade", "crescendo"])
    simulated: bool = Field(default=True, description="恒为 true")


class CapabilitiesDeclaration(BaseModel):
    """下游连接后的能力菜单注册（上行握手消息）。"""

    model_config = ConfigDict(extra="allow")

    protocol_version: str = Field(default=VPP_PROTOCOL_VERSION)
    crew_name: str = Field(max_length=60)
    session_id: str | None = None
    declared_at: str = Field(default_factory=now_iso)
    effects: list[CapabilitySpec] = Field(default_factory=list)
    notes: str = Field(default="", max_length=300)


# ---------------------------------------------------------------- 统一结果


class ActionResult(BaseModel):
    """统一的 Action Result。所有动作（含拒绝）都返回本结构。

    - accepted  是否通过校验（拒绝时附带 error）
    - executed  是否真正落了状态（dry_run 恒为 False）
    - simulated 恒为 True：全部效果为本地模拟
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str = Field(default=VPP_PROTOCOL_VERSION)
    accepted: bool
    executed: bool
    simulated: bool = True
    request_id: str
    session_id: str
    dry_run: bool = False
    idempotent_replay: bool = Field(default=False, description="命中幂等缓存：未重复执行")
    state: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    scheduled_effects: list[CueCard] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    audit_id: str = ""
    error: dict[str, Any] | None = None
