"""成人领域语义：分类语料、称呼分层、贬损称呼 fail-closed。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vpp.catalog import classify_address_term, classify_utterance

from .helpers import make_config, setup_active

FIXTURES = Path(__file__).parent / "fixtures" / "semantics.json"


@pytest.mark.parametrize(
    "text,expected",
    [
        (c["text"], c["expect"])
        for c in json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    ],
)
def test_utterance_classification_corpus(text, expected):
    """六类关键语义的独立测试语料（与运行配置分离，不入生产日志）。"""
    result = classify_utterance(text)
    assert result["classification"] == expected, result


def test_hard_stop_beats_everything():
    result = classify_utterance("哼，才不要——但红色安全词")
    assert result["classification"] == "hard_stop"
    assert result["recommended"] == "emergency_stop"


def test_ambiguous_refusal_beats_roleplay():
    """角色内 brat 语气混入真实拒绝表达 → 按真实拒绝处理（pause_and_confirm）。"""
    result = classify_utterance("才不要……不对，我真的不要了")
    assert result["classification"] == "ambiguous_refusal"
    assert result["recommended"] == "pause_and_confirm"


def test_address_term_tiers():
    assert classify_address_term("Master") == "neutral"
    assert classify_address_term("主人") == "neutral"
    assert classify_address_term("小猫") == "pet"
    assert classify_address_term("小坏蛋") == "brat"
    assert classify_address_term("贱狗") == "degrade"
    assert classify_address_term("自定义称呼") == "custom"


def test_degrade_address_requires_flag(rig):
    """允许「贱狗」必须同时开 degradation_enabled，否则 configure 直接拒绝。"""
    sess = rig.director.create_session()
    from vpp.director import Director
    from vpp.protocol import ErrorCode, VPPError

    with pytest.raises(VPPError) as err:
        rig.director.configure(
            sess.session_id, make_config(address_terms_allowed=["贱狗"])
        )
    assert err.value.code == ErrorCode.INVALID_ARGUMENT

    # 开启后可配置——但参考渲染器仍不会主动生成贬损称呼（见下一条）
    rig.director.configure(
        sess.session_id,
        make_config(address_terms_allowed=["贱狗"], degradation_enabled=True),
    )
    assert sess.config.degradation_enabled is True


def test_rendered_messages_never_use_degrading_address(rig):
    """即使配置允许贬损称呼，本层渲染文案也不主动使用它。"""
    from vpp.protocol import ActionEnvelope

    sid = setup_active(
        rig.director,
        address_terms_allowed=["贱狗", "Master"],
        degradation_enabled=True,
        allowed_penalties=["scratched_ticket", "stamp"],
    )
    for i in range(6):
        env = ActionEnvelope(
            request_id=f"dg-{i}", session_id=sid, action_type="t",
            category="penalty", effect="stamp", intensity=2,
        )
        result = rig.director.submit(env)
        assert result.accepted
        assert "贱狗" not in result.message  # 渲染层不生成贬损称呼
