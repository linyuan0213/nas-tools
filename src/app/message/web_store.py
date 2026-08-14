"""内置 Web 消息流存储 — 交互页的消息汇聚点

游标式消息存储：命令回复（WEB 渠道）与事件通知（Web 客户端）统一写入。
- 内存 deque 作热缓存（SSE 1.5s 轮询）
- DB 持久化（AGENT_WEB_MESSAGE）：刷新/重启后按游标恢复，通知不丢失
- 游标 = DB 自增 ID（跨重启单调）；DB 不可用时降级纯内存（fallback 序号）
- 按用户隔离：user_id='' 全局消息所有用户可见，具体用户消息仅本人可见
"""

import itertools
import time
from collections import deque
from threading import Lock

import log
from app.db.repositories.web_message_repo_adapter import WebMessageRepositoryAdapter
from app.db.web_visibility import is_visible
from app.infrastructure.image_proxy.proxy import ImageProxy


class WebMessageStore:
    """内置 Web 消息存储（DB 持久化 + 内存热缓存）"""

    _instance: "WebMessageStore | None" = None
    _lock = Lock()

    def __init__(self, maxlen: int = 200, enable_db: bool = True):
        self._items: deque = deque(maxlen=maxlen)
        self._write_lock = Lock()
        self._repo = None
        if enable_db:
            try:
                self._repo = WebMessageRepositoryAdapter()
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 仓储初始化失败，降级纯内存: {e}")
        # fallback 序号从当前 DB 最大游标接续，保证 DB 故障期间写入的消息
        # 游标单调递增（大于既有 DB 行），不会对既有 SSE 客户端不可见
        self._fallback_seq = itertools.count(self._db_max_cursor() + 1)

    def _db_max_cursor(self) -> int:
        """当前 DB 最大游标（fallback 序号接续基线）"""
        if self._repo is None:
            return 0
        try:
            return self._repo.max_cursor()
        except Exception as e:
            log.warn(f"[WebMessageStore]DB 游标读取失败: {e}")
            return 0

    @staticmethod
    def build_list_items(medias: list) -> list[dict]:
        """媒体列表 → 内置消息页列表项（dispatcher 与 Web 客户端共用同一序列化）"""
        items = []
        for index, media in enumerate(medias):
            title_str = media.get_title_string() if hasattr(media, "get_title_string") else str(media)
            vote_str = media.get_vote_string() if hasattr(media, "get_vote_string") else ""
            type_str = media.get_type_string() if hasattr(media, "get_type_string") else ""
            year = str(media.year) if getattr(media, "year", None) else ""
            image = media.get_message_image() if hasattr(media, "get_message_image") else ""
            url = media.get_detail_url() if hasattr(media, "get_detail_url") else ""
            items.append(
                {
                    "index": index,
                    "title": title_str,
                    "vote": vote_str,
                    "type": type_str,
                    "year": year,
                    "image": image or "",
                    "url": url or "",
                }
            )
        return items

    @classmethod
    def instance(cls) -> "WebMessageStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def add(
        self,
        title: str,
        content: str = "",
        kind: str = "notify",
        image: str = "",
        url: str = "",
        items: list[dict] | None = None,
        user_id: str = "",
    ) -> dict:
        """写入消息，返回条目（kind: notify 事件通知 / reply 交互回复 / list 列表）

        user_id="": 全局消息（系统通知），所有用户可见；
        user_id=<具体用户>: 仅该用户可见（命令交互回复）。
        """
        proxied_image = ImageProxy.get_proxy_image_url(image) if image else ""
        proxied_items = self._proxy_items(items or [])
        cursor = None
        if self._repo is not None:
            try:
                cursor = self._repo.add_message(
                    user_id=user_id,
                    kind=kind,
                    title=(title or "").strip(),
                    content=(content or "").strip(),
                    image=proxied_image,
                    url=(url or "").strip(),
                    items=proxied_items,
                )
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 写入失败，降级内存: {e}")
        with self._write_lock:
            item = {
                "cursor": cursor if cursor is not None else next(self._fallback_seq),
                "kind": kind,
                "title": (title or "").strip(),
                "content": (content or "").strip(),
                "image": proxied_image,
                "items": proxied_items,
                "url": (url or "").strip(),
                "user_id": user_id,
                "time": time.strftime("%H:%M:%S"),
                "ts": time.time(),
            }
            self._items.append(item)
            return item

    @staticmethod
    def _proxy_items(items: list[dict]) -> list[dict]:
        """条目内图片转本地代理路径"""
        proxied = []
        for it in items:
            entry = dict(it)
            img = entry.get("image") or ""
            entry["image"] = ImageProxy.get_proxy_image_url(img) if img else ""
            proxied.append(entry)
        return proxied

    def after(self, cursor: int = 0, limit: int = 50, user_id: str = "") -> list[dict]:
        """读取 cursor 之后的消息；按用户隔离"""
        # 内存窗口覆盖 cursor → 走内存热路径
        with self._write_lock:
            if self._items and cursor >= self._items[0]["cursor"]:
                items = [i for i in self._items if i["cursor"] > cursor and is_visible(i.get("user_id"), user_id)]
                # 与 DB 路径语义一致：返回 cursor 之后的前 limit 条（而非最新 limit 条）
                return items[:limit]
        # 窗口外（重启 / 游标早于内存窗口）→ DB 兜底
        if self._repo is not None:
            try:
                return self._repo.after(cursor, user_id, limit)
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 读取失败: {e}")
        # DB 不可用 → 内存尽力返回
        with self._write_lock:
            items = [i for i in self._items if i["cursor"] > cursor and is_visible(i.get("user_id"), user_id)]
            return items[:limit]

    def history(self, user_id: str, limit: int = 50) -> list[dict]:
        """最近通知历史（刷新恢复用）"""
        if self._repo is not None:
            try:
                return self._repo.history(user_id, limit)
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 历史读取失败: {e}")
        with self._write_lock:
            items = [i for i in self._items if is_visible(i.get("user_id"), user_id)]
            return items[-limit:]

    def unread_list(self, user_id: str, limit: int = 50) -> list[dict]:
        """当前用户未读消息列表（通知栏下拉，轻量）"""
        if self._repo is not None:
            try:
                return self._repo.unread_list(user_id, limit)
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 未读列表读取失败: {e}")
        with self._write_lock:
            items = [i for i in self._items if is_visible(i.get("user_id"), user_id) and i.get("read") is not True]
            return items[-limit:]

    def unread_count(self, user_id: str) -> int:
        """当前用户未读消息数"""
        if self._repo is not None:
            try:
                return self._repo.unread_count(user_id)
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 未读数读取失败: {e}")
        return 0

    def mark_read(self, user_id: str, ids: list[int] | None = None) -> int:
        """标记已读（ids 为空则全部已读）"""
        if self._repo is not None:
            try:
                return self._repo.mark_read(user_id, ids)
            except Exception as e:
                log.warn(f"[WebMessageStore]DB 标记已读失败: {e}")
        return 0
