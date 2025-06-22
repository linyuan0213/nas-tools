# 安装指南

## Docker 安装

### 方式一：使用docker-compose
1. 创建docker-compose.yml文件：
```yaml
version: "3"
services:
  nas-tools:
    image: linyuan0213/nas-tools:latest
    ports:
      - 3000:3000        # 默认的webui控制端口
    volumes:
      - ./config:/config   # 冒号左边请修改为你想保存配置的路径
      - /你的媒体目录:/你想设置的容器内能见到的目录   # 媒体目录，多个目录需要分别映射进来
    environment: 
      - PUID=0    # 用户uid
      - PGID=0    # 用户gid
      - UMASK=000 # 掩码权限，默认000
      - NT_PORT=3000 # web端口，默认3000
    restart: always
    network_mode: bridge
    hostname: nas-tools
    container_name: nas-tools
    depends_on:
      - ocr
      - chrome

  ocr:
    image: linyuan0213/nas-tools-ocr:latest
    container_name: nas-tools-ocr
    ports:
      - 9300:9300
    restart: always

  chrome:
    image: linyuan0213/nas-tools-chrome:latest
    container_name: nas-tools-chrome
    shm_size: 2g # 共享内存大小
    ports:
      - 9850:9850
    restart: always
```

2. 启动服务：
```bash
docker-compose up -d
```

### 方式二：直接运行docker命令
```bash
# 主服务
docker run -d \
    --name nas-tools \
    --hostname nas-tools \
    -p 3000:3000   `# 默认的webui控制端口` \
    -v $(pwd)/config:/config  `# 冒号左边请修改为你想在主机上保存配置文件的路径` \
    -v /你的媒体目录:/你想设置的容器内能见到的目录 `# 媒体目录，多个目录需要分别映射进来` \
    -e PUID=0     `# 想切换为哪个用户来运行程序，该用户的uid` \
    -e PGID=0     `# 想切换为哪个用户来运行程序，该用户的gid` \
    -e UMASK=000  `# 掩码权限，默认000，可以考虑设置为022` \
    linyuan0213/nas-tools:latest

# OCR服务（可选，用于验证码识别）
docker run -d \
    --name nas-tools-ocr \
    -p 9300:9300 \
    linyuan0213/nas-tools-ocr:latest

# Chrome服务（可选，用于网页自动化）
docker run -d \
    --name nas-tools-chrome \
    -p 9850:9850 \
    --shm-size=2g `# 共享内存大小` \
    linyuan0213/nas-tools-chrome:latest
```
