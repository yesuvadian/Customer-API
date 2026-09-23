import json
import time
import redis
from typing import Any, Optional
from config import REDIS_CONFIG


class RedisCacheService:
    _client: Optional[redis.Redis] = None

    # Circuit breaker: once a call fails to reach Redis, every other call
    # (there are several per request across the app, all fired in the same
    # burst during page bootstrap) would otherwise independently re-pay the
    # full socket_connect_timeout trying the same doomed connection. That
    # stacks into real, user-visible latency when Redis is simply down/
    # unreachable (e.g. local dev with no Redis running) - down here just
    # means "skip the network attempt" for a short cooldown instead.
    _down_until: float = 0.0
    _cooldown_seconds: float = 10.0

    @classmethod
    def _available(cls) -> bool:
        return time.monotonic() >= cls._down_until

    @classmethod
    def _mark_down(cls) -> None:
        cls._down_until = time.monotonic() + cls._cooldown_seconds

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.Redis(**REDIS_CONFIG)
        return cls._client

    # ------------------------------
    # BASIC KEY-VALUE
    # ------------------------------
    @classmethod
    def delete_pattern(cls, pattern: str) -> int:
        """
        Delete all keys matching a Redis glob-style pattern.
        Returns number of deleted keys.
        """
        if not cls._available():
            return 0
        try:
            client = cls.get_client()
            deleted = 0
            for key in client.scan_iter(match=pattern):
                deleted += client.delete(key)
            return deleted
        except Exception as e:
            print("[CACHE][DELETE_PATTERN ERROR]", e)
            cls._mark_down()
            return 0

    @classmethod
    def set(
        cls,
        key: str,
        value: Any,
        ttl: int | None = None
    ) -> bool:
        if not cls._available():
            return False
        try:
            client = cls.get_client()
            if ttl is None:
                client.set(key, json.dumps(value))  # 🔥 NO EXPIRY
            else:
                client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            print("[CACHE][SET ERROR]", e)
            cls._mark_down()
            return False


    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        if not cls._available():
            return None
        try:
            client = cls.get_client()
            data = client.get(key)
            return json.loads(data) if data else None
        except Exception:
            cls._mark_down()
            return None

    @classmethod
    def delete(cls, key: str) -> bool:
        if not cls._available():
            return False
        try:
            cls.get_client().delete(key)
            return True
        except Exception:
            cls._mark_down()
            return False

    # ------------------------------
    # HASHES (objects)
    # ------------------------------

    @classmethod
    def hset(
    cls,
    key: str,
    mapping: dict,
    ttl: int | None = None
) -> bool:
        if not cls._available():
            return False
        try:
            client = cls.get_client()
            client.hset(key, mapping=mapping)
            if ttl is not None:
                client.expire(key, ttl)
            return True
        except Exception as e:
            print("[CACHE][HSET ERROR]", e)
            cls._mark_down()
            return False


    @classmethod
    def hgetall(cls, key: str) -> dict:
        if not cls._available():
            return {}
        try:
            return cls.get_client().hgetall(key) or {}
        except Exception:
            cls._mark_down()
            return {}

    # ------------------------------
    # UTILITIES
    # ------------------------------

    @classmethod
    def exists(cls, key: str) -> bool:
        if not cls._available():
            return False
        try:
            return bool(cls.get_client().exists(key))
        except Exception:
            cls._mark_down()
            return False

    @classmethod
    def ttl(cls, key: str) -> int:
        if not cls._available():
            return -1
        try:
            return cls.get_client().ttl(key)
        except Exception:
            cls._mark_down()
            return -1

    @classmethod
    def flush(cls) -> None:
        if not cls._available():
            return
        try:
            cls.get_client().flushdb()
        except Exception:
            cls._mark_down()
