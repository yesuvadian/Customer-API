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
    def delete_pattern(cls, pattern: str) -> int:
        """
        Delete all keys matching a Redis glob-style pattern.
        Returns number of deleted keys.
        """
        try:
            client = cls.get_client()
            deleted = 0
            for key in client.scan_iter(match=pattern):
                deleted += client.delete(key)
            return deleted
        except Exception as e:
            print("[CACHE][DELETE_PATTERN ERROR]", e)
            return 0
        
    @classmethod
    def set(
        cls,
        key: str,
        value: Any,
        ttl: int | None = None
    ) -> bool:
        try:
            client = cls.get_client()
            if ttl is None:
                client.set(key, json.dumps(value))  # 🔥 NO EXPIRY
            else:
                client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            print("[CACHE][SET ERROR]", e)
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
    ttl: int | None = None
) -> bool:
        try:
            client = cls.get_client()
            client.hset(key, mapping=mapping)
            if ttl is not None:
                client.expire(key, ttl)
            return True
        except Exception as e:
            print("[CACHE][HSET ERROR]", e)
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
