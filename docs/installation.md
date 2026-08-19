# 安装指南

## 镜像特点

- 基于 Debian（`python:3.14-slim-trixie`）
- 支持 amd64 / arm64 架构
- 内嵌 nginx 反代，后端容器统一 **8080** 端口对外（内部服务监听 3000）
- 非 root 用户运行（nexus:nexus，UID 911，可用 PUID/PGID 覆盖）
- s6-overlay 进程管理，支持优雅退出
- 数据库迁移由 compose 独立的 migration 服务执行（`alembic upgrade head`），后端通过 `SKIP_MIGRATION=true` 跳过

## 端口约定（重要）

后端镜像内嵌 nginx：nginx 监听容器内 **8080**，反向代理到内部 nexus-media 服务（3000）。因此：

| 服务 | 容器内端口 | 实际 compose 宿主机映射 |
|------|-----------|------------------------|
| 后端（经 nginx） | 8080 | `3000:8080` |
| 前端 Web UI | 8080 | `8080:8080` |
| Redis | 6379 | 不映射（仅内网） |
| MySQL | 3306 | `3306:3306`（可选） |
| PostgreSQL | 5432 | `5432:5432`（可选） |
| nexus-chrome | 9850 / 6080 | `9850:9850` / `6080:6080` |
| nexus-verify | 9300 | `9300:9300` |

## Docker Compose 安装（推荐）

项目根目录的 `docker-compose.yml` 支持多种部署模式（通过 `--profile` 选择）。

### 简单示例（开箱即用）

如果觉得完整 `docker-compose.yml` 复杂，可以直接使用下面两个简化版。

**版本一：前后端 + Redis + MySQL（推荐）**

```yaml
services:
  frontend:
    image: linyuan0213/nexus-media-web:latest
    container_name: nexus-media-web
    ports:
      - "8080:8080"                    # 前端访问端口
    environment:
      - BACKEND_HOST=backend
      - BACKEND_PORT=3000
    depends_on:
      - backend
    restart: always

  backend:
    image: linyuan0213/nexus-media:latest
    container_name: nexus-media
    hostname: nexus-media
    ports:
      - "3000:8080"                    # 后端访问端口（容器内 nginx 8080）
    volumes:
      - ./data:/data                   # 配置/数据库/插件数据
      - /mnt/media:/media              # ← 替换为你的媒体库目录
    environment:
      - PUID=0
      - PGID=0
      - UMASK=000
      - NEXUS_PORT=3000
      - REDIS__HOST=redis
      - REDIS__PORT=6379
      - REDIS__DB=0
      - DATABASE__TYPE=mysql
      - DATABASE__HOST=mysql
      - DATABASE__PORT=3306
      - DATABASE__USERNAME=nexus_media
      - DATABASE__PASSWORD=nexus_media_password   # 与 mysql 服务保持一致
      - DATABASE__DATABASE=nexus_media
    depends_on:
      - redis
      - mysql
    restart: always

  redis:
    image: redis:7-alpine
    container_name: nexus-media-redis
    volumes:
      - ./data/redis_data:/data
    command: redis-server --save "" --appendonly no --dir /data
    restart: always

  mysql:
    image: mysql:8.4
    container_name: nexus-media-mysql
    environment:
      - MYSQL_ROOT_PASSWORD=root_password
      - MYSQL_DATABASE=nexus_media
      - MYSQL_USER=nexus_media
      - MYSQL_PASSWORD=nexus_media_password   # 与 backend 保持一致
    volumes:
      - ./mysql_data:/var/lib/mysql
    restart: always
```

将上面的 YAML 保存为 `docker-compose.simple.yml`（放在项目或任意目录下）后启动：

```bash
docker compose -f docker-compose.simple.yml up -d
```

**版本二：仅前后端（SQLite，无需 Redis/数据库，适合体验）**

```yaml
services:
  frontend:
    image: linyuan0213/nexus-media-web:latest
    container_name: nexus-media-web
    ports:
      - "8080:8080"
    environment:
      - BACKEND_HOST=backend
      - BACKEND_PORT=3000
    depends_on:
      - backend
    restart: always

  backend:
    image: linyuan0213/nexus-media:latest
    container_name: nexus-media
    hostname: nexus-media
    ports:
      - "3000:8080"
    volumes:
      - ./data:/data
      - /mnt/media:/media              # ← 替换为你的媒体库目录
    environment:
      - PUID=0
      - PGID=0
      - UMASK=000
      - NEXUS_PORT=3000
    restart: always
```

> 简单示例中后端**不设置 `SKIP_MIGRATION`**，启动时自动执行数据库迁移（`alembic upgrade head`）；完整 `docker-compose.yml` 使用独立 migration 服务，故后端设 `SKIP_MIGRATION=true`。

### 完整 docker-compose.yml（profile 模式）

如需数据库密码自定义、OCR/Chrome 组件、PostgreSQL 支持，使用项目根目录的完整 `docker-compose.yml`：

| 模式 | 说明 | 命令 |
|------|------|------|
| 基础 MySQL（默认） | 前端 + 后端 + Redis + MySQL + 迁移 | `docker compose --profile basic-mysql up -d` |
| 基础 PostgreSQL | 前端 + 后端 + Redis + PostgreSQL + 迁移 | `docker compose --profile basic-postgresql up -d` |
| 完整 MySQL | 基础模式 + OCR（nexus-verify）+ Chrome（nexus-chrome） | `docker compose --profile full-mysql up -d` |
| 完整 PostgreSQL | 基础模式 + OCR + Chrome | `docker compose --profile full-postgresql up -d` |
| 仅前后端 | 前端 + 后端 + SQLite，无需 Redis/DB | `docker compose --profile app-only up -d` |

> 不带 `--profile` 时默认启用基础 MySQL 模式（`""` 空 profile 命中的服务）。

### 可选组件：nexus-verify 与 nexus-chrome

`full-mysql` / `full-postgresql` profile 会额外启动两个可选组件：

| 组件 | 镜像 | 端口 | 作用 |
|------|------|------|------|
| nexus-verify | `linyuan0213/nexus-verify` | 9300 | OCR 验证码识别，用于站点自动签到 |
| nexus-chrome | `linyuan0213/nexus-chrome` | 9850 / 6080 | 浏览器自动化，用于站点 Cookie 更新、网页自动化登录、AI 助手网页抓取 |

组件已随 compose 自动配置好网络互通。若需单独部署，后端通过以下设置启用对应能力：

- 验证码识别：**系统设置 → 基础设置 → 实验室** 中「启用验证码识别服务器」，填 `http://nexus-verify:9300`
- 网页自动化：**系统设置 → 基础设置 → 实验室** 中「启用网页自动化」，填 `http://nexus-chrome:9850`

> nexus-chrome 的浏览器页面可通过 VNC（端口 6080）实时查看。
> **安全提示**：VNC 密码为必填项，**禁止使用默认值 `password`**。请在项目目录 `.env` 中配置，例如：
>
> ```bash
> # .env
> VNC_PASSWORD=你的强密码
> ```
>
> 未设置 `VNC_PASSWORD` 时 `docker compose up` 会直接报错并提示，避免默认弱口令暴露 VNC 远程桌面。

### 1. 修改 docker-compose.yml

克隆项目后，按需修改 `docker-compose.yml`：

**目录挂载**（`x-backend-common` 卷）：

```yaml
x-backend-common:
  volumes:
    - ./data:/data                # 配置、数据库、插件数据（必须）
    # 替换为你的实际媒体目录：
    # - /mnt/media:/media          # 媒体库目录（必须，否则无法转移）
```

**数据库密码**（MySQL 服务与 `migration-mysql` / `backend-mysql` 三处需保持一致）：

```yaml
  mysql:
    environment:
      - MYSQL_ROOT_PASSWORD=你的root密码
      - MYSQL_DATABASE=nexus_media
      - MYSQL_USER=nexus_media
      - MYSQL_PASSWORD=你的数据库密码
```

### 2. 启动服务

```bash
# 基础 MySQL 模式
docker compose --profile basic-mysql up -d

# 或完整模式（含 OCR + Chrome）
docker compose --profile full-mysql up -d
```

### 3. 访问

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
    restart: always
    hostname: nexus-media
    container_name: nexus-media
```

> 单独部署后端时（无 compose 内 Redis/DB），需配置 `REDIS__HOST` 与 `DATABASE__*` 指向外部 Redis / 数据库。

## 单独部署前端

前端 Docker 镜像内嵌 nginx，通过环境变量指向后端地址，所有 `/api/`、`/ws` 请求由 nginx 转发到后端。

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
      - BACKEND_HOST=nexus-media   # 后端服务地址（compose 内为服务名）
      - BACKEND_PORT=3000          # 后端宿主机映射端口
    restart: always
    container_name: nexus-media-web
```

> `BACKEND_PORT` 填后端**宿主机映射端口**（compose 示例中后端 `3000:8080`，故填 `3000`）；前端 nginx 会转发到 `BACKEND_HOST:BACKEND_PORT`。

## 反向代理部署

通过 Nginx 将 Nexus Media 挂到域名下对外访问时，只需代理**前端端口**（宿主机 `8080`）。前端容器内嵌 nginx 会继续将 `/api`、`/ws` 转发到后端。

!!! warning
    必须配置 WebSocket 转发头，否则日志、进度等实时推送功能不可用。

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name media.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;

        # WebSocket 支持（必须）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 大文件上传（备份恢复等场景）
        client_max_body_size 100m;
        proxy_read_timeout 300s;
    }
}

server {
    listen 80;
    server_name media.example.com;
    return 301 https://$host$request_uri;
}
```

配合设置：

1. 在 **系统设置 → 基础设置 → 系统** 中将「外网访问地址」填为 `https://media.example.com`，消息通知中的链接才能正确跳转
2. 子路径部署（如 `/nexus`）暂不支持，请使用独立域名或端口
3. 使用**企业微信交互功能**时，还需把 `/wechat` 直接转发到后端端口（前端 nginx 不转发该路径），详见 [通知渠道配置](notifications.md#交互功能可选)

## Redis 配置

### compose 模式

compose 中 Redis 服务已配置好（无密码、使用 `/data/redis_data` 持久化）：

```yaml
  redis:
    image: redis:7-alpine
    container_name: nexus-media-redis
    volumes:
      - ./data/redis_data:/data
    command: redis-server --save "" --appendonly no --dir /data
```

后端通过 `REDIS__*` 环境变量连接（compose 的 `x-env-db-common` 已设置）：

```yaml
    environment:
      - REDIS__HOST=nexus-media-redis
      - REDIS__PORT=6379
      - REDIS__DB=0
```

### 外部 Redis

单独部署后端且使用外部 Redis 时，设置：

```yaml
    environment:
      - REDIS__HOST=你的redis地址
      - REDIS__PORT=6379
      - REDIS__PASSWORD=你的redis密码   # 无密码则省略
      - REDIS__DB=0
```

## 数据库配置

### 模式 3（仅前后端 / SQLite）

`app-only` profile 使用 SQLite，无需配置数据库与 Redis：

```bash
docker compose --profile app-only up -d
```

数据文件保存在 `./data/db/`（由 `NEXUS_MEDIA_DATA=/data` 决定）。

### MySQL / PostgreSQL（compose 模式）

compose 已配置好 MySQL（默认）或 PostgreSQL 模式，后端通过 `DATABASE__*` 环境变量连接：

```yaml
    environment:
      - DATABASE__TYPE=mysql            # 或 postgresql
      - DATABASE__HOST=mysql            # 或 postgresql（compose 服务名）
      - DATABASE__PORT=3306             # 或 5432
      - DATABASE__USERNAME=nexus_media
      - DATABASE__PASSWORD=nexus_media_password
      - DATABASE__DATABASE=nexus_media
```

迁移由独立的 `migration-mysql` / `migration-postgresql` 服务在启动时执行（`alembic upgrade head`），后端使用 `SKIP_MIGRATION=true` 跳过迁移。

### 外部数据库

单独部署后端使用外部数据库时，设置 `DATABASE__*` 指向外部实例，并手动执行迁移（或设置 `SKIP_MIGRATION=false` 让启动时自动迁移）。

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
| `SKIP_MIGRATION` | false | 设为 `true` 跳过启动时数据库迁移（compose 由独立 migration 服务执行迁移） |
| `TZ` | Asia/Shanghai | 时区 |
| `NEXUS_MEDIA_DATA` | /data | 数据目录（config.yaml、数据库、插件数据） |
| `NEXUS_MEDIA_CONFIG` | /data/config.yaml | 配置文件路径（可选，默认自动发现 `data/config.yaml`） |

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
| `APP__DEBUG` | false | Debug 模式，开启后提供 `/docs` API 文档，生产环境保持关闭 |

### 数据库配置变量（`database` 节点）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE__TYPE` | sqlite | 数据库类型：`sqlite` / `mysql` / `postgresql` |
| `DATABASE__HOST` | localhost | 数据库地址 |
| `DATABASE__PORT` | 0 | 数据库端口 |
| `DATABASE__USERNAME` | — | 数据库用户名 |
| `DATABASE__PASSWORD` | — | 数据库密码 |
| `DATABASE__DATABASE` | nexus_media | 数据库名称 |
| `DATABASE__SQLITE_PATH` | data/user.db | SQLite 数据库文件路径（`TYPE=sqlite` 时生效） |

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

## 目录说明

| 容器路径 | 说明 |
|----------|------|
| `/data` | 配置文件（config.yaml）、数据库、插件数据（必须挂载） |
| `/data/redis_data` | Redis 持久化数据（compose 内） |
| `/nexus-media` | 应用代码目录 |
| `/media` | 媒体库目录（需自行映射，例如 `/mnt/media:/media`） |

## PUID / PGID 说明

- 若同时使用 Emby / Jellyfin / Plex / qBittorrent 等 Docker 镜像，建议保持 PUID / PGID 一致
- 在宿主机上执行 `id -u` 和 `id -g` 获取对应值

## 首次使用

1. 访问前端页面 http://localhost:8080
2. 默认账号密码：
   - 用户名: `admin`
   - 密码: `password`
3. **首次登录后必须修改默认密码**
4. 进入 **设置 > 基础设置 > 媒体** 配置 TMDB API Key（必须）
5. 进入 **设置 > 下载器** 添加下载器
6. 进入 **设置 > 媒体服务器** 添加 Emby/Jellyfin/Plex
7. 进入 **站点 > 站点维护** 添加 PT 站点
