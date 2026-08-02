# 安装指南

## 镜像特点

- 基于 Debian（`python:3.14-slim-trixie`）
- 支持 amd64 / arm64 架构
- 内嵌 nginx 反代，统一 8080 端口对外
- 非 root 用户运行（nexus:nexus，UID 911）
- s6-overlay 进程管理，支持优雅退出
- 数据库迁移在启动时自动执行（alembic upgrade head）

## Docker Compose 安装（推荐）

前后端分离部署，包含 Nexus Media 后端、前端 Web UI、Redis、OCR 和 Chrome 服务。

### 1. 创建 docker-compose.yml

```yaml
services:
  frontend:
    image: linyuan0213/nexus-media-web:latest
    ports:
      - 3000:8080
    restart: always
    container_name: nexus-media-web
    environment:
      - BACKEND_HOST=nexus-media
      - BACKEND_PORT=8080
    networks:
      - nexus-media-network
    depends_on:
      - backend

  backend:
    image: linyuan0213/nexus-media:latest
    ports:
      - 3001:3000
    volumes:
      - ./data:/data
      - /你的媒体目录:/media
    environment:
      - PUID=0
      - PGID=0
      - UMASK=000
      - NEXUS_PORT=3000
    restart: always
    hostname: nexus-media
    container_name: nexus-media
    networks:
      - nexus-media-network
    healthcheck:
      test: "wget -qO- http://localhost:3000/health || exit 1"
      interval: 30s
      timeout: 30s
      retries: 3
      start_period: 40s
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    container_name: nexus-media-redis
    volumes:
      - ./data/redis_data:/data
      - ./config/redis.conf:/usr/local/etc/redis/redis.conf
    command: redis-server /usr/local/etc/redis/redis.conf
    restart: always
    networks:
      - nexus-media-network

  nexus-verify:
    image: linyuan0213/nexus-verify:latest
    container_name: nexus-verify
    ports:
      - 9300:9300
    restart: always
    networks:
      - nexus-media-network

  nexus-chrome:
    image: linyuan0213/nexus-chrome:latest
    container_name: nexus-chrome
    shm_size: 2g
    environment:
      - VNC_PASSWORD=password
    volumes:
      - ./data:/var/lib/chromium/user_data
    ports:
      - 9850:9850
      - 6080:6080
    restart: always
    networks:
      - nexus-media-network

networks:
  nexus-media-network:
    driver: bridge
    name: nexus-media-network
```

### 2. 启动服务

```bash
docker compose up -d
```

### 3. 访问

- 前端 Web UI: http://localhost:3000
- 后端 API: http://localhost:3001

## 快速开始（profile 模式）

项目根目录的 `docker-compose.yml` 也支持通过 `--profile` 选择部署模式：

| 模式 | 说明 | 命令 |
|------|------|------|
| 基础 MySQL（默认） | 前端 + 后端 + Redis + MySQL | `docker compose --profile basic-mysql up -d` |
| 基础 PostgreSQL | 前端 + 后端 + Redis + PostgreSQL | `docker compose --profile basic-postgresql up -d` |
| 完整 MySQL | 基础模式 + OCR + Chrome | `docker compose --profile full-mysql up -d` |
| 完整 PostgreSQL | 基础模式 + OCR + Chrome | `docker compose --profile full-postgresql up -d` |
| 仅前后端 | 前端 + 后端 + SQLite，无需 Redis/DB | `docker compose --profile app-only up -d` |

## 单独部署后端

**docker cli**

```bash
docker run -d \
  --name nexus-media \
  --hostname nexus-media \
  -p 3001:3000 \
  -v $(pwd)/data:/data \
  -v /你的媒体目录:/media \
  -e PUID=0 \
  -e PGID=0 \
  -e UMASK=000 \
  linyuan0213/nexus-media:latest
```

**docker-compose**

```yaml
services:
  nexus-media:
    image: linyuan0213/nexus-media:latest
    ports:
      - 3001:3000
    volumes:
      - ./data:/data
      - /你的媒体目录:/media
    environment:
      - PUID=0
      - PGID=0
      - UMASK=000
      - NEXUS_PORT=3000
    restart: always
    hostname: nexus-media
    container_name: nexus-media
```

## 单独部署前端

### 两种后端地址配置方式

前端 Docker 镜像支持两种方式指定后端地址：

1. **环境变量**（Nginx 代理层）：容器启动时通过 `BACKEND_HOST` / `BACKEND_PORT` 配置 nginx 反代目标，所有 `/api/`、`/ws` 等请求由 nginx 转发。
2. **运行时设置**（浏览器端）：在页面 **Settings** 中设置后端地址，前端直接跨域请求后端，绕过 nginx 代理。该值存储在浏览器 `localStorage` 中。

### 环境变量方式

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
      - BACKEND_HOST=nexus-media
      - BACKEND_PORT=8080
    restart: always
    container_name: nexus-media-web
```

> 使用项目根目录 `docker-compose.yml` 部署时无需手动设置，默认值即为 compose 网络内后端服务名。

### 运行时设置方式

若不设置环境变量，或需要动态切换后端，可在前端页面 **Settings** → **Backend URL** 中输入后端完整地址（如 `http://192.168.1.100:3000`）。此时前端直连后端，需确保后端允许 CORS。

## 反向代理部署

通过 Nginx 将 Nexus Media 挂到域名下对外访问时，只需代理**前端端口**（compose 示例中为宿主机 `3000`），前端容器内嵌的 nginx 会继续将 `/api`、`/ws` 转发到后端。

!!! warning
    必须配置 WebSocket 转发头，否则日志、进度等实时推送功能不可用。

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name media.example.com;

    location / {
        proxy_pass http://127.0.0.1:3000;

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

## 可选组件：nexus-verify 与 nexus-chrome

两个增强组件，仅在 `full-mysql` / `full-postgresql` profile 下默认启动，也可单独部署：

| 组件 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| nexus-verify | `linyuan0213/nexus-verify` | 9300 | 验证码识别（OCR），用于站点签到、浏览器登录时的验证码自动识别 |
| nexus-chrome | `linyuan0213/nexus-chrome` | 9850 / 6080 | 浏览器内核，用于 Cloudflare 防护站点签到、自动登录更新 Cookie |

### nexus-verify（验证码识别）

```yaml
nexus-verify:
  image: linyuan0213/nexus-verify:latest
  container_name: nexus-verify
  ports:
    - 9300:9300
  restart: always
```

无额外环境变量。部署后在 **系统设置 → 基础设置 → 实验室** 中：

1. 开启「启用验证码识别服务器」
2. 「验证码识别服务器」填写 `http://<宿主机IP>:9300`（compose 同网络内可用 `http://nexus-verify:9300`）

### nexus-chrome（浏览器内核）

```yaml
nexus-chrome:
  image: linyuan0213/nexus-chrome:latest
  container_name: nexus-chrome
  shm_size: 2g
  environment:
    - VNC_PASSWORD=password      # noVNC 访问密码，务必修改
    - SESSION_TTL=1800           # 浏览器会话空闲回收时间（秒）
    - SESSION_CLEANUP_INTERVAL=60  # 会话清理检查间隔（秒）
  volumes:
    - ./data:/var/lib/chromium/user_data   # 持久化浏览器用户数据（登录态等）
  ports:
    - 9850:9850   # DrissionPage 服务，供后端调用
    - 6080:6080   # noVNC 网页版远程桌面，可观察自动化过程
  restart: always
```

!!! warning
    `shm_size: 2g` 必须配置，共享内存不足会导致 Chrome 崩溃；`VNC_PASSWORD` 务必修改为强密码，6080 端口不要直接暴露公网。

部署后在 **系统设置 → 基础设置 → 实验室** 中：

1. 开启「启用网页自动化」
2. 「网页自动化服务器」填写 `http://<宿主机IP>:9850`（compose 同网络内可用 `http://nexus-chrome:9850`）

配置生效后：

- 站点签到遇到验证码时自动 OCR 识别（成功率约 90%）
- Cloudflare / 雷池防护站点可在 [自动签到插件](plugins.md) 中标记为「浏览器站点」，使用真实浏览器签到
- 站点维护中「更新 Cookie」可用浏览器模拟登录自动获取 Cookie 和 UA
- 访问 `http://<宿主机IP>:6080` 打开 noVNC 可实时观察浏览器操作过程

## 环境变量

环境变量优先级：`环境变量 > .env > config.yaml`。除 Docker 镜像专用变量外，其余变量对应 `src/app/core/settings.py` 中的配置节点，使用 `__` 作为嵌套分隔符，例如 `APP__WEB_HOST`、`DATABASE__TYPE`、`REDIS__HOST`。

### Docker 镜像专用变量

**后端镜像 (`linyuan0213/nexus-media`)**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUID` | 0 | 运行用户 UID |
| `PGID` | 0 | 运行用户 GID |
| `UMASK` | 000 | 文件权限掩码 |
| `NEXUS_PORT` | 3000 | 容器内部服务端口 |
| `SKIP_MIGRATION` | false | 设为 `true` 跳过启动时数据库迁移 |
| `TZ` | Asia/Shanghai | 时区 |

**前端镜像 (`linyuan0213/nexus-media-web`)**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKEND_HOST` | `nexus-media` | 后端服务地址（compose 内为服务名，独立部署时设为 IP 或域名） |
| `BACKEND_PORT` | `8080` | 后端服务端口（容器内端口，即 compose 中后端 `host` 端口） |

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
| `REDIS__HOST` | 127.0.0.1 | Redis 地址 |
| `REDIS__PORT` | 6379 | Redis 端口 |
| `REDIS__PASSWORD` | — | Redis 密码 |
| `REDIS__DB` | 0 | Redis 数据库索引 |

### 其他常用变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXUS_MEDIA_CONFIG` | — | 配置文件路径（可选，默认自动发现） |
| `NEXUS_MEDIA_DATA` | — | 数据目录路径（可选，默认 `./data`） |
| `LOG__FORMAT` | text | 设为 `json` 输出 ELK 兼容日志 |

## 目录说明

| 容器路径 | 说明 |
|----------|------|
| `/data` | 配置文件、数据库、插件数据 |
| `/nexus-media` | 应用代码目录 |
| `/media` | 媒体目录（需自行映射） |

## PUID / PGID 说明

- 若同时使用 Emby / Jellyfin / Plex / qBittorrent 等 Docker 镜像，建议保持 PUID / PGID 一致
- 在宿主机上执行 `id -u` 和 `id -g` 获取对应值

## 首次使用

1. 访问前端页面 http://localhost:3000
2. 默认账号密码：
   - 用户名: `admin`
   - 密码: `password`
3. **首次登录后必须修改默认密码**
4. 进入 **设置 > 基础设置 > 媒体** 配置 TMDB API Key（必须）
5. 进入 **设置 > 下载器** 添加下载器
6. 进入 **设置 > 媒体服务器** 添加 Emby/Jellyfin/Plex
7. 进入 **站点 > 站点维护** 添加 PT 站点
