# 架构图依据（图元素 ↔ 代码证据）

> 目的：说明 `docs/architecture*.json/html` 中每个节点与连线的出处，禁止猜测性绘制。
> 引用路径均相对 `backend/src/`；行号为提交时的源码位置，模块级引用为主。

## 大图 `docs/architecture.json`（architecture.html）

### 接入与 API 层

| 图元素 | 依据 |
|---|---|
| web → FastAPI | 前端 `nexus-media-web` 通过 REST 调 `/api/*`；后端入口 `api/main.py`，路由注册于 `api/routers/`（download/media/site/chat 等） |
| 安全层 | `api/routers/rbac.py`、`api/routers/auth.py`、`api/routers/apikey.py`；依赖注入鉴权在 `api/deps.py` |
| DI 装配 | `app/di/builders/*`（facades/services/infrastructure/agent/context/coordinators）；无 DI 框架，`api/main.py` 通过 builders 装配 |
| API→下载/索引/媒体 | `api/routers/download.py`、`api/routers/media.py`、`api/routers/sync.py`、`api/routers/subscription.py` 调用 `app/services/*` 与 `app/indexer/indexer.py` |

### 应用服务层

| 图元素 | 依据 |
|---|---|
| 任务调度 scheduler_core | `app/services/scheduler/scheduler_core.py`（APScheduler） |
| 刷流中心 services/brush | `app/services/brush/`（scheduler_core 中注册，见 `app/services/brush/scheduler.py`） |
| 下载编排 | `app/services/download_service.py`、`app/services/downloader_core.py`、`app/services/download_monitor.py` |
| 识别转移 | `app/services/transfer/filetransfer_service.py`、`app/services/transfer/history_manager.py` |
| 媒体服务 | `app/media/service.py`、`app/media/scraper/__init__.py`（刮削走后台队列 `scrape_queue_service`） |
| 索引器 | `app/indexer/indexer.py`、`app/indexer/core/pipeline.py` |
| 站点引擎 | `app/sites/engine.py`、`app/sites/siteuserinfo/config_html.py`、`app/sites/html_searcher.py` |

### 连线语义与出处

| 连线 | 依据 |
|---|---|
| scheduler → brush → dl | `scheduler_core` 注册刷流/订阅任务；`services/brush/helpers.py` 与 `downloader/pipeline.py` 调用 `siteconf.check_torrent_attr` / 投递下载 |
| dl → 下载客户端 | `app/downloader/` 客户端抽象（qB/T/Aria2）通过 `downloader_core` 控制 |
| dl → 事件总线 → transfer | 下载完成经 `app/infrastructure/event.py` 发布；`initializer.init_event_handlers()` 注册事件桥接订阅（见 `src/initializer.py`） |
| transfer → media | 转移成功调用 `media.get_tmdb_info` / 提交刮削（`transfer/filetransfer_service.py:801-836`） |
| transfer → 存储后端 | 目的目录写入经存储抽象（`app/storage/backends/base.py`、`cross_backend.py`，dst_backend 可为 local/Minio/Rclone） |
| media → 媒体库目录 / Emby·Jellyfin | 刮削写入媒体库目录（存储后端）；媒体服务器刷新由内置 `libraryrefresh` / `libraryscraper` 插件或手动触发（`plugin_framework/builtin_plugins/libraryrefresh/backend/plugin.py`），非默认直连 |
| media → TMDB/豆瓣 | `app/media/service.py` 与 `external/douban.py`、`external/bangumi.py`、TMDB lookup |
| indexer → sites → site-ext | `indexer` 调站点引擎按 `config/sites/*.json`（api/html）检索；直连逻辑见 `sites/engine.py` |
| sites → Chrome（小图中） | `sites/engine.py` 直连失败/挑战时 `build_browser_mode` → `HttpClient` ChromeTransport（`infrastructure/http/browser_transport.py`）→ nexus-chrome |
| dl → 事件总线（下载完成） | `download_event_queue.py` / `event.py` publish（`app/services/download_event_queue.py`） |
| 基础设施 db/redis/cache | `app/db/database_factory.py`（SQLite/MySQL）、`app/infrastructure/cache_system/`（Redis+内存） |

## 小图 `docs/architecture-sites.json`（architecture-sites.html）

| 图元素 | 依据 |
|---|---|
| 站点引擎 | `app/sites/engine.py`（`_fetch_page` 直连失败→`build_browser_mode`） |
| 直连 PT 站点 | `sites/engine.py`、`config/sites/api/*.json`、`config/sites/html/*.json` |
| Chrome 客户端 | `app/infrastructure/http/browser_transport.py`（ChromeTransport/AsyncChromeTransport + 会话删除）、`app/infrastructure/chrome/session.py` |
| nexus-chrome | `infrastructure/chrome/` 对接外部 nexus-chrome 服务（抓取/指纹/会话） |
| 非持久会话用完即删 | `browser_transport.py` `_BaseChromeTransport.close()`（delete_session）与 `client.py` 池释放 |
| browser_persistent | `browser_mode.build_browser_mode()`、站点 note `browser_persistent`（`site_cache.py:198`） |

> 覆盖说明：AI 助手工具循环、消息渠道、插件框架等在本仓库代码中确有实现
> （`agent/`、`message/`、`plugin_framework/`），未在大图主链路展开，可作为独立小图继续产出。

## 小图 `docs/architecture-agent.json`（architecture-agent.html）

| 图元素 | 依据 |
|---|---|
| 路由/SSE | `api/routers/chat.py`；推理内容实时 SSE 推送见 `agent/pydantic_agent.py` 与相关 API |
| 助手核心 | `app/agent/pydantic_agent.py`、`app/agent/service.py`（多步工具循环） |
| 工具执行 | `app/agent/tool_executor.py`；系统工具在 `app/agent/tools/handlers/`（搜索/下载/订阅/知识库/浏览器） |
| 会话与记忆 | `app/agent/agents/memory/`（会话/长程记忆）、`app/agent/rag/` |
| 推理提供方 | `app/agent/providers/`（openai/gemini/ollama base） |

## 小图 `docs/architecture-msg.json`（architecture-msg.html）

| 图元素 | 依据 |
|---|---|
| 插件框架 | `app/plugin_framework/`（service + sandbox + builtin_plugins）；启动/事件触发见 `initializer.py` 与 `di/builders/agent_reload.py` |
| 内置插件 | `app/plugin_framework/builtin_plugins/`：autogenrss、autosignin、torrenttransfer、msg_bark/chanify/dingtalk/…（消息渠道为 msg_* 子目录） |
| 通知中心 | `app/message/message_center.py`、`app/message/message.py`、`message/formatter.py` |
| 渠道注册表 | `app/message/client_registry.py` 与 `app/message/client/` |
| 插件调用服务 | 插件后端 handler 复用服务层（如 autogenrss/backend/handlers/mteam.py 调搜索/下载服务） |

## `architecture-brush-flow.json`（dataflow，刷流/订阅）

| 元素 | 依据 |
|---|---|
| 订阅匹配 | `app/services/subscription/`（subscribe_tv/movie、matcher）；`app/services/filter_service.py` 过滤规则 |
| 刷流筛选 | `app/services/brush/`：`scheduler.py`、`rss_checker.py`、`helpers.py`、`matcher`（free/hr/大小/排除） |
| 投递下载 | `app/services/download_service.py` / `downloader/pipeline.py`（check_torrent_attr 后投递） |
| 做种保种/清理 | `app/services/brush/torrent_lifecycle.py`（做种时长/免费/HR 检查）；删除与磁盘回收在 brush 删除规则、内置 `torrentremover` / `diskspacesaver` 插件 |

## `architecture-scrape.json`（dataflow，刮削队列）

| 元素 | 依据 |
|---|---|
| 非阻塞提交 | `app/services/scrape_queue_service.py`（`submit_file_scrape` / `submit_folder_scrape`）；调用点 `transfer/filetransfer_service.py` |
| 刮削类别 | `app/media/scraper/__init__.py`（NFO/海报/图片），FFmpeg 见 `app/infrastructure/ffmpeg/` |
| 写库目录 | `app/storage/backends/*`（dst_backend 本地/Minio/Rclone） |

## `architecture-brush-lifecycle.json`（lifecycle，刷流任务状态）

| 元素 | 依据 |
|---|---|
| RUNNING / STOPPED / DISABLED | `app/domain/entities/brush.py`（BrushTaskState: Y/S/N）；启停更新 `app/services/brush/task_service.py`（update_brushtask_state） |
| 周期性执行 | `app/services/brush/scheduler.py` 注册到 `scheduler_core`（APScheduler） |

> 注：本图聚焦任务级状态（运行/停止）；单次异常不改变任务状态、仅日志记录；禁用态（N）作为配置标记存在，可在刷流管理操作，未单独绘制以免引入状态穿越歧义。
