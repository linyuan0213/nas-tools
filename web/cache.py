from config import REDIS_HOST, REDIS_PORT
from flask_caching import Cache

config = {
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 1
}

cache = Cache(config=config)
