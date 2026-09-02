"""RedisDistributedLock - 基于 Redis 的分布式锁实现."""

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.infrastructure.distributed_lock.base import DistributedLock
from app.infrastructure.redis import RedisStore


class RedisDistributedLock(DistributedLock):
    """基于 Redis 的分布式锁实现.

    使用 Redis SET key value NX EX seconds 原子命令获取锁，
    使用 Lua 脚本确保只有锁持有者才能释放锁.
    """

    _RELEASE_SCRIPT = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
    """

    _EXTEND_SCRIPT = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
    """

    def __init__(self, lock_key: str, ttl_seconds: int = 60, redis_store: RedisStore | None = None):
        super().__init__(lock_key, ttl_seconds)
        self._redis = redis_store or RedisStore()

    def acquire(self) -> bool:
        """尝试获取 Redis 分布式锁."""
        client = self._redis._ensure_connection()
        if client is None:
            log.warn(f"[RedisLock]Redis 不可用，无法获取锁: {self._lock_key}")
            return False

        try:
            result = client.set(self._lock_key, self._token, nx=True, ex=self._ttl_seconds)
            if result:
                self._owned = True
                return True
            else:
                log.debug(f"[RedisLock]锁已被占用: {self._lock_key}")
                return False
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[RedisLock]获取锁异常: {self._lock_key}, {e}")
            return False

    def release(self) -> None:
        """释放 Redis 分布式锁."""
        if not self._owned:
            return

        client = self._redis._ensure_connection()
        if client is None:
            log.warn(f"[RedisLock]Redis 不可用，无法释放锁: {self._lock_key}")
            self._owned = False
            return

        try:
            result = client.eval(self._RELEASE_SCRIPT, 1, self._lock_key, self._token)
            if not result:
                log.warn(f"[RedisLock]释放锁失败（非持有者）: {self._lock_key}")
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[RedisLock]释放锁异常: {self._lock_key}, {e}")
        finally:
            self._owned = False

    def extend(self, additional_seconds: int) -> bool:
        """延长 Redis 锁的过期时间."""
        if not self._owned:
            return False

        client = self._redis._ensure_connection()
        if client is None:
            return False

        try:
            result = client.eval(self._EXTEND_SCRIPT, 1, self._lock_key, self._token, str(additional_seconds))
            return bool(result)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[RedisLock]延长锁异常: {self._lock_key}, {e}")
            return False
