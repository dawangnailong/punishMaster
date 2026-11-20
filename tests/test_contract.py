"""设备契约的行为测试：语义动作、realization、拒绝、停止、安全、反馈。"""

from __future__ import annotations

import json

from punishmaster.contract import ActionRequest, Realization
from punishmaster.virtual import VirtualDevice


def test_capabilities_declare_realization(device: VirtualDevice) -> None:
    caps = device.capabilities()
    actions = {a.action_id: a for a in caps.semantic_actions}

    assert caps.simulated is True
    assert actions["stimulate"].realization == Realization.NATIVE
    assert actions["tease"].realization == Realization.MODE_MAPPING
    assert actions["check"].realization == Realization.UNSUPPORTED
    assert actions["deep_suck"].realization == Realization.MODE_MAPPING
    assert {m.mode_id for m in caps.modes} >= {"gentle", "wave", "squeeze", "deep"}

    # 安全声明是语义级的，且明确原始数值不上行
    assert caps.safety["local_auto_stop"] is True
    assert caps.safety["physical_stop_button"] is True
    assert caps.safety["agent_stop"] is True
    assert caps.safety["raw_sensor_data_exposed"] is False


def test_native_action_executes(device: VirtualDevice) -> None:
    result = device.execute(
        ActionRequest(
            action_id="stimulate",
            level=4,
            duration_s=60,
            params={"depth": "deep", "rhythm": "pulse"},
        )
    )

    assert result.accepted is True
    assert result.executed is True
    assert result.supported is True
    assert result.realization == Realization.NATIVE
    assert result.simulated is True
    assert result.state.running is True
    assert result.state.current_action == "stimulate"
    assert result.state.remaining_s == 60
    assert "深部" in result.message
    assert "模拟" in result.message


def test_unsupported_action_is_refused_explicitly(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="check"))

    assert result.accepted is False
    assert result.executed is False
    assert result.supported is False
    assert result.realization == Realization.UNSUPPORTED
    assert result.state.running is False
    assert "unsupported" in result.message
    assert "未发生" in result.message


def test_unknown_action_is_refused(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="does_not_exist"))

    assert result.supported is False
    assert result.executed is False
    assert result.realization == Realization.UNSUPPORTED


def test_mode_mapping_executes_through_mode(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="tease", level=2, duration_s=30))

    assert result.accepted is True
    assert result.executed is True
    assert result.realization == Realization.MODE_MAPPING
    assert result.state.current_mode == "gentle"
    assert result.state.current_action is None


def test_vendor_extension_maps_to_mode(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="deep_suck", level=4, duration_s=30))

    assert result.executed is True
    assert result.state.current_mode == "deep"


def test_stop_is_idempotent(device: VirtualDevice) -> None:
    device.execute(ActionRequest(action_id="stimulate", duration_s=0))

    first = device.stop()
    assert first.executed is True
    assert first.state.running is False

    second = device.stop()
    assert second.executed is False
    assert second.state.running is False


def test_agent_and_physical_stop_share_the_path(device: VirtualDevice) -> None:
    device.execute(ActionRequest(action_id="stimulate", duration_s=0))
    physical = device.physical_stop()

    assert physical.executed is True
    assert physical.source == "hardware"
    assert physical.state.running is False


def test_set_level_keeps_running(device: VirtualDevice) -> None:
    device.execute(ActionRequest(action_id="stimulate", level=2, duration_s=0))
    result = device.set_level(5)

    assert result.executed is True
    assert result.state.level == 5
    assert result.state.running is True


def test_level_out_of_range_is_rejected(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="stimulate", level=9))
    assert result.accepted is False
    assert result.executed is False
    assert result.error is not None
    assert result.error["code"] == "LEVEL_OUT_OF_RANGE"


def test_duration_is_capped_by_device(device: VirtualDevice) -> None:
    result = device.execute(ActionRequest(action_id="stimulate", duration_s=99999))
    assert result.accepted is False
    assert result.error is not None
    assert result.error["code"] == "DURATION_EXCEEDED"


def test_safety_auto_stop(clock) -> None:
    device = VirtualDevice(clock=clock, max_on_s=10)
    device.execute(ActionRequest(action_id="stimulate", duration_s=0))

    clock.advance(10.1)
    state = device.status()

    assert state.running is False
    assert state.safety == "safety_stop"
    assert "安全" in state.feedback
    events, _ = device.poll_events()
    assert any(e.kind == "safety" for e in events)


def test_hardware_can_request_upstream_reasoning(clock) -> None:
    device = VirtualDevice(clock=clock, max_on_s=10)
    device.execute(ActionRequest(action_id="stimulate", duration_s=0))

    clock.advance(9.1)
    device.status()

    events, next_cursor = device.poll_events()
    assert next_cursor >= 1
    assert any(e.kind == "reasoning_request" for e in events)


def test_status_has_no_raw_sensor_numbers(device: VirtualDevice) -> None:
    device.execute(
        ActionRequest(action_id="stimulate", params={"rhythm": "pulse", "depth": "deep"})
    )
    blob = json.dumps(device.status().model_dump(mode="json"), ensure_ascii=False).lower()

    for banned in ("sensor", "raw", "bpm", "pulse_hz", "mmhg"):
        assert banned not in blob


def test_media_channel_is_optional_and_empty(device: VirtualDevice) -> None:
    assert device.media() == []
    assert device.capabilities().supports_media is False
