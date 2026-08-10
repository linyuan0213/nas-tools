"""记忆键 — 三维作用域（user × channel × session）"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryKey:
    """记忆作用域键"""

    user_id: str
    channel: str = "web"
    session_id: str = ""

    def cache_key(self) -> str:
        return f"agent:conv:{self.user_id}:{self.channel}:{self.session_id}"
