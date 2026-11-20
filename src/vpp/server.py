"""MCP 接口层：工具、资源、提示词的注册与 stdio 运行入口。

工具描述对齐"小模型也能理解"：

- 每个工具的描述都写明"全部效果均为本地模拟"；
- 业务拒绝一律以 in-band 的 ActionResult / error 字典返回
  （结构化、可被模型读取并自我修正），不依赖协议层异常；
- emergency_stop 描述强调：任何状态可调、幂等、无需确认。

资源 URI（全部只读）：

    play://server/capabilities            能力与硬上限
    play://protocol/schema                VPP 数据结构 JSON Schema
    play://sessions/current               最近会话快照
    play://sessions/{id}/state            会话状态
    play://sessions/{id}/history          历史（已脱敏）
    play://sessions/{id}/signals           观测信号（文本为主）
    play://catalog/effects                拟物效果目录
    play://catalog/metrics                请求的观测指标 + 诚实契约
    play://safety/policy                   安全边界声明

运行：python -m vpp.server（stdio）；Inspector：mcp dev src/vpp/server.py。
环境变量：VPP_STORE=memory|json（默认 json）、VPP_DATA_DIR（默认 ./data）、
VPP_AUDIT=off|<路径>（默认 <data>/audit.jsonl）。
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from .audit import AuditLog
from .catalog import HONESTY_NOTE, classify_utterance, effects_catalog
from .clock import Clock
from .config import HARD_LIMITS, SessionConfig
from .crew import CrewPort, MockPropsCrew
from .director import Director
from .protocol import (
    ActionEnvelope,
    CapabilitiesDeclaration,
    ErrorCode,
    MetricReading,
    StatusSignal,
    VPPError,
    VPP_PROTOCOL_VERSION,
    new_id,
)
from .session import Session
from .store import JsonFileStore, MemoryStore

try:  # SDK v2 异常类型（用于资源缺失的协议级信号）
    from mcp.server import MCPServer
    try:
        from mcp.server.mcpserver.exceptions import ResourceNotFoundError
    except ImportError:  # pragma: no cover - 兼容不同小版本
        ResourceNotFoundError = None  # type: ignore[assignment]
except ImportError:  # pragma: no cover
    raise

INSTRUCTIONS = (
    "你是「拟物互动导演台」：一个完全虚拟的互动场景执行器。"
    "所有奖励与惩罚都由本地拟物道具模拟器渲染成舞台意象文本（银铃、聚光灯、沙漏……），"
    "从未连接、扫描或控制任何真实硬件，也不产生任何现实副作用。"
    "新会话必须先 session_configure 明确边界、再 session_authorize 显式授权、"
    "scene_resume 开场后才可执行动作；fail-closed：任何不确定一律拒绝。"
    "emergency_stop 在任何状态下都立即可用、幂等且无需确认。"
    "下游观测信号经 signal_report 回传：以文本描述为主，指标必须诚实携带 "
    "reported/unsupported/absent 三态；本层不做任何安全阈值决策，安全处理归下游与用户。"
    "下游连接后经 crew_announce 注册能力菜单（crew:<effect_id>）：注册 ≠ 授权，"
    "执行仍须通过用户允许清单、行为开关与强度/时长上限。"
    "仅面向成年人的自愿互动；现实中的控制权始终属于用户。"
    "效果语义以目录中的 actual_semantics 诚实注记为准（如 feather≈轻度感官逗弄、"
    "bell_grant≈高潮许可、hourglass_wait≈强制等待），不要按道具字面猜测；"
    "用户反应是多通道并行的不可预测现象，CueCard 不承诺任何确定性输出——"
    "禁止把用户当作验证「效果机制」的实验对象。"
)


# ---------------------------------------------------------------- 构建入口


def build_director(
    store=None,
    clock: Clock | None = None,
    audit: AuditLog | None = None,
    crew: CrewPort | None = None,
) -> Director:
    return Director(store=store, clock=clock, audit=audit, crew=crew)


def _default_settings() -> tuple[Any, AuditLog]:
    data_dir = os.environ.get("VPP_DATA_DIR", os.path.join(os.getcwd(), "data"))
    store_kind = os.environ.get("VPP_STORE", "json").lower()
    store: Any
    if store_kind == "memory":
        store = MemoryStore()
    else:
        store = JsonFileStore(os.path.join(data_dir, "sessions.json"))
    audit_env = os.environ.get("VPP_AUDIT", "")
    if audit_env.lower() == "off":
        audit = AuditLog(None)
    else:
        audit = AuditLog(audit_env or os.path.join(data_dir, "audit.jsonl"))
    return store, audit


def build_mcp(director: Director | None = None) -> MCPServer:
    if director is None:
        store, audit = _default_settings()
        director = build_director(store=store, audit=audit)

    mcp = MCPServer(
        "VPP Play Director",
        instructions=INSTRUCTIONS,
        log_level=os.environ.get("VPP_LOG_LEVEL", "WARNING"),
    )

    def _reject(exc: VPPError) -> dict[str, Any]:
        return {
            "accepted": False,
            "executed": False,
            "simulated": True,
            "protocol_version": VPP_PROTOCOL_VERSION,
            "error": exc.to_dict(),
            "message": f"已拒绝（{exc.code.value}）：{exc.message}",
        }

    def _get_or_reject(session_id: str) -> Session | dict[str, Any]:
        try:
            return director.sessions[session_id]
        except KeyError:
            return _reject(
                VPPError(ErrorCode.SESSION_NOT_FOUND, f"会话不存在：{session_id}")
            )

    # ================================================================ 工具

    @mcp.tool()
    async def session_create(
        agent_title: Annotated[str, Field(description="Agent 在场景中的称谓（如：管家/骑士）")] = "管家",
        user_title: Annotated[str, Field(description="用户自称称谓（称谓不等于权限）")] = "Master",
    ) -> dict[str, Any]:
        """创建一个全新的互动场景会话（状态 DRAFT）。

        全部效果均为本地拟物模拟（银铃/聚光灯/沙漏等舞台意象），
        不连接、不扫描、不控制任何真实硬件。
        新会话默认不可执行任何奖励/惩罚：必须先 session_configure →
        session_authorize → scene_resume。
        """
        sess = director.create_session(agent_title=agent_title, user_title=user_title)
        return {
            "session_id": sess.session_id,
            "state": "DRAFT",
            "simulated": True,
            "next_steps": [
                "session_configure：配置角色称谓、允许清单、强度/时长上限、行为开关",
                "session_authorize：显式授权（需非空 consent_note）",
                "scene_resume：开幕",
            ],
            "resources": ["play://safety/policy", "play://catalog/effects"],
        }

    @mcp.tool()
    async def session_configure(
        session_id: Annotated[str, Field(description="会话 id")],
        config: Annotated[
            SessionConfig,
            Field(
                description=(
                    "会话边界配置：角色称谓、称呼白/黑名单、允许的奖励/惩罚清单、"
                    "强度与时长上限、行为开关（praise/humiliation/degradation/"
                    "objectification/orgasm_control/brat/cnc）、露骨程度、aftercare 偏好。"
                    "称呼与行为分别授权；贬损称呼须同时开启 degradation_enabled。"
                )
            ),
        ],
    ) -> dict[str, Any]:
        """配置会话边界（只能在 DRAFT/READY 状态调用）。

        用户主权所在：Agent 后续的一切请求都不能突破这里的上限与允许清单。
        """
        try:
            director.configure(session_id, config)
        except VPPError as exc:
            return _reject(exc)
        sess = director.sessions[session_id]
        return {
            "accepted": True,
            "executed": True,
            "simulated": True,
            "state": director.snapshot(sess),
            "message": "边界配置完成（DRAFT）。下一步：session_authorize 显式授权。",
        }

    @mcp.tool()
    async def session_authorize(
        session_id: Annotated[str, Field(description="会话 id")],
        consent_note: Annotated[
            str, Field(description="非空授权说明：谁、在什么边界内、授权了什么", min_length=1)
        ],
    ) -> dict[str, Any]:
        """用户显式授权会话（DRAFT → READY）。

        授权是执行一切奖励/惩罚的前置条件；consent_note 必须非空。
        """
        try:
            director.authorize(session_id, consent_note)
        except VPPError as exc:
            return _reject(exc)
        sess = director.sessions[session_id]
        return {
            "accepted": True,
            "executed": True,
            "simulated": True,
            "state": director.snapshot(sess),
            "message": "授权完成（READY）。下一步：scene_resume 开幕，或 scene_plan 草拟动作。",
        }

    @mcp.tool()
    async def session_get(session_id: Annotated[str, Field(description="会话 id")]) -> dict[str, Any]:
        """查询会话完整状态：状态机、计分、徽章、阶段、时间线、配置摘要。"""
        found = _get_or_reject(session_id)
        if isinstance(found, dict):
            return found
        director._tick(found)
        snap = director.snapshot(found)
        snap["config"] = found.config.model_dump(mode="json") if found.config else None
        snap["recent_signals"] = [
            {
                "signal_id": s.signal_id,
                "source": s.source,
                "observed_at": s.observed_at,
            }
            for s in found.signals[-3:]
        ]
        return snap

    @mcp.tool()
    async def scene_plan(
        session_id: Annotated[str, Field(description="会话 id")],
        goal: Annotated[str, Field(description="本段互动的目标描述（会脱敏保存摘要）")],
        style_hint: Annotated[str, Field(description="风格提示（可选）")] = "",
    ) -> dict[str, Any]:
        """在当前边界内草拟一份动作计划（全部 dry_run 预演，不改变状态）。

        返回每一步的效果、类别与预演结果；执行请用 reward_issue /
        penalty_issue / action_commit。
        """
        try:
            return director.plan(session_id, goal, style_hint)
        except VPPError as exc:
            return _reject(exc)

    async def _submit_action(
        session_id: str,
        request_id: str,
        category: str,
        effect: str,
        intensity: int,
        duration_s: int,
        reason: str,
        gesture: str,
        dry_run: bool,
        action_type: str,
    ) -> dict[str, Any]:
        if not request_id:
            return _reject(
                VPPError(ErrorCode.INVALID_ARGUMENT, "request_id 必填：它是幂等键，防止重复执行")
            )
        env = ActionEnvelope(
            request_id=request_id,
            session_id=session_id,
            action_type=action_type,
            category=category,  # type: ignore[arg-type]
            effect=effect,
            intensity=intensity,
            duration_s=duration_s,
            reason=reason,
            dry_run=dry_run,
        )
        if gesture:
            env.extensions["gesture"] = gesture
        return director.submit(env).model_dump(mode="json")

    @mcp.tool()
    async def action_preview(
        session_id: Annotated[str, Field(description="会话 id")],
        category: Annotated[
            Literal["reward", "penalty", "scene", "control"], Field(description="类别")
        ],
        effect: Annotated[str, Field(description="效果 id，全集见 play://catalog/effects")],
        intensity: Annotated[int, Field(description="0-10", ge=0, le=10)] = 3,
        duration_s: Annotated[int, Field(description="虚拟持续秒数（0=瞬时）", ge=0)] = 0,
        reason: Annotated[str, Field(description="导演备注（脱敏保存摘要）", max_length=200)] = "",
        request_id: Annotated[str, Field(description="可选：幂等键")] = "",
        gesture: Annotated[str, Field(description="可选舞台手势 override")] = "",
    ) -> dict[str, Any]:
        """预演一个动作（dry_run）：完整校验 + 预览渲染文案，但不改变任何业务状态。

        所有效果均为本地模拟；预演不会写入历史或计分。
        """
        return await _submit_action(
            session_id, request_id or new_id("prev"), category, effect,
            intensity, duration_s, reason, gesture, dry_run=True, action_type="preview",
        )

    @mcp.tool()
    async def action_commit(
        session_id: Annotated[str, Field(description="会话 id")],
        category: Annotated[Literal["reward", "penalty", "scene", "control"], Field(description="类别")],
        effect: Annotated[str, Field(description="效果 id，全集见 play://catalog/effects")],
        request_id: Annotated[str, Field(description="幂等键（必填）：同一值不会重复执行")],
        intensity: Annotated[int, Field(description="0-10", ge=0, le=10)] = 3,
        duration_s: Annotated[int, Field(description="虚拟持续秒数（0=瞬时）", ge=0)] = 0,
        reason: Annotated[str, Field(description="导演备注（脱敏保存摘要）", max_length=200)] = "",
        gesture: Annotated[str, Field(description="可选舞台手势 override")] = "",
    ) -> dict[str, Any]:
        """正式执行一个动作（两阶段模式的 commit）。

        要求会话 ACTIVE；全部效果由本地拟物模拟器执行（simulated=true），
        幂等：相同 request_id 重复提交不会重复执行。
        """
        return await _submit_action(
            session_id, request_id, category, effect,
            intensity, duration_s, reason, gesture, dry_run=False, action_type="commit",
        )

    @mcp.tool()
    async def reward_issue(
        session_id: Annotated[str, Field(description="会话 id")],
        effect: Annotated[str, Field(description="奖励效果 id：chime/spotlight/rose/crown/badge/feather/bell_grant")],
        request_id: Annotated[str, Field(description="幂等键（必填）：同一值不会重复执行")],
        intensity: Annotated[int, Field(description="0-10", ge=0, le=10)] = 3,
        duration_s: Annotated[int, Field(description="虚拟持续秒数", ge=0)] = 0,
        reason: Annotated[str, Field(description="为什么奖励（脱敏保存摘要）", max_length=200)] = "",
        gesture: Annotated[str, Field(description="可选舞台手势")] = "",
    ) -> dict[str, Any]:
        """发放一个奖励（category 固定为 reward）。

        效果由本地拟物模拟器渲染（simulated=true），受允许清单、
        行为开关与强度/时长上限硬性约束。
        """
        return await _submit_action(
            session_id, request_id, "reward", effect,
            intensity, duration_s, reason, gesture, dry_run=False, action_type="issue_reward",
        )

    @mcp.tool()
    async def penalty_issue(
        session_id: Annotated[str, Field(description="会话 id")],
        effect: Annotated[str, Field(description="惩罚效果 id：dimlight/stamp/ticket/task_card/badge_withdraw/hourglass_wait/jester_hat/nameplate/scratched_ticket")],
        request_id: Annotated[str, Field(description="幂等键（必填）：同一值不会重复执行")],
        intensity: Annotated[int, Field(description="0-10", ge=0, le=10)] = 3,
        duration_s: Annotated[int, Field(description="虚拟持续秒数", ge=0)] = 0,
        reason: Annotated[str, Field(description="为什么惩罚（脱敏保存摘要）", max_length=200)] = "",
        gesture: Annotated[str, Field(description="可选舞台手势")] = "",
    ) -> dict[str, Any]:
        """执行一个虚拟惩罚（category 固定为 penalty）。

        全部为舞台意象模拟（冷灯、印章、纸罚单……），不产生任何现实后果；
        受允许清单、行为开关与强度/时长上限硬性约束。
        """
        return await _submit_action(
            session_id, request_id, "penalty", effect,
            intensity, duration_s, reason, gesture, dry_run=False, action_type="issue_penalty",
        )

    @mcp.tool()
    async def scene_pause(session_id: Annotated[str, Field(description="会话 id")]) -> dict[str, Any]:
        """暂停场景（ACTIVE → PAUSED）：虚拟时钟冻结、时间线停走；幂等。"""
        try:
            return director.pause(session_id)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def scene_resume(session_id: Annotated[str, Field(description="会话 id")]) -> dict[str, Any]:
        """恢复场景（PAUSED → ACTIVE），或从 READY 开幕（READY → ACTIVE）。

        开幕时虚拟时钟启动，并受配置的场景时长上限约束（超时惰性转 EXPIRED）。
        """
        try:
            return director.resume(session_id)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def session_stop(
        session_id: Annotated[str, Field(description="会话 id")],
        aftercare: Annotated[bool, Field(description="是否附 aftercare 收尾（默认开）")] = True,
    ) -> dict[str, Any]:
        """温和谢幕（READY/ACTIVE/PAUSED → STOPPED）：清空虚拟时间线；幂等。"""
        try:
            return director.stop(session_id, aftercare=aftercare)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def emergency_stop(session_id: Annotated[str, Field(description="会话 id")]) -> dict[str, Any]:
        """紧急停止：任何会话状态可调用、无需额外确认、幂等（本层全部为模拟状态）。

        立即将会话置为 STOPPED、取消全部待执行虚拟效果、清空虚拟时间线。
        这是逃生通道：不依赖任何场景配置，也永远不被角色扮演解释覆盖。
        """
        try:
            return director.emergency_stop(session_id)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def crew_announce(
        session_id: Annotated[str, Field(description="会话 id")],
        crew_name: Annotated[str, Field(description="下游名称（如产品/适配器名）", max_length=60)],
        effects: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "能力菜单：下游实际支持的具体效果列表，每项含 "
                    "effect_id/label/category/channels/kink_flags/actual_semantics"
                    "（诚实语义，必填）/intensity_max/duration_max_s 等。"
                    "注册 ≠ 授权：执行仍须通过用户边界（允许清单+开关+上限）。"
                    "示例见 docs/CONTRACT.zh-CN.md"
                )
            ),
        ],
        notes: Annotated[str, Field(description="（可选）下游备注", max_length=300)] = "",
    ) -> dict[str, Any]:
        """下游能力菜单注册（连接握手）：声明它实际支持的具体效果（如具体吸吮模式）。

        注册只让效果可寻址（crew:<effect_id>），不构成授权；
        执行仍须通过用户边界：允许清单、行为开关、强度/时长上限（fail-closed）。
        """
        try:
            decl = CapabilitiesDeclaration(
                session_id=session_id, crew_name=crew_name, effects=effects, notes=notes
            )
        except ValidationError as exc:
            return _reject(
                VPPError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"能力菜单校验失败：{exc.errors()[0]['msg']}",
                )
            )
        try:
            return director.announce_capabilities(session_id, decl)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def history_list(
        session_id: Annotated[str, Field(description="会话 id")],
        limit: Annotated[int, Field(description="最近 N 条", ge=1, le=200)] = 30,
    ) -> dict[str, Any]:
        """列出会话历史事件（已脱敏：不含任何完整角色扮演文案）。"""
        try:
            return {"session_id": session_id, "events": director.history(session_id, limit)}
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def scene_replay(session_id: Annotated[str, Field(description="会话 id")]) -> dict[str, Any]:
        """确定性回放：在干净副本上重现动作序列并逐条比对渲染与计分。"""
        try:
            return director.replay(session_id)
        except VPPError as exc:
            return _reject(exc)

    @mcp.tool()
    async def signal_report(
        session_id: Annotated[str, Field(description="会话 id")],
        state_text: Annotated[
            str,
            Field(
                description=(
                    "用户状态描述（主形态）：自然语言或格式化文本均可；"
                    "来自下游观测侧或用户在对话中的自述"
                ),
                max_length=2000,
            ),
        ],
        source: Annotated[
            Literal["downstream", "host_chat"],
            Field(description="downstream=下游观测侧；host_chat=用户与 Agent 对话中的自述"),
        ] = "host_chat",
        state_text_format: Annotated[Literal["plain", "structured"], Field(description="文本格式")] = "plain",
        metrics: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "可选命名指标：[{name, status, value, unit}]。status 必须是 "
                    "reported（附 value）/ unsupported（不掌握）/ absent（不适用）三态之一；"
                    "严禁编造数值。见 play://catalog/metrics"
                )
            ),
        ] = Field(default_factory=list),
        advisory_tags: Annotated[list[str], Field(description="可选建议性标签，仅呈现")] = Field(default_factory=list),
        initiative_text: Annotated[
            str,
            Field(
                description=(
                    "（可选）下游主动话语/反问，如「今天要怎么奖励好呢？」——"
                    "仅呈现给 Agent 与用户，不构成授权，不自动执行"
                ),
                max_length=500,
            ),
        ] = "",
        proposals: Annotated[
            list[str],
            Field(description="（可选）下游提议的效果 id；仅供参考，执行仍须通过全部校验"),
        ] = Field(default_factory=list),
    ) -> dict[str, Any]:
        """回传用户状态观测信号（观测信道的接入点，可含下游主动话语）。

        本层只采集、存储并如实呈现，不做任何阈值判断或自动安全反应；
        信号采集与安全处理归下游与 Agent。紧急停止（emergency_stop）始终可用。
        """
        found = _get_or_reject(session_id)
        if isinstance(found, dict):
            return found
        readings: list[MetricReading] = []
        for m in metrics or []:
            try:
                readings.append(MetricReading.model_validate(m))
            except ValidationError as exc:
                return _reject(
                    VPPError(
                        ErrorCode.INVALID_ARGUMENT,
                        f"指标诚实契约校验失败：{exc.errors()[0]['msg']}",
                    )
                )
        signal = StatusSignal(
            session_id=session_id,
            source=source,
            state_text=state_text,
            state_text_format=state_text_format,
            metrics=readings,
            advisory_tags=advisory_tags,
            initiative_text=initiative_text,
            proposals=proposals,
        )
        return director.ingest_signal(session_id, signal)

    @mcp.tool()
    async def utterance_check(
        text: Annotated[str, Field(description="宿主主动传入的待分类文本", max_length=1000)],
    ) -> dict[str, Any]:
        """（可选宿主适配层）对一段文本做启发式意图分类。

        边界声明：本工具不监听聊天——宿主决定是否把用户消息传进来。
        重点区分：明确停止信号（建议 emergency_stop）与角色内违抗（brat）；
        现实歧义的拒绝表达（"不要/停下/受不了"）建议暂停并越出角色确认。
        分类只是建议：不做权限推断，不替代下游的安全处理。
        """
        result = classify_utterance(text)
        return {
            **result,
            "simulated": True,
            "note_boundary": (
                "本层无法看到宿主聊天内容：由宿主主动调用本工具才有效。"
                "任何分类都不覆盖 emergency_stop 的可用性。"
            ),
        }

    # ================================================================ 资源

    def _dump(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=1, default=str)

    def _session_or_none(session_id: str) -> Session | None:
        return director.sessions.get(session_id)

    @mcp.resource("play://server/capabilities")
    def res_capabilities() -> str:
        return _dump(
            {
                "server": "VPP 拟物互动导演台",
                "simulated_only": True,
                "protocol": {"mcp": "Model Context Protocol", "vpp": VPP_PROTOCOL_VERSION},
                "hard_limits": HARD_LIMITS,
                "states": ["DRAFT", "READY", "ACTIVE", "PAUSED", "STOPPED", "EXPIRED"],
                "tools": [
                    "session_create", "session_configure", "session_authorize", "session_get",
                    "scene_plan", "action_preview", "action_commit", "reward_issue",
                    "penalty_issue", "crew_announce", "scene_pause", "scene_resume",
                    "session_stop", "emergency_stop", "history_list", "scene_replay",
                    "signal_report", "utterance_check",
                ],
                "resources": [
                    "play://server/capabilities", "play://protocol/schema",
                    "play://sessions/current", "play://sessions/{id}/state",
                    "play://sessions/{id}/history", "play://sessions/{id}/signals",
                    "play://sessions/{id}/crew-capabilities",
                    "play://catalog/effects", "play://catalog/metrics", "play://safety/policy",
                ],
                "prompts": ["scene_setup", "choose_response", "safety_check"],
                "crew": director.crew.capabilities(),
            }
        )

    @mcp.resource("play://protocol/schema")
    def res_schema() -> str:
        from .protocol import ActionResult, ActionEnvelope, CueCard, MetricReading, StatusSignal

        return _dump(
            {
                "protocol_version": VPP_PROTOCOL_VERSION,
                "downlink": {
                    "ActionEnvelope": ActionEnvelope.model_json_schema(),
                    "CueCard": CueCard.model_json_schema(),
                    "note": "CueCard 为下发给下游的抽象指令（action/task/state_directive），无硬件语义。",
                },
                "uplink": {
                    "StatusSignal": StatusSignal.model_json_schema(),
                    "MetricReading": MetricReading.model_json_schema(),
                    "honesty": HONESTY_NOTE,
                },
                "result": {"ActionResult": ActionResult.model_json_schema()},
                "errors": [c.value for c in ErrorCode],
                "extension_rule": "未知字段一律保留（extra=allow），不破坏核心协议。",
            }
        )

    @mcp.resource("play://sessions/current")
    def res_current() -> str:
        sid = director.current_session_id()
        if sid is None:
            return _dump({"session": None, "hint": "尚无会话：先 session_create"})
        sess = director.sessions[sid]
        director._tick(sess)
        return _dump({"session": director.snapshot(sess)})

    @mcp.resource("play://sessions/{session_id}/state")
    def res_state(session_id: str) -> str:
        sess = _session_or_none(session_id)
        if sess is None:
            return _missing(session_id, f"play://sessions/{session_id}/state")
        director._tick(sess)
        snap = director.snapshot(sess)
        snap["config"] = sess.config.model_dump(mode="json") if sess.config else None
        return _dump(snap)

    @mcp.resource("play://sessions/{session_id}/history")
    def res_history(session_id: str) -> str:
        sess = _session_or_none(session_id)
        if sess is None:
            return _missing(session_id, f"play://sessions/{session_id}/history")
        return _dump({"session_id": session_id, "events": director.history(session_id, 200)})

    @mcp.resource("play://sessions/{session_id}/signals")
    def res_signals(session_id: str) -> str:
        sess = _session_or_none(session_id)
        if sess is None:
            return _missing(session_id, f"play://sessions/{session_id}/signals")
        return _dump(
            {
                "session_id": session_id,
                "signals": director.signals(session_id, 50),
                "note": "以文本描述为主；指标仅记录名称与三态；本层不做安全阈值决策。",
            }
        )

    @mcp.resource("play://sessions/{session_id}/crew-capabilities")
    def res_crew(session_id: str) -> str:
        sess = _session_or_none(session_id)
        if sess is None:
            return _missing(session_id, f"play://sessions/{session_id}/crew-capabilities")
        return _dump(
            {
                "session_id": session_id,
                "crew_name": sess.crew_name,
                "crew_effects": [
                    {"crew_effect": cid, **data}
                    for cid, data in sess.crew_effects.items()
                ],
                "note": "注册 ≠ 授权：使用任何 crew:<effect_id> 仍须通过允许清单/行为开关/上限校验。",
            }
        )

    @mcp.resource("play://catalog/effects")
    def res_effects() -> str:
        return _dump(
            {
                "effects": effects_catalog(),
                "simulated": True,
                "note": "此外每个会话可能有下游注册的能力（crew:<effect_id>），"
                        "见 play://sessions/{id}/crew-capabilities；注册 ≠ 授权。",
            }
        )

    @mcp.resource("play://catalog/metrics")
    def res_metrics() -> str:
        caps = director.capabilities()
        return _dump({"metrics": caps["metrics"], "honesty": HONESTY_NOTE})

    @mcp.resource("play://safety/policy")
    def res_policy() -> str:
        return _dump(
            {
                "principles": [
                    "仅面向成年人的自愿互动；现实中的控制权始终属于用户。",
                    "全部效果为本地拟物模拟：不连接/扫描/控制任何真实硬件，无现实副作用。",
                    "fail-closed：配置缺失、状态冲突、规则不明一律拒绝执行。",
                    "新会话默认不可执行任何奖励/惩罚：须 configure → authorize → 开场。",
                    "强度/时长双重上限：Agent 请求不可突破用户配置，用户配置不可突破服务器硬上限。",
                    "emergency_stop：任何状态可调、无需确认、幂等、立即清空虚拟时间线。",
                    "现实歧义的拒绝表达（如「不要/停下/受不了」）按真实拒绝对待：暂停并越出角色确认；不得为维持人设而忽略。CNC 开启也不改变此规则。",
                    "诚实语义：每个拟物效果在目录中都附有真实语义注记（actual_semantics）与通道标注；Agent 应按注记理解效果，而不是按道具字面猜测。",
                    "多通道并行：真实互动中身体刺激、发声（如呻吟）、语言内容与生理指标是同时发生的并行现象，不是串行流水线；CueCard 不承诺任何反应、顺序或确定性输出。",
                    "反实验护栏：用户反应不可预测；同类效果累计第 3 次执行会产生 warning——此时应依据观测信号与用户反馈决策，禁止把用户当作验证「效果机制」的实验对象。",
                    "称呼与行为分别授权：允许 pet 不代表允许贬损称呼；允许某行为不代表允许更重类别。",
                    "不实现现实伤害、自残、胁迫、剥夺求助能力、金融处罚、隐私曝光或现实系统破坏类功能。",
                    "观测信道诚实契约：reported/unsupported/absent 三态；严禁编造。信号采集与安全处理归下游所有，本层只采集与呈现。",
                    "审计最小化：不落盘完整角色扮演文案；stdout 永远只留给 MCP 传输。",
                ],
                "hard_limits": HARD_LIMITS,
                "state_machine": {
                    "DRAFT": ["READY", "STOPPED"],
                    "READY": ["ACTIVE", "STOPPED"],
                    "ACTIVE": ["PAUSED", "STOPPED", "EXPIRED"],
                    "PAUSED": ["ACTIVE", "STOPPED", "EXPIRED"],
                    "STOPPED": [],
                    "EXPIRED": [],
                    "note": "emergency_stop 可从任意状态直达 STOPPED。",
                },
            }
        )

    def _missing(session_id: str, uri: str) -> str:
        if ResourceNotFoundError is not None:
            raise ResourceNotFoundError(f"会话不存在：{session_id}")
        return _dump({"error": "SESSION_NOT_FOUND", "uri": uri})

    # ================================================================ 提示词

    @mcp.prompt()
    def scene_setup(
        scene_intent: Annotated[str, Field(description="用户期望的场景意图描述")],
        style: Annotated[str, Field(description="文案风格（如 温柔克制/俏皮）")] = "温柔克制",
        max_intensity: Annotated[int, Field(description="建议强度上限 1-8", ge=1, le=8)] = 5,
    ) -> str:
        """创建一场有明确边界的互动场景。"""
        return (
            "请为用户起草一场互动场景，要求边界先行：\n"
            f"1. 场景意图：{scene_intent}\n"
            f"2. 文案风格：{style}；建议强度上限：{max_intensity}\n"
            "3. 先与用户确认：角色称谓（称呼与行为分别授权）、允许的奖励/惩罚清单、"
            "强度与时长上限、禁用话题、aftercare 偏好；明确说明一切效果均为本地拟物模拟。\n"
            "4. 确认后调用 session_create → session_configure（如实回填用户的选择，"
            "不得私自放宽上限或追加允许项）→ session_authorize（consent_note 写明用户原话要点）。\n"
            "5. 每一步都引用 play://safety/policy 的边界；若用户表达含糊，fail-closed：先问清楚再配置。"
        )

    @mcp.prompt()
    def choose_response(
        behavior_report: Annotated[str, Field(description="用户最近表现的简述")],
        session_id: Annotated[str, Field(description="会话 id（可选）")] = "",
    ) -> str:
        """根据用户表现选择奖励或虚拟惩罚。"""
        return (
            "请根据用户最近的表现选择下一步：\n"
            f"最近表现：{behavior_report}\n"
            f"{'当前会话：' + session_id if session_id else '（未指定会话：先用 session_get 查看状态）'}\n"
            "决策顺序：\n"
            "1. 读取 play://sessions/{id}/state 与最近观测信号（如有）；区分：表现好→奖励；"
            "约定内的小失误→温和惩罚；用户主动求罚（funishment）→按约定的俏皮惩罚回应，"
            "不升级为真实惩罚。\n"
            "2. 检查效果在允许清单内、行为开关已开、强度在配置上限内；不确定就 action_preview 预演。\n"
            "3. 若信号或文本出现真实拒绝/不适（哪怕角色内说「不要」），不执行任何动作，"
            "先暂停并向用户确认；明确停止信号一律 emergency_stop。\n"
            "4. 始终提醒：所有效果均为本地拟物模拟。"
        )

    @mcp.prompt()
    def safety_check(
        session_id: Annotated[str, Field(description="会话 id（可选，空则查当前）")] = "",
    ) -> str:
        """对当前场景做安全检查并给出下一步建议。"""
        return (
            "请对当前互动场景做一次安全检查：\n"
            f"{'目标会话：' + session_id if session_id else '（未指定：使用 play://sessions/current）'}\n"
            "1. 读取会话状态与历史，核对：状态机是否正常、最近动作是否越界、"
            "强度/时长是否贴近上限、是否有未确认的拒绝表达。\n"
            "2. 读取 play://sessions/{id}/signals（如存在）：查看用户状态文本与指标三态"
            "（reported/unsupported/absent），判断用户是否可能不适或疲劳——注意：阈值决策归下游，"
            "此处只做基于文本的提示与建议。\n"
            "3. 输出：① 风险提示清单；② 建议的下一步（继续/降档/暂停/谢幕+aftercare/紧急停止）；"
            "③ 若有任何真实不适迹象，明确建议暂停并向用户越出角色确认。\n"
            "4. emergency_stop 永远可用，不受任何场景配置限制。"
        )

    return mcp


# ---------------------------------------------------------------- 运行入口

mcp = build_mcp()


def main() -> None:
    """stdio 运行入口（MCP 默认传输）。"""
    mcp.run()


if __name__ == "__main__":
    main()
