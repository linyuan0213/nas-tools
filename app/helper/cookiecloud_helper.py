
import json
from app.utils.commons import SingletonMeta
from app.utils.redis_store import RedisStore

class CookiecloudHelper(metaclass=SingletonMeta):
    def __init__(self):
      self.redis_store = RedisStore()
    
    def get_cookie(self, domain_url: str) -> str:
       cookie = self.redis_store.hget('cookie', domain_url)
       if cookie:
          return cookie.decode("utf-8")
    
    def get_local_storage(self, domain_url: str) -> dict:
       storage = self.redis_store.hget('local_storage', domain_url)
       if storage:
          data = json.loads(storage.decode("utf-8"))
          # 修复反斜杠转义问题，保留单个反斜杠，修复双反斜杠
          return self._fix_backslash_escapes(data)
       return {}

    def _fix_backslash_escapes(self, data):
        """
        递归处理数据中的反斜杠转义问题，修复双反斜杠为单反斜杠
        """
        if isinstance(data, dict):
            return {key: self._fix_backslash_escapes(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._fix_backslash_escapes(item) for item in data]
        elif isinstance(data, str):
            # 修复双反斜杠为单反斜杠，但保留合法的转义序列
            # 使用正则表达式替换双反斜杠为单反斜杠，但避免破坏合法的转义序列
            import re
            # 替换连续的双反斜杠为单反斜杠
            fixed_string = re.sub(r'\\\\', r'\\', data)
            return fixed_string
        else:
            return data
