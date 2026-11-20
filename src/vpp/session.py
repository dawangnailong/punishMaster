"""会话实体与状态机。

状态机（转换必须显式校验，不接受任意跳转）：

    DRAFT ──configure+authorize──▶ READY ──开场──▶ ACTIVE ⇄ PAUSED
                                       │             │      │
                                       └──stop──────▶┴─stop──▶ STOPPED
    （ACTIVE/PAUSED 虚拟时钟超过场景时长上限 → 惰性转 EXPIRED）
    emergency_stop 可从任意状态直达 STOPPED，幂等，立即清空虚拟时间线。

所有计时基于虚拟时钟（注入 Clock），无任何后台线程/定时器。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .config import SessionConfig
from .protocol import (
    ActionEnvelope,
    ActionResult,
    CueCard,
    ScheduledCue,
    StatusSignal,
    new_id,
    now_iso,
    parse_iso,
    sha1_short,
)


class SessionState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    EXPIRED = "EXPIRED"


# 合法状态转换表（emergency_stop 走独立通道：任意状态 → STOPPED）
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.DRAFT: frozenset({SessionState.READY, SessionState.STOPPED}),
    SessionState.READY: frozenset({SessionState.ACTIVE, SessionState.STOPPED}),
    SessionState.ACTIVE: frozenset(
        {SessionState.PAUSED, SessionState.STOPPED, SessionState.EXPIRED}
    ),
    SessionState.PAUSED: frozenset(
        {SessionState.ACTIVE, SessionState.STOPPED, SessionState.EXPIRED}
    ),
    SessionState.STOPPED: frozenset(),
    SessionState.EXPIRED: frozenset(),
}


class HistoryEvent(BaseModel):
    """审计友好的历史事件：不含任何完整文案，只留类别与脱敏摘要。"""

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    at: str = Field(default_factory=now_iso)
    kind: str = Field(
        description="session_created|configured|authorized|state_change|action|"
                    "signal|cue_due|emergency_stop"
    )
    summary: str = ""
    request_id: str | None = None
    category: str | None = None
    effect: str | None = None
    intensity: int | None = None
    duration_s: int | None = None
    gesture: str | None = None
    stage_note: str | None = Field(default=None, description="脱敏后的导演备注（回放重建渲染用）")
    error_code: str | None = None
    state_after: str | None = None
    score_after: int | None = None
    message_sha: str | None = Field(
        default=None, description="渲染文案的短哈希（replay 比对用，不留明文）"
    )


class Session(BaseModel):
    """会话全部状态（Pydantic 化，便于持久化 round-trip）。"""

    session_id: str = Field(default_factory=lambda: new_id("ses"))
    created_at: str = Field(default_factory=now_iso)
    state: SessionState = SessionState.DRAFT

    config: SessionConfig | None = None
    configured: bool = False  # 是否经过显式的 session_configure
    consent_note: str = ""
    authorized_at: str | None = None

    # 虚拟时钟锚点
    activated_at: str | None = None
    deadline_s: int = 0
    paused_at: str | None = None
    paused_total_s: float = 0.0

    # 场景内状态
    score: int = 0
    badges: list[str] = Field(default_factory=list)
    phase: int = 0
    frozen: bool = False
    effect_counts: dict[str, int] = Field(default_factory=dict, description="各类效果累计次数（反实验护栏用）")

    # 记录
    history: list[HistoryEvent] = Field(default_factory=list)
    signals: list[StatusSignal] = Field(default_factory=list)
    results: dict[str, ActionResult] = Field(default_factory=dict)
    timeline: list[ScheduledCue] = Field(default_factory=list)

    # 下游注册的能力菜单（crew:<effect_id> → CapabilitySpec 序列化；注册 ≠ 授权）
    crew_effects: dict[str, dict[str, Any]] = Field(default_factory=dict)
    crew_name: str | None = None

    # 确定性
    rng_salt: str = Field(default_factory=lambda: new_id("salt"))

    # ---------------------------------------------------------------- 状态机

    def can_transition(self, target: SessionState) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: SessionState) -> None:
        if not self.can_transition(target):
            raise ValueError(f"illegal transition {self.state.value} -> {target.value}")
        self.state = target

    # ---------------------------------------------------------------- 事件

    def record(self, event: HistoryEvent) -> HistoryEvent:
        self.history.append(event)
        return event

    def action_events(self) -> list[HistoryEvent]:
        return [e for e in self.history if e.kind == "action" and e.request_id]

    # ---------------------------------------------------------------- 虚拟时钟

    def virtual_now(self, clock_now) -> float:
        """场景虚拟时钟（秒）。未激活返回 -1；暂停期间冻结。"""
        if not self.activated_at:
            return -1.0
        base = parse_iso(self.activated_at)
        elapsed = (clock_now - base).total_seconds() - self.paused_total_s
        if self.paused_at:
            elapsed -= (clock_now - parse_iso(self.paused_at)).total_seconds()
        return max(0.0, elapsed)

    def public_snapshot(self, virtual_now_s: float) -> dict[str, Any]:
        cfg = self.config
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "authorized": self.authorized_at is not None,
            "score": self.score,
            "badges": list(self.badges),
            "phase": self.phase,
            "frozen": self.frozen,
            "scene_elapsed_s": round(virtual_now_s, 1) if virtual_now_s >= 0 else None,
            "scene_deadline_s": self.deadline_s or None,
            "timeline_pending": sum(1 for c in self.timeline if not c.rendered),
            "signals_count": len(self.signals),
            "history_count": len(self.history),
            "crew_effects_registered": len(self.crew_effects),
            "crew_name": self.crew_name,
            "agent_title": cfg.agent_title if cfg else None,
            "user_title": cfg.user_title if cfg else None,
        }


def envelope_signature(env: ActionEnvelope) -> str:
    return sha1_short(f"{env.session_id}|{env.request_id}|{env.category}|{env.effect}")
