"""浏览器指纹注入服务 — 将前端采集的用户真实指纹同步到 nexus-chrome 指纹画像。

流程：用户浏览器(前端)采集真实指纹 → 后端按 user_id 映射 fp_profile_id
     → 写入 nexus-chrome /api/profiles → 会话以 fp_profile_id 使用该指纹。
"""

from __future__ import annotations

import httpx2

import log
from app.core.settings import settings
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.db.repositories.site_repo_adapter import SiteRepositoryAdapter
from app.sites.engine import SiteEngine
from app.utils.browser_mode import get_chrome_server_url
from app.utils.fingerprint_headers import fingerprint_to_browser_headers, merge_fingerprint_headers
from app.utils.json_utils import JsonUtils


def _normalize_headers(headers) -> dict:
    """归一化站点高级请求头为 dict（兼容字符串 JSON 存储）。"""
    if not headers:
        return {}
    if isinstance(headers, str):
        try:
            headers = JsonUtils.loads(headers) or {}
        except Exception:  # noqa: BLE001
            return {}
    return headers if isinstance(headers, dict) else {}


def _chrome_admin_token() -> str:
    return str((settings.get("laboratory") or {}).get("chrome_admin_token") or "")


def _set_default_fp_profile_id(profile_id: str) -> None:
    """把指纹画像 ID 写入系统配置（laboratory.chrome_fp_profile_id）。"""
    try:
        current = str((settings.get("laboratory") or {}).get("chrome_fp_profile_id") or "")
        if current == profile_id:
            return
        full = settings.get()
        full.setdefault("laboratory", {})["chrome_fp_profile_id"] = profile_id
        settings.save(full)
        log.info(f"[Fingerprint] 已更新默认指纹画像: {profile_id}")
    except Exception as e:  # noqa: BLE001
        log.warn(f"[Fingerprint] 保存默认指纹画像失败: {e}")


def _sanitize_fingerprint(raw: dict) -> dict:
    """清洗前端指纹：只保留 nexus-chrome FingerprintFields 支持的字段，限制取值。"""
    allowed = {
        "ua": str,
        "ua_full_version": str,
        "ua_brand_version": str,
        "languages": list,
        "platform": str,
        "cores": int,
        "memory": (int, float),
        "webgl_vendor": str,
        "webgl_renderer": str,
        "screen_width": int,
        "screen_height": int,
        "screen_color_depth": int,
        "uad_platform": str,
        "uad_platform_version": str,
        "uad_arch": str,
        "uad_model": str,
        "touch_points": int,
        "vendor": str,
        "app_version": str,
        "dnt": bool,
        "online": str,
        "net_rtt": int,
        "net_downlink": (int, float),
        "net_effective_type": str,
    }
    out: dict = {}
    for key, type_ in allowed.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, type_):
            out[key] = value
    # 渲染类指纹无法注入（容器为 swiftshader 渲染），强制确定性
    out["canvas_noise"] = False
    out["audio_noise"] = False
    return out


def apply_fingerprint_to_site_configs(fingerprint: dict) -> int:
    """把指纹 UA/浏览器请求头应用到已启用站点配置（区分 API / HTML 站点）.

    站点配置存储为 CONFIG_SITE（NOTE.ua / NOTE.headers / HEADERS 列）——
    运行时站点请求（RSS/刷流/统计）与索引器搜索（SiteCache）以及前端维护页
    均读取该表；INDEXER_SITE_CONFIG 仅用于启用状态过滤。

    更新站点维护的 UA 与高级请求头（headers）：
    - API 站点：Accept 为 JSON、Fetch 语义为 cors/empty
    - HTML 站点：Accept 为文档、Fetch 语义为 navigate/document
    只覆盖 UA 相关键，保留用户手工配置的 Cookie/认证头等自定义值。
    """
    ua = str(fingerprint.get("ua") or "").strip()
    if not ua:
        log.info("[Fingerprint]指纹缺少 UA，跳过站点配置更新")
        return 0

    engine = SiteEngine()
    site_repo = SiteRepositoryAdapter()
    indexer_repo = IndexerSiteConfigRepositoryAdapter()
    enabled_names = {n.lower() for n in indexer_repo.list_enabled_names()}
    updated = 0
    for site in site_repo.list_all():
        if site.name.lower() not in enabled_names:
            continue
        note = dict(site.note or {})
        site_url = str(note.get("signurl") or note.get("rssurl") or site.sign_url or site.rss_url or "")
        site_def = engine.get_by_url(site_url) if site_url else None
        site_type = "api" if (site_def and site_def.api) else "html"
        fp_headers = fingerprint_to_browser_headers(fingerprint, site_type)
        # UA 由站点 UA 字段承载（认证信息 User-Agent），高级请求头不再重复写入 User-Agent
        fp_headers.pop("User-Agent", None)
        existing_headers = _normalize_headers(note.get("headers") or site.headers)
        merged_headers = merge_fingerprint_headers(existing_headers, fp_headers)
        note["headers"] = merged_headers
        note["ua"] = ua
        site.headers = JsonUtils.dumps(merged_headers, ensure_ascii=False)
        site.note = note
        try:
            site_repo.update(site)
            updated += 1
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Fingerprint]更新站点 {site.name} 配置失败: {e}")
    if updated:
        log.info(f"[Fingerprint]已更新 {updated} 个站点的 UA/请求头")
    return updated


def sync_fingerprint_to_chrome(user_id: int, fingerprint: dict) -> str | None:
    """把用户真实指纹同步到 nexus-chrome，返回 fp_profile_id；失败返回 None。"""
    profile_id = f"user_{user_id}"
    server = get_chrome_server_url()
    if not server:
        log.warn("[Fingerprint] nexus-chrome 服务器未配置，跳过指纹同步")
        return None

    sanitized = _sanitize_fingerprint(fingerprint)
    payload = {
        "profile_id": profile_id,
        "name": f"user_{user_id} real fingerprint",
        "fingerprint": sanitized,
    }
    headers = {}
    token = _chrome_admin_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx2.post(f"{server}/api/profiles", json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        # 同步成功：写入实验室默认指纹画像，供全局后台流程（站点定时刷新/RSS 自动化）使用
        _set_default_fp_profile_id(profile_id)
        # 指纹 UA/浏览器请求头同步到站点配置（区分 API / HTML）
        try:
            apply_fingerprint_to_site_configs(sanitized)
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Fingerprint]应用指纹到站点配置失败: {e}")
        log.info(f"[Fingerprint] 用户 {user_id} 指纹已同步: {profile_id}")
        return profile_id
    except Exception as e:  # noqa: BLE001
        log.warn(f"[Fingerprint] 同步用户 {user_id} 指纹失败: {e}")
        return None
