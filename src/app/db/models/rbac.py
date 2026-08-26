"""
RBAC (Role-Based Access Control) 权限管理模型
包含: 用户、角色、权限、菜单、用户角色关联、角色权限关联
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app.db.models.base import Base

# 用户角色关联表
user_roles = Table(
    "RBAC_USER_ROLES",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("RBAC_USERS.ID", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("RBAC_ROLES.ID", ondelete="CASCADE"), primary_key=True),
)


# 角色权限关联表
role_permissions = Table(
    "RBAC_ROLE_PERMISSIONS",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("RBAC_ROLES.ID", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("RBAC_PERMISSIONS.ID", ondelete="CASCADE"), primary_key=True),
)


# 角色菜单关联表（用于控制角色可访问的菜单）
role_menus = Table(
    "RBAC_ROLE_MENUS",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("RBAC_ROLES.ID", ondelete="CASCADE"), primary_key=True),
    Column("menu_id", Integer, ForeignKey("RBAC_MENUS.ID", ondelete="CASCADE"), primary_key=True),
)


class RBACUser(Base):
    """
    RBAC用户表
    存储用户基本信息，与角色多对多关联
    """

    __tablename__ = "RBAC_USERS"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    USERNAME: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    PASSWORD_HASH: Mapped[str] = mapped_column(String(255), nullable=False)
    EMAIL: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    NICKNAME: Mapped[str] = mapped_column(String(255), nullable=True)
    AVATAR: Mapped[str] = mapped_column(String(512), nullable=True)

    # 用户状态: 1=启用, 0=禁用
    STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 最后登录信息
    LAST_LOGIN_AT: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    LAST_LOGIN_IP: Mapped[str] = mapped_column(String(64), nullable=True)

    # 时间戳
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 多对多关联
    roles = relationship("RBACRole", secondary=user_roles, back_populates="users")

    def __repr__(self):
        return f"<RBACUser(ID={self.ID}, USERNAME='{self.USERNAME}')>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.ID,
            "username": self.USERNAME,
            "email": self.EMAIL,
            "nickname": self.NICKNAME,
            "avatar": self.AVATAR,
            "status": self.STATUS,
            "last_login_at": self.LAST_LOGIN_AT.strftime("%Y-%m-%d %H:%M:%S")
            if self.LAST_LOGIN_AT is not None
            else None,
            "last_login_ip": self.LAST_LOGIN_IP,
            "created_at": self.CREATED_AT.strftime("%Y-%m-%d %H:%M:%S") if self.CREATED_AT is not None else None,
            "roles": [role.to_dict() for role in self.roles] if self.roles else [],
        }


class RBACRole(Base):
    """
    RBAC角色表
    定义系统中的角色，如管理员、普通用户等
    """

    __tablename__ = "RBAC_ROLES"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    ROLE_NAME: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    ROLE_CODE: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    DESCRIPTION: Mapped[str] = mapped_column(Text, nullable=True)

    # 角色级别: 数字越小级别越高
    ROLE_LEVEL: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # 状态: 1=启用, 0=禁用
    STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 时间戳
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 多对多关联
    users = relationship("RBACUser", secondary=user_roles, back_populates="roles")
    permissions = relationship("RBACPermission", secondary=role_permissions, back_populates="roles")
    menus = relationship("RBACMenu", secondary=role_menus, back_populates="roles")

    def __repr__(self):
        return f"<RBACRole(ID={self.ID}, ROLE_NAME='{self.ROLE_NAME}')>"

    def to_dict(self):
        """转换为字典"""
        is_superadmin = str(self.ROLE_CODE or "") == "superadmin"
        _perms = list(self.permissions) if self.permissions is not None else []
        _menus = list(self.menus) if self.menus is not None else []

        if is_superadmin and _perms:
            # 超级管理员返回全部权限
            perms = [p.to_dict() for p in _perms]
        elif _perms:
            perms = [p.to_dict() for p in _perms]
        else:
            perms = []

        if is_superadmin and _menus:
            # 超级管理员返回全部菜单
            menus = [m.to_dict() for m in _menus]
        elif _menus:
            menus = [m.to_dict() for m in _menus]
        else:
            menus = []

        return {
            "id": self.ID,
            "role_name": self.ROLE_NAME,
            "role_code": self.ROLE_CODE,
            "description": self.DESCRIPTION,
            "role_level": self.ROLE_LEVEL,
            "status": self.STATUS,
            "created_at": self.CREATED_AT.strftime("%Y-%m-%d %H:%M:%S") if self.CREATED_AT is not None else None,
            "permissions": perms,
            "menus": menus,
            "users_count": len(self.users) if self.users else 0,
        }


class RBACPermission(Base):
    """
    RBAC权限表
    定义系统中的权限点，如 user:create, menu:view 等
    """

    __tablename__ = "RBAC_PERMISSIONS"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    PERMISSION_NAME: Mapped[str] = mapped_column(String(255), nullable=False)
    PERMISSION_CODE: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    DESCRIPTION: Mapped[str] = mapped_column(Text, nullable=True)

    # 权限类型: menu=菜单权限, api=接口权限, action=操作权限
    PERMISSION_TYPE: Mapped[str] = mapped_column(String(64), default="api", nullable=False)

    # 所属模块
    MODULE: Mapped[str] = mapped_column(String(255), nullable=True)

    # 状态: 1=启用, 0=禁用
    STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 时间戳
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 多对多关联
    roles = relationship("RBACRole", secondary=role_permissions, back_populates="permissions")

    def __repr__(self):
        return f"<RBACPermission(ID={self.ID}, PERMISSION_CODE='{self.PERMISSION_CODE}')>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.ID,
            "permission_name": self.PERMISSION_NAME,
            "permission_code": self.PERMISSION_CODE,
            "description": self.DESCRIPTION,
            "permission_type": self.PERMISSION_TYPE,
            "module": self.MODULE,
            "status": self.STATUS,
            "created_at": self.CREATED_AT.strftime("%Y-%m-%d %H:%M:%S") if self.CREATED_AT is not None else None,
        }


class RBACMenu(Base):
    """
    RBAC菜单表
    定义系统中的菜单结构，支持多级菜单
    """

    __tablename__ = "RBAC_MENUS"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    MENU_NAME: Mapped[str] = mapped_column(String(255), nullable=False)
    MENU_CODE: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # 父菜单ID，为None表示顶级菜单
    PARENT_ID: Mapped[int] = mapped_column(Integer, ForeignKey("RBAC_MENUS.ID"), nullable=True, index=True)

    # 菜单路径/路由
    PATH: Mapped[str] = mapped_column(String(512), nullable=True)

    # 菜单图标
    ICON: Mapped[str] = mapped_column(String(512), nullable=True)

    # 组件路径（前端组件）
    COMPONENT: Mapped[str] = mapped_column(String(512), nullable=True)

    # 排序号
    SORT_ORDER: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 菜单级别: 1=一级菜单, 2=二级菜单, 3=三级菜单
    MENU_LEVEL: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 是否隐藏: 1=隐藏, 0=显示
    IS_HIDDEN: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 是否外链: 1=是, 0=否
    IS_EXTERNAL: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 外链链接
    EXTERNAL_LINK: Mapped[str] = mapped_column(String(512), nullable=True)

    # 状态: 1=启用, 0=禁用
    STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 权限标识（关联的权限code）
    PERMISSION_CODE: Mapped[str] = mapped_column(String(255), nullable=True)

    # Vben Admin 路由元数据扩展字段
    REDIRECT: Mapped[str] = mapped_column(String(512), nullable=True)
    KEEP_ALIVE: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    AFFIX_TAB: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    HIDE_IN_MENU: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    HIDE_IN_TAB: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    HIDE_IN_BREADCRUMB: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ACTIVE_ICON: Mapped[str] = mapped_column(String(512), nullable=True)
    BADGE: Mapped[str] = mapped_column(String(64), nullable=True)
    BADGE_TYPE: Mapped[str] = mapped_column(String(32), nullable=True)
    # 是否内置菜单（由 DEFAULT_MENUS 初始化）。0=用户自建/插件，1=内置。用户自建菜单不会在启动初始化时被清理
    IS_BUILTIN: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 时间戳
    CREATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    UPDATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # 自关联：子菜单
    children = relationship("RBACMenu", backref="parent", remote_side=[ID])

    # 多对多关联
    roles = relationship("RBACRole", secondary=role_menus, back_populates="menus")

    def __repr__(self):
        return f"<RBACMenu(ID={self.ID}, MENU_NAME='{self.MENU_NAME}')>"

    def to_dict(self):
        """转换为字典"""
        # 处理children，避免递归和类型错误
        children_list = []
        if object_session(self) is not None:
            try:
                if self.children:
                    # children可能是列表或单个对象
                    if isinstance(self.children, list):
                        children_list = [child.to_dict() for child in self.children]
                    else:
                        # 单个对象情况
                        children_list = [self.children.to_dict()]
            except (TypeError, AttributeError):
                children_list = []

        return {
            "id": self.ID,
            "menu_name": self.MENU_NAME,
            "menu_code": self.MENU_CODE,
            "parent_id": self.PARENT_ID,
            "path": self.PATH,
            "icon": self.ICON,
            "component": self.COMPONENT,
            "sort_order": self.SORT_ORDER,
            "menu_level": self.MENU_LEVEL,
            "is_hidden": self.IS_HIDDEN,
            "is_external": self.IS_EXTERNAL,
            "external_link": self.EXTERNAL_LINK,
            "status": self.STATUS,
            "permission_code": self.PERMISSION_CODE,
            "redirect": self.REDIRECT,
            "keep_alive": self.KEEP_ALIVE,
            "affix_tab": self.AFFIX_TAB,
            "hide_in_menu": self.HIDE_IN_MENU,
            "hide_in_tab": self.HIDE_IN_TAB,
            "hide_in_breadcrumb": self.HIDE_IN_BREADCRUMB,
            "active_icon": self.ACTIVE_ICON,
            "badge": self.BADGE,
            "badge_type": self.BADGE_TYPE,
            "created_at": self.CREATED_AT.strftime("%Y-%m-%d %H:%M:%S") if self.CREATED_AT is not None else None,
            "children": children_list,
        }

    def to_tree_dict(self):
        """转换为树形结构字典"""
        data = self.to_dict()
        # 避免递归过深，children不再展开
        data["children"] = None
        return data


class RBACUserLoginLog(Base):
    """
    用户登录日志表
    记录用户登录历史
    """

    __tablename__ = "RBAC_USER_LOGIN_LOGS"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    USER_ID: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("RBAC_USERS.ID", ondelete="CASCADE"), nullable=True, index=True
    )
    USERNAME: Mapped[str] = mapped_column(String(255), nullable=False)
    LOGIN_IP: Mapped[str] = mapped_column(String(64), nullable=True)
    LOGIN_LOCATION: Mapped[str] = mapped_column(String(255), nullable=True)
    USER_AGENT: Mapped[str] = mapped_column(Text, nullable=True)
    LOGIN_TYPE: Mapped[str] = mapped_column(String(64), default="password", nullable=False)  # password, token, oauth
    LOGIN_STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=成功, 0=失败
    FAIL_REASON: Mapped[str] = mapped_column(String(255), nullable=True)
    LOGIN_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f"<RBACUserLoginLog(ID={self.ID}, USERNAME='{self.USERNAME}')>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.ID,
            "user_id": self.USER_ID,
            "username": self.USERNAME,
            "login_ip": self.LOGIN_IP,
            "login_location": self.LOGIN_LOCATION,
            "login_type": self.LOGIN_TYPE,
            "login_status": self.LOGIN_STATUS,
            "fail_reason": self.FAIL_REASON,
            "login_at": self.LOGIN_AT.strftime("%Y-%m-%d %H:%M:%S") if self.LOGIN_AT is not None else None,
        }


class RBACOperationLog(Base):
    """
    操作日志表
    记录用户的重要操作
    """

    __tablename__ = "RBAC_OPERATION_LOGS"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    USER_ID: Mapped[int] = mapped_column(
        Integer, ForeignKey("RBAC_USERS.ID", ondelete="SET NULL"), nullable=True, index=True
    )
    USERNAME: Mapped[str] = mapped_column(String(255), nullable=True)

    # 操作模块
    MODULE: Mapped[str] = mapped_column(String(255), nullable=True)

    # 操作类型: CREATE, UPDATE, DELETE, QUERY, EXPORT, etc.
    OPERATION_TYPE: Mapped[str] = mapped_column(String(64), nullable=False)

    # 操作描述
    DESCRIPTION: Mapped[str] = mapped_column(Text, nullable=True)

    # 请求方法: GET, POST, PUT, DELETE
    REQUEST_METHOD: Mapped[str] = mapped_column(String(16), nullable=True)

    # 请求URL
    REQUEST_URL: Mapped[str] = mapped_column(String(512), nullable=True)

    # 请求参数
    REQUEST_PARAMS: Mapped[str] = mapped_column(Text, nullable=True)

    # 响应结果
    RESPONSE_DATA: Mapped[str] = mapped_column(Text, nullable=True)

    # 操作IP
    OPERATION_IP: Mapped[str] = mapped_column(String(64), nullable=True)

    # 执行时长(毫秒)
    EXECUTION_TIME: Mapped[int] = mapped_column(Integer, nullable=True)

    # 操作结果: 1=成功, 0=失败
    OPERATION_STATUS: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 错误信息
    ERROR_MSG: Mapped[str] = mapped_column(Text, nullable=True)

    # 操作时间
    OPERATED_AT: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f"<RBACOperationLog(ID={self.ID}, USERNAME='{self.USERNAME}')>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.ID,
            "user_id": self.USER_ID,
            "username": self.USERNAME,
            "module": self.MODULE,
            "operation_type": self.OPERATION_TYPE,
            "description": self.DESCRIPTION,
            "request_method": self.REQUEST_METHOD,
            "request_url": self.REQUEST_URL,
            "operation_ip": self.OPERATION_IP,
            "execution_time": self.EXECUTION_TIME,
            "operation_status": self.OPERATION_STATUS,
            "error_msg": self.ERROR_MSG,
            "operated_at": self.OPERATED_AT.strftime("%Y-%m-%d %H:%M:%S") if self.OPERATED_AT is not None else None,
        }
