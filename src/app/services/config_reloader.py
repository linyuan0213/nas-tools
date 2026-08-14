"""ConfigReloader — 集中式配置热重载协调器.

职责：
1. 维护需要重建的 provider 列表及工厂函数
2. 配置变更时调用工厂重建 provider 并替换到 AppContext
3. 失败隔离：单个 provider 重建失败不影响其他
4. 可观测：每一步都记录日志
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import log
from app.core.settings import settings
from app.di.builders.agent_reload import rebuild_agent_rag
from app.di.context import AppContext
from app.media.lookup.tmdb_client import TmdbClient
from app.services.scheduler_jobs import reload_default_jobs


@dataclass(order=True)
class _ReloadStep:
    """重载步骤 — 按 priority 排序（数值越小越优先）."""

    priority: int
    name: str = field(compare=False)
    factory: Callable[[], Any] | None = field(default=None, compare=False)


class ConfigReloader:
    """集中式配置热重载协调器."""

    PRIORITY_SETTINGS = 0
    PRIORITY_INFRA = 10
    PRIORITY_MEDIA = 15
    PRIORITY_AGENT = 20
    PRIORITY_SCHEDULER = 30

    def __init__(self, context: AppContext):
        self._context = context
        self._steps: list[_ReloadStep] = []
        self._version = 0
        self._agent_snapshot: dict | None = None
        self._media_snapshot: dict | None = None
        self._scheduler_snapshot: dict | None = None
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册需要重建的 provider 及工厂函数."""
        self.register("system_config", self.PRIORITY_SETTINGS)
        self.register("tmdb_client", self.PRIORITY_INFRA, factory=lambda: TmdbClient())
        self.register_media_server()
        self.register_agent_rag()
        self.register_scheduler_jobs()

    def register_media_server(self) -> None:
        """媒体服务器配置变更时清除类型/实例缓存，下次访问按新配置重建（支持 emby↔jellyfin 切换）。"""
        ctx = self._context
        self._media_snapshot = self._media_cfg_snapshot()

        def _rebuild() -> None:
            current = self._media_cfg_snapshot()
            if current == self._media_snapshot:
                return  # 媒体服务器配置未变，跳过
            ctx.media_server.refresh()
            self._media_snapshot = current

        self.register("media_server", self.PRIORITY_MEDIA, factory=_rebuild)

    @staticmethod
    def _media_cfg_snapshot() -> dict:
        return settings.get("media") or {}

    def register_agent_rag(self) -> None:
        """agent 配置变更时刷新 Provider 并重建 RAG + 工具层（快照对比，避免无关配置触发）。"""
        ctx = self._context
        self._agent_snapshot = self._agent_cfg_snapshot()

        def _rebuild() -> None:
            current = self._agent_cfg_snapshot()
            if current == self._agent_snapshot:
                return  # agent/RAG 配置未变，跳过重建
            ctx.agent_service.refresh_config()
            rebuild_agent_rag(ctx)
            self._agent_snapshot = current

        self.register("agent_rag", self.PRIORITY_AGENT, factory=_rebuild)

    @staticmethod
    def _agent_cfg_snapshot() -> dict:
        """agent 配置快照（RAG/记忆/embedding 均读此节点）"""
        return settings.get("agent") or {}

    def register_scheduler_jobs(self) -> None:
        """定时任务相关配置（pt/subscribe/media 周期、agent 记忆 ttl、RAG 可用性）变更时重注册默认定时任务。"""
        ctx = self._context
        self._scheduler_snapshot = self._scheduler_cfg_snapshot()

        def _rebuild() -> None:
            current = self._scheduler_cfg_snapshot()
            if current == self._scheduler_snapshot:
                return  # 定时任务相关配置未变，跳过
            reload_default_jobs(
                ctx.scheduler_core,
                thread_executor=ctx.thread_executor,
                site_userinfo=ctx.site_service.site_user_info,
                subscription_monitor=ctx.subscription_monitor,
                media_server=ctx.media_server,
                sync_engine=ctx.sync_engine,
                subscribe_service=ctx.subscribe_service,
                knowledge_ingestor=ctx.knowledge_ingestor,
                conversation_store=ctx.conversation_store,
            )
            self._scheduler_snapshot = current

        self.register("scheduler_jobs", self.PRIORITY_SCHEDULER, factory=_rebuild)

    def _scheduler_cfg_snapshot(self) -> dict:
        """定时任务配置快照（含 RAG 可用性，AgentMaintenance 任务依赖）"""
        cfg = settings.get()
        return {
            "pt": cfg.get("pt"),
            "subscribe": cfg.get("subscribe"),
            "media": cfg.get("media"),
            "agent_memory": (cfg.get("agent") or {}).get("memory"),
            "kb_available": self._context.knowledge_ingestor is not None
            or self._context.conversation_store is not None,
        }

    def register(self, provider_name: str, priority: int = 100, factory: Callable[[], Any] | None = None) -> None:
        self._steps = [s for s in self._steps if s.name != provider_name]
        self._steps.append(_ReloadStep(priority, provider_name, factory))
        self._steps.sort()

    def reload(self) -> dict:
        """执行配置重载：settings.reload() + 重建注册的 provider."""
        self._version += 1
        log.info(f"[ConfigReloader]开始配置重载，版本 v{self._version}")

        results: dict[str, bool] = {}
        failed: list[str] = []

        for step in self._steps:
            try:
                if step.name == "system_config":
                    settings.reload()
                    results[step.name] = True
                    continue

                if step.factory is None:
                    continue

                new_instance = step.factory()
                # 多字段重建步骤在工厂内部自行更新 context，返回 None 表示"已处理"，不覆盖字段；
                # 单实例 provider 重建失败返回 None 时保留旧实例（失败隔离）
                if new_instance is not None:
                    object.__setattr__(self._context, step.name, new_instance)
                results[step.name] = True
                log.debug(f"[ConfigReloader][{step.priority}] {step.name} 重建成功")
            except Exception as e:
                results[step.name] = False
                failed.append(step.name)
                log.error(f"[ConfigReloader][{step.priority}] {step.name} 失败: {e}")

        if failed:
            log.warn(f"[ConfigReloader]重载完成 v{self._version}，{len(failed)}/{len(self._steps)} 失败: {failed}")
        else:
            log.info(f"[ConfigReloader]重载完成 v{self._version}，全部 {len(self._steps)} 步成功")

        return {"version": self._version, "results": results, "failed": failed}

    @property
    def version(self) -> int:
        return self._version

    @property
    def steps(self) -> list[str]:
        return [s.name for s in self._steps]
