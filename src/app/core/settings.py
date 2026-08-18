"""
AppSettings - 基于 pydantic-settings 的应用配置
支持 .env 文件、环境变量和 config.yaml，优先级：环境变量 > .env > config.yaml
"""

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import ruamel.yaml
from filelock import FileLock
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.core.root_path import get_project_root


def _drop_scalar_overrides(settings_cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """剔除与嵌套模型字段同名的标量值（如环境变量 AGENT=1），防止其覆盖整个嵌套配置段"""
    for key in list(data.keys()):
        field_info = settings_cls.model_fields.get(key)
        if field_info is None:
            continue
        annotation = field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel) and not isinstance(data[key], dict):
            del data[key]
    return data


class _NestedSafeEnvSource(EnvSettingsSource):
    """env 源包装：标量同名环境变量不覆盖嵌套模型字段"""

    def __call__(self) -> dict[str, Any]:
        return _drop_scalar_overrides(self.settings_cls, super().__call__())


class _NestedSafeDotEnvSource(DotEnvSettingsSource):
    """dotenv 源包装：同上"""

    def __call__(self) -> dict[str, Any]:
        return _drop_scalar_overrides(self.settings_cls, super().__call__())


_PROJECT_ROOT = get_project_root()


def _load_dotenv(path: str | None = None) -> bool:
    """手动加载 .env 文件（早于 pydantic-settings，用于发现 NEXUS_MEDIA_CONFIG）。"""
    env_path = Path(path) if path else _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return False
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    return True


def _resolve_config_path() -> str:
    """解析运行时配置文件路径，按优先级：环境变量 > data/config.yaml > 有效默认值（从 config/ 模板复制）。"""
    candidate = os.environ.get("NEXUS_MEDIA_CONFIG", "")
    if candidate and os.path.exists(candidate):
        return candidate
    if candidate:
        os.makedirs(os.path.dirname(candidate), exist_ok=True)

    # 默认运行时配置路径：data/config.yaml（与静态模板分离）
    data_config = str(_PROJECT_ROOT / "data" / "config.yaml")
    if os.path.exists(data_config):
        return os.path.abspath(data_config)

    os.makedirs(os.path.dirname(data_config), exist_ok=True)
    template = str(_PROJECT_ROOT / "config" / "config.yaml.example")
    if os.path.exists(template):
        shutil.copy(template, data_config)
        print(f"[Config]已从模板创建配置文件：{data_config}")
    return os.path.abspath(data_config)


class AppConfig(BaseModel):
    """应用核心配置"""

    web_host: str = "::"
    web_port: int = 3000
    login_user: str = "admin"
    login_password: str = "password"
    ssl_cert: str = ""
    ssl_key: str = ""
    rmt_tmdbkey: str = ""
    rmt_match_mode: str = "normal"
    proxies: dict = Field(default_factory=lambda: {"https": None, "http": None})
    domain: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    )
    init_files: list[str] = Field(default_factory=list)
    # 默认分类配置是否已初始化（防止清空后重启被重新导入默认值）
    category_default_seeded: bool = False
    tmdb_domain: str = "api.themoviedb.org"
    debug: bool = False
    tmdb_image_url: str = ""
    enable_image_proxy: int = 1
    cookie_secure: bool = False


class MediaConfig(BaseModel):
    """媒体库配置（路径字段已迁移到数据库 CONFIGMEDIA 表）"""

    mediasync_interval: int = 8
    sync_transfer_interval: int = 60
    category: str = "default-category"
    min_filesize: int = 150
    filesize_cover: bool = True
    movie_name_format: str = "{title} ({year})/{title}-{part} ({year}) - {videoFormat}"
    tv_name_format: str = "{title} ({year})/Season {season}/{title}-{part} - {season_episode} - 第{episode}集"
    nfo_poster: bool = True
    refresh_mediaserver: bool = True
    ignored_paths: str = "Specials;Extras;Bonus.*;.*Scan;Menu.*;CDs"
    ignored_files: str = "SP\\d+"
    media_default_path: str = ""
    default_rmt_mode: str = "link"
    tmdb_language: str = "zh"
    episode_mapping_enabled: bool = True


class PtConfig(BaseModel):
    """站点搜索配置"""

    search_auto: bool = False
    search_no_result_rss: bool = False
    pt_check_interval: int = 3600
    search_rss_interval: int = 6
    download_order: str = "seeder"
    ptrefresh_date_cron: str = "22:36"


class SubscribeConfig(BaseModel):
    """订阅监控调度配置（ADR-007 统一配置）"""

    queue_interval: int = 300
    rss_interval: int = 1800
    search_interval: int = 6


class SecurityConfig(BaseModel):
    """安全配置"""

    jwt_secret: str = ""


class LaboratoryConfig(BaseModel):
    """实验室功能配置"""

    search_keyword: bool = False
    tmdb_cache_expire: bool = True
    use_douban_titles: bool = True
    search_en_title: bool = True
    show_more_sites: bool = True
    ocr_server_host: str = ""
    ocr_enabled: bool = True
    search_multi_language: bool = True
    chrome_enabled: bool = True
    chrome_server_host: str = ""
    # 浏览器自动化默认指纹画像：用户登录同步真实浏览器指纹后写入，
    # 全局后台流程（站点定时刷新 / RSS 自动化等无用户上下文场景）使用该指纹。
    chrome_fp_profile_id: str = ""
    # ADR-014 身份解析体系灰度开关
    identity_index: bool = False  # P1 别名索引（get_all_names 走索引）
    identity_resolver: bool = False  # P2 统一识别决策流（BatchIdentifier → IdentityResolver）
    target_matcher: bool = False  # P3 TargetMatcher 统一判等


class AgentProviderConfig(BaseModel):
    """Agent 提供商配置"""

    api_key: str = ""
    api_url: str = ""
    model: str = ""


class AgentEmbeddingConfig(BaseModel):
    """Embedding 配置（api_key/api_url 留空继承对应 provider）"""

    provider: str = ""
    model: str = ""
    api_key: str = ""
    api_url: str = ""
    proxy: str | None = None
    timeout: int = 60


class AgentStoreConfig(BaseModel):
    """向量库存储路径（留空/相对路径基于数据目录解析）"""

    path: str = ""


class AgentRagConfig(BaseModel):
    """RAG 检索参数"""

    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 6
    rerank_top_k: int = 3
    namespaces: list[str] = Field(default_factory=lambda: ["media_library", "messages", "faq", "operations"])


class AgentShortTermMemoryConfig(BaseModel):
    """短程记忆配置"""

    store: str = "db"
    max_tokens: int = 4000
    ttl_days: int = 30


class AgentLongTermMemoryConfig(BaseModel):
    """长程语义记忆配置（用户偏好/事实，向量库存储）"""

    enabled: bool = False
    top_k: int = 5
    extraction: str = "on_session_end"  # on_session_end | on_turn_end | off


class AgentMemoryConfig(BaseModel):
    """记忆配置"""

    max_steps: int = 8
    short_term: AgentShortTermMemoryConfig = Field(default_factory=AgentShortTermMemoryConfig)
    long_term: AgentLongTermMemoryConfig = Field(default_factory=AgentLongTermMemoryConfig)


class AgentNotifyConfig(BaseModel):
    """Agent 通知增强配置（通知发送出口按 msg_type 单流替换模板）"""

    enabled: bool = False
    msg_types: list[str] = Field(
        default_factory=lambda: [
            "download_start",
            "download_fail",
            "rss_finished",
            "transfer_finished",
            "transfer_fail",
            "site_signin",
        ]
    )
    temperature: float = 0.3


class AgentConfig(BaseModel):
    """Agent 配置"""

    enabled: bool = False
    default_provider: str = ""
    media_recognizer_enabled: bool = False
    batch_size: int = 100
    reasoning_effort: str = "high"  # low | high | max（统一作用于所有 Agent LLM 调用）
    disable_thinking: bool = False  # true = 关闭思考模式
    providers: dict[str, AgentProviderConfig] = Field(default_factory=dict)
    fallback: list[str] = Field(default_factory=list)
    embedding: AgentEmbeddingConfig = Field(default_factory=AgentEmbeddingConfig)
    vector_store: str = "sqlite"
    sqlite: AgentStoreConfig = Field(default_factory=AgentStoreConfig)
    lancedb: AgentStoreConfig = Field(default_factory=AgentStoreConfig)
    rag: AgentRagConfig = Field(default_factory=AgentRagConfig)
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    notify: AgentNotifyConfig = Field(default_factory=AgentNotifyConfig)


class DatabaseConfig(BaseModel):
    """数据库配置"""

    type: str = "sqlite"
    host: str = "localhost"
    port: int = 0
    username: str = ""
    password: str = ""
    database: str = "nexus_media"


class RedisConfig(BaseModel):
    """Redis 缓存配置"""

    host: str = "127.0.0.1"
    port: int = 6379
    password: str = ""
    db: int = 0


class LogConfig(BaseModel):
    """日志配置"""

    type: str = "file"
    level: str = "debug"
    format: str = "text"
    path: str = ""


def _filter_none(data: dict[str, Any]) -> dict[str, Any]:
    """递归移除 YAML 中的 None 值（ruamel.yaml 将空值解析为 None）。"""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, dict):
            result[k] = _filter_none(v)
        else:
            result[k] = v
    return result


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """从 config.yaml 加载配置的自定义 SettingsSource"""

    def get_field_value(self, field, field_name: str) -> tuple[Any, str, bool]:
        yaml_data = self._load_yaml()
        value = yaml_data.get(field_name)
        if value is not None:
            return value, field_name, False
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        yaml_data = self._load_yaml()
        result: dict[str, Any] = {}
        for field_name in self.settings_cls.model_fields:
            if field_name in yaml_data:
                result[field_name] = yaml_data[field_name]
        return result

    @staticmethod
    def _load_yaml() -> dict[str, Any]:
        config_path = os.environ.get("NEXUS_MEDIA_CONFIG", "")
        if not config_path or not os.path.exists(config_path):
            return {}
        try:
            with open(config_path, encoding="utf-8") as f:
                data = ruamel.yaml.YAML().load(f) or {}
            return _filter_none(data)
        except Exception:
            return {}


class AppSettings(BaseSettings):
    """
    Nexus Media 统一配置（pydantic-settings）
    支持环境变量、.env 文件和 config.yaml，优先级：环境变量 > .env > config.yaml
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    nexus_media_config: str = ""
    nexus_media_data: str = ""
    tz: str = "Asia/Shanghai"

    app: AppConfig = Field(default_factory=AppConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    pt: PtConfig = Field(default_factory=PtConfig)
    subscribe: SubscribeConfig = Field(default_factory=SubscribeConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    laboratory: LaboratoryConfig = Field(default_factory=LaboratoryConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig, validate_default=True)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)

    @field_validator("agent", mode="before")
    @classmethod
    def _validate_agent(cls, v):
        if not isinstance(v, dict):
            return AgentConfig()
        return v

    log: LogConfig = Field(default_factory=LogConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _NestedSafeEnvSource(settings_cls),
            _NestedSafeDotEnvSource(settings_cls),
            YamlConfigSettingsSource(settings_cls),
        )

    def get(self, node: str | None = None) -> Any:
        """读取配置节点；node=None 时返回全部字典"""
        data = self.model_dump(exclude={"nexus_media_config", "tz"}, exclude_none=False)
        if not node:
            return data
        return data.get(node, {})

    def save(self, new_cfg: dict[str, Any]) -> None:
        """保存完整配置到 YAML 文件"""
        yaml = ruamel.yaml.YAML()
        try:
            yaml.dump(new_cfg, io.StringIO())
        except Exception as e:
            raise ValueError(f"Invalid YAML data: {e}") from e

        config_path = self._config_path()
        lock_path = config_path + ".lock"
        with FileLock(lock_path):
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as temp_file:
                yaml.dump(new_cfg, temp_file)
                temp_path = temp_file.name
            shutil.move(temp_path, config_path)

    def reload(self) -> None:
        """重新从 YAML 文件加载配置"""
        new = AppSettings()
        for key in self.model_fields:
            setattr(self, key, getattr(new, key))

    def get_database_config(self) -> dict[str, Any]:
        """获取数据库配置字典"""
        config: dict[str, Any] = {}
        if self.database.type:
            config["type"] = self.database.type
        if self.database.host:
            config["host"] = self.database.host
        if self.database.port:
            config["port"] = self.database.port
        if self.database.username:
            config["username"] = self.database.username
        if self.database.password:
            config["password"] = self.database.password
        if self.database.database:
            config["database"] = self.database.database
        return config

    def _config_path(self) -> str:
        return self.nexus_media_config or os.environ.get("NEXUS_MEDIA_CONFIG", "")

    @property
    def config_path(self) -> str:
        path = self._config_path()
        if not path:
            path = _resolve_config_path()
        dirname = os.path.dirname(path)
        return dirname or "."

    @property
    def data_path(self) -> str:
        path = self.nexus_media_data or os.environ.get("NEXUS_MEDIA_DATA", "")
        if path:
            abs_path = os.path.abspath(path)
            os.makedirs(abs_path, exist_ok=True)
            return abs_path
        data_dir = str(_PROJECT_ROOT / "data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir


def _init_config_file() -> str:
    config_path = _resolve_config_path()
    os.environ.setdefault("NEXUS_MEDIA_CONFIG", config_path)
    return config_path


def _apply_env_database_config(settings: AppSettings) -> None:
    env_db_keys = [k for k in os.environ if k.upper().startswith("DATABASE__")]
    if not env_db_keys:
        return
    env_db = settings.database.model_dump()
    full = settings.get()
    full["database"] = env_db
    try:
        settings.save(full)
        print("[Config]已从环境变量更新数据库配置到配置文件")
    except Exception as e:
        print(f"[Config]保存数据库配置到文件失败：{e!s}")


_load_dotenv()

_config_path = _init_config_file()

tz = os.environ.get("TZ", "Asia/Shanghai")
if not os.environ.get("TZ"):
    os.environ["TZ"] = tz

settings = AppSettings()

print(f"正在加载配置：{_config_path}")
_apply_env_database_config(settings)
