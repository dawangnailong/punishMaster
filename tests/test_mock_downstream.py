"""独立模拟下游（参考实现）的契约行为。"""

from __future__ import annotations

import pytest

from mock_downstream import MockDownstream, ObserveContext
from vpp.crew import RenderContext
from vpp.protocol import CueCard


def _cue(effect: str, gesture: str, seed_note: str = "备注") -> CueCard:
    return CueCard(
        cue_id="cue_test", session_id="ses_test", request_id="req_test",
        effect=effect, gesture=gesture, stage_note=seed_note,
    )


def test_render_is_deterministic_and_simulated():
    ds = MockDownstream()
    ctx = RenderContext(address="小猫", seed=42)
    a = ds.render(_cue("chime", "strike"), ctx)
    b = ds.render(_cue("chime", "strike"), ctx)
    assert a.text == b.text
    assert a.simulated is True
    assert "模拟下游渲染" in a.text
    assert "小猫" in a.text
    assert "导演备注" in a.text  # stage_note 被呈现为导演备注


def test_render_falls_back_gracefully():
    ds = MockDownstream()
    ctx = RenderContext(address="Master", seed=7)
    out = ds.render(_cue("curtain_open", "open"), ctx)
    assert out.text  # 未收录的组合走手势兜底，不崩溃


def test_observe_covers_all_three_honest_statuses():
    ds = MockDownstream()
    signal = ds.observe(ObserveContext(session_id="s1", seed=7, address="小猫"))
    assert signal.source == "downstream"
    statuses = {m.name: m.status for m in signal.metrics}
    assert statuses["pulse"] == "reported"      # 声明性模拟值（note 明示）
    assert statuses["hardness"] == "unsupported"
    assert statuses["pupil"] == "unsupported"
    assert statuses["wetness"] == "absent"
    # 文本是主形态
    assert signal.state_text
    # 声明性模拟必须在文本里自我声明（不冒充真实采集）
    assert "模拟" in signal.state_text


def test_observe_is_deterministic():
    ds = MockDownstream()
    a = ds.observe(ObserveContext(session_id="s1", seed=99))
    b = ds.observe(ObserveContext(session_id="s1", seed=99))
    assert a.state_text == b.state_text
    assert [m.value for m in a.metrics] == [m.value for m in b.metrics]


def test_initiative_asks_and_proposes_without_authorizing():
    ds = MockDownstream()
    sig = ds.initiative(
        ObserveContext(session_id="s1", seed=5, address="小猫"),
        proposals=["chime", "spotlight"],
    )
    assert sig.initiative_text
    assert "小猫" in sig.initiative_text
    assert sig.proposals == ["chime", "spotlight"]
    # 主动话语只是文本：不携带任何会被执行的结构化动作
    assert sig.source == "downstream"


def test_downstream_can_drive_director_end_to_end(rig):
    """把模拟下游接进导演台（作为 Crew）：下发 → 下游渲染 → 上行观测/主动话语，整条回环跑通。"""
    from vpp.protocol import ActionEnvelope
    from vpp.session import SessionState
    from .helpers import setup_active

    ds = MockDownstream()
    rig.director.crew = ds  # 下游接管拟物渲染
    sid = setup_active(rig.director)

    # 1. 下发奖励：渲染文本来自模拟下游
    env = ActionEnvelope(
        request_id="loop-1", session_id=sid, action_type="issue_reward",
        category="reward", effect="spotlight", intensity=4, reason="回环测试",
    )
    result = rig.director.submit(env)
    assert result.accepted and result.executed
    assert "模拟下游渲染" in result.message

    # 2. 下游观测回传（诚实三态）+ 主动话语
    observe = ds.observe(ObserveContext(session_id=sid, seed=11, address="小猫"))
    ingested = rig.director.ingest_signal(sid, observe)
    assert ingested["received"] is True
    ask = ds.initiative(
        ObserveContext(session_id=sid, seed=12, address="小猫"), proposals=["chime"],
    )
    ingested2 = rig.director.ingest_signal(sid, ask)
    assert ingested2["received"] is True

    # 3. 导演层只呈现：状态与计分不受信号影响
    sess = rig.director.sessions[sid]
    assert sess.state is SessionState.ACTIVE
    assert len(sess.signals) == 2
    assert sess.signals[-1].initiative_text == ask.initiative_text

    # 4. 提议不构成授权：执行仍走全部校验
    env2 = ActionEnvelope(
        request_id="loop-2", session_id=sid, action_type="issue_penalty",
        category="penalty", effect="jester_hat", intensity=2,
    )
    result2 = rig.director.submit(env2)
    assert result2.accepted is False
    assert result2.error["code"] in ("ACTION_NOT_ALLOWED", "CONSENT_REQUIRED")
