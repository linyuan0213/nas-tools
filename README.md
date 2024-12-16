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

### 网页自动化（仿真）
安装 docker 镜像 linyuan0213/nas-tools-chrome

使用 docker-compose 参考 docker/compose.yml 文件

在 nas-tools 设置 > 基础设置 > 实验室 里添加 部署的 chrome 容器网址，格式：http://127.0.0.1:9850

### 插件

待完善


### 开启公开站点

在 config.yaml 的 laboratory 添加 ```show_more_sites: true```



### Docker 镜像地址：

[linyuan0213/nas-tools](https://hub.docker.com/r/linyuan0213/nas-tools)



### 版本更新

#### v3.6.2

##### 功能优化
- 支持 YemaPT 和 OurBits签到
- 仿真拆分，支持大部分PT站点

##### 问题修复
- NT 推送下载不自动开始
- 数据统计部分站点显示问题
- 刷流时间间隔支持多个时间段
- 刷流时间间隔支持跨天

#### v3.6.1

##### 功能优化
- 支持 Qbittorrent 5.0.1

##### 问题修复
- 群辉机器人部分消息发送失败
- IYUU API域名修复

#### v3.6.0

##### 功能优化
- 刷流
   - 支持排除订阅
   - 支持与模式
   - 支持种子Free到期删除
   - 支持磁盘剩余空间不足删除
   - 支持开启时间段
- 支持 柠檬、PTLGS 站点

##### 问题修复
- 刷流Free种子到期不暂停
- 刷流平均上传速度通过 Qbittorrent API 获取
- 刷流删种不执行
- 自动订阅默认设置不生效
- 群辉机器人发送消息失败
- 部分Rss获取数据失败
- 配置文件修改乱码
- 种子标记部分站点标记错误

#### v3.5.7

##### 功能优化
- CookieCloud支持黑白名单
- 企业微信插件运行时自动同步CookieCloud
- 支持星空站点
- FSM 获取注册时间
- 站点访问增加重试机制

##### 问题修复
- Yema获取发布时间失败
- 观众获取流量数据失败
- 修复PTT副标题显示
- 部分馒头资源获取不到下载链接
- 海胆之家、象岛、高清杜比部分字段缺失

#### v3.5.6

##### 功能优化
- 新增企业微信可信IP更新插件
- 新增熊猫、海胆之家站点
- Qbittorrent api 支持 4.6.5
- 签到插件支持仿真

##### 问题修复
- Cloudflare 验证失败
- OpenCD刷流
- 部分站点rss和网页发布时间不统一
- 移除自定义识别词TMDB分组
- 调度重启不自动执行
- 副标题没有集数无法订阅
- socks5h 支持

#### v3.5.5

##### 问题修复
- 修复索引器分类搜索
- 修复解析副标题集数失败
- 订阅搜索报错

#### v3.5.4

##### 问题修复
- 修复多语言搜索数据库异常
- 修复馒头 观众获取做种总量失败
- 瓣订阅近期动态定时任务时间错误
- 高级搜索tmdb报错

#### v3.5.3

##### 问题修复
- 修复订阅数据库异常
- 修复部分剧集转移失败
- 索引器重启清除统计数据

#### v3.5.2

##### 功能优化
- 自定义识别词支持使用TMDB分组
- 增加多语言切换按钮
- 增加BT站点显示按钮

##### 问题修复
- 修复仿真打开浏览器失败
- 单站测试点击不显示测试结果
- 修复部分电视剧显示集数的问题

#### v3.5.1

##### 问题修复
- 订阅功能优化

#### v3.5.0

##### 功能优化

- 订阅搜索支持多语言搜索
- 支持单站连通性测试
- 支持重启
##### 问题修复

- 站点粤语标签缺失
- YemaPT 等级和标签显示
- YemaPT Rss获取失败
- M-Team 签到插件修复以及Rss连接修复
- 刷新媒体库插件 异常修复
- HDVIDEO HR修复
- 下载管理手动添加磁力链接失败修复

#### v3.4.10

##### 功能优化

- 新增识别历史记录清除选项
- 搜索订阅 6小时限制放宽至2小时

##### 问题修复

- 馒头 碟粉 SSD 末日种子库等标签缺失

- 文件识别失败读取上级文件夹

  

#### v3.4.9

##### 问题修复

- CookieCloud 更新失败
- Monika 刷流失败
- 天空 碟粉 红豆饭 副标题缺失
- 刷流删种调度失效
- 仿真代理失效
- YemaPT 做种体积缺失
- 52pt 学校 末日种子库 ICC2022 添加 HR 过滤
- 限速插件启动失败

#### v3.4.8

##### 功能优化

- 新增 YemaPT DogPT

##### 问题修复

- 馒头刷流下载失败
- Ubits刷流 HR不生效


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

### 已支持站点

|       站点名        | 刷流 | 搜索订阅 |
| :-----------------: | :--: | :------: |
|    OurBits/我堡     |  ✅   |    ✅     |
|       海棠PT        |  ✅   |    ✅     |
|     Azusa/梓喵      |  ✅   |    ✅     |
|       聆音PT        |  ✅   |    ✅     |
|        红叶         |  ✅   |    ✅     |
|        UBits        |  ✅   |    ✅     |
|  Hd Dolby/高清杜比  |  ✅   |    ✅     |
|        朋友         |  ✅   |    ✅     |
|   CyanBug/大青虫    |  ✅   |    ✅     |
|    PTHome/铂金家    |  ✅   |    ✅     |
|       HDZone        |  ✅   |    ✅     |
|  PTChina/铂金学院   |  ✅   |    ✅     |
|      Pig/猪猪       |  ✅   |    ✅     |
|       HDmayi        |  ✅   |    ✅     |
|      ZmPT/织梦      |  ✅   |    ✅     |
|       OshenPT       |  ✅   |    ✅     |
|  wintersakura/冬樱  |  ✅   |    ✅     |
|     HHCLUB/憨憨     |  ✅   |    ✅     |
|        CarPT        |  ✅   |    ✅     |
|       百川PT        |  ✅   |    ✅     |
|        蝶粉         |  ✅   |    ✅     |
|      FileList       |  ✅   |    ✅     |
|     好多油/HDU      |  ✅   |    ✅     |
|       PT时间        |  ✅   |    ✅     |
|       ultrahd       |  ✅   |    ✅     |
|       HDVIDEO       |  ✅   |    ✅     |
|        朱雀         |  ✅   |    ✅     |
|       北洋园        |  ✅   |    ✅     |
|        明教         |  ✅   |    ✅     |
|    兽站/HD4FANS     |  ✅   |    ✅     |
|        JPTV         |  ✅   |    ✅     |
|       彩虹岛        |  ✅   |    ✅     |
|     老师/NicePT     |  ✅   |    ✅     |
|     家园/HDHome     |  ✅   |    ✅     |
| 莫妮卡/MONIKADESIGN |  ✅   |    ✅     |
|        1PTBA        |  ✅   |    ✅     |
|         TTG         |  ✅   |    ✅     |
|        学校         |  ✅   |    ✅     |
|    CinemaGeddon     |  ✅   |    ✅     |
|    TorrentLeech     |  ✅   |    ✅     |
|     天空/HDSky      |  ✅   |    ✅     |
|        52pt         |  ✅   |    ✅     |
|         IPT         |  ✅   |    ✅     |
|        葡萄         |  ✅   |    ✅     |
|    红豆饭/HDFans    |  ✅   |    ✅     |
|        南洋         |  ✅   |    ✅     |
|       Uploads       |  ✅   |    ✅     |
|       伊甸园        |  ✅   |    ✅     |
|     馒头/M-Team     |  ✅   |    ✅     |
|     吐鲁番/TLF      |  ✅   |    ✅     |
|       HDTime        |  ✅   |    ✅     |
|       2xFree        |  ✅   |    ✅     |
|      春天/SSD       |  ✅   |    ✅     |
|        观众         |  ✅   |    ✅     |
|       龙之家        |  ✅   |    ✅     |
|      幼儿园/U2      |  ✅   |    ✅     |
|   阿童木/HDATMOS    |  ✅   |    ✅     |
|  自由农场/FreeFarm  |  ✅   |    ✅     |
|   高清视界/HDArea   |  ✅   |    ✅     |
|     开心/JoyHD      |  ✅   |    ✅     |
|    他吹吹风/TCCF    |  ✅   |    ✅     |
|   冰淇淋/ICC2022    |  ✅   |    ✅     |
|    天雪/SkySnow     |  ✅   |    ✅     |
|   烧包乐园/ptsbao   |  ✅   |    ✅     |
|   猫站/PTer Club    |  ✅   |    ✅     |
|    麒麟/HDKylin     |  ✅   |    ✅     |
|        OKPT         |  ✅   |    ✅     |
|  花梨月下/ECUST PT  |  ✅   |    ✅     |
|     肉丝/ROUSI      |  ✅   |    ✅     |
|  末日种子库/AGSVPT  |  ✅   |    ✅     |
|        打胶         |  ✅   |    ✅     |
|        咖啡         |  ✅   |    ✅     |
|        象岛         |  ✅   |    ✅     |
|  飞天拉面神教/FSM   |  ✅   |    ❌     |
|        青蛙         |  ✅   |    ✅     |
|        ToSky        |  ✅   |    ✅     |
|     ilolicon PT     |  ✅   |    ✅     |
|        库非         |  ✅   |    ✅     |
|        HDFun        |  ✅   |    ✅     |
|        星空         |  ✅   |    ✅     |
|       YemaPT        |  ✅   |    ✅     |
|        DogPT        |  ✅   |    ✅     |
|        海胆之家        |  ✅   |    ✅     |
|        熊猫/PANDA        |  ✅   |    ✅     |
|        PTLGS        |  ✅   |    ✅     |
|        柠檬        |  ✅   |    ✅     |