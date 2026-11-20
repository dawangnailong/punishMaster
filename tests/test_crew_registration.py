"""下游能力菜单注册（crew_announce）：注册 ≠ 授权。"""

from __future__ import annotations

import pytest

from .helpers import call, client_setup


async def _announce(client, sid: str) -> dict:
    from mock_downstream import capabilities_menu_payload

    return await call(client, "crew_announce", {
        "session_id": sid,
        "crew_name": "E-Pneumatic-Pro 模拟器（测试）",
        "effects": capabilities_menu_payload(),
    })


@pytest.mark.anyio
async def test_announce_registers_capability_menu(client):
    created = await call(client, "session_create", {})
    sid = created["session_id"]
    r = await _announce(client, sid)
    assert r["accepted"] is True
    ids = {e["crew_effect"] for e in r["registered"]}
    assert {"crew:suction_gentle", "crew:deep_throat", "crew:warm_hug"} <= ids
    assert "注册 ≠ 授权" in r["note"] or "不构成授权" in r["note"]


@pytest.mark.anyio
async def test_registered_but_not_allowed_is_rejected(client):
    """注册了 ≠ 可以用：不在允许清单 → ACTION_NOT_ALLOWED（fail-closed）。"""
    sid = await client_setup(client)  # allowed_rewards 不含 crew:*
    await _announce(client, sid)
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "crew:deep_throat", "request_id": "c1", "intensity": 3,
    })
    assert r["accepted"] is False
    assert r["error"]["code"] == "ACTION_NOT_ALLOWED"


@pytest.mark.anyio
async def test_allowed_and_flagged_capability_executes(client):
    """允许清单 + 行为开关都满足时，注册能力可以执行且全部为模拟。"""
    sid = await client_setup(
        client,
        allowed_rewards=["chime", "crew:suction_gentle", "crew:deep_throat", "crew:warm_hug"],
    )
    await _announce(client, sid)
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "crew:deep_throat", "request_id": "c2",
        "intensity": 5, "duration_s": 120, "reason": "表现很好，用户允许了四档",
    })
    assert r["accepted"] is True and r["executed"] is True
    assert r["simulated"] is True
    gloss = r["scheduled_effects"][0]["semantics_gloss"]
    assert "最强" in gloss or "最深档" in gloss or "强感官" in gloss
    # 带时长的感官效果会占用虚拟时间线（收尾卡）
    assert r["state"]["timeline_pending"] == 1


@pytest.mark.anyio
async def test_capability_intensity_cap_enforced(client):
    """能力自报上限同样硬性：四档自报 8，但会话上限 5 时以更低者为准。"""
    sid = await client_setup(
        client, allowed_rewards=["crew:deep_throat"], max_intensity=5,
    )
    await _announce(client, sid)
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "crew:deep_throat", "request_id": "c3", "intensity": 6,
    })
    assert r["error"]["code"] == "LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_capability_duration_range_enforced(client):
    sid = await client_setup(client, allowed_rewards=["crew:warm_hug"])
    await _announce(client, sid)
    # warm_hug 自报 duration_min_s=60：短于下限被拒
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "crew:warm_hug", "request_id": "c4",
        "duration_s": 10,
    })
    assert r["error"]["code"] == "LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_unregistered_crew_effect_rejected(client):
    sid = await client_setup(client, allowed_rewards="all")
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "crew:nonexistent", "request_id": "c5",
    })
    assert r["accepted"] is False
    assert r["error"]["code"] == "INVALID_ARGUMENT"
    assert "crew_announce" in r["message"]


@pytest.mark.anyio
async def test_announce_rejected_without_honest_semantics(client):
    sid = await client_setup(client)
    r = await call(client, "crew_announce", {
        "session_id": sid,
        "crew_name": "某下游",
        "effects": [{"effect_id": "x_mode", "label": "神秘模式",
                     "description": "很厉害", "actual_semantics": ""}],
    })
    assert r["accepted"] is False
    assert "诚实语义" in r["message"]


@pytest.mark.anyio
async def test_crew_capabilities_resource(client):
    sid = await client_setup(client)
    await _announce(client, sid)
    res = await client.read_resource(f"play://sessions/{sid}/crew-capabilities")
    text = res.contents[0].text if hasattr(res, "contents") else str(res)
    import json as _json

    data = _json.loads(text)
    ids = {e["crew_effect"] for e in data["crew_effects"]}
    assert "crew:deep_throat" in ids
    assert "注册 ≠ 授权" in data["note"]
