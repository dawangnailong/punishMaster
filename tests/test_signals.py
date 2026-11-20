"""观测信道：诚实三态、文本主形态、主动话语、无自动行为。"""

from __future__ import annotations

import json

import pytest

from .helpers import call, client_setup


@pytest.mark.anyio
async def test_signal_report_honest_metrics(client):
    sid = await client_setup(client)
    r = await call(client, "signal_report", {
        "session_id": sid,
        "source": "downstream",
        "state_text": "呼吸平稳，自述投入，无不适表达。",
        "metrics": [
            {"name": "pulse", "status": "reported", "value": 88, "unit": "bpm"},
            {"name": "hardness", "status": "unsupported", "note": "下游不掌握"},
            {"name": "wetness", "status": "absent", "note": "当前不适用"},
        ],
    })
    assert r["received"] is True
    statuses = {m["name"]: m["status"] for m in r["metrics_summary"]}
    assert statuses == {"pulse": "reported", "hardness": "unsupported", "wetness": "absent"}


@pytest.mark.anyio
async def test_reported_without_value_rejected(client):
    """诚实契约：reported 必须携带 value，编造/缺值一律拒绝。"""
    sid = await client_setup(client)
    r = await call(client, "signal_report", {
        "session_id": sid,
        "source": "downstream",
        "state_text": "x",
        "metrics": [{"name": "pulse", "status": "reported"}],  # 缺 value
    })
    assert r["accepted"] is False
    assert r["error"]["code"] == "INVALID_ARGUMENT"
    assert "诚实契约" in r["message"] or "value" in r["message"]


@pytest.mark.anyio
async def test_signal_ingest_has_no_side_effect_on_scene(client):
    """信号只采集与呈现：不做任何安全决策或状态改变。"""
    sid = await client_setup(client)
    before = await call(client, "session_get", {"session_id": sid})
    await call(client, "signal_report", {
        "session_id": sid,
        "source": "downstream",
        "state_text": "用户似乎有点累了。",
        "metrics": [{"name": "breath", "status": "reported", "value": "略快"}],
        "advisory_tags": ["fatigue_reported_by_downstream"],
    })
    after = await call(client, "session_get", {"session_id": sid})
    assert after["state"] == before["state"]
    assert after["score"] == before["score"]
    assert after["signals_count"] == before["signals_count"] + 1


@pytest.mark.anyio
async def test_initiative_question_is_presented_not_executed(client):
    """下游主动话语（「今天要怎么奖励好呢？」）只呈现，不构成授权、不自动执行。"""
    sid = await client_setup(client)
    before = await call(client, "session_get", {"session_id": sid})
    r = await call(client, "signal_report", {
        "session_id": sid,
        "source": "downstream",
        "state_text": "（主动话语）等待用户点单。",
        "initiative_text": "今天要怎么奖励好呢？",
        "proposals": ["chime", "spotlight"],
    })
    assert r["received"] is True

    # 状态没被提议“自动执行”
    after = await call(client, "session_get", {"session_id": sid})
    assert after["score"] == before["score"]

    # 提议在信号资源里可见
    res = await client.read_resource(f"play://sessions/{sid}/signals")
    text = res.contents[0].text if hasattr(res, "contents") else str(res)
    data = json.loads(text)
    sig = data["signals"][-1]
    assert sig["initiative_text"] == "今天要怎么奖励好呢？"
    assert sig["proposals"] == ["chime", "spotlight"]


@pytest.mark.anyio
async def test_observe_request_effect_emits_cue_with_metric_list(client):
    sid = await client_setup(client)
    r = await call(client, "action_commit", {
        "session_id": sid, "category": "control", "effect": "observe_request",
        "request_id": "obs-1",
    })
    assert r["accepted"] is True
    cue = r["scheduled_effects"][0]
    assert "requested_metrics" in cue["extensions"]
    assert "pulse" in cue["extensions"]["requested_metrics"]
