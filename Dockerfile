# 使用多阶段构建优化镜像大小
FROM python:3.11-alpine3.19 AS builder

# 减少 COPY 操作的次数
COPY ./package_list.txt /tmp/
# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 安装依赖，安装 rclone 和 mc，清理无用文件
RUN apk add --no-cache $(cat /tmp/package_list.txt) \
    && curl -sSL https://rclone.org/install.sh | bash \
    && ARCH=$(case "$(uname -m)" in x86_64) echo "amd64";; aarch64) echo "arm64";; esac) \
    && curl -sSL https://dl.min.io/client/mc/release/linux-${ARCH}/mc -o /usr/bin/mc \
    && chmod +x /usr/bin/mc \
    && rm -rf /tmp/* /root/.cache /var/cache/apk/*

# 添加 rootfs 文件
COPY --chmod=755 ./docker/rootfs /

# 最小化的运行时镜像
FROM scratch AS app

# 复制 builder 阶段的内容到运行时
COPY --from=builder / /

# 设置环境变量
ENV S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    PS1="\u@\h:\w \$ " \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    ALPINE_MIRROR="mirrors.ustc.edu.cn" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    NT_PORT=3000 \
    WORKDIR="/nas-tools"

# 创建必要的目录
RUN mkdir -p ${WORKDIR} ${HOME}

# 复制应用代码到镜像
ADD ./ ${WORKDIR}/

WORKDIR ${WORKDIR}
# 添加用户和用户组，并设置系统参数
RUN apk add --no-cache --virtual .build-deps \
            libffi-dev \
            gcc \
            musl-dev \
            libxml2-dev \
            libxslt-dev \
    && addgroup -S nt -g 911 \
    && adduser -S nt -G nt -h ${HOME} -s /bin/bash -u 911 \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo 'vm.overcommit_memory=1' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && uv sync --frozen --no-cache\
    && apk del --purge .build-deps \
    && rm -rf /tmp/* /root/.cache /var/cache/apk/*

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --retries=3 \
    CMD wget -qO- http://localhost:${NT_PORT}/healthcheck || exit 1

# 暴露端口
EXPOSE ${NT_PORT}

# 挂载配置目录
VOLUME ["/config"]

# 启动入口
ENTRYPOINT ["/init"]