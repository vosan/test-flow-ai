"""
MemoryManager: simple in-memory cache for resolved selectors during a single run.

Responsibilities:
- Store mapping: target (str) -> {"selector": str, "confidence": float}
- Read-through before resolution
- Invalidate entry on execution failure
- Update entry after successful execution

Scope: per-process, per-orchestrator instance; no persistence to disk.
"""
from __future__ import annotations

from typing import Dict, Optional, Any


class MemoryManager:
    def __init__(self) -> None:
        # Clear on startup: empty dict
        self._store: Dict[str, Dict[str, Any]] = {}

    def clear(self) -> None:
        self._store.clear()

    def get(self, target: Optional[str]) -> Optional[Dict[str, Any]]:
        if not target:
            return None
        return self._store.get(target)

    def set(self, target: Optional[str], selector: Optional[str], confidence: float) -> None:
        if not target or not selector:
            return
        try:
            conf = float(confidence)
        except Exception:
            conf = 0.0
        self._store[target] = {"selector": selector, "confidence": conf}

    def invalidate(self, target: Optional[str]) -> None:
        if not target:
            return
        if target in self._store:
            self._store.pop(target, None)

    def __len__(self) -> int:  # convenience
        return len(self._store)
