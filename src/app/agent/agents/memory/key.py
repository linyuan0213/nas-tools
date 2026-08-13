"""记忆键 — 三维作用域（user × channel × session）"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryKey:
    """记忆作用域键"""

    user_id: str
    channel: str = "web"
    session_id: str = ""

    def cache_key(self) -> str:
        # v3：缓存消息结构需含 created_at（时间线合并），版本号使旧结构缓存自动失效
        return f"agent:conv:v3:{self.user_id}:{self.channel}:{self.session_id}"
