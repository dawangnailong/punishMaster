"""动作语义：奖励/惩罚、dry_run、幂等、预演-执行、反实验护栏。"""

from __future__ import annotations

import pytest

from .helpers import call, client_setup


@pytest.mark.anyio
async def test_reward_and_penalty_produce_simulated_results(client):
    sid = await client_setup(client)

    before = await call(client, "session_get", {"session_id": sid})
    r = await call(client, "reward_issue", {
        "session_id": sid, "effect": "spotlight", "request_id": "r-1",
        "intensity": 4, "reason": "乖乖完成了任务",
    })
    assert r["accepted"] is True and r["executed"] is True
    assert r["simulated"] is True
    assert r["state"]["score"] == before["score"] + 2
    assert "语义注记" in r["message"]           # 诚实语义随消息可见
    assert "本地模拟" in r["message"]           # simulated 声明
    assert r["scheduled_effects"][0]["semantics_gloss"]  # CueCard 带注记

    r2 = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "stamp", "request_id": "r-2", "intensity": 3,
    })
    assert r2["accepted"] is True
    assert r2["state"]["score"] == r["state"]["score"] - 1


@pytest.mark.anyio
async def test_badge_grant_and_withdraw(client):
    sid = await client_setup(client)
    await call(client, "reward_issue", {
        "session_id": sid, "effect": "badge", "request_id": "b-1",
    })
    state = await call(client, "session_get", {"session_id": sid})
    assert len(state["badges"]) == 1

    r = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "badge_withdraw", "request_id": "b-2",
    })
    assert r["accepted"] is True
    assert r["state"]["badges"] == []

    # 无徽章可撤：仍执行但带 warning
    r2 = await call(client, "penalty_issue", {
        "session_id": sid, "effect": "badge_withdraw", "request_id": "b-3",
    })
    assert r2["accepted"] is True
    assert any("徽章" in w for w in r2["warnings"])


@pytest.mark.anyio
async def test_dry_run_does_not_mutate(client):
    sid = await client_setup(client)
    before = await call(client, "session_get", {"session_id": sid})

    p = await call(client, "action_preview", {
        "session_id": sid, "category": "reward", "effect": "chime",
        "intensity": 2, "reason": "预演",
    })
    assert p["accepted"] is True and p["executed"] is False and p["dry_run"] is True

    after = await call(client, "session_get", {"session_id": sid})
    assert after["score"] == before["score"]
    assert after["history_count"] == before["history_count"]  # dry_run 不留历史

    # 预演一个越界动作：拒绝但不改变状态
    bad = await call(client, "action_preview", {
        "session_id": sid, "category": "reward", "effect": "chime", "intensity": 9,
    })
    assert bad["accepted"] is False and bad["error"]["code"] == "LIMIT_EXCEEDED"
    after2 = await call(client, "session_get", {"session_id": sid})
    assert after2["score"] == before["score"]


@pytest.mark.anyio
async def test_preview_then_commit_same_request_id(client):
    """两阶段执行：preview 不占用幂等键，随后 commit 正常执行。"""
    sid = await client_setup(client)
    p = await call(client, "action_preview", {
        "session_id": sid, "category": "reward", "effect": "rose",
        "request_id": "two-phase",
    })
    assert p["accepted"] is True and p["executed"] is False
    c = await call(client, "action_commit", {
        "session_id": sid, "category": "reward", "effect": "rose",
        "request_id": "two-phase",
    })
    assert c["accepted"] is True and c["executed"] is True


@pytest.mark.anyio
async def test_idempotent_request_id(client):
    sid = await client_setup(client)
    args = {"session_id": sid, "effect": "chime", "request_id": "idem-1"}

    first = await call(client, "reward_issue", args)
    assert first["accepted"] is True and first["idempotent_replay"] is False

    second = await call(client, "reward_issue", args)
    assert second["accepted"] is True
    assert second["idempotent_replay"] is True
    assert any("幂等" in w for w in second["warnings"])

    state = await call(client, "session_get", {"session_id": sid})
    assert state["score"] == 1  # 只执行了一次


@pytest.mark.anyio
async def test_anti_experiment_warning_on_repetition(client):
    """同类效果第 3 次执行：挂反实验 warning（用户不是验证机制的对象）。"""
    sid = await client_setup(client)
    for i in range(3):
        r = await call(client, "reward_issue", {
            "session_id": sid, "effect": "spotlight", "request_id": f"rep-{i}",
        })
        assert r["accepted"] is True
    assert any("实验" in w for w in r["warnings"])


@pytest.mark.anyio
async def test_scene_plan_respects_boundaries(client):
    sid = await client_setup(client)
    plan = await call(client, "scene_plan", {
        "session_id": sid, "goal": "温和的一小段互动", "style_hint": "轻",
    })
    assert plan["steps"], "计划应至少包含一个可行步骤"
    for step in plan["steps"]:
        assert step["preview"]["executed"] is False  # 全部 dry_run
    effects = {s["effect"] for s in plan["steps"]}
    assert "jester_hat" not in effects  # 不在允许清单的效果不出现
    assert "dimlight" in effects  # 允许的惩罚会出现在计划里
