"""MCP 设备面的可发现性与端到端行为。"""

from __future__ import annotations

import json

import pytest

from .helpers import call

EXPECTED_TOOLS = {
    "device_capabilities",
    "device_status",
    "device_do",
    "device_set_mode",
    "device_set_level",
    "device_stop",
    "device_media",
    "device_events",
}


@pytest.mark.anyio
async def test_tools_discoverable(client) -> None:
    tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names

    by_name = {t.name: (t.description or "") for t in tools}
    assert "语义" in by_name["device_do"]
    assert "幂等" in by_name["device_stop"]


@pytest.mark.anyio
async def test_capabilities_and_execute_roundtrip(client) -> None:
    caps = await call(client, "device_capabilities")
    assert caps["simulated"] is True
    assert caps["safety"]["raw_sensor_data_exposed"] is False
    assert {a["action_id"] for a in caps["semantic_actions"]} >= {
        "stimulate", "tease", "check", "stop"
    }

    result = await call(
        client,
        "device_do",
        {
            "action_id": "stimulate",
            "level": 4,
            "duration_s": 30,
            "params": {"depth": "deep", "rhythm": "pulse"},
        },
    )
    assert result["accepted"] is True
    assert result["executed"] is True
    assert result["supported"] is True
    assert result["simulated"] is True
    assert result["state"]["running"] is True

    state = await call(client, "device_status")
    assert state["running"] is True
    assert state["current_action"] == "stimulate"


@pytest.mark.anyio
async def test_unsupported_is_refused_over_mcp(client) -> None:
    result = await call(client, "device_do", {"action_id": "check"})
    assert result["supported"] is False
    assert result["executed"] is False
    assert result["realization"] == "unsupported"

    state = await call(client, "device_status")
    assert state["running"] is False


@pytest.mark.anyio
async def test_stop_over_mcp(client) -> None:
    await call(client, "device_do", {"action_id": "stimulate", "duration_s": 0})
    stopped = await call(client, "device_stop")

    assert stopped["executed"] is True
    assert stopped["state"]["running"] is False


@pytest.mark.anyio
async def test_set_level_and_mode_over_mcp(client) -> None:
    mode = await call(
        client, "device_set_mode", {"mode_id": "wave", "level": 3, "duration_s": 20}
    )
    assert mode["executed"] is True
    assert mode["state"]["current_mode"] == "wave"

    level = await call(client, "device_set_level", {"level": 5})
    assert level["executed"] is True
    assert level["state"]["level"] == 5


@pytest.mark.anyio
async def test_media_and_events_over_mcp(client) -> None:
    media = await call(client, "device_media")
    assert media["simulated"] is True
    assert media["items"] == []

    events = await call(client, "device_events", {"cursor": 0})
    assert events["simulated"] is True
    assert isinstance(events["events"], list)
    assert isinstance(events["next_cursor"], int)


@pytest.mark.anyio
async def test_capabilities_resource(client) -> None:
    result = await client.read_resource("device://capabilities")
    text = result.contents[0].text if hasattr(result, "contents") else str(result)
    data = json.loads(text)
    assert data["simulated"] is True
    assert data["device_class"] == "suction_cup"
