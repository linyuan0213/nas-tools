from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.deps import get_current_user, get_rbac_service, require_any_permission, require_permission
from app.core.error_codes import ErrorCode
from app.core.exceptions import NexusError, ResourceAlreadyExistsError, ResourceNotFoundError, ServiceError
from app.core.settings import settings
from app.schemas.auth import UserContext
from app.schemas.common import CommonResponse
from app.utils.response import fail, success

router = APIRouter()


# ---------- Request Models ----------


class IdRequest(BaseModel):
    id: int


class CreateMenuRequest(BaseModel):
    menu_name: str
    menu_code: str
    parent_id: int | None = None
    path: str | None = None
    icon: str | None = None
    component: str | None = None
    sort_order: int = 0
    menu_level: int = 1
    permission_code: str | None = None
    redirect: str | None = None
    keep_alive: int | None = 0
    affix_tab: int | None = 0
    hide_in_menu: int | None = 0
    hide_in_tab: int | None = 0
    hide_in_breadcrumb: int | None = 0
    active_icon: str | None = None
    badge: str | None = None
    badge_type: str | None = None


class UpdateMenuRequest(BaseModel):
    id: int
    menu_name: str | None = None
    menu_code: str | None = None
    path: str | None = None
    icon: str | None = None
    component: str | None = None
    sort_order: int | None = None
    parent_id: int | None = None
    is_hidden: int | None = None
    status: int | None = None
    permission_code: str | None = None
    redirect: str | None = None
    keep_alive: int | None = None
    affix_tab: int | None = None
    hide_in_menu: int | None = None
    hide_in_tab: int | None = None
    hide_in_breadcrumb: int | None = None
    active_icon: str | None = None
    badge: str | None = None
    badge_type: str | None = None


class MenuOrderItem(BaseModel):
    id: int
    sort_order: int
    parent_id: int | None = None


class UpdateMenuSortRequest(BaseModel):
    menu_orders: list[MenuOrderItem] = []


class CreateRoleRequest(BaseModel):
    role_name: str
    role_code: str
    description: str | None = None
    role_level: int = 100
    permission_ids: list[int] = []
    menu_ids: list[int] = []


class UpdateRoleRequest(BaseModel):
    id: int
    role_name: str | None = None
    description: str | None = None
    role_level: int | None = None
    status: int | None = None
    permission_ids: list[int] | None = None
    menu_ids: list[int] | None = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    nickname: str | None = None
    role_ids: list[int] = []


class UpdateUserRequest(BaseModel):
    id: int
    username: str | None = None
    email: str | None = None
    nickname: str | None = None
    status: int | None = None
    avatar: str | None = None
    role_ids: list[int] | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str
    old_password: str | None = None


# ---------- Helpers ----------


def _get_user_id_from_ctx(current_user):
    """兼容层：从 UserContext 或 str 提取用户ID"""
    return getattr(current_user, "user_id", 0)


# ---------- 用户管理 ----------


@router.post("/users/create", response_model=CommonResponse, summary="创建用户")
def create_user(
    req: CreateUserRequest,
    current_user: UserContext = Depends(require_permission("user:create")),
    svc=Depends(get_rbac_service),
):
    if not req.username or not req.password:
        return fail(success=False, message="用户名和密码不能为空")

    try:
        result = svc.create_user(
            username=req.username,
            password=req.password,
            email=req.email or "",
            nickname=req.nickname or "",
            role_ids=req.role_ids,
        )
        return success(data={"success": True, "message": "创建成功", "data": result.to_dict()})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/users/delete", response_model=CommonResponse, summary="删除用户")
def delete_user(
    req: IdRequest,
    current_user: UserContext = Depends(require_permission("user:delete")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="用户ID不能为空")

    try:
        _ = svc.delete_user(req.id, current_user_id=current_user.user_id)
        return success(data={"success": True, "message": "删除成功"})
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ServiceError) as e:
        return fail(success=False, message=e.message)


@router.post("/users/update", response_model=CommonResponse, summary="更新用户")
def update_user(
    req: UpdateUserRequest,
    current_user: UserContext = Depends(require_permission("user:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="用户ID不能为空")

    update_fields = {}
    for field in ["username", "email", "nickname", "status", "avatar"]:
        val = getattr(req, field, None)
        if val is not None:
            update_fields[field] = val

    try:
        svc.update_user(req.id, **update_fields)

        # 仅当明确传入非空角色列表时才重新分配角色，避免编辑资料时误传空列表清空角色导致权限丢失
        if req.role_ids:
            svc.assign_roles_to_user(req.id, req.role_ids)

        return success(data={"success": True, "message": "更新成功"})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/users/detail", response_model=CommonResponse, summary="获取用户详情")
def get_user_detail(
    req: IdRequest,
    current_user: UserContext = Depends(require_any_permission("user:view", "user:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="用户ID不能为空")

    user = svc.get_user_by_id(req.id)
    if user:
        return success(data={"success": True, "data": user.to_dict()})
    return fail(success=False, message="用户不存在")


@router.post("/users", response_model=CommonResponse, summary="获取用户列表")
def get_users(
    current_user: UserContext = Depends(require_any_permission("user:view", "user:update")),
    svc=Depends(get_rbac_service),
):
    users_raw, _ = svc.get_users(page=1, page_size=1000)
    users = []
    for user in users_raw:
        d = user.to_dict()
        last_login = None
        if user.last_login_at:
            last_login = user.last_login_at.strftime("%Y-%m-%d %H:%M")

        roles = d.get("roles", [])
        users.append(
            {
                "id": d["id"],
                "name": d["username"],
                "username": d["username"],
                "nickname": d["nickname"] or d["username"],
                "email": d["email"],
                "avatar": d.get("avatar"),
                "status": d["status"],
                "roles": roles,
                "last_login_at": last_login,
                "pris": [role.get("role_name") for role in roles] if roles else ["普通用户"],
            }
        )
    return success(data=users)


def _is_admin(user: UserContext) -> bool:
    """检查是否为管理员（拥有 user:update 权限）"""
    return "user:update" in (user.permissions or [])


@router.post("/users/{user_id}/reset-password", response_model=CommonResponse, summary="重置密码")
def reset_password(
    user_id: int,
    req: ResetPasswordRequest,
    current_user: UserContext = Depends(get_current_user),
    svc=Depends(get_rbac_service),
):
    if not req.new_password:
        return fail(success=False, message="新密码不能为空")

    is_admin = _is_admin(current_user)
    is_self = current_user.user_id == user_id

    # 只能改自己，或管理员改任何人
    if not is_admin and not is_self:
        return fail(success=False, message="无权重置该用户密码")

    # 非管理员改自己需要旧密码
    if not is_admin and req.old_password is None:
        return fail(success=False, message="请输入旧密码")

    try:
        message = svc.reset_password(user_id, req.new_password, req.old_password)
        return success(data={"success": True, "message": message})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/users/{user_id}/avatar", response_model=CommonResponse, summary="上传头像")
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    current_user: UserContext = Depends(require_permission("user:update")),
    svc=Depends(get_rbac_service),
):
    """上传用户头像"""
    if not file.content_type or not file.content_type.startswith("image/"):
        return fail(success=False, message="请上传图片文件")

    try:
        # 头像保存目录
        avatar_dir = Path(settings.data_path) / "static" / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        ext = Path(file.filename).suffix.lower() if file.filename else ".png"
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            ext = ".png"
        filename = f"user_{user_id}_{int(datetime.now().timestamp())}{ext}"
        file_path = avatar_dir / filename

        # 保存文件
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # 通过 API 路径访问头像，避免 /static 被前端路由拦截
        avatar_url = f"/api/rbac/avatars/{filename}"

        # 更新用户头像到数据库
        svc.update_user(user_id, avatar=avatar_url)

        return success(data={"success": True, "url": avatar_url})
    except Exception as e:
        return fail(success=False, message=f"上传失败: {str(e)}")


@router.get("/avatars/{filename}", summary="获取头像")
async def get_avatar(filename: str):
    """获取用户头像文件"""
    avatar_dir = Path(settings.data_path) / "static" / "avatars"
    file_path = avatar_dir / filename
    if not file_path.exists():
        raise NexusError("头像不存在", errcode=ErrorCode.RESOURCE_NOT_FOUND, http_status=404)
    return FileResponse(file_path)


# ---------- 角色管理 ----------


@router.post("/roles/create", response_model=CommonResponse, summary="创建角色")
def create_role(
    req: CreateRoleRequest,
    current_user: UserContext = Depends(require_permission("role:create")),
    svc=Depends(get_rbac_service),
):
    if not req.role_name or not req.role_code:
        return fail(success=False, message="角色名称和代码不能为空")

    try:
        result = svc.create_role(
            role_name=req.role_name,
            role_code=req.role_code,
            description=req.description,
            role_level=req.role_level,
            permission_ids=req.permission_ids,
            menu_ids=req.menu_ids,
        )
        return success(data={"success": True, "message": "创建成功", "data": result.to_dict()})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/roles/delete", response_model=CommonResponse, summary="删除角色")
def delete_role(
    req: IdRequest,
    current_user: UserContext = Depends(require_permission("role:delete")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="角色ID不能为空")

    try:
        message = svc.delete_role(req.id)
        return success(data={"success": True, "message": message})
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ServiceError) as e:
        return fail(success=False, message=e.message)


@router.post("/roles/update", response_model=CommonResponse, summary="更新角色")
def update_role(
    req: UpdateRoleRequest,
    current_user: UserContext = Depends(require_permission("role:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="角色ID不能为空")

    update_fields = {}
    for field in ["role_name", "description", "role_level", "status"]:
        val = getattr(req, field, None)
        if val is not None:
            update_fields[field] = val

    try:
        svc.update_role(req.id, **update_fields)

        if req.permission_ids is not None:
            svc.assign_permissions_to_role(req.id, req.permission_ids)

        if req.menu_ids is not None:
            svc.assign_menus_to_role(req.id, req.menu_ids)

        return success(data={"success": True, "message": "更新成功"})
    except (ResourceAlreadyExistsError, ResourceNotFoundError, ServiceError) as e:
        return fail(success=False, message=e.message)


@router.post("/roles/detail", response_model=CommonResponse, summary="获取角色详情")
def get_role_detail(
    req: IdRequest,
    current_user: UserContext = Depends(require_any_permission("role:view", "role:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="角色ID不能为空")

    role = svc.get_role_by_id(req.id)
    if role:
        d = role.to_dict()
        # 超级管理员返回所有权限和菜单
        if str(role.ROLE_CODE or "") == "superadmin":
            d["permissions"] = [p.to_dict() for p in svc.get_all_permissions()]
            d["menus"] = [m.to_dict() for m in svc.get_all_menus()]
        return success(data={"success": True, "data": d})
    return fail(success=False, message="角色不存在")


@router.post("/roles", response_model=CommonResponse, summary="获取角色列表")
def get_roles(
    current_user: UserContext = Depends(require_any_permission("role:view", "role:update")),
    svc=Depends(get_rbac_service),
):
    """角色列表（新增）"""
    roles = svc.get_all_roles()
    result = []
    all_permissions = None
    all_menus = None
    for role in roles:
        d = role.to_dict()
        # 超级管理员返回所有权限和菜单
        if str(role.ROLE_CODE or "") == "superadmin":
            if all_permissions is None:
                all_permissions = [p.to_dict() for p in svc.get_all_permissions()]
            if all_menus is None:
                all_menus = [m.to_dict() for m in svc.get_all_menus()]
            d["permissions"] = all_permissions
            d["menus"] = all_menus
        result.append(d)
    return success(data=result)


# ---------- 菜单管理 ----------


@router.post("/menus/create", response_model=CommonResponse, summary="创建菜单")
def create_menu(
    req: CreateMenuRequest,
    current_user: UserContext = Depends(require_permission("menu:create")),
    svc=Depends(get_rbac_service),
):
    if not req.menu_name or not req.menu_code:
        return fail(success=False, message="菜单名称和代码不能为空")

    try:
        result = svc.create_menu(
            menu_name=req.menu_name,
            menu_code=req.menu_code,
            parent_id=req.parent_id,
            path=req.path,
            icon=req.icon,
            component=req.component,
            sort_order=req.sort_order,
            menu_level=req.menu_level,
            permission_code=req.permission_code,
            redirect=req.redirect,
            keep_alive=req.keep_alive,
            affix_tab=req.affix_tab,
            hide_in_menu=req.hide_in_menu,
            hide_in_tab=req.hide_in_tab,
            hide_in_breadcrumb=req.hide_in_breadcrumb,
            active_icon=req.active_icon,
            badge=req.badge,
            badge_type=req.badge_type,
        )
        return success(data={"success": True, "message": "创建成功", "data": result.to_dict()})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/menus/delete", response_model=CommonResponse, summary="删除菜单")
def delete_menu(
    req: IdRequest,
    current_user: UserContext = Depends(require_permission("menu:delete")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="菜单ID不能为空")

    try:
        message = svc.delete_menu(req.id)
        return success(data={"success": True, "message": message})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/menus/reset", response_model=CommonResponse, summary="重置菜单到初始状态")
def reset_menus(
    current_user: UserContext = Depends(require_permission("menu:update")),
    svc=Depends(get_rbac_service),
):
    try:
        affected = svc.reset_menus()
        return success(data={"success": True, "affected": affected, "message": "菜单已重置为默认"})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/menus/update", response_model=CommonResponse, summary="更新菜单")
def update_menu(
    req: UpdateMenuRequest,
    current_user: UserContext = Depends(require_permission("menu:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="菜单ID不能为空")

    update_fields = {}
    for field in [
        "menu_name",
        "menu_code",
        "path",
        "icon",
        "component",
        "sort_order",
        "parent_id",
        "is_hidden",
        "status",
        "permission_code",
        "redirect",
        "keep_alive",
        "affix_tab",
        "hide_in_menu",
        "hide_in_tab",
        "hide_in_breadcrumb",
        "active_icon",
        "badge",
        "badge_type",
    ]:
        if field in req.model_fields_set:
            update_fields[field] = getattr(req, field)

    try:
        svc.update_menu(req.id, **update_fields)
        return success(data={"success": True, "message": "更新成功"})
    except (ResourceAlreadyExistsError, ResourceNotFoundError) as e:
        return fail(success=False, message=e.message)


@router.post("/menus/sort", response_model=CommonResponse, summary="更新菜单排序")
def update_menu_sort(
    req: UpdateMenuSortRequest,
    current_user: UserContext = Depends(require_permission("menu:update")),
    svc=Depends(get_rbac_service),
):
    if not req.menu_orders:
        return fail(success=False, message="菜单排序数据不能为空")

    success_count = 0
    for item in req.menu_orders:
        menu_id = item.id
        sort_order = item.sort_order
        parent_id = item.parent_id

        if menu_id is not None and sort_order is not None:
            update_fields = {"sort_order": sort_order, "parent_id": parent_id}
            ok2 = svc.update_menu(menu_id, **update_fields)
            if ok2:
                success_count += 1

    return success(data={"success": True, "message": f"成功更新 {success_count} 个菜单排序"})


@router.post("/menus/detail", response_model=CommonResponse, summary="获取菜单详情")
def get_menu_detail(
    req: IdRequest,
    current_user: UserContext = Depends(require_any_permission("menu:view", "menu:update")),
    svc=Depends(get_rbac_service),
):
    if not req.id:
        return fail(success=False, message="菜单ID不能为空")

    menu = svc.get_menu_by_id(req.id)
    if menu:
        return success(data={"success": True, "data": menu.to_dict()})
    return fail(success=False, message="菜单不存在")


@router.post("/menus", response_model=CommonResponse, summary="获取当前用户菜单")
def get_user_menus(
    current_user: UserContext = Depends(get_current_user),
    svc=Depends(get_rbac_service),
):
    """
    当前用户菜单树 - 直接输出 Vben Admin 格式（service 层已构建）
    """
    user_id = _get_user_id_from_ctx(current_user)
    if not user_id:
        return fail(success=False, message="用户不存在")
    tree = svc.get_user_menus(user_id)
    return success(data=tree)


def _build_management_tree(menus, parent_id=None):
    """构建菜单管理树（保留 id/pid 等管理字段）"""
    result = []
    for m in menus:
        pid = m.PARENT_ID
        mid = m.ID
        if (parent_id is None and pid is None) or (pid == parent_id):
            name = getattr(m, "MENU_NAME", None) or getattr(m, "menu_name", "")
            path = getattr(m, "PATH", None) or getattr(m, "path", "")
            icon = getattr(m, "ICON", None) or getattr(m, "icon", None)
            component = getattr(m, "COMPONENT", None) or getattr(m, "component", None)
            sort_order = getattr(m, "SORT_ORDER", None) or getattr(m, "sort_order", 0)
            menu_level = getattr(m, "MENU_LEVEL", None) or getattr(m, "menu_level", 1)
            permission_code = getattr(m, "PERMISSION_CODE", None) or getattr(m, "permission_code", None)
            redirect = getattr(m, "REDIRECT", None) or getattr(m, "redirect", None)
            keep_alive = getattr(m, "KEEP_ALIVE", None) or getattr(m, "keep_alive", 0)
            affix_tab = getattr(m, "AFFIX_TAB", None) or getattr(m, "affix_tab", 0)
            hide_in_menu = getattr(m, "HIDE_IN_MENU", None) or getattr(m, "hide_in_menu", 0)
            hide_in_tab = getattr(m, "HIDE_IN_TAB", None) or getattr(m, "hide_in_tab", 0)
            hide_in_breadcrumb = getattr(m, "HIDE_IN_BREADCRUMB", None) or getattr(m, "hide_in_breadcrumb", 0)
            active_icon = getattr(m, "ACTIVE_ICON", None) or getattr(m, "active_icon", None)
            badge = getattr(m, "BADGE", None) or getattr(m, "badge", None)
            badge_type = getattr(m, "BADGE_TYPE", None) or getattr(m, "badge_type", None)
            status = getattr(m, "STATUS", None) or getattr(m, "status", 1)
            auth_code = permission_code or ""

            meta = {"title": name}
            if icon:
                meta["icon"] = icon
            if sort_order is not None:
                meta["order"] = sort_order
            if keep_alive:
                meta["keepAlive"] = bool(keep_alive)
            if affix_tab:
                meta["affixTab"] = bool(affix_tab)
            if hide_in_menu:
                meta["hideInMenu"] = bool(hide_in_menu)
            if hide_in_tab:
                meta["hideInTab"] = bool(hide_in_tab)
            if hide_in_breadcrumb:
                meta["hideInBreadcrumb"] = bool(hide_in_breadcrumb)
            if active_icon:
                meta["activeIcon"] = active_icon
            if badge:
                meta["badge"] = badge
            if badge_type:
                meta["badgeType"] = badge_type

            menu_code = getattr(m, "MENU_CODE", None) or getattr(m, "menu_code", "")
            # path 必须唯一，否则 Vben menu 组件会用 path 作为 key 导致多个菜单联动
            # 注意：空字符串是合法的 path，不能用 or fallback 到 menu_code
            route_path = (path if path is not None else menu_code).lstrip("/")

            item = {
                "id": mid,
                "parent_id": pid,
                "menu_name": name,
                "menu_code": menu_code,
                "path": route_path,
                "type": "catalog"
                if menu_level == 1 and not pid
                else ("button" if auth_code and not component else "menu"),
                "status": status,
                "permission_code": auth_code,
                "sort_order": sort_order,
                "menu_level": menu_level,
                "hide_in_menu": hide_in_menu,
                "icon": icon,
                "meta": meta,
            }
            if component:
                item["component"] = component
            if redirect:
                item["redirect"] = redirect

            children = _build_management_tree(menus, mid)
            if children:
                item["children"] = children
            result.append(item)
    return result


@router.post("/menus/all", response_model=CommonResponse, summary="获取所有菜单")
def get_all_menus_for_management(
    current_user: UserContext = Depends(require_any_permission("menu:view", "menu:update")),
    svc=Depends(get_rbac_service),
):
    """
    获取所有菜单（菜单管理专用，包含完整管理字段）
    """
    menus = svc.get_all_menus()
    tree = _build_management_tree(menus)
    return success(data=tree)


@router.post("/menus/top", response_model=CommonResponse, summary="获取顶部菜单")
def get_top_menus(
    current_user: UserContext = Depends(get_current_user),
    svc=Depends(get_rbac_service),
):
    user_id = _get_user_id_from_ctx(current_user)
    if not user_id:
        return fail(success=False, message="用户不存在")
    menus = svc.get_user_menus(user_id)
    return success(data=menus)


# ---------- 权限管理 ----------


@router.post("/permissions", response_model=CommonResponse, summary="获取权限列表")
def get_all_permissions(
    current_user: UserContext = Depends(require_any_permission("permission:view", "permission:update")),
    svc=Depends(get_rbac_service),
):
    """
    获取所有权限列表（供角色权限配置使用）
    """
    try:
        permissions = svc.get_all_permissions()
        return success(data=[p.to_dict() for p in permissions])
    except Exception as e:
        return fail(success=False, message=str(e))


# ---------- 权限码 ----------


@router.get("/codes", response_model=CommonResponse, summary="获取用户权限码")
def get_user_codes(
    current_user: UserContext = Depends(get_current_user),
    svc=Depends(get_rbac_service),
):
    """
    获取当前用户的权限码列表（供前端 Vben 权限系统使用）
    """
    user_id = _get_user_id_from_ctx(current_user)
    if not user_id:
        return fail(success=False, message="用户不存在")
    try:
        permissions = svc.get_user_permissions(user_id)
        codes = list(permissions) if permissions else []
        return success(data=codes)
    except Exception as e:
        return fail(success=False, message=str(e))
