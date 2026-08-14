"""分类配置初始化：从 YAML 模板加载默认分类到数据库"""

import os

import ruamel.yaml

import log
from app.core.root_path import get_project_root
from app.core.settings import settings
from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.db.session import Database

_MARKER_KEY = "category_default_seeded"


class CategoryInitializer:
    """负责从 default-category.yaml 模板初始化数据库中的分类配置

    默认分类仅在**首次初始化**时导入：数据库已有数据或已初始化过（用户可能主动清空）
    均不再自动导入，避免"删除分类后重启被还原为默认值"。
    """

    _TEMPLATE_PATH = os.path.join(str(get_project_root()), "config", "default-category.yaml")

    def __init__(self, repo: CategoryConfigRepositoryAdapter | None = None):
        self._repo = repo or CategoryConfigRepositoryAdapter()

    def _ensure_tables(self) -> None:
        """确保分类配置表已创建"""
        try:
            db = Database()
            db.create_all()
            log.info("[CategoryInit]数据库表检查/创建完成")
        except Exception as e:
            log.warn(f"[CategoryInit]create_all 执行提示: {e}")

    def _seeded(self) -> bool:
        """默认分类是否已初始化过"""
        return bool((settings.get("app") or {}).get(_MARKER_KEY))

    def _mark_seeded(self) -> None:
        """记录默认分类已初始化，防止清空后重启被重新导入"""
        try:
            cfg = settings.get()
            cfg.setdefault("app", {})[_MARKER_KEY] = True
            settings.save(cfg)
            log.info("[CategoryInit]已记录分类配置初始化标记")
        except Exception as e:
            log.warn(f"[CategoryInit]记录初始化标记失败: {e}")

    def run(self) -> None:
        """数据库中无分类配置且从未初始化过时才导入默认数据"""
        log.info("[CategoryInit]开始检查默认分类配置...")

        self._ensure_tables()

        try:
            existing = self._repo.get_all()
            log.info(f"[CategoryInit]数据库中已有 {len(existing)} 条分类配置")
            if existing:
                # 已有数据：视为已初始化，记录标记（此后即使清空也不再自动导入默认值）
                if not self._seeded():
                    self._mark_seeded()
                return
        except Exception as e:
            log.error(f"[CategoryInit]查询分类配置失败: {e}")
            return

        if self._seeded():
            # 已初始化过但当前为空 = 用户主动清空，保留用户意图
            log.info("[CategoryInit]分类配置已初始化过且为空，跳过默认导入（保留用户配置）")
            return

        if not os.path.exists(self._TEMPLATE_PATH):
            log.warn(f"[CategoryInit]模板文件不存在: {self._TEMPLATE_PATH}")
            return

        try:
            with open(self._TEMPLATE_PATH, encoding="utf-8") as f:
                yaml = ruamel.yaml.YAML()
                data = yaml.load(f) or {}
        except Exception as e:
            log.error(f"[CategoryInit]读取模板失败: {e}")
            return

        sort_order = 0
        for media_type, categories in data.items():
            if not isinstance(categories, dict):
                continue
            for name, rules in categories.items():
                sort_order += 1
                is_default = 1 if rules is None else 0
                rule_dict = rules if isinstance(rules, dict) else {}
                try:
                    self._repo.save(
                        media_type=media_type,
                        name=name,
                        sort_order=sort_order,
                        is_default=is_default,
                        rules=rule_dict,
                    )
                except Exception as e:
                    log.error(f"[CategoryInit]保存分类 '{name}' 失败: {e}")

        log.info(f"[CategoryInit]已从模板导入 {sort_order} 条默认分类配置")
        self._mark_seeded()
