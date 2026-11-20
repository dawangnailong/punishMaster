"""验收全流程演示：Inspector 等效客户端的完整走查。

跑法：
    PYTHONPATH=src .venv/bin/python examples/full_flow.py

流程（对应任务书第九节验收清单）：
创建会话 → 配置边界 → 授权 → 预演 → 执行奖励 → 执行虚拟惩罚 →
暂停 → 恢复 → 查询历史 → 下游观测回传 + 主动话语 → 紧急停止 → 验证停止后动作被拒绝。

模拟下游（mock_downstream.MockDownstream）接管拟物渲染，
端到端演示：下发 CueCard → 下游渲染 → 上行 StatusSignal 的完整回环。
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp import Client  # noqa: E402

from mock_downstream import (  # noqa: E402
    MockDownstream,
    ObserveContext,
    capabilities_menu_payload,
)
from vpp.audit import AuditLog  # noqa: E402
from vpp.clock import FakeClock  # noqa: E402
from vpp.config import SessionConfig  # noqa: E402
from vpp.server import build_director, build_mcp  # noqa: E402
from vpp.store import MemoryStore  # noqa: E402

PASS = "  ✓"
FAIL = "✗ 失败："


def banner(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


async def step(client, name: str, tool: str, args: dict, check=None) -> dict:
    result = await client.call_tool(tool, args)
    data = result.structured_content
    ok = True
    if check is not None:
        ok = check(data)
    print(f"{PASS if ok else FAIL} {name}")
    msg = data.get("message", "")
    if msg:
        for line in msg.splitlines()[:3]:
            print(f"    {line}")
    if not ok:
        raise SystemExit(f"验收失败：{name} -> {data.get('error')}")
    return data


async def main() -> None:
    clock = FakeClock()
    crew = MockDownstream()  # 独立模拟下游接管拟物渲染
    director = build_director(
        store=MemoryStore(), clock=clock, audit=AuditLog(None), crew=crew
    )
    mcp = build_mcp(director)

    async with Client(mcp, raise_exceptions=True) as c:
        banner("① 创建会话")
        created = await step(c, "session_create", "session_create", {},
                             lambda d: d["state"] == "DRAFT")
        sid = created["session_id"]

        banner("② 配置边界（称呼/允许清单/上限/行为开关）")
        cfg = SessionConfig(
            agent_title="管家",
            user_title="Master",
            address_terms_allowed=["小猫", "Master"],
            address_terms_blocked=[],
            allowed_rewards=[
                "chime", "spotlight", "rose", "crown", "badge", "feather", "bell_grant",
                "crew:suction_gentle", "crew:deep_throat",
            ],
            allowed_penalties=["dimlight", "stamp", "ticket", "task_card", "badge_withdraw", "hourglass_wait"],
            max_intensity=5,
            max_action_duration_s=600,
            max_scene_duration_s=7200,
            praise_enabled=True,
            orgasm_control_enabled=True,
            explicitness_level="moderate",
            aftercare_preferences="温和收尾：一句总结 + 一个拥抱符号",
        )
        await step(c, "session_configure", "session_configure",
                   {"session_id": sid, "config": cfg.model_dump(mode="json")},
                   lambda d: d["accepted"] is True)

        banner("③ 显式授权")
        await step(c, "session_authorize（consent_note 非空）", "session_authorize",
                   {"session_id": sid, "consent_note": "用户口头确认：称呼小猫，强度≤5，今晚只玩轻的"},
                   lambda d: d["accepted"] is True)

        banner("④ 开幕")
        await step(c, "scene_resume（READY→ACTIVE）", "scene_resume",
                   {"session_id": sid}, lambda d: d["executed"] is True)

        banner("④b 下游连接：注册能力菜单（注册 ≠ 授权）")
        menu = crew.capabilities_declaration(session_id=sid)
        announced = await step(c, "crew_announce（E-Pneumatic-Pro 模拟器）", "crew_announce",
                              {"session_id": sid, "crew_name": menu.crew_name,
                               "effects": capabilities_menu_payload(),
                               "notes": menu.notes},
                              lambda d: d["accepted"] is True)
        print(f"    注册能力：{', '.join(e['crew_effect'] for e in announced['registered'])}")

        banner("⑤ 预演（dry_run，不落状态）")
        preview = await step(c, "action_preview reward/spotlight", "action_preview",
                             {"session_id": sid, "category": "reward", "effect": "spotlight",
                              "intensity": 4, "reason": "乖乖汇报了行程"},
                             lambda d: d["accepted"] is True and d["executed"] is False)
        assert preview["dry_run"] is True

        banner("⑥ 执行奖励（模拟下游渲染）")
        reward = await step(c, "reward_issue spotlight", "reward_issue",
                            {"session_id": sid, "effect": "spotlight", "request_id": "flow-r1",
                             "intensity": 4, "reason": "乖乖汇报了行程"},
                            lambda d: d["executed"] is True)
        assert reward["scheduled_effects"][0]["semantics_gloss"], "CueCard 应带诚实语义注记"

        banner("⑥b 下发注册能力（下游渲染四档吮吸意象）")
        crew_reward = await step(c, "reward_issue crew:deep_throat", "reward_issue",
                                  {"session_id": sid, "effect": "crew:deep_throat",
                                   "request_id": "flow-c1", "intensity": 5,
                                   "duration_s": 120, "reason": "用户明确允许了四档"},
                                  lambda d: d["executed"] is True)
        assert "模拟下游渲染" in crew_reward["message"]

        banner("⑦ 执行虚拟惩罚")
        penalty = await step(c, "penalty_issue stamp", "penalty_issue",
                             {"session_id": sid, "effect": "stamp", "request_id": "flow-p1",
                              "intensity": 3, "reason": "偷偷熬夜"},
                             lambda d: d["executed"] is True)
        print(f"    当前计分：{penalty['state']['score']}")

        banner("⑧ 暂停 → 恢复")
        await step(c, "scene_pause", "scene_pause", {"session_id": sid},
                   lambda d: d["executed"] is True)
        await step(c, "scene_resume", "scene_resume", {"session_id": sid},
                   lambda d: d["executed"] is True)

        banner("⑨ 查询历史（已脱敏）")
        hist = await step(c, "history_list", "history_list",
                          {"session_id": sid, "limit": 20}, lambda d: len(d["events"]) >= 4)
        for ev in hist["events"][-4:]:
            print(f"    · [{ev['kind']}] {ev['summary']}")

        banner("⑩ 下游观测回传（诚实三态）+ 主动话语")
        obs = crew.observe(ObserveContext(session_id=sid, seed=42, address="小猫"))
        await step(c, "signal_report（downstream）", "signal_report",
                   {"session_id": sid,
                    "source": "downstream",
                    "state_text": obs.state_text,
                    "metrics": [m.model_dump(mode="json") for m in obs.metrics]},
                   lambda d: d["received"] is True)
        ask = crew.initiative(ObserveContext(session_id=sid, seed=43, address="小猫"),
                               proposals=["chime", "feather"])
        print(f"    下游主动话语：「{ask.initiative_text}」")
        await step(c, "signal_report（主动话语）", "signal_report",
                   {"session_id": sid, "source": "downstream",
                    "state_text": ask.state_text,
                    "initiative_text": ask.initiative_text,
                    "proposals": ask.proposals},
                   lambda d: d["received"] is True)

        banner("⑪ 紧急停止")
        await step(c, "emergency_stop", "emergency_stop", {"session_id": sid},
                   lambda d: d["executed"] is True and d["state"]["state"] == "STOPPED")
        await step(c, "emergency_stop（重复，幂等）", "emergency_stop", {"session_id": sid},
                   lambda d: d["executed"] is False)

        banner("⑫ 停止后动作被拒绝")
        await step(c, "reward_issue 被拒绝", "reward_issue",
                   {"session_id": sid, "effect": "chime", "request_id": "flow-after"},
                   lambda d: d["accepted"] is False and d["error"]["code"] == "INVALID_STATE")

    print("\n" + "═" * 60)
    print("验收流程全部通过：12 步 ✓（全链路为本地拟物模拟，无任何真实设备）")


if __name__ == "__main__":
    asyncio.run(main())
