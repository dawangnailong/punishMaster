"""本仓库仍然只是虚拟设备：源码中不允许出现真实硬件/网络路径。"""

from __future__ import annotations

import re
from pathlib import Path

from punishmaster.virtual import VirtualDevice

SRC = Path(__file__).parent.parent / "src" / "punishmaster"

BANNED = [
    r"\bimport\s+bleak\b",
    r"\bfrom\s+bleak\b",
    r"\bimport\s+serial\b",
    r"\bfrom\s+serial\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+subprocess\b",
    r"\bfrom\s+subprocess\b",
    r"\bimport\s+threading\b",
    r"\bimport\s+requests\b",
    r"\bimport\s+urllib\b",
]


def test_no_real_hardware_or_network_imports() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in BANNED:
            if re.search(pattern, text):
                offenders.append(f"{path.name}: {pattern}")
    assert not offenders, f"发现真实硬件/网络路径：{offenders}"


def test_virtual_device_is_honest() -> None:
    caps = VirtualDevice().capabilities()
    assert caps.simulated is True
    assert caps.safety["raw_sensor_data_exposed"] is False
