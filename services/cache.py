"""
Small in-memory TTL + LRU cache used to avoid repeat calls to upstream services
"""

import time
from collections import OrderedDict
from typing import Any, Hashable, Optional, Tuple


class TTLCache:
    """Least-recently-used cache whose entries expire after `ttl` seconds"""

    def __init__(self, max_items: int, ttl: float):
        self.max_items = max_items
        self.ttl = ttl
        self._data: OrderedDict[Hashable, Tuple[float, Any]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl > 0 and self.max_items > 0

    def get(self, key: Hashable) -> Optional[Any]:
        """Return the cached value, or None if missing or expired"""
        if not self.enabled:
            return None
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Hashable, value: Any) -> None:
        """Store a value, evicting the least recently used entry when full"""
        if not self.enabled:
            return
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)

    def delete(self, key: Hashable) -> None:
        self._data.pop(key, None)

    def keys(self) -> list[Hashable]:
        """Live keys, oldest first; expired entries are removed first"""
        now = time.monotonic()
        for key in [key for key, (expires, _) in self._data.items() if expires < now]:
            del self._data[key]
        return list(self._data)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
