from __future__ import annotations

import pytest

from punishmaster.server import build_mcp
from punishmaster.virtual import VirtualDevice


class FakeClock:
    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def device(clock: FakeClock) -> VirtualDevice:
    return VirtualDevice(clock=clock)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(device: VirtualDevice):
    mcp = build_mcp(device)
    from mcp import Client

    async with Client(mcp, raise_exceptions=True) as c:
        yield c
