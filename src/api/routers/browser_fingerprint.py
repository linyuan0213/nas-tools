"""浏览器指纹注入路由 — 前端采集真实指纹后提交，按用户映射 nexus-chrome 指纹画像。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

import log
from api.deps import get_current_user
from app.core.error_codes import ErrorCode
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.services.browser_fingerprint_service import sync_fingerprint_to_chrome

router = APIRouter()


@router.post("/browser/fingerprint", response_model=CommonResponse)
async def submit_fingerprint(
    fingerprint: dict[str, Any],
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """提交当前用户浏览器的真实指纹，注入 nexus-chrome 指纹画像。

    同步成功后：
    - 将指纹 UA / 浏览器请求头更新到已启用站点配置（区分 API / HTML）；
    - 刷新站点缓存使新 UA / 请求头立即生效。

    移动端保护：站点已由桌面端指纹设置时，移动端提交仅同步独立画像
    （site_skipped=true），不覆盖站点 UA/请求头，避免 PC/移动指纹交替触发风控。

    返回 fp_profile_id，后续会话携带该 ID 即呈现与用户真实浏览器一致的指纹。
    """
    result = sync_fingerprint_to_chrome(user.user_id, fingerprint)
    if not result.profile_id:
        return CommonResponse(
            code=ErrorCode.OPERATION_FAILED,
            message="指纹同步失败（nexus-chrome 不可达或未配置）",
            data=None,
        )
    # 站点配置已更新：刷新站点缓存使新 UA/请求头立即生效
    ctx = getattr(request.app.state, "context", None)
    site_cache = getattr(ctx, "site_cache", None)
    if site_cache is not None:
        try:
            site_cache.refresh()
        except Exception:  # noqa: BLE001
            log.debug("[Fingerprint]刷新站点缓存失败（不影响指纹同步结果）")
    data: dict[str, Any] = {"fp_profile_id": result.profile_id}
    if result.site_skipped:
        data["site_skipped"] = True
        data["site_skip_reason"] = result.site_skip_reason
    return CommonResponse(code=0, message="ok", data=data)
