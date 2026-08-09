"""浏览器指纹注入路由 — 前端采集真实指纹后提交，按用户映射 nexus-chrome 指纹画像。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.services.browser_fingerprint_service import sync_fingerprint_to_chrome

router = APIRouter()


@router.post("/browser/fingerprint", response_model=CommonResponse)
async def submit_fingerprint(
    fingerprint: dict[str, Any],
    user: UserContext = Depends(get_current_user),
):
    """提交当前用户浏览器的真实指纹，注入 nexus-chrome 指纹画像。

    返回 fp_profile_id，后续会话携带该 ID 即呈现与用户真实浏览器一致的指纹。
    """
    profile_id = sync_fingerprint_to_chrome(user.user_id, fingerprint)
    if not profile_id:
        return CommonResponse(code=1, message="指纹同步失败（nexus-chrome 不可达或未配置）", data=None)
    return CommonResponse(code=0, message="ok", data={"fp_profile_id": profile_id})
