"""DbDistributedLock - 基于数据库的分布式锁降级实现."""

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.db.repositories.distributed_lock_repository import DistributedLockRepository
from app.infrastructure.distributed_lock.base import DistributedLock


class DbDistributedLock(DistributedLock):
    """基于数据库的分布式锁降级实现.

    当 Redis 不可用时使用数据库唯一约束实现互斥.
    利用 INSERT 唯一约束冲突保证只有一个实例能获取锁.

    注意：此实现性能低于 Redis 锁，仅作为降级方案.
    """

    def __init__(self, lock_key: str, ttl_seconds: int = 60):
        super().__init__(lock_key, ttl_seconds)
        self._repo = DistributedLockRepository()

    def acquire(self) -> bool:
        """尝试获取数据库锁."""
        try:
            instance = self._token.split(":")[0]
            result = self._repo.acquire(
                lock_key=self._lock_key,
                token=self._token,
                instance=instance,
                ttl_seconds=self._ttl_seconds,
            )
            if result:
                self._owned = True
            else:
                log.debug(f"[DbLock]锁已被占用: {self._lock_key}")
            return result
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[DbLock]获取锁异常: {self._lock_key}, {e}")
            return False

    def release(self) -> None:
        """释放数据库锁."""
        if not self._owned:
            return
        try:
            self._repo.release(self._lock_key, self._token)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[DbLock]释放锁异常: {self._lock_key}, {e}")
        finally:
            self._owned = False

    def extend(self, additional_seconds: int) -> bool:
        """延长数据库锁的过期时间."""
        if not self._owned:
            return False
        try:
            return self._repo.extend(self._lock_key, self._token, additional_seconds)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            log.error(f"[DbLock]延长锁异常: {self._lock_key}, {e}")
            return False
