"""
Shared state backends: in-memory (default) or Redis (when REDIS_URL is set)

In-memory state is per process, so with several replicas each one has its own cache, rate
limits and conversations, and a restart forgets them. With Redis they are shared and survive
restarts.
"""

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Tuple

import config
from services.cache import TTLCache

logger = logging.getLogger(__name__)

_redis: Any = None


class StoreError(Exception):
    """The shared storage backend could not be reached"""


def using_redis() -> bool:
    return bool(config.REDIS_URL)


def get_redis() -> Any:
    """The shared async Redis client, created on first use"""
    global _redis
    if _redis is None:
        import redis.asyncio as redis

        _redis = redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
            socket_timeout=config.REDIS_TIMEOUT,
            socket_connect_timeout=config.REDIS_TIMEOUT,
        )
    return _redis


def set_redis(client: Any) -> None:
    """Replace the Redis client (used by tests to inject a fake one)"""
    global _redis
    _redis = client


async def ping() -> bool:
    """Whether the configured backend is usable (always true for in-memory storage)"""
    if not using_redis():
        return True
    try:
        return bool(await get_redis().ping())
    except Exception:
        logger.warning("Redis is unreachable", exc_info=True)
        return False


# --- Key-value store ---------------------------------------------------------------------


class KeyValueStore(ABC):
    """JSON-serialisable values with a time-to-live"""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]: ...

    @abstractmethod
    async def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    async def update(
        self, key: str, mutator: Callable[[Optional[Any]], Optional[Any]]
    ) -> Optional[Any]:
        """Atomically read, transform and write a value; return None to leave it unchanged"""

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class MemoryStore(KeyValueStore):
    """Per-process TTL/LRU store"""

    def __init__(self, max_items: int, ttl: float) -> None:
        self._cache = TTLCache(max_items=max_items, ttl=ttl)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._cache.set(key, value)

    async def update(
        self, key: str, mutator: Callable[[Optional[Any]], Optional[Any]]
    ) -> Optional[Any]:
        async with self._lock:
            current = self._cache.get(key)
            updated = mutator(current)
            if updated is not None:
                self._cache.set(key, updated)
            return updated

    async def delete(self, key: str) -> None:
        self._cache.delete(key)

    def clear(self) -> None:
        self._cache.clear()


class RedisStore(KeyValueStore):
    """Redis store; every key gets REDIS_PREFIX + namespace and expires after `ttl` seconds"""

    def __init__(
        self,
        namespace: str,
        ttl: float,
        max_items: int = 0,
        enforce_max_items: bool = False,
    ) -> None:
        self.namespace = namespace
        self.ttl = ttl
        self.max_items = max(0, max_items)
        self.enforce_max_items = enforce_max_items and self.max_items > 0

    def _key(self, key: str) -> str:
        return f"{config.REDIS_PREFIX}{self.namespace}:{key}"

    def _index_key(self) -> str:
        return f"{config.REDIS_PREFIX}{self.namespace}:__index"

    async def get(self, key: str) -> Optional[Any]:
        if self.ttl <= 0:
            return None
        try:
            raw = await get_redis().get(self._key(key))
        except Exception as e:
            raise StoreError(str(e)) from e
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any) -> None:
        if self.ttl <= 0:
            return
        try:
            redis = get_redis()
            data_key = self._key(key)
            payload = json.dumps(value, ensure_ascii=False)
            if not self.enforce_max_items:
                await redis.set(data_key, payload, ex=max(1, int(self.ttl)))
                return

            # Keep an index of keys so Redis honours CONVERSATION_MAX_ITEMS.
            index_key = self._index_key()
            now = time.time()
            for _ in range(5):
                try:
                    async with redis.pipeline(transaction=True) as pipe:
                        await pipe.watch(index_key)
                        pipe.multi()
                        pipe.set(data_key, payload, ex=max(1, int(self.ttl)))
                        pipe.zadd(index_key, {data_key: now})
                        pipe.zremrangebyscore(index_key, 0, now - self.ttl)
                        pipe.zcard(index_key)
                        result = await pipe.execute()
                    count = int(result[-1])
                    if count > self.max_items:
                        evicted = await redis.zrange(index_key, 0, count - self.max_items - 1)
                        if evicted:
                            await redis.delete(*evicted)
                            await redis.zrem(index_key, *evicted)
                    return
                except Exception as e:
                    if type(e).__name__ == "WatchError":
                        continue
                    raise
            raise StoreError("concurrent set conflict")
        except StoreError:
            raise
        except Exception as e:
            raise StoreError(str(e)) from e

    async def update(
        self, key: str, mutator: Callable[[Optional[Any]], Optional[Any]]
    ) -> Optional[Any]:
        if self.ttl <= 0:
            return None
        try:
            redis = get_redis()
            redis_key = self._key(key)
            for _ in range(5):
                try:
                    async with redis.pipeline(transaction=True) as pipe:
                        await pipe.watch(redis_key)
                        raw = await pipe.get(redis_key)
                        current = None if raw is None else json.loads(raw)
                        updated = mutator(current)
                        if updated is None:
                            await pipe.unwatch()
                            return None
                        pipe.multi()
                        pipe.set(
                            redis_key,
                            json.dumps(updated, ensure_ascii=False),
                            ex=max(1, int(self.ttl)),
                        )
                        if self.enforce_max_items:
                            index_key = self._index_key()
                            now = time.time()
                            pipe.zadd(index_key, {redis_key: now})
                            pipe.zremrangebyscore(index_key, 0, now - self.ttl)
                        await pipe.execute()
                        return updated
                except Exception as e:
                    if type(e).__name__ == "WatchError":
                        continue
                    raise
            raise StoreError("concurrent update conflict")
        except StoreError:
            raise
        except Exception as e:
            raise StoreError(str(e)) from e

    async def delete(self, key: str) -> None:
        try:
            redis = get_redis()
            data_key = self._key(key)
            await redis.delete(data_key)
            if self.enforce_max_items:
                await redis.zrem(self._index_key(), data_key)
        except Exception as e:
            raise StoreError(str(e)) from e

    def clear(self) -> None:
        """Nothing to clear locally; data lives in Redis"""


def make_store(
    namespace: str,
    max_items: int,
    ttl: float,
    *,
    enforce_max_items: bool = False,
) -> KeyValueStore:
    """A Redis-backed store when REDIS_URL is set, otherwise an in-memory one"""
    if using_redis():
        return RedisStore(
            namespace,
            ttl,
            max_items=max_items,
            enforce_max_items=enforce_max_items,
        )
    return MemoryStore(max_items, ttl)


# --- Rate limiter --------------------------------------------------------------------------


class RedisRateLimiter:
    """
    Sliding-window rate limiter shared by every replica, using one sorted set per client.
    If Redis is unreachable requests are allowed (fail open) rather than all rejected.
    """

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window

    async def hit(self, client_id: str) -> Tuple[bool, int, float]:
        """
        Record a request for `client_id`

        Returns:
            (allowed, remaining requests, seconds until a slot frees up)
        """
        now = time.time()
        key = f"{config.REDIS_PREFIX}ratelimit:{client_id}"
        member = f"{now:.6f}:{uuid.uuid4().hex}"
        try:
            redis = get_redis()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, now - self.window)
                pipe.zadd(key, {member: now})
                pipe.zcard(key)
                pipe.zrange(key, 0, 0, withscores=True)
                pipe.expire(key, int(self.window) + 1)
                _, _, count, oldest, _ = await pipe.execute()

            if count > self.limit:
                # Rejected requests don't use up the window
                await redis.zrem(key, member)
                oldest_score = oldest[0][1] if oldest else now
                return False, 0, max(0.0, oldest_score + self.window - now)
            return True, self.limit - count, 0.0
        except Exception:
            logger.warning("Rate limiter storage unavailable; allowing request", exc_info=True)
            return True, self.limit, 0.0

    def reset(self) -> None:
        """Nothing to reset locally; data lives in Redis"""
