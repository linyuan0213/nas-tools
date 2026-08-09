"""浏览器指纹注入服务 — 将前端采集的用户真实指纹同步到 nexus-chrome 指纹画像。

流程：用户浏览器(前端)采集真实指纹 → 后端按 user_id 映射 fp_profile_id
     → 写入 nexus-chrome /api/profiles → 会话以 fp_profile_id 使用该指纹。
"""

from __future__ import annotations

import httpx2

import log
from app.core.settings import settings
from app.utils.browser_mode import get_chrome_server_url


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


def sync_fingerprint_to_chrome(user_id: int, fingerprint: dict) -> str | None:
    """把用户真实指纹同步到 nexus-chrome，返回 fp_profile_id；失败返回 None。"""
    profile_id = f"user_{user_id}"
    server = get_chrome_server_url()
    if not server:
        log.warn("[Fingerprint] nexus-chrome 服务器未配置，跳过指纹同步")
        return None

    payload = {
        "profile_id": profile_id,
        "name": f"user_{user_id} real fingerprint",
        "fingerprint": _sanitize_fingerprint(fingerprint),
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
        log.info(f"[Fingerprint] 用户 {user_id} 指纹已同步: {profile_id}")
        return profile_id
    except Exception as e:  # noqa: BLE001
        log.warn(f"[Fingerprint] 同步用户 {user_id} 指纹失败: {e}")
        return None
