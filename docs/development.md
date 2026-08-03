# 本地开发

## 环境要求

- Python >= 3.11
- uv (Python 包管理器)
- Redis (可选，用于缓存)
- 前端开发需 Node.js >= 20 + pnpm

## 后端开发

### 1. 安装依赖

```bash
uv sync
uv sync --dev
```

### 2. 配置文件

创建 `data/config.yaml`，最小配置：

```yaml
app:
  web_host: '0.0.0.0'
  web_port: 3000
  rmt_tmdbkey: '你的TMDB_API_KEY'
```

### 3. 启动开发服务器

```bash
uv run python run.py
```

后端在 http://localhost:3000 启动，API 文档在 http://localhost:3000/docs。

Docker Compose 部署时后端外部映射为 3000:8080（容器内 nginx 8080），前端占用宿主 8080。

### 4. 代码检查

```bash
uv run ruff check <文件>
uv run pyright <文件>
```

### 5. 运行测试

```bash
# 运行全部测试
uv run pytest tests/ -v

# 运行测试并生成覆盖率报告
uv run pytest tests/ -v --cov=app --cov-report=term-missing
```

测试使用内存 SQLite 数据库，无需额外配置。测试配置位于 `tests/config_test.yaml`。

### 6. 本地提交前检查

安装 pre-commit 钩子后，每次提交前会自动运行 ruff 和 pyright：

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## 前端开发

前端在独立仓库 `frontend/`。

```bash
cd frontend
pnpm install
pnpm dev
```

前端代理默认将 `/api` 转发到 `http://127.0.0.1:3000`（Docker Compose 部署时后端宿主机映射端口）。
本地开发时，代理目标为后端本地端口 3000。

## 项目结构

```
backend/
├── api/              FastAPI 路由
│   ├── main.py       应用入口
│   └── routers/      API 路由
├── app/
│   ├── domain/       业务逻辑
│   ├── db/           数据库模型、仓库
│   ├── schemas/      Pydantic 模型
│   ├── services/     服务层
│   ├── plugins/      插件系统
│   └── utils/        工具函数
├── config/           配置文件
├── docker/           Docker 构建文件
├── docs/             文档
├── tests/            测试
└── run.py            开发启动入口
```

## 数据库迁移

```bash
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
```
