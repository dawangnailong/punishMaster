"""测试帮助函数：构造配置与标准化会话搭建。"""

from __future__ import annotations

from typing import Any

from vpp.config import SessionConfig


def make_config(**over: Any) -> SessionConfig:
    base: dict[str, Any] = dict(
        address_terms_allowed=["小猫", "Master"],
        address_terms_blocked=[],
        max_intensity=5,
        max_action_duration_s=600,
        max_scene_duration_s=7200,
        praise_enabled=True,
        orgasm_control_enabled=True,
        humiliation_enabled=False,
        degradation_enabled=False,
        objectification_enabled=False,
        allowed_rewards="all",
        allowed_penalties=[
            "dimlight", "stamp", "ticket", "task_card",
            "badge_withdraw", "hourglass_wait",
        ],
        explicitness_level="moderate",
    )
    base.update(over)
    return SessionConfig(**base)


def setup_active(director, **cfg: Any) -> str:
    """导演级：创建 → 配置 → 授权 → 开场，返回 session_id。"""
    sess = director.create_session()
    director.configure(sess.session_id, make_config(**cfg))
    director.authorize(sess.session_id, "授权说明：用于自动化测试")
    director.resume(sess.session_id)
    return sess.session_id


async def client_setup(client, **cfg: Any) -> str:
    """MCP 客户端级：同样的搭建流程，返回 session_id。"""
    created = await client.call_tool("session_create", {})
    sid = created.structured_content["session_id"]
    config = make_config(**cfg)
    await client.call_tool(
        "session_configure",
        {"session_id": sid, "config": config.model_dump(mode="json")},
    )
    await client.call_tool(
        "session_authorize", {"session_id": sid, "consent_note": "授权说明：用于自动化测试"}
    )
    await client.call_tool("scene_resume", {"session_id": sid})
    return sid


async def call(client, tool: str, args: dict) -> dict:
    result = await client.call_tool(tool, args)
    return result.structured_content
