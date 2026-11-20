from __future__ import annotations

from typing import Any


async def call(client, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    result = await client.call_tool(tool, args or {})
    return result.structured_content
