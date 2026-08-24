"""
FastAPI 图片代理路由
兼容前端通过 ImageProxy 生成的 /img/* 请求
复用 app.helper.image_proxy_core 的下载/缓存逻辑
"""

import asyncio
import os
import time
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse, RedirectResponse, Response

import log
from app.core.constants import TMDB_IMAGE_DOMAIN
from app.core.error_codes import ErrorCode
from app.core.exceptions import DomainError, NexusError, ServiceError
from app.core.settings import settings
from app.infrastructure.image_proxy import (
    MAX_CACHE_DAYS,
    SIZE_DIMENSIONS,
    SOURCE_DOMAINS,
    ImageProxy,
    download_image,
    get_cache_path,
    resize_image,
)

router = APIRouter()


async def _serve_image(
    cache_path: str,
    image_url: str,
    size: str | None = None,
    referer: str | None = None,
    media_type: str = "image/jpeg",
    downloader=None,
):
    """FastAPI 版本的缓存检查/下载/返回图片"""
    # 检查缓存（30 天过期），空缓存直接删除重下
    if os.path.exists(cache_path):
        try:
            stat = os.stat(cache_path)
            if stat.st_size > 0 and time.time() - stat.st_mtime < MAX_CACHE_DAYS * 24 * 3600:
                return FileResponse(cache_path, media_type=media_type)
            else:
                os.remove(cache_path)
        except (ServiceError, DomainError) as e:
            log.error(f"[ImageProxy]读取缓存失败: {e.message}")
        except Exception as e:
            log.error(f"[ImageProxy]读取缓存失败: {str(e)}")

    # 下载图片（同步 downloader 放线程池，避免阻塞事件循环）
    if downloader:
        image_data = await asyncio.to_thread(downloader, image_url)
    else:
        image_data = await download_image(image_url, referer=referer)
    if not image_data or len(image_data) < 100:
        log.error(f"[ImageProxy]下载内容为空或过小: {image_url}")
        raise NexusError("获取图片失败", errcode=ErrorCode.IMAGE_FETCH_FAILED, http_status=404)

    # 调整尺寸（PIL CPU 密集，放线程池）
    if size and size != "original":
        image_data = await asyncio.to_thread(resize_image, image_data, size)

    # 保存到缓存
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(image_data)
    except (ServiceError, DomainError) as e:
        log.error(f"[ImageProxy]保存缓存失败: {e.message}")
    except Exception as e:
        log.error(f"[ImageProxy]保存缓存失败: {str(e)}")

    return Response(image_data, media_type=media_type)


@router.get("/tmdb/{size}/{img_path:path}", summary="代理 TMDB 图片")
async def proxy_tmdb_image(size: str, img_path: str):
    """代理 TMDB 图片"""
    if size not in SIZE_DIMENSIONS:
        size = "w500"
    cache_path = get_cache_path("tmdb", img_path, size)
    original_url = f"https://{TMDB_IMAGE_DOMAIN}/t/p/original/{img_path}"
    return await _serve_image(cache_path, original_url, size)


@router.get("/douban/{img_path:path}", summary="代理豆瓣图片")
async def proxy_douban_image(img_path: str):
    """代理豆瓣图片"""
    decoded_path = urllib.parse.unquote(img_path)
    cache_path = get_cache_path("douban", decoded_path)
    if decoded_path.startswith("http"):
        image_url = decoded_path
    else:
        image_url = f"https://{SOURCE_DOMAINS['douban']}/{decoded_path}"
    return await _serve_image(cache_path, image_url, referer="https://movie.douban.com")


@router.get("/bgm/{img_path:path}", summary="代理 Bangumi 图片")
async def proxy_bgm_image(img_path: str):
    """代理 Bangumi 图片"""
    decoded_path = urllib.parse.unquote(img_path)
    cache_path = get_cache_path("bgm", decoded_path)
    if decoded_path.startswith("http"):
        image_url = decoded_path
    else:
        image_url = f"https://{SOURCE_DOMAINS['bgm']}/{decoded_path}"
    return await _serve_image(cache_path, image_url)


@router.get("/library/{img_url:path}", summary="代理媒体库图片")
async def proxy_library_image(request: Request, img_url: str):
    """代理媒体库内网图片"""
    decoded_url = urllib.parse.unquote(img_url)
    # 重新附加查询参数（如 Plex 的 X-Plex-Token）
    if request.query_params:
        separator = "&" if "?" in decoded_url else "?"
        query_string = str(request.query_params)
        decoded_url += separator + query_string
    cache_path = get_cache_path("library", decoded_url)
    if "/v/api/v1/sys/img/" in decoded_url:
        ms = request.app.state.context.media_server
        return await _serve_image(cache_path, decoded_url, downloader=lambda u: ms.download_image(u))
    return await _serve_image(cache_path, decoded_url)


@router.get("", summary="图片代理重定向")
@router.get("/", summary="图片代理重定向（兼容斜杠）")
def proxy_image_redirect(request: Request, url: str | None = None):
    """
    旧格式兼容：/img?url=...
    1. /img?url=/img/tmdb/xxx.jpg -> 重定向到 /img/tmdb/xxx.jpg
    2. /img?url=https://... -> 转换为代理路径后重定向
    """
    if not url:
        raise NexusError("参数错误", errcode=ErrorCode.PARAM_VALIDATION_FAILED, http_status=400)

    # 如果 url 是本地代理路径（以 /img/ 开头），重定向到新路由
    if url.startswith("/img/"):
        return RedirectResponse(url=url, status_code=307)

    # 外部图片 URL：转换为代理路径后重定向
    try:
        proxy_url = ImageProxy.get_proxy_image_url(url, use_proxy=True)
    except (ServiceError, DomainError):
        proxy_url = None
    except Exception:
        proxy_url = None

    if proxy_url and proxy_url.startswith("/img/"):
        return RedirectResponse(url=proxy_url, status_code=307)

    # 兜底：无法生成代理路径时，直接代理
    raise NexusError("无法处理该图片 URL", errcode=ErrorCode.IMAGE_FETCH_FAILED, http_status=404)


@router.get("/favicon/external/{encoded_url:path}", summary="代理外部 favicon URL")
async def proxy_favicon_external(encoded_url: str):
    """代理外部 favicon URL."""
    favicon_url = urllib.parse.unquote(encoded_url)
    cache_path = get_cache_path("favicon", urllib.parse.quote(favicon_url, safe=""))
    return await _serve_image(cache_path, favicon_url, referer=favicon_url, media_type="image/x-icon")


@router.get("/favicon/{domain:path}", summary="代理站点 favicon")
async def proxy_favicon(domain: str):
    """代理站点 favicon.ico，下载到本地缓存并返回."""
    favicon_url = f"https://{domain}/favicon.ico"
    cache_path = get_cache_path("favicon", domain)
    return await _serve_image(cache_path, favicon_url, referer=f"https://{domain}", media_type="image/x-icon")


@router.get("/agent/{name}", summary="Agent 浏览器截图")
async def agent_screenshot(name: str):
    """返回 Agent 浏览器工具保存的截图（数据目录 static/agent，防路径穿越）"""
    safe = Path(name).name
    if not safe.endswith(".png"):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(settings.data_path) / "static" / "agent" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, media_type="image/png")
