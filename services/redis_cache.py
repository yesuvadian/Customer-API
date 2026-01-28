import json
import redis
from typing import Any, Optional
from config import REDIS_CONFIG


class RedisCacheService:
    _client: Optional[redis.Redis] = None

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.Redis(**REDIS_CONFIG)
        return cls._client

    # ------------------------------
    # BASIC KEY-VALUE
    # ------------------------------

    @classmethod
    def set(
        cls,
        key: str,
        value: Any,
        ttl: int = 300
    ) -> bool:
        try:
            client = cls.get_client()
            client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception:
            return False

    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        try:
            client = cls.get_client()
            data = client.get(key)
            return json.loads(data) if data else None
        except Exception:
            return None

    @classmethod
    def delete(cls, key: str) -> bool:
        try:
            cls.get_client().delete(key)
            return True
        except Exception:
            return False

    # ------------------------------
    # HASHES (objects)
    # ------------------------------

    @classmethod
    def hset(
        cls,
        key: str,
        mapping: dict,
        ttl: int = 300
    ) -> bool:
        try:
            client = cls.get_client()
            client.hset(key, mapping=mapping)
            client.expire(key, ttl)
            return True
        except Exception:
            return False

    @classmethod
    def hgetall(cls, key: str) -> dict:
        try:
            return cls.get_client().hgetall(key) or {}
        except Exception:
            return {}

    # ------------------------------
    # UTILITIES
    # ------------------------------

    @classmethod
    def exists(cls, key: str) -> bool:
        try:
            return bool(cls.get_client().exists(key))
        except Exception:
            return False

    @classmethod
    def ttl(cls, key: str) -> int:
        try:
            return cls.get_client().ttl(key)
        except Exception:
            return -1

    @classmethod
    def flush(cls) -> None:
        try:
            cls.get_client().flushdb()
        except Exception:
            pass
