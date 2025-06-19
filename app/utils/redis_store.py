import redis
import json
from typing import Any, Optional, List

from config import REDIS_HOST, REDIS_PORT


class RedisStore:
    def __init__(self):
        self.client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        """设置键值对，可设置过期时间(秒)"""
        self.client.set(key, value, ex=ex)

    def get(self, key: str) -> Optional[Any]:
        """获取键值"""
        return self.client.get(key)

    def hset(self, name: str, key: str, value: Any) -> None:
        """设置哈希字段"""
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        self.client.hset(name, key, value)

    def hget(self, name: str, key: str) -> Optional[Any]:
        """获取哈希字段值"""
        return self.client.hget(name, key)

    def hdel(self, name: str, key: str) -> None:
        """删除哈希字段"""
        self.client.hdel(name, key)

    def hgetall(self, name: str) -> dict:
        """获取所有哈希字段"""
        return {k.decode('utf-8'): self.hget(name, k) for k in self.client.hkeys(name)}

    def lpush(self, name: str, *values: Any) -> None:
        """列表左推入"""
        self.client.lpush(name, *[json.dumps(v) if isinstance(v, (dict, list)) else v for v in values])

    def rpop(self, name: str) -> Optional[Any]:
        """列表右弹出"""
        return self.client.rpop(name)

    def rpush(self, name: str, *values: Any) -> None:
        """列表右推入"""
        self.client.rpush(name, *[json.dumps(v) if isinstance(v, (dict, list)) else v for v in values])

    def lpop(self, name: str) -> Optional[Any]:
        """列表左弹出"""
        return self.client.lpop(name)

    def llen(self, name: str) -> int:
        """获取列表长度"""
        return self.client.llen(name)

    def delete(self, *keys: str) -> None:
        """删除键"""
        self.client.delete(*keys)
        
    def ping(self) -> bool:
        """测试连接"""
        return self.client.ping()

    def keys(self, pattern: str) -> List[str]:
        """查找匹配模式的键"""
        return [k.decode('utf-8') for k in self.client.keys(pattern)]

    def expire(self, key: str, seconds: int) -> None:
        """设置键过期时间"""
        self.client.expire(key, seconds)

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return bool(self.client.exists(key))

    def ttl(self, key: str) -> int:
        """获取键的剩余生存时间(秒)
        返回:
            -2: 键不存在
            -1: 键存在但没有设置过期时间
            >=0: 剩余生存时间(秒)
        """
        return self.client.ttl(key)
