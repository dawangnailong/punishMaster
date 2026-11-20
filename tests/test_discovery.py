"""MCP 工具/资源/提示词能被发现（spec 验收 1）。"""

from __future__ import annotations

import json

import pytest

from .helpers import client_setup

EXPECTED_TOOLS = {
    "session_create", "session_configure", "session_authorize", "session_get",
    "scene_plan", "action_preview", "action_commit", "reward_issue",
    "penalty_issue", "scene_pause", "scene_resume", "session_stop",
    "emergency_stop", "history_list", "scene_replay", "signal_report",
    "utterance_check",
}


@pytest.mark.anyio
async def test_tools_discoverable(client):
    tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names
    # 描述必须声明“模拟”，防止模型误以为在控制真实设备
    for t in tools:
        blob = (t.description or "") + (t.name or "")
        if t.name in {
            "reward_issue", "penalty_issue", "action_commit", "action_preview",
            "emergency_stop", "session_create",
        }:
            assert "模拟" in blob, f"{t.name} 描述缺少 simulated 声明"


@pytest.mark.anyio
async def test_resources_discoverable(client):
    resources = (await client.list_resources()).resources
    uris = {str(r.uri) for r in resources}
    assert {
        "play://server/capabilities", "play://sessions/current",
        "play://catalog/effects", "play://catalog/metrics", "play://safety/policy",
    } <= uris

    templates = (await client.list_resource_templates()).resource_templates
    template_uris = {str(t.uri_template) for t in templates}
    assert {
        "play://sessions/{session_id}/state",
        "play://sessions/{session_id}/history",
        "play://sessions/{session_id}/signals",
    } <= template_uris


@pytest.mark.anyio
async def test_capabilities_resource(client):
    result = await client.read_resource("play://server/capabilities")
    text = result.contents[0].text if hasattr(result, "contents") else str(result)
    data = json.loads(text)
    assert data["simulated_only"] is True
    assert data["hard_limits"]["max_intensity"] == 8
    assert data["crew"]["real_hardware"] is False


@pytest.mark.anyio
async def test_protocol_schema_resource(client):
    result = await client.read_resource("play://protocol/schema")
    text = result.contents[0].text if hasattr(result, "contents") else str(result)
    data = json.loads(text)
    assert data["protocol_version"] == "1.0"
    assert "CueCard" in data["downlink"]
    assert "StatusSignal" in data["uplink"]
    assert "honesty" in data["uplink"]


@pytest.mark.anyio
async def test_prompts_discoverable(client):
    prompts = (await client.list_prompts()).prompts
    names = {p.name for p in prompts}
    assert {"scene_setup", "choose_response", "safety_check"} <= names

    got = await client.get_prompt("safety_check", {"session_id": "x"})
    messages = got.messages if hasattr(got, "messages") else []
    assert messages, "safety_check prompt 应返回消息"


@pytest.mark.anyio
async def test_session_state_resource_roundtrip(client):
    sid = await client_setup(client)
    result = await client.read_resource(f"play://sessions/{sid}/state")
    text = result.contents[0].text if hasattr(result, "contents") else str(result)
    data = json.loads(text)
    assert data["session_id"] == sid
    assert data["state"] == "ACTIVE"
    assert data["config"]["max_intensity"] == 5
