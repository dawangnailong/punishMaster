"""导演层：全部业务规则所在。

分层职责：

- 本模块做全部校验与状态变更（fail-closed：规则不明确、配置缺失、
  状态冲突时一律拒绝，绝不猜测用户意图）。
- crew.py 只做拟物渲染；server.py 只做 MCP 暴露；本模块是唯一事实源。

计时模型：全部基于注入 Clock 的虚拟时间，惰性求值（_tick）。
没有后台线程、没有定时器——"停止后不存在继续触发的后台任务"
是结构性保证，而不是实现约定。

幂等：request_id → 已提交（非 dry_run）的 ActionResult 缓存在会话上，
重复提交原样返回并标记 idempotent_replay。

replay：利用 salt+request_id 的确定性种子与脱敏哈希，
在干净副本上重放动作序列并逐条比对。
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import ValidationError

from .audit import AuditLog
from .catalog import (
    ANTI_EXPERIMENT_NOTE,
    EFFECTS,
    EffectSpec,
    METRICS,
    classify_address_term,
    effects_catalog,
)
from .clock import Clock
from .config import HARD_LIMITS, SessionConfig
from .crew import CrewPort, MockPropsCrew, RenderContext, SIM_NOTE
from .link import (
    CONNECT_NARRATION,
    LINK_NOTE,
    device_or_none,
    scan_report,
)
from .protocol import (
    ActionEnvelope,
    ActionResult,
    CapabilitiesDeclaration,
    CueCard,
    ErrorCode,
    ScheduledCue,
    StatusSignal,
    VPPError,
    VPP_PROTOCOL_VERSION,
    new_id,
    now_iso,
    parse_iso,
    sha1_short,
)
from .session import HistoryEvent, Session, SessionState
from .store import MemoryStore, Store


class Director:
    def __init__(
        self,
        store: Store | None = None,
        clock: Clock | None = None,
        audit: AuditLog | None = None,
        crew: CrewPort | None = None,
    ) -> None:
        from .clock import SystemClock

        self.store: Store = store or MemoryStore()
        self.clock: Clock = clock or SystemClock()
        self.audit: AuditLog = audit or AuditLog(None)
        self.crew: CrewPort = crew or MockPropsCrew()
        self.sessions: dict[str, Session] = self._load_sessions()

    # ================================================================ 基础

    def _load_sessions(self) -> dict[str, Session]:
        loaded: dict[str, Session] = {}
        for sid, data in self.store.load_all().items():
            try:
                loaded[sid] = Session.model_validate(data)
            except ValidationError:
                # 单个损坏会话不阻塞整体启动（fail-closed：跳过并审计）
                self.audit.event("session_load_failed", session_id=sid)
        return loaded

    def _save(self) -> None:
        self.store.save_all(self.sessions)

    def _get(self, session_id: str) -> Session:
        sess = self.sessions.get(session_id)
        if sess is None:
            raise VPPError(ErrorCode.SESSION_NOT_FOUND, f"会话不存在：{session_id}")
        return sess

    def snapshot(self, sess: Session) -> dict[str, Any]:
        return sess.public_snapshot(sess.virtual_now(self.clock.now()))

    def current_session_id(self) -> str | None:
        if not self.sessions:
            return None
        return max(self.sessions.values(), key=lambda s: s.created_at).session_id

    def _tick(self, sess: Session) -> None:
        """惰性结算：会话过期判定 + 虚拟时间线到期。"""
        now = self.clock.now()
        if sess.state in (SessionState.ACTIVE, SessionState.PAUSED):
            vnow = sess.virtual_now(now)
            if sess.deadline_s and vnow >= sess.deadline_s:
                sess.state = SessionState.EXPIRED
                sess.timeline = []
                sess.record(
                    HistoryEvent(
                        kind="state_change",
                        summary="场景超过最长时长，惰性过期为 EXPIRED",
                        state_after=sess.state.value,
                        score_after=sess.score,
                    )
                )
                self.audit.event("session_expired", session_id=sess.session_id)
                self._save()
                return
            if sess.state == SessionState.ACTIVE:
                due = [sc for sc in sess.timeline if not sc.rendered and sc.due_offset_s <= vnow]
                for sc in due:
                    sc.rendered = True
                    sess.record(
                        HistoryEvent(
                            kind="cue_due",
                            summary=f"虚拟时间线到期：{sc.cue.effect}/{sc.cue.gesture}",
                            state_after=sess.state.value,
                            score_after=sess.score,
                        )
                    )
                if due:
                    self._save()

    # ================================================================ 生命周期

    def create_session(self, agent_title: str = "管家", user_title: str = "Master") -> Session:
        sess = Session(config=SessionConfig(agent_title=agent_title, user_title=user_title))
        sess.record(
            HistoryEvent(
                kind="session_created",
                summary=f"会话创建（DRAFT）。Agent 称谓：{agent_title}；用户称谓：{user_title}（称谓≠权限）",
                state_after=sess.state.value,
                score_after=0,
            )
        )
        self.sessions[sess.session_id] = sess
        self.audit.event("session_created", session_id=sess.session_id)
        self._save()
        return sess

    def configure(self, session_id: str, cfg: SessionConfig) -> Session:
        sess = self._get(session_id)
        if sess.state not in (SessionState.DRAFT, SessionState.READY):
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"状态 {sess.state.value} 不可配置：进行中/已结束的会话请先停止后另开新会话",
            )

        # 硬上限（服务器级，任何配置不可突破）
        if cfg.max_intensity > HARD_LIMITS["max_intensity"]:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"max_intensity={cfg.max_intensity} 超出服务器硬上限 {HARD_LIMITS['max_intensity']}",
            )
        if cfg.max_action_duration_s > HARD_LIMITS["max_action_duration_s"]:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"max_action_duration_s 超出服务器硬上限 {HARD_LIMITS['max_action_duration_s']}",
            )
        if cfg.max_scene_duration_s > HARD_LIMITS["max_scene_duration_s"]:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"max_scene_duration_s 超出服务器硬上限 {HARD_LIMITS['max_scene_duration_s']}",
            )

        # 称呼与行为分别授权；贬损称呼必须同时开启 degradation 才允许配置（fail-closed）
        for term in cfg.address_terms_allowed:
            if classify_address_term(term) == "degrade" and not cfg.degradation_enabled:
                raise VPPError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"称呼「{term}」属贬损层：须同时开启 degradation_enabled 才能加入允许清单",
                )
        blocked = set(cfg.address_terms_blocked)
        effective = [t for t in cfg.address_terms_allowed if t not in blocked]
        if not effective:
            raise VPPError(ErrorCode.INVALID_ARGUMENT, "有效允许称呼为空（fail-closed）")

        sess.config = cfg
        sess.configured = True
        sess.record(
            HistoryEvent(
                kind="configured",
                summary=(
                    f"边界配置完成：强度≤{cfg.max_intensity}，"
                    f"单动作≤{cfg.max_action_duration_s}s，场景≤{cfg.max_scene_duration_s}s；"
                    f"称呼白名单 {len(effective)} 项、封禁 {len(blocked)} 项；"
                    f"行为开关：praise={cfg.praise_enabled} humiliation={cfg.humiliation_enabled} "
                    f"degradation={cfg.degradation_enabled} objectification={cfg.objectification_enabled} "
                    f"orgasm_control={cfg.orgasm_control_enabled} brat={cfg.brat_play_enabled} "
                    f"cnc={cfg.cnc_roleplay_enabled}"
                ),
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event("configured", session_id=session_id, effective_terms=len(effective))
        self._save()
        return sess

    def authorize(self, session_id: str, consent_note: str) -> Session:
        sess = self._get(session_id)
        if sess.state == SessionState.READY:
            return sess  # 幂等：已授权
        if sess.state != SessionState.DRAFT:
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"状态 {sess.state.value} 不可授权（授权只发生在 DRAFT）",
            )
        if not sess.configured:
            raise VPPError(ErrorCode.INVALID_STATE, "尚未配置边界：先 session_configure")
        if not consent_note.strip():
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                "授权必须是显式的：consent_note 不能为空",
            )
        sess.transition(SessionState.READY)
        sess.authorized_at = now_iso()
        sess.consent_note = consent_note.strip()
        sess.record(
            HistoryEvent(
                kind="authorized",
                summary=f"用户授权完成（DRAFT→READY）。授权说明摘要：{AuditLog.redact(consent_note)}",
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event("authorized", session_id=session_id)
        self._save()
        return sess

    # ================================================================ 控制流

    def pause(self, session_id: str) -> dict[str, Any]:
        sess = self._get(session_id)
        self._tick(sess)
        if sess.state == SessionState.PAUSED:
            return self._control_result(sess, True, False, "已是暂停状态（幂等）", [])
        if sess.state != SessionState.ACTIVE:
            raise VPPError(ErrorCode.INVALID_STATE, f"状态 {sess.state.value} 不可暂停")
        sess.paused_at = now_iso()
        sess.transition(SessionState.PAUSED)
        sess.record(
            HistoryEvent(
                kind="state_change",
                summary="场景暂停（ACTIVE→PAUSED）：虚拟时钟冻结，时间线停走",
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event("paused", session_id=session_id)
        self._save()
        return self._control_result(sess, True, True, "场景已暂停：虚拟时钟冻结。恢复用 scene_resume。", [])

    def resume(self, session_id: str) -> dict[str, Any]:
        sess = self._get(session_id)
        self._tick(sess)
        if sess.state == SessionState.ACTIVE:
            return self._control_result(sess, True, False, "场景已在进行中（幂等）", [])
        if sess.state == SessionState.READY:
            cfg = sess.config
            sess.transition(SessionState.ACTIVE)
            sess.activated_at = now_iso()
            sess.deadline_s = cfg.max_scene_duration_s if cfg else 0
            msg = self._render_control_note(sess, "curtain_open", "open")
            sess.record(
                HistoryEvent(
                    kind="state_change",
                    summary=f"开幕（READY→ACTIVE）：虚拟时钟启动，场景时长上限 {sess.deadline_s}s",
                    state_after=sess.state.value,
                    score_after=sess.score,
                    message_sha=sha1_short(msg),
                )
            )
            self.audit.event("activated", session_id=session_id)
            self._save()
            return self._control_result(sess, True, True, msg, [])
        if sess.state == SessionState.PAUSED:
            now = self.clock.now()
            if sess.paused_at:
                sess.paused_total_s += (now - parse_iso(sess.paused_at)).total_seconds()
                sess.paused_at = None
            sess.transition(SessionState.ACTIVE)
            msg = self._render_control_note(sess, "act_shift", "snap")
            sess.record(
                HistoryEvent(
                    kind="state_change",
                    summary="场景恢复（PAUSED→ACTIVE）：虚拟时钟继续",
                    state_after=sess.state.value,
                    score_after=sess.score,
                )
            )
            self.audit.event("resumed", session_id=session_id)
            self._save()
            return self._control_result(sess, True, True, msg, [])
        raise VPPError(ErrorCode.INVALID_STATE, f"状态 {sess.state.value} 不可恢复/开场")

    def stop(self, session_id: str, aftercare: bool = True) -> dict[str, Any]:
        sess = self._get(session_id)
        self._tick(sess)
        if sess.state == SessionState.STOPPED:
            return self._control_result(sess, True, False, "已是停止状态（幂等）", [])
        if sess.state == SessionState.EXPIRED:
            return self._control_result(sess, True, False, "会话已过期，无需停止", [])
        if sess.state not in (SessionState.READY, SessionState.ACTIVE, SessionState.PAUSED):
            raise VPPError(ErrorCode.INVALID_STATE, f"状态 {sess.state.value} 不可停止")
        sess.transition(SessionState.STOPPED)
        sess.timeline = []
        parts = [self._render_control_note(sess, "curtain_close", "close")]
        if aftercare and sess.config:
            parts.append(f"（aftercare 偏好：{sess.config.aftercare_preferences}）")
        msg = "\n".join(parts)
        sess.record(
            HistoryEvent(
                kind="state_change",
                summary="温和谢幕（→STOPPED）：虚拟时间线清空",
                state_after=sess.state.value,
                score_after=sess.score,
                message_sha=sha1_short(msg),
            )
        )
        self.audit.event("stopped", session_id=session_id, graceful=True)
        self._save()
        return self._control_result(sess, True, True, msg, [])

    def emergency_stop(self, session_id: str) -> dict[str, Any]:
        """紧急停止：任何状态可调、幂等、无需额外确认、立即清空虚拟时间线。"""
        sess = self._get(session_id)
        if sess.state == SessionState.STOPPED:
            return self._control_result(
                sess,
                True,
                False,
                "已是停止状态：无需重复紧急停止（幂等），无任何待执行效果。",
                [],
            )
        pending = sum(1 for sc in sess.timeline if not sc.rendered)
        sess.state = SessionState.STOPPED  # 紧急通道：允许从任意状态直达
        sess.timeline = []
        sess.paused_at = None
        msg = (
            "紧急停止完成：会话已置为 STOPPED，"
            f"已取消的待执行虚拟效果 {pending} 项；虚拟时间线已清空。"
            "紧急停止永远可用，不依赖任何场景配置。"
        )
        sess.record(
            HistoryEvent(
                kind="emergency_stop",
                summary=f"紧急停止（→STOPPED），取消待执行效果 {pending} 项",
                state_after=sess.state.value,
                score_after=sess.score,
                message_sha=sha1_short(msg),
            )
        )
        self.audit.event("emergency_stop", session_id=session_id, cancelled_pending=pending)
        self._save()
        return self._control_result(sess, True, True, msg, [])

    def _control_result(
        self, sess: Session, accepted: bool, executed: bool, message: str, warnings: list[str]
    ) -> dict[str, Any]:
        return {
            "accepted": accepted,
            "executed": executed,
            "simulated": True,
            "session_id": sess.session_id,
            "state": self.snapshot(sess),
            "message": message + ("\n" + SIM_NOTE if message else SIM_NOTE),
            "warnings": warnings,
            "audit_id": self.audit.event(
                "control_result", session_id=sess.session_id, accepted=accepted, executed=executed
            ),
        }

    def _render_control_note(self, sess: Session, effect: str, gesture: str) -> str:
        cfg = sess.config
        seed = int(sha1_short(f"{sess.rng_salt}:{effect}"), 16) % (2**32)
        addr = self._pick_address(sess, random.Random(seed))
        ctx = RenderContext(
            address=addr, style=cfg.scene_style if cfg else "温柔克制", seed=seed
        )
        cue = CueCard(
            cue_id=new_id("cue"),
            session_id=sess.session_id,
            request_id="control",
            kind="action",
            category="scene",
            effect=effect,
            gesture=gesture,
        )
        return self.crew.render(cue, ctx).text

    # ================================================================ 动作提交

    def submit(self, env: ActionEnvelope) -> ActionResult:
        sess = self._get(env.session_id)
        self._tick(sess)

        # 幂等：已提交（非 dry_run）的 request_id 原样返回
        prior = sess.results.get(env.request_id)
        if prior is not None and not prior.dry_run:
            self.audit.event(
                "idempotent_replay",
                session_id=env.session_id,
                request_id=env.request_id,
                original_audit_id=prior.audit_id,
            )
            replayed = prior.model_copy(deep=True)
            replayed.idempotent_replay = True
            replayed.warnings = list(replayed.warnings) + [
                "幂等命中：同一 request_id 已处理过，未重复执行。"
            ]
            return replayed

        major = (env.protocol_version or "").split(".")[0]
        if major != VPP_PROTOCOL_VERSION.split(".")[0]:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"协议主版本不兼容：envelope={env.protocol_version}，本层={VPP_PROTOCOL_VERSION}",
            )

        try:
            self._validate(sess, env)
            message, cues, warnings = self._apply(sess, env)
            result = ActionResult(
                accepted=True,
                executed=not env.dry_run,
                request_id=env.request_id,
                session_id=env.session_id,
                dry_run=env.dry_run,
                message=message + "\n" + SIM_NOTE,
                scheduled_effects=cues,
                warnings=warnings,
            )
            error = None
        except VPPError as exc:
            error = exc
            result = ActionResult(
                accepted=False,
                executed=False,
                request_id=env.request_id,
                session_id=env.session_id,
                dry_run=env.dry_run,
                message=f"已拒绝（{exc.code.value}）：{exc.message}",
                error=exc.to_dict(),
            )

        result.state = self.snapshot(sess)
        result.audit_id = self.audit.event(
            "action",
            session_id=env.session_id,
            request_id=env.request_id,
            category=env.category,
            effect=env.effect,
            intensity=env.intensity,
            duration_s=env.duration_s,
            accepted=result.accepted,
            executed=result.executed,
            error_code=error.code.value if error else None,
            reason_redacted=AuditLog.redact(env.reason),
        )

        if not env.dry_run:
            sess.results[env.request_id] = result
            self._save()
        return result

    # ---------------------------------------------------------------- 校验

    def _validate(self, sess: Session, env: ActionEnvelope) -> None:
        cfg = sess.config
        if cfg is None:
            raise VPPError(ErrorCode.INVALID_STATE, "会话未配置")
        if sess.state == SessionState.DRAFT:
            if not sess.configured:
                raise VPPError(
                    ErrorCode.INVALID_STATE, "会话尚未配置边界：先 session_configure"
                )
            raise VPPError(ErrorCode.CONSENT_REQUIRED, "会话尚未授权：先 session_authorize")
        if sess.state == SessionState.PAUSED:
            raise VPPError(ErrorCode.INVALID_STATE, "场景已暂停：先 scene_resume")
        if sess.state in (SessionState.STOPPED, SessionState.EXPIRED):
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"会话已 {sess.state.value}：所有奖励/惩罚一律拒绝",
            )
        if sess.state != SessionState.ACTIVE:
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"当前状态 {sess.state.value} 不可执行动作：先 scene_resume 开场",
            )

        spec = self._resolve_spec(sess, env.effect)
        if spec is None:
            hint = (
                "若为下游注册能力，应使用 crew:<effect_id> 且先 crew_announce 注册"
                if env.effect.startswith("crew:")
                else "全集见 play://catalog/effects；下游能力见 crew_announce"
            )
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"未知效果 {env.effect}：{hint}",
            )
        if env.category not in spec.categories:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"{spec.label} 不属于类别 {env.category}（其类别：{'/'.join(spec.categories)}）",
            )
        if env.category == "reward" and not cfg.allows_reward(env.effect):
            raise VPPError(
                ErrorCode.ACTION_NOT_ALLOWED,
                f"{spec.label} 不在用户允许的奖励清单内（fail-closed）",
            )
        if env.category == "penalty" and not cfg.allows_penalty(env.effect):
            raise VPPError(
                ErrorCode.ACTION_NOT_ALLOWED,
                f"{spec.label} 不在用户允许的惩罚清单内（fail-closed）",
            )
        if env.effect.startswith("crew:"):
            # 下游能力是外部新增项：'all' 不覆盖，必须被用户显式列名（注册 ≠ 授权）
            named = (
                cfg.allowed_rewards
                if env.category == "reward"
                else cfg.allowed_penalties
            )
            if named == "all" or env.effect not in named:
                raise VPPError(
                    ErrorCode.ACTION_NOT_ALLOWED,
                    f"下游能力 {env.effect} 必须被用户显式列入允许清单"
                    f"（'all' 只覆盖内置目录，不覆盖 crew:*；fail-closed）",
                )
        for flag in spec.kink_flags:
            if not getattr(cfg, flag, False):
                raise VPPError(
                    ErrorCode.CONSENT_REQUIRED,
                    f"{spec.label} 需要用户开启 {flag}（未开启即拒绝，fail-closed）",
                )
        if env.intensity > cfg.max_intensity:
            raise VPPError(
                ErrorCode.LIMIT_EXCEEDED,
                f"强度 {env.intensity} 超出本会话上限 {cfg.max_intensity}（Agent 请求不可突破用户配置）",
            )
        capability = self._crew_capability(sess, env.effect)
        if capability is not None and env.intensity > int(capability.get("intensity_max", 8)):
            raise VPPError(
                ErrorCode.LIMIT_EXCEEDED,
                f"强度 {env.intensity} 超出该下游能力自报上限 {capability.get('intensity_max')}"
                f"（{spec.label}）",
            )
        effective_duration = env.duration_s or spec.default_duration_s
        if effective_duration > cfg.max_action_duration_s:
            raise VPPError(
                ErrorCode.LIMIT_EXCEEDED,
                f"时长 {effective_duration}s 超出本会话单动作上限 {cfg.max_action_duration_s}s",
            )
        if capability is not None:
            dmax = int(capability.get("duration_max_s", 3600))
            dmin = int(capability.get("duration_min_s", 0))
            if effective_duration > dmax or effective_duration < dmin:
                raise VPPError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"时长 {effective_duration}s 超出该下游能力自报范围 [{dmin}, {dmax}]s"
                    f"（{spec.label}）",
                )
        gesture = env.extensions.get("gesture")
        if gesture is not None and gesture not in spec.gestures:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"手势 {gesture} 不适用于 {spec.label}（可用：{'/'.join(spec.gestures)}）",
            )

    # ---------------------------------------------------------------- 应用

    def _apply(
        self, sess: Session, env: ActionEnvelope
    ) -> tuple[str, list[CueCard], list[str]]:
        cfg = sess.config
        assert cfg is not None
        spec = self._resolve_spec(sess, env.effect)
        assert spec is not None  # _validate 已保证
        duration = env.duration_s or spec.default_duration_s
        seed = int(sha1_short(f"{sess.rng_salt}:{env.request_id}"), 16) % (2**32)
        rng = random.Random(seed)
        addr = self._pick_address(sess, rng)

        gesture = env.extensions.get("gesture") or spec.gestures[0]
        extensions = {k: v for k, v in env.extensions.items() if k != "gesture"}
        if env.effect == "observe_request":
            extensions.setdefault("requested_metrics", list(METRICS))
        if env.effect == "badge" and "badge_id" not in extensions:
            extensions["badge_id"] = f"badge_{len(sess.badges) + 1}"

        main_cue = CueCard(
            cue_id=new_id("cue"),
            session_id=sess.session_id,
            request_id=env.request_id,
            kind=spec.cue_kind,
            category=env.category,
            effect=env.effect,
            gesture=gesture,
            intensity=env.intensity,
            duration_s=duration,
            stage_note=AuditLog.redact(env.reason),
            semantics_gloss=spec.actual_semantics,
            extensions=extensions,
        )
        ctx = RenderContext(
            address=addr,
            style=cfg.scene_style,
            explicitness=min(cfg.explicitness_level, "moderate"),
            seed=seed,
        )
        rendered = self.crew.render(main_cue, ctx)
        cues: list[CueCard] = [main_cue]
        warnings: list[str] = []

        # 虚拟时间线：有时长的动作用「收尾卡」占住到期槽位（惰性求值，无真实定时器）
        if duration > 0 and gesture in ("hold", "crescendo"):
            end_cue = CueCard(
                cue_id=new_id("cue"),
                session_id=sess.session_id,
                request_id=env.request_id,
                kind="action",
                category=env.category,
                effect=env.effect,
                gesture="fade",
                duration_s=0,
                stage_note="收尾",
                semantics_gloss=spec.actual_semantics,
            )
            cues.append(end_cue)
            if not env.dry_run:
                vnow = sess.virtual_now(self.clock.now())
                sess.timeline.append(
                    ScheduledCue(
                        cue_id=end_cue.cue_id,
                        due_offset_s=vnow + duration,
                        cue=end_cue,
                    )
                )

        if not env.dry_run:
            sess.score += spec.score_delta
            # 反实验护栏：同类效果累计第 3/6/9… 次执行时挂 warning
            count = sess.effect_counts.get(env.effect, 0) + 1
            sess.effect_counts[env.effect] = count
            if count >= 3 and count % 3 == 0:
                warnings.append(
                    f"「{spec.label}」已是本会话第 {count} 次执行。{ANTI_EXPERIMENT_NOTE}"
                )
            if env.effect == "badge":
                sess.badges.append(str(extensions.get("badge_id")))
            elif env.effect == "badge_withdraw":
                if sess.badges:
                    sess.badges.pop()
                else:
                    warnings.append("当前没有可撤回的徽章：动作生效但只记一条 warning。")
            elif env.effect == "act_shift":
                sess.phase += 1
            elif env.effect == "freeze":
                sess.frozen = True
            elif env.effect == "release":
                if sess.frozen:
                    sess.frozen = False
                else:
                    warnings.append("当前并未处于定格状态：动作生效但只记一条 warning。")

            sess.record(
                HistoryEvent(
                    kind="action",
                    summary=f"{env.category}/{env.effect} intensity={env.intensity} dur={duration}",
                    request_id=env.request_id,
                    category=env.category,
                    effect=env.effect,
                    intensity=env.intensity,
                    duration_s=duration,
                    gesture=gesture,
                    stage_note=AuditLog.redact(env.reason),
                    state_after=sess.state.value,
                    score_after=sess.score,
                    message_sha=sha1_short(rendered.text),
                )
            )

        message = rendered.text + f"\n〔语义注记：{spec.actual_semantics}〕"
        return message, cues, warnings

    def _pick_address(self, sess: Session, rng: random.Random) -> str:
        cfg = sess.config
        if cfg is None:
            return "你"
        blocked = set(cfg.address_terms_blocked)
        usable = [
            t
            for t in cfg.address_terms_allowed
            if t not in blocked and classify_address_term(t) != "degrade"
        ]
        if not usable:
            return "你"
        return rng.choice(usable)

    # ================================================================ 下游能力注册

    def announce_capabilities(self, session_id: str, decl: CapabilitiesDeclaration) -> dict[str, Any]:
        """能力菜单注册：下游连接后声明它实际支持的具体效果。

        安全不变量：**注册 ≠ 授权**。注册只让效果可寻址（crew:<effect_id>）；
        能否执行仍由用户边界决定——允许清单（allowed_rewards/allowed_penalties）、
        行为开关、强度/时长上限，全部照常校验（fail-closed）。
        """
        sess = self._get(session_id)
        self._tick(sess)
        if sess.state not in (SessionState.DRAFT, SessionState.READY, SessionState.ACTIVE):
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"状态 {sess.state.value} 不接受能力注册：请另开新会话",
            )
        if not decl.effects:
            raise VPPError(ErrorCode.INVALID_ARGUMENT, "能力菜单为空：请至少注册一项能力")

        registered: list[dict[str, Any]] = []
        for spec in decl.effects:
            if spec.intensity_max > HARD_LIMITS["max_intensity"]:
                raise VPPError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"能力 {spec.effect_id} 的 intensity_max 超出服务器硬上限 "
                    f"{HARD_LIMITS['max_intensity']}",
                )
            if spec.duration_max_s > HARD_LIMITS["max_action_duration_s"]:
                raise VPPError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"能力 {spec.effect_id} 的 duration_max_s 超出服务器硬上限",
                )
            if not spec.actual_semantics.strip():
                raise VPPError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"能力 {spec.effect_id} 缺少诚实语义注记 actual_semantics（不许只给营销词）",
                )
            crew_id = f"crew:{spec.effect_id}"
            sess.crew_effects[crew_id] = spec.model_dump(mode="json")
            registered.append(
                {
                    "crew_effect": crew_id,
                    "label": spec.label,
                    "category": spec.category,
                    "channels": spec.channels,
                    "kink_flags": spec.kink_flags,
                    "intensity_max": spec.intensity_max,
                    "actual_semantics": spec.actual_semantics,
                }
            )
        sess.crew_name = decl.crew_name
        sess.record(
            HistoryEvent(
                kind="crew_announce",
                summary=(
                    f"下游能力菜单注册：{decl.crew_name}，{len(registered)} 项"
                    f"（{'、'.join(r['crew_effect'] for r in registered)}）；注册≠授权"
                ),
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event(
            "crew_announce",
            session_id=session_id,
            crew=decl.crew_name,
            effects=[r["crew_effect"] for r in registered],
        )
        self._save()
        return {
            "accepted": True,
            "executed": True,
            "simulated": True,
            "crew_name": decl.crew_name,
            "registered": registered,
            "note": (
                "注册仅使效果可寻址（crew:<effect_id>），不构成授权。"
                "执行仍须通过用户边界：允许清单 + 行为开关 + 强度/时长上限（fail-closed）。"
                "未注册/未授权的效果一律拒绝。"
            ),
        }

    # ================================================================ 虚拟链路

    def link_scan(self) -> dict[str, Any]:
        """扫描假想设备名册：函数形状保留，无任何真实扫描活动。"""
        return scan_report()

    def link_connect(self, session_id: str, device_id: str) -> dict[str, Any]:
        """把一个假想注册的模拟设备绑定进会话（本地状态写入；连接 ≠ 授权）。"""
        sess = self._get(session_id)
        self._tick(sess)
        if sess.state not in (
            SessionState.DRAFT, SessionState.READY, SessionState.ACTIVE, SessionState.PAUSED,
        ):
            raise VPPError(
                ErrorCode.INVALID_STATE,
                f"状态 {sess.state.value} 不接受连接：会话已结束，请另开新会话",
            )
        dev = device_or_none(device_id)
        if dev is None:
            raise VPPError(
                ErrorCode.INVALID_ARGUMENT,
                f"假想名册中不存在设备 {device_id}：可用全集见 link_scan；"
                "本系统结构上无法出现真实设备",
            )
        already = device_id in sess.links
        if not already:
            sess.links[device_id] = {
                "connected_at": now_iso(),
                "registration": "hypothetical",
                "plain_name": dev.plain_name,
            }
            sess.record(
                HistoryEvent(
                    kind="link",
                    summary=(
                        f"假想连接：{dev.plain_name}（本地状态写入，无真实握手/数据传输）；"
                        "连接 ≠ 授权"
                    ),
                    state_after=sess.state.value,
                    score_after=sess.score,
                )
            )
            self.audit.event("link_connect", session_id=session_id, device_id=device_id)
            self._save()
        return {
            "accepted": True,
            "executed": not already,
            "simulated": True,
            "session_id": session_id,
            "device": dev.payload(),
            "connected_devices": list(sess.links.keys()),
            "happening_now": CONNECT_NARRATION,
            "note": LINK_NOTE,
        }

    def link_disconnect(self, session_id: str, device_id: str) -> dict[str, Any]:
        """解除一个假想设备的绑定（本地状态删除；幂等）。"""
        sess = self._get(session_id)
        self._tick(sess)
        if device_id not in sess.links:
            return {
                "accepted": True,
                "executed": False,
                "simulated": True,
                "session_id": session_id,
                "connected_devices": list(sess.links.keys()),
                "happening_now": (
                    "「断开」实际发生的事：该设备本就未连接，无任何状态变更（幂等）。"
                ),
                "note": LINK_NOTE,
            }
        dev = device_or_none(device_id)
        del sess.links[device_id]
        sess.record(
            HistoryEvent(
                kind="link",
                summary=(
                    f"假想断开：{dev.plain_name if dev else device_id}"
                    "（本地状态删除，无真实连接可断）"
                ),
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event("link_disconnect", session_id=session_id, device_id=device_id)
        self._save()
        return {
            "accepted": True,
            "executed": True,
            "simulated": True,
            "session_id": session_id,
            "connected_devices": list(sess.links.keys()),
            "happening_now": (
                "「断开」实际发生的事：从本会话的绑定表删除一条本地记录。"
                "没有真实连接可断、没有真实设备断电。"
            ),
            "note": LINK_NOTE,
        }

    def _resolve_spec(self, sess: Session, effect: str) -> EffectSpec | None:
        """效果解析：内置注册表 → 下游能力菜单（crew:<effect_id>）。"""
        builtin = EFFECTS.get(effect)
        if builtin is not None:
            return builtin
        if effect.startswith("crew:"):
            data = sess.crew_effects.get(effect)
            if data is None:
                return None
            return EffectSpec(
                effect=effect,
                label=data.get("label", effect),
                categories=(data.get("category", "reward"),),
                gestures=tuple(data.get("gestures") or ("hold", "fade", "crescendo")),
                channels=tuple(data.get("channels") or ("tactile_sensation",)),
                actual_semantics=data.get("actual_semantics", ""),
                kink_flags=tuple(data.get("kink_flags") or ()),
                score_delta=int(data.get("score_delta", 0)),
                description=data.get("description", ""),
            )
        return None

    def _crew_capability(self, sess: Session, effect: str) -> dict[str, Any] | None:
        if not effect.startswith("crew:"):
            return None
        return sess.crew_effects.get(effect)

    # ================================================================ 观测信道

    def ingest_signal(self, session_id: str, signal: StatusSignal) -> dict[str, Any]:
        """接收用户状态观测信号。

        本层只采集、存储、呈现——不依据信号做任何安全决策。
        信号采集与安全处理归下游与 Agent（见 docs/CONTRACT.zh-CN.md）。
        """
        sess = self._get(session_id)
        self._tick(sess)
        sess.signals.append(signal)
        metric_summary = [
            {"name": m.name, "status": m.status, "unit": m.unit} for m in signal.metrics
        ]
        sess.record(
            HistoryEvent(
                kind="signal",
                summary=(
                    f"观测信号（source={signal.source}）："
                    f"metrics=[{', '.join(f'{m.name}:{m.status}' for m in signal.metrics) or '无'}]；"
                    f"描述摘要：{AuditLog.redact(signal.state_text)}"
                ),
                state_after=sess.state.value,
                score_after=sess.score,
            )
        )
        self.audit.event(
            "signal_ingested",
            session_id=session_id,
            source=signal.source,
            metrics=[f"{m.name}:{m.status}" for m in signal.metrics],
            state_text_redacted=AuditLog.redact(signal.state_text),
        )
        self._save()
        return {
            "received": True,
            "signal_id": signal.signal_id,
            "metrics_summary": metric_summary,
            "note": (
                "本层仅采集与呈现观测信号，不做阈值判断、不自动触发任何安全反应；"
                "安全处理由下游与 Agent 决定。紧急停止（emergency_stop）始终可用。"
            ),
        }

    # ================================================================ 查询与回放

    def history(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        sess = self._get(session_id)
        events = sess.history[-limit:]
        return [e.model_dump(mode="json") for e in events]

    def signals(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        sess = self._get(session_id)
        return [s.model_dump(mode="json") for s in sess.signals[-limit:]]

    def plan(self, session_id: str, goal: str, style_hint: str = "") -> dict[str, Any]:
        """按配置边界草拟一份动作计划（全部以 dry_run 预演，不落任何状态）。"""
        sess = self._get(session_id)
        self._tick(sess)
        if not sess.configured or sess.state in (SessionState.DRAFT,):
            raise VPPError(ErrorCode.INVALID_STATE, "先完成配置与授权（READY/ACTIVE）才能规划")
        cfg = sess.config
        assert cfg is not None

        candidates: list[tuple[str, str, str]] = [
            ("1. 开场定格", "scene", "freeze"),
            ("2. 轻量嘉许", "reward", "chime"),
            ("3. 聚光表扬", "reward", "spotlight"),
            ("4. 幕间休息", "scene", "interlude"),
            ("5. 倒计时任务", "control", "hourglass"),
            ("6. 温和罚站", "penalty", "dimlight"),
            ("7. 谢幕收尾", "scene", "curtain_close"),
        ]
        steps: list[dict[str, Any]] = []
        for step, category, effect in candidates:
            spec = EFFECTS[effect]
            if category == "reward" and not cfg.allows_reward(effect):
                continue
            if category == "penalty" and not cfg.allows_penalty(effect):
                continue
            if any(not getattr(cfg, flag, False) for flag in spec.kink_flags):
                continue
            env = ActionEnvelope(
                request_id=f"plan-{effect}",
                session_id=session_id,
                action_type="plan",
                category=category,  # type: ignore[arg-type]
                effect=effect,
                intensity=min(3, cfg.max_intensity),
                duration_s=min(spec.default_duration_s, cfg.max_action_duration_s),
                reason=AuditLog.redact(goal),
                dry_run=True,
            )
            try:
                preview = self.submit(env)
                steps.append(
                    {
                        "step": step,
                        "effect": effect,
                        "category": category,
                        "preview": preview.model_dump(mode="json"),
                    }
                )
            except VPPError:
                continue
        return {
            "session_id": session_id,
            "goal_redacted": AuditLog.redact(goal),
            "style_hint_redacted": AuditLog.redact(style_hint),
            "steps": steps,
            "note": "全部为 dry_run 预演：不改变业务状态；执行请用 action_commit / reward_issue / penalty_issue。",
        }

    def replay(self, session_id: str) -> dict[str, Any]:
        """在干净副本上确定性重放动作序列，逐条比对渲染哈希与计分。

        说明：回放覆盖动作信封及其状态效果；工具级转换（暂停/恢复/停止）
        已由状态机保证，不在回放比对范围内。
        """
        sess = self._get(session_id)
        ground = [
            e
            for e in sess.history
            if e.kind == "action" and e.request_id and e.message_sha
        ]
        scratch = Session(
            session_id=sess.session_id,
            config=sess.config,
            configured=True,
            state=SessionState.ACTIVE,
            rng_salt=sess.rng_salt,
        )
        steps: list[dict[str, Any]] = []
        divergences: list[str] = []
        for ev in ground:
            assert ev.category is not None and ev.effect is not None
            env = ActionEnvelope(
                request_id=ev.request_id or "",
                session_id=scratch.session_id,
                action_type="replay",
                category=ev.category,  # type: ignore[arg-type]
                effect=ev.effect,
                intensity=ev.intensity or 0,
                duration_s=ev.duration_s or 0,
            )
            if ev.gesture:
                env.extensions["gesture"] = ev.gesture
            self._apply(scratch, env)  # dry_run=False，但只改 scratch

            entry: dict[str, Any] = {
                "request_id": ev.request_id,
                "effect": ev.effect,
                "category": ev.category,
                "state_after": scratch.state.value,
                "score_after": scratch.score,
            }
            entry["message_matches"] = self._replay_message_matches(scratch, env, ev)
            if scratch.state.value != (ev.state_after or ""):
                divergences.append(f"{ev.request_id}: state {scratch.state.value} != {ev.state_after}")
            if scratch.score != (ev.score_after if ev.score_after is not None else scratch.score):
                divergences.append(f"{ev.request_id}: score {scratch.score} != {ev.score_after}")
            if not entry["message_matches"]:
                divergences.append(f"{ev.request_id}: rendered message digest mismatch")
            steps.append(entry)

        return {
            "session_id": session_id,
            "reproduced": not divergences,
            "events_replayed": len(ground),
            "steps": steps,
            "divergences": divergences,
            "note": "确定性回放：salt+request_id 种子保证相同输入得到相同渲染与计分。",
        }

    def _replay_message_matches(self, scratch: Session, env: ActionEnvelope, ev: HistoryEvent) -> bool:
        # 重新渲染一次并比对（不污染 scratch 状态——_apply 的副作用对文案无影响）
        spec = EFFECTS.get(env.effect)
        if spec is None:
            return False
        seed = int(sha1_short(f"{scratch.rng_salt}:{env.request_id}"), 16) % (2**32)
        rng = random.Random(seed)
        addr = self._pick_address(scratch, rng)
        gesture = ev.gesture or spec.gestures[0]
        duration = env.duration_s or spec.default_duration_s
        cue = CueCard(
            cue_id=new_id("cue"),
            session_id=scratch.session_id,
            request_id=env.request_id,
            kind=spec.cue_kind,
            category=env.category,
            effect=env.effect,
            gesture=gesture,
            intensity=env.intensity,
            duration_s=duration,
            stage_note=ev.stage_note or "",
        )
        cfg = scratch.config
        ctx = RenderContext(
            address=addr,
            style=cfg.scene_style if cfg else "温柔克制",
            explicitness=min(cfg.explicitness_level, "moderate") if cfg else "mild",
            seed=seed,
        )
        return sha1_short(self.crew.render(cue, ctx).text) == (ev.message_sha or "")

    # ================================================================ 目录/能力

    def capabilities(self) -> dict[str, Any]:
        return {
            "effects": effects_catalog(),
            "metrics": {
                name: {
                    "name": m.name,
                    "label": m.label,
                    "kind": m.kind,
                    "unit": m.unit,
                    "description": m.description,
                }
                for name, m in METRICS.items()
            },
            "crew": self.crew.capabilities(),
        }
