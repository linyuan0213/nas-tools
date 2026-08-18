"""浏览器指纹 → HTTP 请求头映射.

将前端采集的真实浏览器指纹（navigator UA / Client Hints）转换为可注入站点的
请求头，区分 API 站点（JSON 接口）与 HTML 站点（页面抓取）两类。

映射只覆盖 UA 相关键，绝不覆盖用户手工配置的认证头（Cookie/Authorization 等）。
"""

from __future__ import annotations

from typing import Any

# API 站点：JSON 接口，Accept 为 JSON，Fetch 语义为 cors/empty
_API_ACCEPT = "application/json, text/plain, */*"

# HTML 站点：页面抓取，Accept 为文档类型，Fetch 语义为 navigate/document
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"

# 需要保留用户自定义值的头部（指纹不覆盖这些键）
_UA_KEYS = {
    "User-Agent",
    "sec-ch-ua",
    "sec-ch-ua-full-version-list",
    "sec-ch-ua-arch",
    "sec-ch-ua-platform",
    "sec-ch-ua-platform-version",
    "sec-ch-ua-model",
    "sec-ch-ua-mobile",
    "sec-ch-ua-bitness",
    "sec-ch-ua-full-version",
    "Accept",
    "Accept-Language",
    "Sec-Fetch-Dest",
    "Sec-Fetch-Mode",
    "Sec-Fetch-Site",
    "Sec-Fetch-User",
    "Upgrade-Insecure-Requests",
}


def _parse_brand_version(value: str) -> str | None:
    """解析 Client Hints 品牌版本（如 "Google Chrome 126.0.0.0" / "Chromium/126.0.0.0"）.

    品牌可含空格（"Google Chrome"），版本为最后一个空白/斜杠分隔的 token。
    """
    if not value:
        return None
    value = value.strip()
    if " " in value:
        brand, _, version = value.rpartition(" ")
    elif "/" in value:
        brand, _, version = value.rpartition("/")
    else:
        brand, version = value, "0.0.0.0"
    if not brand or not version:
        return None
    return f'"{brand}";v="{version}"'


def _build_sec_ch_ua(fingerprint: dict) -> str | None:
    """从 ua_brand_version 构建 sec-ch-ua 品牌列表."""
    brand_value = str(fingerprint.get("ua_brand_version") or "").strip()
    item = _parse_brand_version(brand_value)
    if not item:
        return None
    brands = [item]
    # 补充稳定品牌串：缺少 chromium 主品牌时补 Not-A.Brand
    if not any("Chromium" in b or "Google Chrome" in b for b in brands):
        brands.append('"Not.A/Brand";v="8"')
    return ", ".join(brands)


def _map_platform(fingerprint: dict) -> str | None:
    """映射平台到 sec-ch-ua-platform（uad_platform 优先，回退 navigator.platform）."""
    uad = str(fingerprint.get("uad_platform") or "").strip()
    if uad:
        return f'"{uad}"'
    platform = str(fingerprint.get("platform") or "")
    if not platform:
        return None
    lower = platform.lower()
    if "win" in lower:
        return '"Windows"'
    if "mac" in lower:
        return '"macOS"'
    if "linux" in lower:
        return '"Linux"'
    if "android" in lower:
        return '"Android"'
    if "iphone" in lower or "ipad" in lower:
        return '"iOS"'
    return f'"{platform}"'


def _is_mobile(fingerprint: dict) -> str:
    """判断移动端（touch_points>0 视为可触屏，结合 uad_platform）."""
    platform = str(fingerprint.get("uad_platform") or fingerprint.get("platform") or "").lower()
    if any(k in platform for k in ("android", "iphone", "ipad", "ios")):
        return "?1"
    touch = fingerprint.get("touch_points")
    if isinstance(touch, int) and touch > 0 and any(k in platform for k in ("linux", "win", "mac")):
        return "?0"
    return "?0"


def _build_accept_language(fingerprint: dict) -> str | None:
    languages = fingerprint.get("languages")
    if isinstance(languages, list) and languages:
        return ", ".join(str(lang) for lang in languages[:6])
    return None


def fingerprint_to_browser_headers(fingerprint: dict[str, Any], site_type: str = "html") -> dict[str, str]:
    """将指纹转换为浏览器请求头.

    :param fingerprint: 清洗后的指纹 dict
    :param site_type: "api" 或 "html"，决定 Accept / Sec-Fetch-* 取值
    :return: 仅包含指纹可推导的请求头（不含认证头）
    """
    is_api = site_type == "api"
    headers: dict[str, str] = {}

    ua = str(fingerprint.get("ua") or "").strip()
    if ua:
        headers["User-Agent"] = ua

    sec_ch_ua = _build_sec_ch_ua(fingerprint)
    if sec_ch_ua:
        headers["sec-ch-ua"] = sec_ch_ua

    platform = _map_platform(fingerprint)
    if platform:
        headers["sec-ch-ua-platform"] = platform
    headers["sec-ch-ua-mobile"] = _is_mobile(fingerprint)

    arch = str(fingerprint.get("uad_arch") or "").strip()
    if arch:
        headers["sec-ch-ua-arch"] = f'"{arch}"'
    model = str(fingerprint.get("uad_model") or "").strip()
    if model:
        headers["sec-ch-ua-model"] = f'"{model}"'
    platform_version = str(fingerprint.get("uad_platform_version") or "").strip()
    if platform_version:
        headers["sec-ch-ua-platform-version"] = f'"{platform_version}"'
    ua_full_version = str(fingerprint.get("ua_full_version") or "").strip()
    if ua_full_version:
        headers["sec-ch-ua-full-version"] = f'"{ua_full_version}"'

    accept_language = _build_accept_language(fingerprint)
    if accept_language:
        headers["Accept-Language"] = accept_language

    headers["Accept"] = _API_ACCEPT if is_api else _HTML_ACCEPT
    if is_api:
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
    else:
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Upgrade-Insecure-Requests"] = "1"
    headers["Sec-Fetch-Site"] = "same-origin"
    return headers


def merge_fingerprint_headers(existing: dict[str, str], fingerprint_headers: dict[str, str]) -> dict[str, str]:
    """合并指纹请求头到站点已有高级请求头（仅覆盖 UA 相关键，保留用户自定义键）."""
    merged = dict(existing or {})
    for key, value in fingerprint_headers.items():
        if key in _UA_KEYS:
            merged[key] = value
    return merged
