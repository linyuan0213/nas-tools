"""RBAC 菜单初始化.

策略：
1. 收集 DEFAULT_MENUS 中所有菜单 code；
2. 删除数据库中不在该集合内的旧菜单（按 level 降序，先删子后删父）；
3. 递归遍历 DEFAULT_MENUS，已存在则更新属性，不存在则创建。
"""

import contextlib
from typing import Any

import log
from app.db.repositories.rbac_repo_adapter import RBACMenuRepositoryAdapter
from app.services.rbac.init.constants import DEFAULT_MENUS
from app.services.rbac.init.menu_tombstone import (
    get_menu_tombstones,
    remove_menu_tombstone,
)


def init_rbac_menus(menu_repo: Any = None, force_defaults: bool = False):
    """初始化菜单数据：同步 DEFAULT_MENUS 到数据库。

    force_defaults=False（默认，用于启动）：保留用户自定义，仅补建缺失、同步技术路由、遵守墓碑。
    force_defaults=True（用于「重置菜单」）：把内置菜单强制恢复为 DEFAULT_MENUS 定义（覆盖名称/图标/
    排序/层级/父级/显隐/权限），并忽略墓碑（重建被删除的内置菜单）。
    """
    menu_repo = menu_repo or RBACMenuRepositoryAdapter()

    # 1. 收集 DEFAULT_MENUS 中所有 code
    default_codes: set[str] = set()

    def collect_codes(menu_data_list):
        for data in menu_data_list:
            default_codes.add(data["code"])
            if "children" in data:
                collect_codes(data["children"])

    collect_codes(DEFAULT_MENUS)

    # 2. 获取数据库中所有现有菜单，删除「已从默认菜单移除的内置菜单」
    #    仅删除内置菜单（IS_BUILTIN=1），保留用户自建菜单与插件菜单，避免重启清空用户菜单
    existing_menus = menu_repo.get_all_menus()
    menus_to_delete = [
        m
        for m in existing_menus
        if m.MENU_CODE not in default_codes
        and not m.MENU_CODE.startswith("Plugin_")
        and getattr(m, "IS_BUILTIN", 0) == 1
    ]
    deleted_count = 0
    # 按 menu_level 降序删除，确保先删子菜单
    for menu in sorted(menus_to_delete, key=lambda m: getattr(m, "MENU_LEVEL", 1), reverse=True):
        try:
            menu_repo.delete_menu(menu.ID)
            deleted_count += 1
            log.info(f"[RBAC]删除旧菜单: {menu.MENU_NAME} ({menu.MENU_CODE})")
        except Exception as e:
            log.warn(f"[RBAC]删除旧菜单失败: {menu.MENU_CODE} - {e}")

    # 3. 递归创建/更新菜单
    created_count = 0
    updated_count = 0
    # 用户删除过的内置菜单（墓碑）：初始化时跳过重建；重置模式(force_defaults)下忽略墓碑
    tombstones = set() if force_defaults else get_menu_tombstones()

    def sync_menu_recursive(menu_data, parent_id=None):
        nonlocal created_count, updated_count

        code = menu_data["code"]
        existing = menu_repo.get_menu_by_code(code)
        if existing:
            # 若该内置菜单曾被删除（有墓碑）但现在又存在（用户手动重建），清除墓碑
            if code in tombstones:
                with contextlib.suppress(Exception):
                    remove_menu_tombstone(code)
                tombstones.discard(code)
            updates: dict = {}
            if force_defaults:
                # 重置模式：强制恢复为默认定义（覆盖全部可自定义字段）
                updates = {
                    "menu_name": menu_data["name"],
                    "path": menu_data.get("path"),
                    "icon": menu_data.get("icon"),
                    "component": menu_data.get("component"),
                    "sort_order": menu_data.get("sort_order", 0),
                    "permission_code": menu_data.get("permission_code"),
                    "hide_in_menu": menu_data.get("hide_in_menu", 0),
                    "parent_id": parent_id,
                    "status": 1,
                    "is_builtin": 1,
                }
            else:
                # 启动模式：仅同步与前端路由强绑定的技术字段（path/component），
                # 保留用户在「菜单设置」中的自定义（名称、图标、排序、层级、父级、显隐等）。
                if existing.PATH != menu_data.get("path"):
                    updates["path"] = menu_data.get("path")
                if existing.COMPONENT != menu_data.get("component"):
                    updates["component"] = menu_data.get("component")
                # 标记为内置菜单（兼容列新增前已存在的默认菜单）
                if getattr(existing, "IS_BUILTIN", 0) != 1:
                    updates["is_builtin"] = 1

            if updates:
                try:
                    menu_repo.update_menu(existing.ID, **updates)
                    updated_count += 1
                    log.info(f"[RBAC]同步菜单: {menu_data['name']}")
                except Exception as e:
                    log.warn(f"[RBAC]更新菜单失败: {menu_data['name']} - {e}")
            menu_id = existing.ID
        else:
            # 用户删除过的内置菜单（墓碑）：跳过重建（含其子菜单），实现删除后重启不恢复
            if code in tombstones:
                return
            # 创建新菜单
            try:
                result = menu_repo.create_menu(
                    menu_name=menu_data["name"],
                    menu_code=menu_data["code"],
                    parent_id=parent_id,
                    path=menu_data.get("path"),
                    icon=menu_data.get("icon"),
                    component=menu_data.get("component"),
                    sort_order=menu_data.get("sort_order", 0),
                    menu_level=menu_data.get("level", 1),
                    permission_code=menu_data.get("permission_code"),
                    hide_in_menu=menu_data.get("hide_in_menu", 0),
                    is_builtin=1,
                )
                if isinstance(result, bool):
                    menu = menu_repo.get_menu_by_code(menu_data["code"])
                else:
                    menu = result

                if menu:
                    created_count += 1
                    log.info(f"[RBAC]创建菜单: {menu_data['name']}")
                    menu_id = menu.ID
                else:
                    log.error(f"[RBAC]创建菜单失败: {menu_data['name']}")
                    return
            except Exception as e:
                log.error(f"[RBAC]创建菜单失败: {menu_data['name']} - {e}")
                return

        if "children" in menu_data:
            for child_data in menu_data["children"]:
                sync_menu_recursive(child_data, menu_id)

    for menu_data in DEFAULT_MENUS:
        sync_menu_recursive(menu_data)

    log.info(f"[RBAC]菜单同步完成，新增 {created_count} 个，更新 {updated_count} 个，删除 {deleted_count} 个")
    return created_count + updated_count
