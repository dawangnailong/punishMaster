"""结构化审计日志。

原则：
- 只记录类别、规则命中、状态变化与必要脱敏摘要；
- 默认不保存任何完整角色扮演文案（reason/文案只留前缀 + 哈希）；
- 绝不向 stdout 写日志（stdout 是 stdio MCP 的传输线）；
- 可整体关闭（path=None 时仅保留内存环形缓冲，供测试断言）；
- 无遥测，无外部上报。
"""

from __future__ import annotations

import json
import os
from typing import Any

from .protocol import new_id, now_iso, sha1_short

_MEMORY_LIMIT = 500


class AuditLog:
    def __init__(self, path: str | None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        if path:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    # ------------------------------------------------------------
    @staticmethod
    def redact(text: str, keep: int = 8) -> str:
        """脱敏：保留短前缀 + 短哈希；短文本原样（本身即非私密）。"""
        t = (text or "").strip()
        if not t:
            return ""
        if len(t) <= keep:
            return t
        return f"{t[:keep]}…<{sha1_short(t)}>"

    # ------------------------------------------------------------
    def event(self, kind: str, **fields: Any) -> str:
        audit_id = new_id("aud")
        record: dict[str, Any] = {"at": now_iso(), "kind": kind, "audit_id": audit_id}
        record.update({k: v for k, v in fields.items() if v is not None})
        self.events.append(record)
        if len(self.events) > _MEMORY_LIMIT:
            del self.events[: len(self.events) - _MEMORY_LIMIT]
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                # 审计写失败不阻塞业务，但保留在内存缓冲中
                pass
        return audit_id
