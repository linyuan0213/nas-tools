import redis

from config import REDIS_HOST, REDIS_PORT


class RedisStore:
    def __init__(self):
        self.client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)

    def set(self, key, value):
        self.client.set(key, value)

    def get(self, key):
        return self.client.get(key)

    def hset(self, name, key, value):
        self.client.hset(name, key, value)

    def hget(self, name, key):
        return self.client.hget(name, key)

    def hdel(self, name, key):
        self.client.hdel(name, key)

    def hgetall(self, name):
        return self.client.hgetall(name)

    def lpush(self, name, *values):
        self.client.lpush(name, *values)

    def rpop(self, name):
        return self.client.rpop(name)

    def rpush(self, name, *values):
        self.client.rpush(name, *values)

    def lpop(self, name):
        return self.client.lpop(name)

    def llen(self, name):
        return self.client.llen(name)

    def delete(self, *keys):
        self.client.delete(*keys)
        
    def ping(self):
        return self.client.ping()
