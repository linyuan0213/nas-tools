# Nexus Media 后端架构文档

> 本文档描述 Nexus Media 后端（`backend/`）的整体架构、模块分层、数据流和关键设计模式。
>
> 技术栈：Python 3.11+ + FastAPI + SQLAlchemy + Alembic + APScheduler

## 0. 架构图（交互式，浏览器打开）

> 图为 Archify 交付物（`.html`），支持主题切换 / 聚焦视图 / 导出；依据与代码映射见 [architecture-evidence.md](./architecture-evidence.md)。

| 文件 | 类型 | 说明 |
|---|---|---|
| [architecture.html](./architecture.html) | 完整架构大图 | 接入 → API/装配 → 应用服务 → 外部/消息 → 基础设施；3 个视图 |
| [architecture-brush-flow.html](./architecture-brush-flow.html) | 数据流 | 刷流/订阅：RSS→匹配→下载→做种保种/识别入库双泳道 |
| [architecture-scrape.html](./architecture-scrape.html) | 数据流 | 识别后刮削队列：NFO/海报/FFmpeg→写库→完成通知 |
| [architecture-brush-lifecycle.html](./architecture-brush-lifecycle.html) | 生命周期 | 刷流任务 停止⇄运行 状态流转 |
| [architecture-agent.html](./architecture-agent.html) | 架构 | AI 助手多步工具循环（providers/工具/记忆/SSE） |
| [architecture-msg.html](./architecture-msg.html) | 架构 | 消息通知中心 + 插件框架（含 msg_* 渠道） |
| [architecture-sites.html](./architecture-sites.html) | 架构 | 站点检索与 nexus-chrome 降级 |

每个 `.json` 为对应图的可校验规格（`archify validate --quality standard` 通过），`.html` 为交付产物。

---

## 1. 顶层目录结构

```
backend/
├── src/                    # 源代码（PEP 517/518 src layout）
│   ├── api/                # FastAPI 入口与路由层
│   │   ├── main.py         # FastAPI 应用实例 + lifespan 生命周期
│   │   └── routers/        # 按领域拆分的 API 路由
│   ├── app/                # 核心业务层
│   │   ├── agent/          # AI Agent 相关
│   │   ├── core/           # 核心配置、常量
│   │   ├── db/             # 数据库模型、仓库、连接工厂
│   │   ├── domain/         # 领域层（实体 + 接口 + 引擎）
│   │   ├── downloader/     # 下载器客户端抽象
│   │   ├── helper/         # 辅助工具类
│   │   ├── indexer/        # 索引器客户端
│   │   ├── infrastructure/ # 基础设施（缓存、事件总线）
│   │   ├── media/          # 媒体处理（识别、查询、刮削）
│   │   ├── mediaserver/    # 媒体服务器客户端（Emby/Jellyfin/Plex）
│   │   ├── message/        # 消息通知客户端
│   │   ├── plugin_framework/ # 插件框架
│   │   ├── services/       # 业务服务层
│   │   ├── sites/          # 站点引擎与管理
│   │   ├── storage/        # 存储后端抽象
│   │   └── utils/          # 通用工具、类型定义
│   ├── log/                # 日志模块（loguru）
│   ├── version.py          # 版本（从 pyproject.toml 动态读取）
│   └── initializer.py      # 启动初始化逻辑
├── tests/                  # 测试
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   └── conftest.py
├── config/                 # 站点 JSON 定义、配置模板
│   └── config.yaml.example # 提交到 git 的配置模板
├── alembic/                # Alembic 迁移目录
│   ├── env.py
│   └── versions/
├── static/                 # 静态文件
├── scripts/                # 工具脚本
├── docker/                 # Docker 构建文件
├── justfile                # 任务运行器
├── run.py                  # 启动入口（uvicorn）
├── gunicorn.conf.py        # Gunicorn 生产配置
└── pyproject.toml
```

### `app/` 子目录职责

| 目录 | 职责 |
|------|------|
| `api/routers/` | FastAPI HTTP 路由层，负责请求校验、权限检查、调用 Service |
| `app/services/` | 业务服务层，编排领域逻辑、调用 Repository 或外部客户端 |
| `app/domain/` | 领域层：定义实体（Entity）、仓库接口（Interface）、领域引擎（Engine） |
| `app/db/` | 数据访问层：SQLAlchemy ORM 模型、Repository 实现、数据库工厂 |
| `app/schemas/` | Pydantic 模型：请求/响应 DTO、数据校验 |
| `app/media/` | 媒体处理：文件名解析、TMDB/豆瓣/Bangumi 查询、元数据刮削 |
| `app/sites/` | 站点引擎：声明式 JSON 站点定义、搜索、下载、用户信息抓取 |
| `app/plugin_framework/` | 插件框架：注册表、钩子系统、沙箱、内置插件 |
| `app/infrastructure/` | 基础设施：统一缓存系统（内存/Redis/分层）、事件总线 |
| `app/downloader/` | 下载器抽象：qBittorrent、Transmission 等客户端封装 |
| `app/mediaserver/` | 媒体服务器抽象：Emby、Jellyfin、Plex 客户端封装 |
| `app/message/` | 消息通知抽象：微信、Telegram、Slack 等客户端封装 |
| `app/indexer/` | 索引器抽象：内置站点、Jackett、Prowlarr 等 |
| `app/storage/` | 存储后端抽象：本地、SMB、对象存储等 |

---

## 2. API 路由层与业务服务层的关系

### `api/routers/` 包含的路由模块

```
api/routers/
├── __init__.py
├── apikey.py
├── auth.py
├── brush.py
├── download.py
├── filter.py
├── image.py
├── media.py
├── message_webhook.py
├── plugin_framework.py
├── rbac.py
├── rss.py
├── scheduler.py
├── site.py
├── storage_backend.py
├── sync.py
├── system.py
├── userrss.py
└── words.py
```

每个路由模块对应一个业务领域，例如 `site.py` 处理站点 CRUD、`download.py` 处理下载任务、`media.py` 处理媒体库查询。

### 依赖注入模式

路由层通过不可变应用上下文（`src/app/di/context.py`）获取依赖。
对象图由分模块 Builder（`src/app/di/builders/`）按拓扑顺序组装，
lifespan 将 `AppContext` 挂载到 `app.state.context`。

```python
from api.deps import get_app_context
from app.di.context import AppContext

@router.get("/")
def list_items(app_context: AppContext = Depends(get_app_context)):
    return app_context.some_service.do_work()
```

`AppContext` 是运行时对象图的唯一持有者，替代了早期的手写 Registry。
Service 内部禁止访问全局上下文，所有依赖必须通过构造函数显式注入。

### 与旧 Flask 控制器的关系

Flask 已完全移除，统一使用 FastAPI。`api/deps.py` 提供兼容的重导出。

---

## 3. 领域层 (`app/domain/`)

领域层采用 **Entity + Interface + Engine** 三层结构：

```
app/domain/
├── __init__.py
├── entities/           # 纯数据实体（Pydantic-like dataclass）
│   ├── apikey.py
│   ├── brush.py
│   ├── config.py
│   ├── download.py
│   ├── plugin.py
│   ├── rss.py
│   ├── rss_torrent.py
│   ├── site.py
│   ├── storage_backend.py
│   ├── sync.py
│   ├── system_dict.py
│   ├── transfer.py
│   ├── transfer_task.py
│   └── word.py
├── interfaces/         # 仓库接口（抽象基类）
│   ├── apikey_repo.py
│   ├── brush_repo.py
│   ├── config_repo.py
│   ├── download_repo.py
│   ├── plugin_repo.py
│   ├── rbac_repo.py
│   ├── rss_repo.py
│   ├── rss_torrent_repo.py
│   ├── search_repo.py
│   ├── site_repo.py
│   ├── storage_backend_repo.py
│   ├── sync_repo.py
│   ├── system_dict_repo.py
│   ├── transfer_repo.py
│   └── word_repo.py
└── engine/
    └── brush_rule_engine.py   # 刷流规则引擎（纯领域逻辑）
```

### 设计意图

- **Entity**：脱离 ORM 的纯数据结构，可在层间传递，避免直接暴露数据库模型
- **Interface**：定义仓库契约，`app/db/repositories/` 中的实现类遵循这些接口
- **Engine**：放置无状态、纯内存的领域算法（如刷流规则匹配引擎）

> 注意：由于项目处于渐进式重构中，并非所有模块都严格遵循 Domain-Driven Design。部分旧代码直接在 Service 中操作 ORM 模型。

---

## 4. 数据访问层 (`app/db/`)

### 4.1 数据库模型 (`app/db/models/`)

所有 ORM 模型基于单一的 `Base = declarative_base()`（`BaseMedia` 也指向同一基类，用于兼容旧双数据库设计）。

按业务域拆分的模型文件：

| 模型文件 | 对应业务域 |
|---------|-----------|
| `apikey.py` | API Key 管理 (`APIKEY`, `APIKEYLOG`) |
| `brush.py` | 刷流规则与任务 (`SITEBRUSHRULE`, `SITEBRUSHTASK`, `SITEBRUSHTORRENTS`) |
| `config.py` | 配置与媒体服务器 (`CONFIGSITE`, `CONFIGUSERS`, `MEDIASERVER` 等) |
| `download.py` | 下载器与历史 (`DOWNLOADER`, `DOWNLOADHISTORY`) |
| `indexer.py` | 索引器统计 (`INDEXERSTATISTICS`) |
| `media_sync.py` | 媒体同步 (`MEDIASYNCITEMS`, `MEDIASYNCSTATISTIC`) |
| `message.py` | 消息客户端 (`MESSAGECLIENT`) |
| `plugin.py` | 插件与黑名单 (`PLUGINMANIFEST`, `PLUGINCONFIG`, `TMDBBLACKLIST` 等) |
| `rbac.py` | RBAC 权限 (`RBACUser`, `RBACRole`, `RBACPermission`, `RBACMenu` 等) |
| `rss.py` | RSS 订阅与历史 (`RSSTVS`, `RSSMOVIES`, `RSSHISTORY` 等) |
| `search.py` | 搜索结果 (`SEARCHRESULTINFO`) |
| `site.py` | 站点统计 (`SITEUSERINFOSTATS`, `SITESTATISTICSHISTORY`) |
| `storage_backend.py` | 存储后端 (`STORAGEBACKEND`) |
| `sync.py` | 同步历史 (`SYNCHISTORY`) |
| `system.py` | 系统字典 (`SYSTEMDICT`) |
| `transfer.py` | 转移历史与黑名单 (`TRANSFERHISTORY`, `TRANSFERUNKNOWN`) |
| `word.py` | 自定义识别词 (`CUSTOMWORDS`, `CUSTOMWORDGROUPS`) |

### 4.2 仓库层 (`app/db/repositories/`)

```
app/db/repositories/
├── base_repository.py          # 基类：提供 query/insert/commit/transactional
├── <name>_repository.py        # 具体仓库（ORM 操作）
├── <name>_repo_adapter.py      # 适配器（将 ORM 模型转换为 Domain Entity）
└── __init__.py                 # 统一导出
```

**BaseRepository** 提供通用数据库操作：
- `query()` / `insert()` / `delete()` / `commit()` / `rollback()` / `flush()`
- `execute()` - 执行 SQL（自动适配不同数据库方言）
- `bulk_insert()` / `bulk_insert_mappings()` - 批量插入
- `transactional()` - 事务上下文管理器（推荐新代码使用）
- `_paginate()` / `_build_like_pattern()` / `exists()` / `count()`

**适配器模式**：`SiteRepositoryAdapter`、`PluginConfigRepositoryAdapter` 等将 ORM 查询结果转换为 `app/domain/entities/` 中的纯数据实体，实现数据库层与业务层的解耦。

### 4.3 数据库连接工厂 (`app/db/database_factory.py`)

`DatabaseFactory` 支持三种数据库：
- **SQLite**（默认）：`sqlite:///<path>?check_same_thread=False`，启用 WAL 模式
- **MySQL**：`mysql+pymysql://...`
- **PostgreSQL**：`postgresql+psycopg2://...`

配置优先级：**环境变量** > `.env` > `data/config.yaml`（可选）。
`NEXUS_MEDIA_CONFIG` 已降级为可选，未设置时自动发现 `./data/config.yaml` 或 `/data/config.yaml`。
首次启动时自动从模板 `config/config.yaml.example` 创建配置文件。

`DatabaseDialect` 类处理跨数据库 SQL 差异（日期函数、LIMIT、字符串连接、随机函数等）。

### 4.4 Session 管理 (`app/db/main_db.py`)

```
SessionManager          # 管理 scoped_session 生命周期
    ├── session_scope() # 上下文管理器（自动 commit/rollback/close）
    ├── query()         # 兼容旧 API
    ├── execute()       # 执行 SQL
    └── ...

Database                # 数据库单例（引擎管理）
    ├── engine
    └── session_manager

MainDb = SessionManager # 向后兼容别名
```

**关键机制**：`scoped_session` 保证同一线程内共享同一个 Session，请求结束后必须调用 `remove_session()` 清理线程本地存储。FastAPI 中通过中间件 `db_session_cleanup` 在每个请求结束后自动执行。

---

## 5. 插件系统 (`app/plugin_framework/`)

插件框架 v2 是一个完整的插件运行时环境：

```
app/plugin_framework/
├── __init__.py              # 导出 PluginRegistry, HookSystem
├── registry.py              # 插件注册表：扫描、安装、启用/禁用
├── hook_system.py           # 全局事件钩子系统
├── sandbox.py               # 插件沙箱：动态加载、热重载
├── context.py               # 插件运行时上下文
├── dependency_manager.py    # 插件依赖管理
├── event_compat.py          # 兼容旧事件系统
└── builtin_plugins/         # 内置插件
    ├── autosignin/          # 自动签到
    ├── autogenrss/          # 自动 RSS 生成
    ├── doubansync/          # 豆瓣同步
    ├── iyuuautoseed/        # IYUU 自动辅种
    ├── libraryscraper/      # 库刮削
    └── ...
```

### 核心组件交互

```
PluginRegistry (单例)
    ├── 扫描 builtin_plugins/ 和 config/plugins/
    ├── 管理 manifest.json（元数据缓存）
    ├── 数据库持久化（PLUGINMANIFEST 表）
    └── 提供 install / enable / disable / uninstall / get_config

HookSystem (单例)
    ├── 预定义 50+ 系统事件（media.scraped, download.completed, site.signed_in 等）
    ├── 插件通过 register(event, plugin_id) 订阅事件
    ├── emit(event, data) 触发事件 → 调用所有订阅插件
    └── 持久化到 PLUGINHOOKS 表

PluginSandbox (单例)
    ├── load(plugin_id)      # 动态 importlib 加载模块，实例化插件类
    ├── unload(plugin_id)    # 调用 on_disable，清理 sys.modules
    ├── reload(plugin_id)    # 热重载（清理缓存 → 重新加载）
    ├── call(plugin_id, method, *args)   # 调用插件方法
    └── call_hook(plugin_id, event, data) # 调用 on_hook 处理器

PluginContext (每个插件实例一个)
    ├── get_config() / set_config()     # 通过 RepositoryAdapter 读写数据库
    ├── log_info() / log_warn() / log_error()  # 同时写文件日志和 PLUGINLOGS 表
    ├── notify()                        # 发送消息通知
    ├── schedule_cron() / schedule_interval()  # 注册定时任务（SchedulerCore）
    ├── emit()                          # 触发全局事件
    └── register_message_command()      # 注册消息命令
```

### 插件数据流

1. 系统事件触发（如下载完成）
2. `HookSystem.emit("download.completed", data)`
3. 遍历该事件的订阅插件
4. `PluginSandbox.call_hook(plugin_id, event, data)`
5. 调用插件实例的 `on_hook(event, data)` 方法
6. 插件通过 `PluginContext` 访问系统能力（配置、日志、通知、定时任务）

---

## 6. 缓存系统 (`app/infrastructure/cache_system/`)

统一缓存框架，支持多后端、命名空间隔离、事件驱动、自动预热。

```
app/infrastructure/cache_system/
├── cache_manager.py    # 统一缓存管理器（单例）
├── adapters.py         # MemoryCacheAdapter, RedisCacheAdapter, TieredCacheAdapter
├── base.py             # CacheAdapter 抽象基类, CacheEntry
├── caches.py           # 专用缓存类（TMDBCache, MediaInfoCache 等）
├── decorators.py       # @cached, @cached_with_lock, @lru_cache_with_ttl
├── events.py           # 缓存事件总线（GET/HIT/MISS/SET/DELETE/EVICT/EXPIRE/CLEAR）
├── warmer.py           # 缓存预热器（ConfigCacheWarmer, SiteCacheWarmer 等）
└── compat.py           # 兼容旧接口 cacheman
```

### 缓存适配器架构

```
CacheManager (单例)
    ├── register(name, adapter)
    ├── create_memory_cache(name, maxsize, ttl)
    ├── create_redis_cache(name, ttl)
    ├── create_tiered_cache(name, memory_maxsize, ttl)
    ├── get(name) → CacheAdapter
    └── cache_get/cache_set/cache_delete/cache_clear(name, key)

MemoryCacheAdapter
    ├── OrderedDict + threading.RLock（线程安全 LRU）
    ├── 支持 TTL 过期
    └── 命中/未命中统计

RedisCacheAdapter
    ├── 基于 app.utils.redis_store.RedisStore
    ├── Redis 不可用时自动回退到 MemoryCacheAdapter（fallback）
    ├── 使用 pickle 序列化值
    └── 自动重连机制

TieredCacheAdapter (L1 + L2)
    ├── L1: MemoryCacheAdapter（高速）
    ├── L2: RedisCacheAdapter（持久化）
    └── 读取时 L1 miss → L2 hit → 回填 L1
```

### 专用缓存实例（模块级单例）

在 `__init__.py` 中预创建：

```python
MediaInfoCache      # 媒体信息缓存（内存，maxsize=1000）
SearchResultCache   # 搜索结果缓存（内存，maxsize=500）
SiteInfoCache       # 站点信息缓存（内存，maxsize=100）
TokenCache          # 认证 Token 缓存（内存，maxsize=512）
ConfigLoadCache     # 配置加载防抖（内存，maxsize=1）
CategoryLoadCache   # 分类加载防抖（内存，maxsize=2）
OpenAISessionCache  # OpenAI 会话缓存（Tiered：L1 内存 + L2 Redis）
TMDBCache           # TMDB API 响应缓存（Redis）
```

---

## 7. 站点引擎 (`app/sites/`)

站点引擎是 Nexus Media 的核心差异化能力，通过 **声明式 JSON 站点定义** 消除散落在代码中的 `"if m-team in url"` 硬编码逻辑。

```
app/sites/
├── engine.py              # SiteEngine：统一站点定义加载与功能入口
├── sites.py               # Sites：旧版站点管理（CRUD、限速、连通性测试）
├── siteconf.py            # 站点配置解析
├── site_cookie.py         # Cookie 管理
├── site_limiter.py        # 站点请求限速器
├── site_subtitle.py       # 字幕下载
├── site_userinfo.py       # 站点用户信息统一接口
├── searcher_factory.py    # 搜索器工厂
├── html_searcher.py       # HTML 站点搜索实现
├── api_searcher.py        # API 站点搜索实现
├── engine_tools.py        # 引擎工具（endpoint 调用、header 构建、认证）
├── engine_download.py     # 下载链接解析
├── engine_connection.py   # 连接测试
├── engine_user_info.py    # 用户信息预取
└── siteuserinfo/          # 各站点框架的用户信息解析器
    ├── __init__.py
    ├── config_api.py      # API 站点用户信息工厂
    ├── config_html.py     # HTML 站点用户信息工厂
    ├── nexus_php.py
    ├── discuz.py
    ├── gazelle.py
    ├── unit3d.py
    └── ...
```

### SiteEngine 架构

`SiteEngine` 从 `config/sites/` 加载声明式 JSON 定义（分为 `api/` 和 `html/` 两个子目录）：

```json
{
  "id": "m-team",
  "name": "M-Team",
  "domain": "api.m-team.io",
  "api": {
    "base_url": "https://api.m-team.io",
    "auth": { "type": "bearer" },
    "endpoints": {
      "search": { "path": "/api/torrent/search", "method": "POST" },
      "test_connection": { ... }
    }
  },
  "download": {
    "type": "api",
    "path": "/api/torrent/genDlToken",
    "method": "POST"
  },
  "subtitle": { ... },
  "user_info": { ... }
}
```

**核心方法**：
- `get_by_id(id)` / `get_by_url(url)` - 查找站点定义
- `test_connection(url, user_config)` - 统一连接测试
- `resolve_download_url(page_url, user_config)` - 解析下载链接
- `resolve_torrent_attr(torrent_url, ...)` - 获取种子属性（FREE/2xFREE/HR/做种数）
- `resolve_subtitle(page_url, torrent_id, subtitle_dir)` - 字幕下载
- `get_user_info(...)` - 站点用户信息（通过工厂模式适配不同站点框架）

### 数据流：站点搜索

```
api/routers/site.py
    → SiteService.list_site_resources()
        → IndexerService.list_resources()
            → SiteEngine.get_by_url(url) 获取站点定义
            → 根据定义类型选择：
                - API 站点 → api_searcher.search()
                - HTML 站点 → html_searcher.search()
            → 返回结构化搜索结果
```

---

## 8. 媒体处理流程 (`app/media/`)

媒体处理模块采用 **Parser + Lookup + Scraper** 解耦架构：

```
app/media/
├── __init__.py            # 统一导出 MediaService, MediaCache, MediaInfo 等
├── service.py             # MediaService：文件名识别门面
├── factory.py             # get_media_service() / get_media_cache() 单例工厂
├── models.py              # MediaInfo：核心数据模型
├── category.py            # 二级分类策略
├── fanart.py              # Fanart.tv 图片获取
│
├── parser/                # 文件名解析层
│   ├── base.py            # BaseParser 接口
│   ├── regex.py           # RegexParser：正则解析（默认）
│   ├── llm.py             # LLMParser：AI 解析（可选）
│   ├── anitopy_adapter.py # Anitopy 动漫解析适配器
│   ├── token_adapter.py   # Token 分词适配器
│   ├── episode_mapper.py  # 集数映射（动漫绝对集号 → TMDB 季/集）
│   ├── _metainfo.py       # 兼容旧接口
│   ├── _video.py          # 视频元信息解析
│   ├── _anime.py          # 动漫元信息解析
│   ├── _customization.py  # 自定义匹配
│   ├── _release_groups.py # 发布组识别
│   ├── video/             # 视频解析子模块
│   │   ├── name_parser.py
│   │   ├── season_episode_parser.py
│   │   ├── resource_parser.py
│   │   └── encode_parser.py
│   └── anime/             # 动漫解析子模块
│       ├── name_parser.py
│       ├── season_episode_parser.py
│       └── resource_parser.py
│
├── lookup/                # 外部数据库查询层
│   ├── base.py            # BaseLookup 接口
│   ├── tmdb_lookup.py     # TMDB 查询（主）
│   ├── tmdb_client.py     # TMDB API 客户端封装
│   ├── tmdb_search.py     # TMDB 搜索
│   ├── tmdb_detail.py     # TMDB 详情
│   ├── tmdb_discover.py   # TMDB 发现/推荐
│   ├── tmdb_person.py     # TMDB 影人
│   ├── tmdb_season.py     # TMDB 季信息
│   ├── douban.py          # 豆瓣查询
│   └── bangumi.py         # Bangumi 查询
│
├── scraper/               # 元数据刮削层
│   ├── __init__.py
│   ├── nfo_generator.py   # NFO 文件生成
│   ├── image_downloader.py # 海报/背景图下载
│   ├── media_library.py   # 媒体库刮削流程
│   └── chinese_credits.py # 中文演职员表
│
├── external/              # 第三方 API 客户端
│   ├── __init__.py
│   ├── douban.py          # 豆瓣 API 客户端
│   └── bangumi.py         # Bangumi API 客户端
│
├── cache/                 # 媒体缓存层
│   ├── __init__.py
│   └── media_cache.py     # MediaCache：已知 tmdb_id 查详情
│
└── batch/                 # 批量处理
    ├── __init__.py
    └── processor.py       # BatchProcessor
```

### 媒体识别数据流

```
输入：文件名（如 "The.Matrix.1999.2160p.UHD.BluRay.x265.mkv"）

1. Parser 层
   → RegexParser.parse(title)              # 默认正则解析
   → 失败则 fallback 到 LLMParser.parse()   # AI 解析兜底
   → 输出：ParserResult {title_en, year, type, season, episode, ...}

2. Lookup 层
   → TmdbLookup.lookup(parsed)             # TMDB API 查询
   → 失败则 fallback：
      - search_tmdbweb()                   # 网页抓取
      - search_engine()                    # 搜索引擎辅助
   → 输出：LookupResult {tmdb_id, title, overview, poster_path, ...}

3. 组装
   → MediaInfo.from_parser(parsed)         # 基础信息
   → 补充 TMDB 详情（genre_ids → 修正 type）
   → EpisodeMapper.map_auto()              # 动漫集数映射（如启用）

4. 缓存
   → TMDBCache / MediaInfoCache.set()      # 写入缓存

输出：MediaInfo 对象（包含完整媒体元数据）
```

### 批量识别优化

`identify_batch()` 实现并发优化：
1. 批量 Parser 解析所有文件名
2. 按 `(title, year, type)` 去重
3. `ThreadPoolExecutor(max_workers=8)` 并发查询 TMDB
4. 结果映射回原始列表
5. 批量 EpisodeMapper 映射

---

## 9. 单例模式

项目广泛使用单例模式管理有状态组件。实现方式有两种：

### 方式一：SingletonMeta（推荐）

```python
# app/utils/commons.py
class SingletonMeta(type):
    _instances = {}
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
```

使用此元类的关键组件：
- `PluginRegistry`
- `HookSystem`
- `PluginSandbox`
- `SystemConfig`
- `Config`（旧版配置单例）
- `Category`
- `Message`
- `MediaServer`
- `Downloader` 各客户端

### 方式二：手动 __new__（CacheManager、Database 等）

```python
class CacheManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *_args, **_kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
```

### 方式三：类变量 + get_instance()

```python
class SiteEngine:
    _engine_instance = None

    @classmethod
    def get_instance(cls, definitions_dir=None):
        if cls._engine_instance is None:
            cls._engine_instance = cls(definitions_dir)
        return cls._engine_instance
```

---

## 10. 启动流程

### 10.1 进程启动（`run.py`）

```
run.py
    └── uvicorn.run(app, host, port, ...)
        └── api/main.py:app
```

### 10.2 FastAPI 生命周期（`src/api/main.py::lifespan`）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化数据库表结构（create_all，不执行迁移）
    init_db()

    # 2. 初始化站点配置
    SiteConfigUpdater().ensure_local_sites(...)
    update_site_config_at_startup()

    # 3. 启动后台服务
    SystemLifecycleService().start_service()

    # 4-6. 注册内置客户端 + 加载插件 + 初始化消息
    init_indexers()
    init_downloaders()
    init_mediaservers()
    init_message_clients()
    PluginSandbox().load_all()
    _ = Message().active_clients
    Message().refresh_menus()

    yield

    # 7. 关闭
    SystemLifecycleService().stop_service()
```

> 注意：Alembic 数据库迁移已从代码中移除，由 Docker entrypoint 或 `docker-compose migrate` 服务在启动前执行 `alembic upgrade head`。

### 10.3 后台服务启动（`SystemLifecycleService.start_service()`）

```python
class SystemLifecycleService:
    def start_service(self):
        # 0. 初始化检查
        check_config()              # 检查配置文件合法性
        update_config()             # 升级/迁移旧配置
        check_redis()               # 检查 Redis 状态
        update_rss_state()          # 重置 RSS 订阅状态
        init_rbac_system()          # 初始化权限系统
        init_message_webhook_apikey() # 初始化 Webhook API Key

        # 1. 启动调度器（APScheduler）
        SchedulerCore().start_service(load_defaults=True)

        # 2. 加载基础组件
        IndexerHelper()             # 索引器助手
        SiteConf()                  # 站点配置

        # 3. 启动各业务服务
        Sync().init()               # 目录同步引擎
        BrushTaskService().init_config()   # 刷流任务
        RssTaskService().init_config()     # RSS 任务
        TorrentRemover().init_config()     # 种子自动删除
        Downloader().init_config()         # 下载器核心
        FileIndexService().start()         # 文件索引服务
```

### 10.4 配置重载

使用 `src/app/core/settings.py` 中的 `AppSettings.reload()` 方法手动重载配置。
应用层调用 `SettingsService.reload_config()` 或通过 API `/system/reload_config` 触发。

---

## 11. 整体数据流概览

### 11.1 典型 HTTP 请求流

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  FastAPI    │────▶│   Router    │────▶│   Service   │
│  (Browser)  │     │   (main.py) │     │(api/routers)│     │(app/services)│
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                    │
                          ┌─────────────────────────────────────────┘
                          ▼
              ┌─────────────────────┐
              │     业务编排分支      │
              └──────┬──────┬───────┘
                     │      │
           ┌─────────┘      └─────────┐
           ▼                          ▼
    ┌─────────────┐            ┌─────────────┐
    │  Repository │            │   External  │
    │ (app/db/...)│            │   Client    │
    └──────┬──────┘            │(sites/media)│
           │                   └──────┬──────┘
           ▼                          │
    ┌─────────────┐                   │
    │  Database   │◀──────────────────┘
    │ (SQLite/    │        结果返回
    │  MySQL/PG)  │
    └─────────────┘
```

### 11.2 媒体识别流

```
文件名输入
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Parser    │────▶│   Lookup    │────▶│  MediaInfo  │────▶│   Cache     │
│(Regex/LLM)  │     │(TMDB/豆瓣/  │     │  组装对象    │     │(写入缓存)   │
│             │     │ Bangumi)    │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### 11.3 搜索与下载流

```
用户搜索关键词
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SearchService                                                           │
│   ├── MediaService.identify(keyword) → 获取 tmdb_id                     │
│   ├── IndexerService.search() → 遍历所有索引器                          │
│   │       ├── 内置站点：SiteEngine → API/HTML Searcher → 站点返回种子列表 │
│   │       └── 外部索引器：Jackett/Prowlarr API                          │
│   └── FilterService.apply() → 应用过滤规则                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ DownloadService                                                         │
│   ├── 用户选择种子 → DownloaderCore.add_torrent()                       │
│   ├── 下载器客户端（qBittorrent/Transmission）添加任务                   │
│   └── 完成后触发：HookSystem.emit("download.completed")                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 11.4 文件转移流

```
下载完成 / 定时扫描
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ TransferEngine / FileTransferService                                    │
│   ├── 扫描下载目录 → 识别文件 → MediaService.identify_files()           │
│   ├── 二级分类策略 Category.get_category() → 确定目标路径               │
│   ├── 执行转移（复制/移动/硬链接/软链接）                                │
│   ├── 元数据刮削 Scraper.scrape() → NFO + 图片                          │
│   ├── 通知媒体服务器 MediaServer.refresh_library()                      │
│   └── 记录历史 TransferHistoryRepository.insert()                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 12. 关键设计决策

| 决策 | 说明 |
|------|------|
| **绞杀式迁移** | 从 Flask 迁移到 FastAPI，新功能用 FastAPI Router，旧功能逐步迁移，共享 Service 层 |
| **声明式站点定义** | 用 JSON 文件描述站点 API/HTML 结构，替代代码中的硬编码 `if site == "m-team"` |
| **Parser + Lookup 解耦** | 文件名解析与外部数据库查询分离，支持 Regex/LLM 双 Parser，TMDB/豆瓣/Bangumi 多 Lookup |
| **插件沙箱** | 动态 `importlib` 加载插件，支持热重载，隔离 `sys.modules` |
| **统一缓存框架** | 内存/Redis/分层三级适配器，事件驱动，装饰器式缓存声明 |
| **scoped_session + 请求清理** | SQLAlchemy `scoped_session` 保证线程安全，FastAPI 中间件确保请求结束后 `remove()` |
| **Repository + Adapter 模式** | 仓库操作 ORM，适配器转换 Domain Entity，新旧代码兼容共存 |
| **RBAC 权限系统** | 自定义权限模型（用户-角色-权限-菜单），替代旧版简单登录 |

---

## 13. 模块依赖原则

```
允许依赖方向（上层可依赖下层）：

api/routers/  ──▶  app/services/  ──▶  app/domain/  ──▶  app/db/repositories/
     │                  │                  │                    │
     │                  │                  │                    ▼
     │                  │                  │              app/db/models/
     │                  │                  │
     │                  ▼                  ▼
     │           app/sites/         app/media/
     │           app/downloader/    app/helper/
     │           app/indexer/
     │           app/mediaserver/
     │           app/message/
     │           app/storage/
     │
     ▼
app/infrastructure/  (cache_system)
app/plugin_framework/
app/core/            (config, constants)
app/utils/           (commons, types, security)
```

**禁止**：下层模块依赖上层模块。如 `app/db/models/` 不能导入 `app/services/`。

**循环依赖处理**：所有 `import` 必须放在文件顶部。如遇循环依赖，通过重构 `__init__.py` 延迟导入或调整模块结构解除，禁止在函数内部使用 `import` 规避。
