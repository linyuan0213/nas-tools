# Nexus Media 项目指南

## 项目概述
Nexus Media 自动化工具，用于媒体管理、种子索引、下载编排，内置 AI 助手。
- **后端**: Python 3.11+, FastAPI, SQLAlchemy, Alembic
- **前端**: 独立仓库 [nexus-media-web](https://github.com/linyuan0213/nexus-media-web)，Vue 3 + Vite + Naive UI + Tailwind CSS（oxfmt + ESLint + vue-tsc 检查）
- **数据库**: SQLite (默认) 或 MySQL/PostgreSQL，通过 `src/app/db/database_factory.py` 配置
- **配置**: `src/app/core/settings.py` (pydantic-settings) + `config/config.yaml.example` + `.env`
- **任务运行**: `just`（`justfile`），替代 Makefile
- **包管理**: `uv`（`uv run` 执行一切命令，禁止手动激活 venv）

## 项目结构（src layout）
```
backend/
├── src/                       # 源码（PEP 517/518 src layout）
│   ├── api/                   # FastAPI 路由层
│   ├── app/                   # 核心业务层
│   │   ├── agent/             # AI 助手（pydantic_agent + providers + tools + rag + memory）
│   │   ├── di/                # 显式工厂注册表（builders/ 模块化装配）
│   │   ├── message/           # 通知渠道（含 Web 消息通道）
│   │   ├── domain/            # 领域层（实体/引擎/接口）
│   │   ├── infrastructure/    # 基础设施（缓存/限流/Chrome 自动化）
│   │   └── ...
│   ├── log/                   # 日志模块（loguru）
│   ├── version.py             # 版本（从 pyproject.toml 读取）
│   └── initializer.py         # 启动初始化
├── tests/                     # 测试（unit/ + integration/ + conftest.py）
├── config/                    # 站点 JSON 定义、配置模板
│   └── config.yaml.example    # 提交到 git 的模板
├── alembic/                   # Alembic 迁移（env.py + versions/）
├── static/                    # 静态文件
├── docker/                    # Docker 构建文件（rootfs/）
├── scripts/                   # 工具脚本（含 scan_secrets.py 密钥扫描）
├── justfile                   # 任务运行器
├── run.py                     # 启动入口
└── pyproject.toml
```

## 配置优先级
环境变量 > `.env` > `data/config.yaml`（可选，自动发现）
- `NEXUS_MEDIA_CONFIG` 已降级为可选，未设置时自动查找 `./data/config.yaml`
- 无配置文件时纯 `.env` + 默认值也可运行
- SQLite 路径由 `DATABASE__SQLITE_PATH` 控制（默认 `data/user.db`），测试强制使用临时文件隔离

## 架构
- **入口**: `run.py` → `src/api/main.py` (FastAPI 应用 + lifespan，调用 `init_db()`)
- **初始化**: `src/initializer.py` 初始化默认过滤规则、默认分类（首次）、RBAC、RSS 状态、索引器站点配置、消息 Webhook APIKey；`init_event_handlers()` 注册 `@on_event` 事件桥接
- **数据库迁移**: 由 Docker entrypoint 或 compose migration 服务执行 `alembic upgrade head`，应用内 `init_db()` 仅 `create_all` 建缺失表
- **DI**: `src/app/di/builders/*`（facades / infrastructure / services / agent / context / coordinators 模块化装配），显式工厂注册表，无依赖注入框架；`build_infrastructure()` 创建 EventBus 后注册 `@on_event` handler
- **AI 助手**: `src/app/agent/pydantic_agent.py` 基于 pydantic-ai 的多步工具循环；推理内容实时 SSE 推送、工具调用事件流式下发；`tools/handlers/` 为系统工具（搜索/下载/订阅/知识库/浏览器）；`providers/` 对接 OpenAI 兼容服务；`agents/memory/` 会话与长程记忆
- **HTTP 客户端**: `HttpClient` / `AsyncHttpClient` 按配置复用底层 `httpx` 连接池，进程退出时 `close_all()` 统一释放
- **缓存**: `src/app/infrastructure/cache_system/` (Redis + 内存适配器、装饰器、事件总线)
- **插件**: `src/app/plugin_framework/builtin_plugins/` — 内置 + 可安装
- **权限**: `src/app/db/models/rbac.py` 中的自定义 RBAC 系统
- **Chrome 自动化**: `src/app/infrastructure/chrome/` 对接 nexus-chrome 服务（浏览器抓取/截图、站点 Cookie 更新）

## 重要约定
- 注释需要精简。
- **所有 `import`/`from` 必须放在文件顶部**，严禁在函数/方法/类内部导入依赖。如遇循环依赖，必须通过重构 `__init__.py` 延迟导入或调整模块结构来解除，禁止使用函数内部导入规避。
- **所有修改必须通过 ruff 和 pyright 检查**后才能提交。运行命令：`uv run ruff check .` 和 `uv run pyright src/ tests/`。
- **修改配置/迁移/模型时，先确认测试与数据库隔离**：`uv run pytest tests/ -q`。
- 优先编辑现有文件，而不是创建新文件。
- 遵循现有代码风格；项目混合了新旧模式，新代码尽量使用新模式。
- `third_party/`、`src/app/media/doubanapi/`、`src/app/media/tmdbv3api/` 中的第三方代码 — 不要重构。

## 数据库
- 工厂: `src/app/db/database_factory.py`
- 迁移: `alembic/` 目录（`alembic upgrade head`）
- 添加模型时，需要添加 Alembic 迁移并更新仓库。

## 安全扫描
- `just bandit` — 源码安全扫描
- `just safety` — 依赖漏洞扫描（pip-audit）
- `just security` — 两者
- **pre-commit 内置密钥扫描**（`scripts/scan_secrets.py`）：提交命中 token/apikey/密钥模式即拦截，需人工确认。

## 测试
- 测试框架: pytest，配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]`
- 全局 fixtures: `tests/conftest.py`（内存数据库 + 临时 SQLite 隔离，`DATABASE__SQLITE_PATH` 指向临时文件，避免污染真实库）
- 测试不使用 `tests/config_test.yaml`（已删除并加入 gitignore）；真实密钥文件一律不入库
- 运行命令: `uv run pytest tests/ -v`
- 覆盖率: `uv run pytest tests/ -v --cov=src/app --cov=src/api --cov=src/log --cov-report=term-missing`

## 版本
- `pyproject.toml` 为版本唯一来源
- `src/version.py` 从 `pyproject.toml` 动态读取，自动加 `v` 前缀

## Git 工作流

### 分支模型
采用简化 Git Flow：

| 分支 | 用途 | 保护策略 |
|------|------|----------|
| `master` | 稳定发布分支 | 禁止直接推送 |
| `dev` | 日常开发分支 | 建议 PR 合并 |
| `release` | 预发布分支 | 禁止直接推送 |
| `feature/*` | 功能分支（可选） | 无 |

### 提交规范
- 使用 Conventional Commits 格式：`<type>: <中文描述>`
- 常用 type：`feat`、`fix`、`refactor`、`perf`、`test`、`docs`、`chore`
- 按模块提交：一个提交只做一件事；测试文件随所属模块提交
- 发布流程：dev → release → master → 打 tag（如 `v4.6.0`），前后端同步

### 前后端协同
- 后端和前端为两个独立 git 仓库，分别提交和发布。
- API 变更时，后端先行提交并确保接口稳定，前端再对接。

### 密钥与安全（强制）
- **禁止提交任何真实密钥/令牌**：API Key、Token、密码、JWT secret、Cookie、sk- 开头密钥等，一律不得入库。
- 含密钥数据的文件（配置文件、`.env`、测试配置等）必须：
  1. 加入 `.gitignore`（如 `tests/config_test.yaml`、`*.lock`）；
  2. 提交前**先经用户确认**，确认无真实密钥后才允许提交/推送。
- 提交前运行密钥扫描（pre-commit 内置 `scan_secrets` 钩子），命中即拦截提交；确认为占位符或经用户确认后方可用 `git commit --no-verify` 强制提交。
- 误提交真实密钥的历史清理（filter-branch/force-push）属高危操作，必须与用户确认范围后再执行，且应尽量缩小重写范围。
- 真实运行配置（如 `data/config.yaml`）不跟踪；测试配置使用占位符。
