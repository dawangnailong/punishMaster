"""会话存储：内存（测试默认）与 JSON 文件（持久化恢复）两种实现。

save_all 在每次状态变更后由导演层调用；load_all 在启动时恢复。
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .session import Session


class Store(Protocol):
    def load_all(self) -> dict[str, dict[str, Any]]: ...

    def save_all(self, sessions: dict[str, Session]) -> None: ...


class MemoryStore:
    """内存存储：轻量、测试默认，进程退出即清空。"""

    def __init__(self) -> None:
        self._dump: dict[str, dict[str, Any]] = {}

    def load_all(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._dump.items()}

    def save_all(self, sessions: dict[str, Session]) -> None:
        self._dump = {sid: s.model_dump(mode="json") for sid, s in sessions.items()}


class JsonFileStore:
    """JSON 文件持久化：崩溃/重启后可恢复全部会话状态。"""

    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def load_all(self) -> dict[str, dict[str, Any]]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def save_all(self, sessions: dict[str, Session]) -> None:
        payload = {sid: s.model_dump(mode="json") for sid, s in sessions.items()}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
