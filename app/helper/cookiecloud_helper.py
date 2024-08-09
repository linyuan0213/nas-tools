
from app.utils.commons import singleton
from app.utils.redis_store import RedisStore

@singleton
class CookiecloudHelper:
    def __init__(self):
      self.redis_store = RedisStore()
    
    def get_cookie(self, domain_url: str) -> str:
       cookie = self.redis_store.hget('cookie', domain_url)
       if cookie:
          return cookie.decode("utf-8")