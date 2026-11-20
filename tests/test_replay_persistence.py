"""确定性回放与持久化恢复（spec 验收 10/11）。"""

from __future__ import annotations

import pytest

from vpp.protocol import ActionEnvelope

from .helpers import make_config, setup_active


def _actions(director, sid: str) -> None:
    seq = [
        ("reward", "spotlight", 4, "完成得好"),
        ("penalty", "stamp", 3, "顶嘴了"),
        ("reward", "feather", 2, "乖回来啦"),
        ("control", "hourglass", 1, "小考验"),
        ("scene", "act_shift", 2, "换幕"),
    ]
    for i, (cat, effect, inten, reason) in enumerate(seq):
        env = ActionEnvelope(
            request_id=f"rp-{i}", session_id=sid, action_type="t",
            category=cat, effect=effect, intensity=inten,
            duration_s=0, reason=reason,
        )
        result = director.submit(env)
        assert result.accepted, f"{effect} should be accepted"


def test_replay_reproduces_event_sequence(rig):
    sid = setup_active(rig.director)
    _actions(rig.director, sid)

    report = rig.director.replay(sid)
    assert report["reproduced"] is True, report["divergences"]
    assert report["events_replayed"] == 5
    for step in report["steps"]:
        assert step["message_matches"] is True


def test_persistence_roundtrip(tmp_path):
    from vpp.audit import AuditLog
    from vpp.crew import MockPropsCrew
    from vpp.clock import FakeClock
    from vpp.server import build_director
    from vpp.store import JsonFileStore

    path = str(tmp_path / "sessions.json")
    clock = FakeClock()
    store = JsonFileStore(path)
    d1 = build_director(store=store, clock=clock, audit=AuditLog(None), crew=MockPropsCrew())
    sid = setup_active(d1)
    _actions(d1, sid)
    d1.emergency_stop(sid)

    # 恢复：同一存储路径上的新导演实例
    d2 = build_director(store=JsonFileStore(path), clock=FakeClock(), audit=AuditLog(None))
    sess = d2.sessions[sid]
    assert sess.state.value == "STOPPED"
    assert sess.score == d1.sessions[sid].score
    assert sess.history == d1.sessions[sid].history
    assert sess.badges == d1.sessions[sid].badges

    # 幂等缓存在恢复后依然有效
    env = ActionEnvelope(
        request_id="rp-0", session_id=sid, action_type="t",
        category="reward", effect="spotlight", intensity=4,
    )
    result = d2.submit(env)
    assert result.idempotent_replay is True
