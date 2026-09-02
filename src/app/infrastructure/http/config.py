"""HTTP 客户端配置."""

from dataclasses import dataclass, field

import httpx2


@dataclass
class BrowserModeConfig:
    """浏览器自动化模式配置."""

    enabled: bool = False
    server_url: str = ""
    session_key: str = "default"
    site_key: str = "default"
    fingerprint_profile: str = "stealth"
    fp_profile_id: str | None = None
    user_agent: str | None = None
    proxy_url: str | None = None
    navigate_timeout: int = 90
    auto_navigate_on_challenge: bool = True
    browser_fetch_on_challenge: bool = True
    render_html: bool = False
    # 持久会话：请求结束后保留浏览器会话（含挑战/2FA 通过后的认证态），供后续复用。
    # 默认 False（用完即删会话，实例由 nexus-chrome 空闲 TTL 保留复用）；
    # 需要长期保持认证态的站点（如 2FA 站点）显式开启。
    persistent_session: bool = False
    # nexus-chrome 认证凭证（API Key / 管理 token），AUTH_PASSWORD 启用时必配
    api_key: str | None = None


@dataclass
class HttpClientConfig:
    """HTTP 客户端配置."""

    # 连接池
    max_connections: int = 100
    max_keepalive: int = 20

    # 超时
    timeout: float = 120.0
    connect_timeout: float = 10.0

    # 行为
    follow_redirects: bool = True
    verify_ssl: bool = True
    enable_http2: bool = True  # AsyncHttpClient 默认启用

    # 代理
    proxy_url: str | None = None

    # 默认请求头
    default_headers: dict[str, str] | None = None

    # 认证（httpx2.Auth 子类）
    auth: httpx2.Auth | None = field(default=None, repr=False)

    # DNS 映射（主机名 → IP 地址），用于替代 /etc/hosts 修改
    host_mapping: dict[str, str] | None = None

    # 浏览器自动化模式（None 表示不启用）
    browser: BrowserModeConfig | None = None
