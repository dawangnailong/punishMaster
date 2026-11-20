"""安全边界与生命周期（spec 验收 2/4/5/6/7 + 状态机）。"""

from __future__ import annotations

import pytest

from .helpers import call, client_setup, make_config


@pytest.mark.anyio
async def test_actions_rejected_before_authorize(client):
    """未配置/未授权的会话不能执行任何奖励或惩罚（fail-closed）。"""
    created = await call(client, "session_create", {})
    sid = created["session_id"]

    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "chime", "request_id": "x1",
    })
    assert r["accepted"] is False
    assert r["error"]["code"] == "INVALID_STATE"  # 未配置

    await call(client, "session_configure", {"session_id": sid, "config": make_config().model_dump(mode="json")})
    r2 = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "stamp", "request_id": "x2",
    })
    assert r2["accepted"] is False
    assert r2["error"]["code"] == "CONSENT_REQUIRED"  # 配置了但未授权
    assert r2["state"]["score"] == 0  # 计分未被污染


@pytest.mark.anyio
async def test_paused_and_stopped_reject_actions(client):
    sid = await client_setup(client)

    paused = await call(client, "scene_pause", {"session_id": sid})
    assert paused["executed"] is True
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "chime", "request_id": "p1",
    })
    assert r["accepted"] is False and r["error"]["code"] == "INVALID_STATE"
    await call(client, "scene_resume", {"session_id": sid})

    stopped = await call(client, "session_stop", {"session_id": sid})
    assert stopped["state"]["state"] == "STOPPED"
    r2 = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "stamp", "request_id": "p2",
    })
    assert r2["accepted"] is False and r2["error"]["code"] == "INVALID_STATE"


@pytest.mark.anyio
async def test_over_limits_rejected(client):
    """越界强度与超长时长被拒绝；Agent 请求不能突破用户配置。"""
    sid = await client_setup(client)

    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "spotlight", "request_id": "l1", "intensity": 6,
    })
    assert r["accepted"] is False and r["error"]["code"] == "LIMIT_EXCEEDED"

    r2 = await call(client, "action_commit", {
        "session_id": sid, "category": "scene", "effect": "interlude",
        "request_id": "l2", "duration_s": 601,
    })
    assert r2["accepted"] is False and r2["error"]["code"] == "LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_configure_rejects_above_hard_caps(client):
    created = await call(client, "session_create", {})
    sid = created["session_id"]
    cfg = make_config(max_intensity=9).model_dump(mode="json")  # > 服务器硬上限 8
    r = await call(client, "session_configure", {"session_id": sid, "config": cfg})
    assert r["accepted"] is False and r["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.anyio
async def test_unknown_effect_and_wrong_category(client):
    sid = await client_setup(client)
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "不存在的效果", "request_id": "u1",
    })
    assert r["error"]["code"] == "INVALID_ARGUMENT"

    # chime 不属于 penalty 类别
    r2 = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "chime", "request_id": "u2",
    })
    assert r2["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.anyio
async def test_not_in_allowlist_and_missing_kink_flag(client):
    sid = await client_setup(client)  # allowed_penalties 不含 jester_hat
    r = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "jester_hat", "request_id": "a1",
    })
    assert r["error"]["code"] == "ACTION_NOT_ALLOWED"

    # 允许清单放行但 humiliation 开关未开 → CONSENT_REQUIRED
    sid2 = await client_setup(client, allowed_penalties=["jester_hat", "stamp"])
    r2 = await call(client, "penalty_issue", {
        "session_id": sid2, "effect": "jester_hat", "request_id": "a2",
    })
    assert r2["error"]["code"] == "CONSENT_REQUIRED"


@pytest.mark.anyio
async def test_illegal_transitions_rejected(client):
    created = await call(client, "session_create", {})
    sid = created["session_id"]

    r = await call(client, "scene_pause", {"session_id": sid})  # DRAFT 不可暂停
    assert r["accepted"] is False and r["error"]["code"] == "INVALID_STATE"

    sid2 = await client_setup(client)
    await call(client, "scene_resume", {"session_id": sid2})  # ACTIVE 中再 resume
    r2 = await call(client, "scene_resume", {"session_id": sid2})
    assert r2["accepted"] is True and r2["executed"] is False  # 幂等


@pytest.mark.anyio
async def test_emergency_stop_active_paused_repeat(client, rig):
    sid = await client_setup(client)

    # ACTIVE 下紧急停止
    es = await call(client, "emergency_stop", {"session_id": sid})
    assert es["accepted"] is True and es["executed"] is True
    assert es["state"]["state"] == "STOPPED"
    assert es["state"]["timeline_pending"] == 0

    # 重复调用幂等
    es2 = await call(client, "emergency_stop", {"session_id": sid})
    assert es2["accepted"] is True and es2["executed"] is False

    # 停止后一切动作被拒绝
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "chime", "request_id": "post-es",
    })
    assert r["accepted"] is False and r["error"]["code"] == "INVALID_STATE"

    # PAUSED 下紧急停止
    sid2 = await client_setup(client)
    await call(client, "scene_pause", {"session_id": sid2})
    es3 = await call(client, "emergency_stop", {"session_id": sid2})
    assert es3["accepted"] is True and es3["executed"] is True
    assert es3["state"]["state"] == "STOPPED"


@pytest.mark.anyio
async def test_no_background_tasks_after_stop(client, rig):
    """停止后不存在继续触发的后台任务：虚拟时间线清空且快进后无新事件。"""
    sid = await client_setup(client)
    await call(client, "action_commit", {
        "session_id": sid, "category": "control", "effect": "hourglass",
        "request_id": "h1", "duration_s": 60,
    })
    state = await call(client, "session_get", {"session_id": sid})
    assert state["timeline_pending"] == 1

    await call(client, "emergency_stop", {"session_id": sid})
    rig.clock.advance(10_000_000)  # 快进约 115 天
    state2 = await call(client, "session_get", {"session_id": sid})
    assert state2["state"] == "STOPPED"
    assert state2["timeline_pending"] == 0
    hist = await call(client, "history_list", {"session_id": sid, "limit": 200})
    kinds = [e["kind"] for e in hist["events"]]
    assert kinds.count("cue_due") == 0  # 时间线已取消，快进也不触发


@pytest.mark.anyio
async def test_virtual_timeline_due_only_when_active(client, rig):
    """暂停期间虚拟时钟冻结：到期卡不结算；恢复后按虚拟时间结算。"""
    sid = await client_setup(client)
    await call(client, "action_commit", {
        "session_id": sid, "category": "control", "effect": "hourglass",
        "request_id": "hh1", "duration_s": 60,
    })
    await call(client, "scene_pause", {"session_id": sid})
    rig.clock.advance(600)
    state = await call(client, "session_get", {"session_id": sid})
    assert state["timeline_pending"] == 1  # 冻结：未到期结算
    await call(client, "scene_resume", {"session_id": sid})
    rig.clock.advance(61)
    state2 = await call(client, "session_get", {"session_id": sid})
    assert state2["timeline_pending"] == 0  # 恢复后按虚拟时间到期
