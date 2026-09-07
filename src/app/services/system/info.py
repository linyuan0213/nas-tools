"""Info services - 系统信息、版本、网络、搜索、进度与用户管理."""

import datetime
import platform

import psutil

from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.settings import settings
from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.domain.enums import ProgressKey
from app.domain.mediatypes import MediaType
from app.infrastructure.external.doubanapi import DoubanApi
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.progress import ProgressTracker
from app.message import Message
from app.message.commands import COMMANDS
from app.schemas.system import (
    NetTestResultDTO,
    ProgressResultDTO,
    SystemInfoDTO,
    UserManageResultDTO,
    VersionInfoDTO,
    WebSearchResultDTO,
)
from app.services.rbac.service import RBACService
from app.services.web import WebUtils
from app.utils.config_tools import get_proxies
from version import APP_VERSION


class SystemInfoService:
    """
    系统信息服务
    获取系统版本、运行时长、Python版本等基本信息
    """

    def __init__(self, message: Message | None = None):
        self._message = message

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """格式化运行时长"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}分钟")
        return "".join(parts)

    @staticmethod
    def get_system_info() -> SystemInfoDTO:
        """获取系统基本信息"""
        process = psutil.Process()
        try:
            start_time = datetime.datetime.fromtimestamp(process.create_time())
            uptime_seconds = (datetime.datetime.now() - start_time).total_seconds()
            uptime = SystemInfoService._format_uptime(uptime_seconds)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception:
            start_time = None
            uptime = "-"
            uptime_seconds = 0

        try:
            mem = process.memory_info()
            memory_mb = round(mem.rss / 1024 / 1024, 1)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception:
            memory_mb = 0

        try:
            cpu_percent = round(psutil.cpu_percent(interval=0.1), 1)
            vmem = psutil.virtual_memory()
            memory_percent = round(vmem.percent, 1)
            memory_used_mb = round(vmem.used / 1024 / 1024, 1)
            memory_total_mb = round(vmem.total / 1024 / 1024, 1)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception:
            cpu_percent = 0.0
            memory_percent = 0.0
            memory_used_mb = 0.0
            memory_total_mb = 0.0

        return SystemInfoDTO(
            version=APP_VERSION,
            python_version=platform.python_version(),
            platform=platform.platform(),
            uptime=uptime,
            uptime_seconds=int(uptime_seconds),
            start_time=start_time.isoformat() if start_time else None,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_used_mb=memory_used_mb,
            memory_total_mb=memory_total_mb,
        )


class VersionService:
    """
    版本检查业务服务
    """

    @staticmethod
    def get_latest_version() -> VersionInfoDTO:
        """获取最新版本信息"""
        version, url, flag = WebUtils.get_latest_version()
        if flag:
            return VersionInfoDTO(version=version or "", url=url or "", has_update=True)
        return VersionInfoDTO(version="", url="", has_update=False)


class NetTestService:
    """
    网络连通性测试业务服务
    """

    def test(self, target: str) -> NetTestResultDTO:
        """测试指定目标的网络连通性.

        语义：仅 HTTP 2xx 视为连通成功；401/404/403 等非 2xx 及连接层错误
        （超时 / SSL / 拒绝 / DNS）均判为失败。
        需要 api_key 的目标（TMDB / LLM）会带上已配置的 key 做真实请求。
        """
        proxies = get_proxies()
        proxy_url = proxies.get("http") if proxies else None
        start_time = datetime.datetime.now()
        try:
            if target == "frodo.douban.com":
                DoubanApi().movie_showing(count=1)
            elif target == "api.themoviedb.org":
                # TMDB API：用已配置的 key 做真实请求
                tmdb_host = settings.get("app").get("tmdb_domain") or "api.themoviedb.org"
                tmdb_key = settings.get("app").get("rmt_tmdbkey") or ""
                HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=5)).get(
                    f"https://{tmdb_host}/3/configuration",
                    params={"api_key": tmdb_key},
                )
            elif target == "api.openai.com":
                # LLM API：用已配置的 provider（api_url + api_key）做真实请求
                prov = self._get_llm_provider()
                base = (prov.get("api_url") or "https://api.openai.com").rstrip("/")
                headers = {}
                if prov.get("api_key"):
                    headers["Authorization"] = f"Bearer {prov['api_key']}"
                HttpClient(config=HttpClientConfig(timeout=5)).get(f"{base}/models", headers=headers)
            else:
                if target == "image.tmdb.org":
                    target = target + "/t/p/w500/wwemzKWzjKYJFfCeiB57q3r4Bcm.png"
                if target == "qyapi.weixin.qq.com":
                    target = target + "/cgi-bin/message/send"
                target = "https://" + target
                if (
                    target.find("themoviedb") != -1
                    or target.find("telegram") != -1
                    or target.find("fanart") != -1
                    or target.find("tmdb") != -1
                ):
                    HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=5)).get(target)
                else:
                    HttpClient(config=HttpClientConfig(timeout=5)).get(target)
            success = True
        except Exception:
            success = False
        elapsed_ms = int((datetime.datetime.now() - start_time).total_seconds() * 1000)
        return NetTestResultDTO(success=success, time_ms=elapsed_ms)

    @staticmethod
    def _get_llm_provider() -> dict:
        """读取当前默认 LLM 提供商配置（含 api_url / api_key）。"""
        agent_cfg = settings.get("agent") or {}
        providers = agent_cfg.get("providers") or {}
        default_provider = agent_cfg.get("default_provider") or ""
        if default_provider and default_provider in providers:
            return providers[default_provider] or {}
        if providers:
            return next(iter(providers.values())) or {}
        return {}


class WebSearchService:
    """
    WEB资源搜索业务服务
    """

    def __init__(self, search_fn):
        # search_fn 由 DI 组装（search_web_entry.make_web_search_fn），统一走 SearchOrchestrator
        self._search_fn = search_fn

    def search(
        self,
        search_word: str,
        ident_flag: bool = True,
        filters=None,
        tmdbid=None,
        media_type=None,
        session_id: str | None = None,
    ) -> WebSearchResultDTO:
        """执行WEB搜索"""
        if not search_word:
            return WebSearchResultDTO(code=0, msg="")
        if media_type:
            if MediaType.from_string(media_type) == MediaType.MOVIE:
                media_type = MediaType.MOVIE
            else:
                media_type = MediaType.TV
        ret, ret_msg = self._search_fn(
            content=search_word,
            ident_flag=ident_flag,
            filters=filters,
            tmdbid=tmdbid,
            media_type=media_type,
            session_id=session_id,
        )
        return WebSearchResultDTO(code=ret, msg=ret_msg or "")


class ProgressService:
    """
    进度查询业务服务
    """

    def __init__(self, progress_helper=None):
        self._progress = progress_helper or ProgressTracker()

    def get_progress(self, ptype: str) -> ProgressResultDTO:
        detail = self._progress.get_process(ProgressKey(ptype))
        if detail:
            return ProgressResultDTO(
                value=detail.get("value", 0),
                text=detail.get("text", ""),
                exists=True,
                enable=bool(detail.get("enable", False)),
            )
        return ProgressResultDTO(exists=False, text="正在处理...")


class UserManageService:
    """
    用户管理业务服务
    """

    def __init__(self, rbac_svc: RBACService):
        self._rbac = rbac_svc

    def _get_rbac(self):
        return self._rbac

    def add_user(self, name: str, password: str, pris=None) -> UserManageResultDTO:
        rbac = self._get_rbac()
        user = rbac.create_user(username=name, password=password)
        return UserManageResultDTO(success=user is not None)

    def delete_user(self, name: str) -> UserManageResultDTO:
        rbac = self._get_rbac()
        user = rbac.get_user_by_username(name)
        if user:
            rbac.delete_user(user.ID)  # type: ignore[arg-type]
            return UserManageResultDTO(success=True)
        return UserManageResultDTO(success=False, message="用户不存在")


def get_commands():
    return [{"id": cid, "name": name} for cid, name in COMMANDS.items()]


def get_rmt_modes():
    return [
        {"value": "copy", "name": "复制"},
        {"value": "move", "name": "移动"},
        {"value": "link", "name": "硬链接"},
        {"value": "softlink", "name": "软链接"},
    ]

    def get_system_message(self, lst_time):
        if self._message is None:
            return {"code": 0, "message": [], "lst_time": lst_time}
        messages = self._message.messagecenter.get_system_messages(lst_time=lst_time)
        if messages:
            lst_time = messages[0].get("time")
        return {"code": 0, "message": messages, "lst_time": lst_time}


def parse_brush_rule_string(rules):
    return BrushRuleEngine.format_rule_html(rules)
