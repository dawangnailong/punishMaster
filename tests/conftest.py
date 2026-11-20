"""共享 fixture：内存存储 + FakeClock 的隔离导演台与内存 MCP 客户端。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vpp.audit import AuditLog
from vpp.clock import FakeClock
from vpp.crew import MockPropsCrew
from vpp.server import build_director, build_mcp
from vpp.store import MemoryStore


@pytest.fixture
def rig():
    """同步导演台：内存存储 + 可快进假时钟 + 内存审计。"""
    clock = FakeClock()
    director = build_director(
        store=MemoryStore(), clock=clock, audit=AuditLog(None), crew=MockPropsCrew()
    )
    return SimpleNamespace(director=director, clock=clock)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(rig):
    """内存 MCP 客户端（Client(mcp) in-process，无子进程无端口）。"""
    mcp = build_mcp(rig.director)
    from mcp import Client

    async with Client(mcp, raise_exceptions=True) as c:
        yield c
