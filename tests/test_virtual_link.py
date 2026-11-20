"""虚拟链路层：扫描/连接的函数形状 + 假想注册的诚实叙述。

验收点：
- link_scan 只遍历本地假想名册，且如实说明没有真实扫描活动；
- link_connect/link_disconnect 是本地状态写入/删除，连接 ≠ 授权；
- 链路返回用直白语言（happening_now），不用舞台意象描述系统行为；
- 每个内置效果都有直白语义名 plain_name（语义优先，拟物退居皮肤）。
"""

from __future__ import annotations

import pytest

from .helpers import call, client_setup


@pytest.mark.anyio
async def test_scan_reads_hypothetical_roster_honestly(client):
    r = await call(client, "link_scan", {})
    assert r["simulated"] is True
    # 诚实叙述：说的是"假想名册/本地内存"，且明示没有真实扫描
    assert "假想" in r["happening_now"]
    assert "没有发生任何" in r["happening_now"]
    devices = r["devices"]
    assert devices, "名册不应为空"
    for d in devices:
        assert d["registration"] == "hypothetical"
        assert d["simulated"] is True
        assert d["plain_name"], "设备必须有直白名称（不做拟物包装）"
        assert "不存在" in d["note"] or "模拟" in d["note"]


@pytest.mark.anyio
async def test_connect_is_local_state_write_and_idempotent(client):
    created = await call(client, "session_create", {})
    sid = created["session_id"]
    r = await call(client, "link_connect", {"session_id": sid, "device_id": "sim-epp-01"})
    assert r["accepted"] is True and r["executed"] is True
    assert "本地状态写入" in r["happening_now"] or "本地内存状态" in r["happening_now"]
    assert "没有发生任何真实握手" in r["happening_now"]
    assert "≠ 授权" in r["note"]
    # 幂等：重复连接不重复执行
    r2 = await call(client, "link_connect", {"session_id": sid, "device_id": "sim-epp-01"})
    assert r2["accepted"] is True and r2["executed"] is False
    assert "sim-epp-01" in r2["connected_devices"]


@pytest.mark.anyio
async def test_connect_unknown_device_rejected(client):
    created = await call(client, "session_create", {})
    r = await call(client, "link_connect", {"session_id": created["session_id"],
                                            "device_id": "real-ble-00"})
    assert r["accepted"] is False
    assert r["error"]["code"] == "INVALID_ARGUMENT"
    assert "假想名册" in r["error"]["message"]


@pytest.mark.anyio
async def test_connect_rejected_after_stop(client):
    sid = await client_setup(client)
    await call(client, "session_stop", {"session_id": sid})
    r = await call(client, "link_connect", {"session_id": sid, "device_id": "sim-epp-01"})
    assert r["accepted"] is False
    assert r["error"]["code"] == "INVALID_STATE"


@pytest.mark.anyio
async def test_disconnect_idempotent_and_visible_in_snapshot(client):
    created = await call(client, "session_create", {})
    sid = created["session_id"]
    await call(client, "link_connect", {"session_id": sid, "device_id": "sim-warm-01"})
    snap = await call(client, "session_get", {"session_id": sid})
    assert "sim-warm-01" in snap["links_connected"]
    r = await call(client, "link_disconnect", {"session_id": sid, "device_id": "sim-warm-01"})
    assert r["executed"] is True
    assert "本地" in r["happening_now"]
    r2 = await call(client, "link_disconnect", {"session_id": sid, "device_id": "sim-warm-01"})
    assert r2["executed"] is False  # 幂等


@pytest.mark.anyio
async def test_scan_connect_then_announce_full_virtual_path(client):
    """完整假想链路：扫描 → 连接 → 注册能力菜单（连接/注册都 ≠ 授权）。"""
    sid = await client_setup(client)
    scan = await call(client, "link_scan", {})
    device_id = scan["devices"][0]["device_id"]
    connected = await call(client, "link_connect", {"session_id": sid, "device_id": device_id})
    assert connected["accepted"] is True

    from mock_downstream import capabilities_menu_payload

    r = await call(client, "crew_announce", {
        "session_id": sid,
        "crew_name": "E-Pneumatic-Pro 模拟器（链路测试）",
        "effects": capabilities_menu_payload(),
    })
    assert r["accepted"] is True
    # 链路事件进入历史且已脱敏为直白描述
    hist = await call(client, "history_list", {"session_id": sid, "limit": 50})
    link_events = [e for e in hist["events"] if e["kind"] == "link"]
    assert link_events and "假想连接" in link_events[0]["summary"]


def test_every_effect_has_plain_name():
    """语义优先的结构保证：每个内置效果都必须有非空直白语义名。"""
    from vpp.catalog import EFFECTS, PLAIN_NAMES, effects_catalog

    assert set(PLAIN_NAMES) == set(EFFECTS), "plain_name 与效果目录必须一一对应"
    for entry in effects_catalog():
        assert entry["plain_name"], f"{entry['effect']} 缺 plain_name"
        # 直白名排在 label 之前：第一名称不依赖舞台意象
        keys = list(entry.keys())
        assert keys.index("plain_name") < keys.index("label")
