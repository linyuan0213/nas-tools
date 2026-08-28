# Nexus Media Docker 部署

## 镜像特点

- 基于 Debian（`python:3.14-slim-trixie`）
- 支持 amd64 / arm64 架构
- 内嵌 nginx 反代，后端容器统一 **8080** 端口对外（内部服务监听 3000）
- 非 root 用户运行（nexus:nexus，UID 911，可用 PUID/PGID 覆盖）
- s6-overlay 进程管理，支持优雅退出
- 数据库迁移由 compose 独立的 migration 服务执行（`alembic upgrade head`），后端通过 `SKIP_MIGRATION=true` 跳过

## 端口约定

后端镜像内嵌 nginx：nginx 监听容器内 **8080**，反向代理到内部 nexus-media 服务（3000）。compose 中后端宿主机映射为 `3000:8080`。

## 快速开始

项目根目录的 `docker-compose.yml` 提供多种部署模式，通过 `--profile` 切换。

> **容器间网络提示**：所有服务运行在自定义网桥 `nexus-media-network` 上，后端通过服务名（`mysql`、`redis`）互访。若之前部署过，旧网络/旧容器残留会导致容器间互连失败、后端连不上数据库一直超时，先 `docker compose down` 并清理残留网络/容器再启动（详见 `docs/installation.md` 的「第一步：先确认容器间网络互通」）。

### 基础模式（默认）

包含前端、后端、Redis 和数据库（默认 MySQL，也可切换为 PostgreSQL）。

**MySQL**

```bash
docker compose --profile basic-mysql up -d
```

**PostgreSQL**

```bash
docker compose --profile basic-postgresql up -d
```

### 完整模式

在基础模式之上增加 OCR（nexus-verify）和 Chrome（nexus-chrome）组件。

**MySQL**

```bash
docker compose --profile full-mysql up -d
```

**PostgreSQL**

```bash
docker compose --profile full-postgresql up -d
```

### 仅前后端（SQLite）

只启动前端和后端，后端使用 SQLite，无需 Redis 和数据库。

```bash
docker compose --profile app-only up -d
```

### 修改配置

部署前按需修改 `docker-compose.yml`：

1. **媒体目录挂载**（`x-backend-common` 卷）：将 `/mnt/media:/media` 替换为你的媒体库目录
2. **数据库密码**：MySQL 服务与 `migration-mysql` / `backend-mysql` 三处的 `MYSQL_PASSWORD` / `DATABASE__PASSWORD` 保持一致
3. **Chrome VNC 密码**（完整模式）：修改 `nexus-chrome` 的 `VNC_PASSWORD`

### 访问

- 前端 Web UI: http://localhost:8080
- 后端 API: http://localhost:3000

## 单独部署后端

**docker cli**

```bash
docker run -d \
  --name nexus-media \
  --hostname nexus-media \
  -p 3000:8080 \
  -v $(pwd)/data:/data \
  -v /mnt/media:/media \
  -e PUID=0 \
  -e PGID=0 \
  -e UMASK=000 \
  -e NEXUS_PORT=3000 \
  -e NEXUS_MEDIA_DATA=/data \
  linyuan0213/nexus-media:latest
```

> 容器内 nginx 监听 8080，`-p 3000:8080` 表示宿主机 3000 访问后端。

**docker-compose**

```yaml
services:
  nexus-media:
    image: linyuan0213/nexus-media:latest
    ports:
      - 3000:8080
    volumes:
      - ./data:/data
      - /mnt/media:/media
    environment:
      - PUID=0
      - PGID=0
      - UMASK=000
      - NEXUS_PORT=3000
      - NEXUS_MEDIA_DATA=/data
    restart: always
    hostname: nexus-media
    container_name: nexus-media
```

> 单独部署后端时（无 compose 内 Redis/DB），需配置 `REDIS__HOST` 与 `DATABASE__*` 指向外部 Redis / 数据库。

## 单独部署前端

前端 Docker 镜像内嵌 nginx，通过环境变量指向后端地址，所有 `/api/`、`/ws` 请求由 nginx 转发。

**docker cli**

```bash
docker run -d \
  --name nexus-media-web \
  -p 8080:8080 \
  -e BACKEND_HOST=192.168.1.100 \
  -e BACKEND_PORT=3000 \
  linyuan0213/nexus-media-web:latest
```

**docker-compose**

```yaml
services:
  nexus-media-web:
    image: linyuan0213/nexus-media-web:latest
    ports:
      - 8080:8080
    environment:
      - BACKEND_HOST=nexus-media   # 后端服务地址
      - BACKEND_PORT=3000          # 后端宿主机映射端口
    restart: always
    container_name: nexus-media-web
```

> `BACKEND_PORT` 填后端**宿主机映射端口**（compose 中后端 `3000:8080`，故填 `3000`）。

## Redis 配置

compose 中 Redis 服务已配置（无密码、使用 `./data/redis_data` 持久化）：

```yaml
  redis:
    image: redis:7-alpine
    container_name: nexus-media-redis
    volumes:
      - ./data/redis_data:/data
    command: redis-server --save "" --appendonly no --dir /data
```

后端通过 `REDIS__*` 环境变量连接（compose 的 `x-env-db-common` 已设置 `REDIS__HOST=nexus-media-redis`）。使用外部 Redis 时，覆盖这些变量即可：

```yaml
    environment:
      - REDIS__HOST=你的redis地址
      - REDIS__PORT=6379
      - REDIS__PASSWORD=你的redis密码   # 无密码则省略
      - REDIS__DB=0
```

## 数据库配置

- **app-only** 模式使用 SQLite，无需配置数据库（数据在 `./data/db/`）
- **MySQL / PostgreSQL** 模式由 compose 自动配置，迁移由独立的 `migration-*` 服务执行，后端 `SKIP_MIGRATION=true`
- 使用外部数据库时设置 `DATABASE__*` 指向外部实例，并手动执行 `alembic upgrade head` 迁移

## 环境变量

环境变量优先级：`环境变量 > .env > config.yaml`。除 Docker 镜像专用变量外，其余变量对应 `src/app/core/settings.py` 中的配置节点，使用 `__` 作为嵌套分隔符，例如 `APP__WEB_HOST`、`DATABASE__TYPE`、`REDIS__HOST`。

### Docker 镜像专用变量

**后端镜像 (`linyuan0213/nexus-media`)**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUID` | 0 | 运行用户 UID |
| `PGID` | 0 | 运行用户 GID |
| `UMASK` | 000 | 文件权限掩码 |
| `NEXUS_PORT` | 3000 | 容器内部 nexus-media 服务端口（nginx 反代到该端口） |
| `SKIP_MIGRATION` | false | 设为 `true` 跳过启动时数据库迁移（compose 由独立 migration 服务执行） |
| `TZ` | Asia/Shanghai | 时区 |
| `NEXUS_MEDIA_DATA` | /data | 数据目录（config.yaml、数据库、插件数据） |
| `NEXUS_MEDIA_CONFIG` | /data/config.yaml | 配置文件路径 |

**前端镜像 (`linyuan0213/nexus-media-web`)**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKEND_HOST` | `nexus-media` | 后端服务地址（compose 内为服务名，独立部署时设为 IP 或域名） |
| `BACKEND_PORT` | `3000` | 后端宿主机映射端口（前端 nginx 转发目标） |

### 前后端配置变量（`app` 节点）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP__WEB_HOST` | :: | Web 监听地址 |
| `APP__WEB_PORT` | 3000 | Web 监听端口 |
| `APP__LOGIN_USER` | admin | 默认登录用户名 |
| `APP__LOGIN_PASSWORD` | password | 默认登录密码 |
| `APP__TMDB_DOMAIN` | api.themoviedb.org | TMDB API 域名 |

### 数据库配置变量（`database` 节点）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE__TYPE` | sqlite | 数据库类型：`sqlite` / `mysql` / `postgresql` |
| `DATABASE__HOST` | localhost | 数据库地址 |
| `DATABASE__PORT` | 0 | 数据库端口 |
| `DATABASE__USERNAME` | — | 数据库用户名 |
| `DATABASE__PASSWORD` | — | 数据库密码 |
| `DATABASE__DATABASE` | nas_tools | 数据库名称 |

### Redis 配置变量（`redis` 节点）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS__HOST` | 127.0.0.1 | Redis 地址（compose 内为 `nexus-media-redis`） |
| `REDIS__PORT` | 6379 | Redis 端口 |
| `REDIS__PASSWORD` | — | Redis 密码 |
| `REDIS__DB` | 0 | Redis 数据库索引 |

### 其他常用变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXUS_MEDIA_CONFIG` | /data/config.yaml | 配置文件路径（可选，默认自动发现） |
| `NEXUS_MEDIA_DATA` | /data | 数据目录路径（可选，默认 `./data`） |
| `LOG__FORMAT` | text | 设为 `json` 输出 ELK 兼容日志 |

## PUID / PGID 说明

- 若同时使用 Emby / Jellyfin / Plex / qBittorrent 等 Docker 镜像，建议保持 PUID / PGID 一致
- 在宿主机上执行 `id -u` 和 `id -g` 获取对应值
