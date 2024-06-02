# NAS媒体库管理工具

### 新增

- 支持 Jackett 和 Prowlarr 索引器
- 支持 Aria2 下载器
- 支持新版馒头刷流和下载
- 3.3.0 以上版本通过 gunicorn 部署，并且依赖redis，其他版本安装请自行安装redis，docker 3.2.6及以下版本需要重新拉取新镜像

### 站点维护

1. 馒头站点维护

   - 添加 User-Agent

   - 不需要模拟登陆只用添加令牌

   1. 令牌获取

      打开馒头 控制台 > 实验室 > 存取令牌 > 建立存取令牌

      1. 复制令牌到 nas-tools 站点维护
      2. 添加请求头参数 格式：{"x-api-key": "令牌"}

   2. 馒头签到

      馒头模拟登录需要添加 auth 参数，通过 auth 访问接口，不排除禁用账户的可能
      添加请求头参数 格式：{"x-api-key": "令牌", "authorization": "auth参数"}

      auth参数获取方式
      ![mt-auth.png](https://raw.github.com/linyuan0213/nas-tools/master/img/mt-auth.png)

2. FSM站点维护

   - 添加 User-Agent

   - API TOKEN 获取方式
     1. 进入站点下拉到最后，找到API链接，点击进入，如图
        ![fsm-api-1.png](https://raw.github.com/linyuan0213/nas-tools/master/img/fsm-api-1.png)
     2. 点击一键生成生成 API TOKEN，如图
        ![fsm-api-2.png](https://raw.github.com/linyuan0213/nas-tools/master/img/fsm-api-2.png)
     3. 添加请求头参数，格式： {"APITOKEN": "这里填 api token"}， 将复制的API TOKEN 填入



### 验证码识别

安装 docker 镜像 [linyuan0213/nas-tools-ocr](https://hub.docker.com/r/linyuan0213/nas-tools-ocr) 

使用 docker-compose 参考 docker/compose.yml 文件

在 nas-tools 设置 > 基础设置 > 实验室 里添加 部署的 ocr 容器网址，格式：http://127.0.0.1:9300

### 插件
待完善



### 开启公开站点

在 config.yaml 的 laboratory 添加 ```show_more_sites: true```



### Docker 镜像地址：

[linyuan0213/nas-tools](https://hub.docker.com/r/linyuan0213/nas-tools)



### 版本更新

#### v3.4.7

##### 功能优化

- 新增 星空 站点

##### 问题修复

- Rss获取数据失败
- 刷流下载失败
- 探索页面数据不更新
- IYUU 插件api更新
- 修复部分资源订阅异常

#### v3.4.6

##### 功能优化

- 新增 库非 HDFun ilolicon 花梨月下 等站点
- U2 通过页面获取发布时间

##### 问题修复

- Transmission 种子属性修复
- CookieCloud 插件同步馒头authorization



### 帮助

TG群： [https://t.me/+UxUIoJMmH2YwYWE1](https://t.me/+UxUIoJMmH2YwYWE1)
