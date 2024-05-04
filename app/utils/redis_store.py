import redis
import pickle

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

    def hgetall(self, name):
        return self.client.hgetall(name)

    def lpush(self, name, *values):
        self.client.lpush(name, *values)

    def rpop(self, name):
        return self.client.rpop(name)

    def lpop(self, name):
        return self.client.lpop(name)

    def llen(self, name):
        return self.client.llen(name)

    def delete(self, *keys):
        self.client.delete(*keys)

    def add_object(self, key, obj_id, obj):
        serialize_obj = pickle.dumps(obj)
        self.client.hset(key, obj_id, serialize_obj)

    def load_object(self, key, obj_id):
        serialize_obj = self.client.hget(key, obj_id)
        if serialize_obj:
            return pickle.loads(serialize_obj)
        else:
            return None

    def delete_obj(self, key, obj_id):
        self.client.hdel(key, obj_id)

    def get_all_object_keys(self, key):
        return [key.decode('utf-8') for key in self.client.hkeys(key)]

    def get_all_object_vals(self, key):
        return [pickle.loads(val) for val in self.client.hvals(key)]

    def get_all_key_values(self, key):
        all_key_values = {}
        hash_data = self.client.hgetall(key)
        for hash_key, serialized_value in hash_data.items():
            value = pickle.loads(serialized_value)
            all_key_values[hash_key.decode('utf-8')] = value
        return all_key_values
