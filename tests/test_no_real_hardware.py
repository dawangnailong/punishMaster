"""结构保证：本仓库不存在真实硬件/网络控制路径（spec 验收 12）。"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"

BANNED_PATTERNS = [
    r"\bimport\s+bleak\b",
    r"\bfrom\s+bleak\b",
    r"\bimport\s+serial\b",
    r"\bfrom\s+serial\b",
    r"\bimport\s+bluetooth\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+threading\b",
    r"\bfrom\s+subprocess\b",
    r"\bimport\s+requests\b",
    r"\bimport\s+urllib\b",
    r"urlopen",
    # BLE 服务/特征 UUID 与 MAC 地址（原参考项目协议，禁止移植）
    r"0000ff[0-9a-fA-F]{2}",
    r"\bffb[0-9a-fA-F]\b",
    r"\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b",
]

FILES = sorted((SRC).rglob("*.py"))


def test_source_files_present():
    assert len(FILES) >= 10, f"src 下应有完整的实现文件，实际 {len(FILES)}"


def test_no_real_hardware_or_network_paths():
    offenders: list[str] = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.name}: {pattern}")
    assert not offenders, f"发现真实硬件/网络控制路径：{offenders}"


def test_crew_and_downstream_declare_not_real():
    from mock_downstream import MockDownstream
    from vpp.crew import MockPropsCrew

    for crew in (MockPropsCrew(), MockDownstream()):
        caps = crew.capabilities()
        assert caps["real_hardware"] is False


def test_no_background_threads_or_timers():
    """所有计时走虚拟时钟惰性求值：不允许线程/定时器/信号闹钟。"""
    offenders = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for banned in ("threading.Timer", "asyncio.create_task", "Timer(", "signal.alarm"):
            if banned in text:
                offenders.append(f"{path.name}: {banned}")
    assert not offenders, f"发现后台任务构造：{offenders}"


def test_every_action_result_is_simulated():
    """ActionResult.simulated 由模型强制恒为 True。"""
    import vpp.protocol as proto

    schema = proto.ActionResult.model_json_schema()
    assert "simulated" in schema["properties"]
    r = proto.ActionResult(accepted=True, executed=True, request_id="x", session_id="y")
    assert r.simulated is True
