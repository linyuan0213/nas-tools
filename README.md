# NAS媒体库管理工具

- 新增更新：

              支持 Jackett 和 Prowlarr 索引器
              支持Aria2下载器
              支持新版馒头刷流和下载

- 馒头站点维护： cookie 和 令牌 二选一（建议使用令牌、如使用令牌 cookie栏 建议项不填写，留空）

   cookie获取：
  
              1.按F12
              2.点击网络
              3.刷新网页查看网络界面的变化
              4.点击网络界面下的标题
              5.找到Cookie并复制后面内容
    
   令牌获取：
  
           1、馒头控制台 > 实验室 > 令牌 > 建立开放令牌令牌
           2、复制令牌到nas-tools站点维护
           3、添加请求头参数格式：{"x-api-key": "xxxx"}

- 开启公开站点：

           在 config.yaml 的实验室添加``` show_more_sites: true ```


# docker参数：
docker 运行 -d \
    --name nas-tools \
    -- 主机名 nas-tools \
    -p 3000:3000       ` #默认的webui控制端口`       \
    -v $(pwd)/config:/config          ` # 左边冒号请为你想在主机上保存配置文件的路径`           \
    -v /你的媒体目录:/你想设置的容器内能看到的目录    ` #媒体目录，多个目录需要分别映射入口`           \
    -e PUID=0               ` # 想切换为哪个用户来运行程序，该用户的uid，见下方说明`          \
    -e PGID=0             ` # 想切换为哪个用户来运行程序，该用户的gid，见下方说明`        \
    -e UMASK=000         ` # 掩码权限，默认000，可以考虑设置为022 `        \
    -e NASTOOL_AUTO_UPDATE=false ` #底座在启动时容器自动升级程序请设置为true `        \
    -e NASTOOL_CN_UPDATE=false ` # 如果开启了容器启动自动升级程序，并且网络不太友好时，可以设置为true，会使用国内源进行软件更新` \

1、资源搜索和订阅
站点RSS聚合，想看的加入订阅，资源自动实时追新。
通过微信、Telegram、Slack、Synology Chat或者WEB界面聚合资源搜索下载，最新热门资源一键搜索或者订阅。
与豆瓣联动，在豆瓣中标记想看后台自动检索下载，未出全的自动加入订阅。
2、媒体库整理
监控下载软件，下载完成后自动识别真实名称，硬链接到媒体库并重命名。
对目录进行监控，文件变化时自动识别媒体信息硬链接到媒体库并重命名。
解决种与媒体库整理冲突的问题，专为中文环境优化，支持自制和，重命名动漫准确率高，改名后Emby/Jellyfin/Plex完美剪裁海报墙。
三、站点作业
全面的站点数据统计，实时监测您的站点流量情况。
全自动化托管养站，支持远程下载器（本工具内建刷流功能分区日常养站使用，如果追求数据建议使用更加强大的刷流工具：Vertex）。
站点每日自动登录保号。
4、消息服务
支持微信、Telegram、Slack、Synology Chat、Bark、PushPlus、爱语飞飞等近十种渠道图文消息通知
支持通过微信、Telegram、Slack、Synology Chat远程控制订阅和下载。
Emby/Jellyfin/Plex播放状态通知。

2、本地运行
python3.10版本，需要预安装cython，如发现缺少依赖包需额外安装

git clone -b master https://github.com/linyuan0213/nas-tools --recurse-submodule
python3 -m pip install -r 要求.txt
导出NASTOOL_CONFIG="/xxx/config/config.yaml"
nohup python3 run.py &


配置
1、申请相关API KEY
申请TMDB用户，在https://www.themoviedb.org/ 申请用户，获得API KEY。

申请消息通知服务

微信（推荐）：在https://work.weixin.qq.com/ 申请企业微信自建应用，获取企业ID、自建应用秘密、代理ID，微信扫描自建应用二维码可在微信中使用实现消息服务，无需打开企业微信
Telegram（推荐）：关注BotFather申请机器人获取token，关注getuserID获取chat_id。该渠道支持远程控制，详情参考：“5、配置微信/Telegram/Slack/Synology Chat远程控制”。
Slack：在 https://api.slack.com/apps 申请应用，该渠道支持远程控制，详情请参阅频道说明。
Synology Chat：在群晖中安装 Synology Chat 套件，点击聊天界面“右上角头像->集成->机器人”创建机器人，“传出URL”设置为：“NAStool地址/synology”，“确定URL”及“令牌”填入NAStool消息服务设置中，该渠道支持远程控制。
其他：仍然会持续增加对通知渠道的支持，API KEY获取方式类似，不一一说明。
2、基础配置
文件转移模式说明： 目前支持六种模式：复制、硬链接、软链接、移动、RCLONE、MINIO。

复制模式下载做种和媒体库是两份，多占用存储（下载盘大小决定能保多少种），好处是媒体库的盘不用24小时运行可以休眠；

硬链接模式不用额外增加存储空间，单独的文件两份目录，但需要在一个磁盘分区或者存储空间上下载目录和媒体库目录；软链接模式就是快捷方式，需要容器内路径与真实路径一致才能正常使用；

移动模式会移动和删除原文件及目录；

RCLONE模式仅针对RCLONE网盘使用场景，注意，使用RCLONE模式需要自行映射rclone配置目录到容器中，具体参考设置项小问号说明；

MINIO只针对S3/云电影场景，注意，使用MINIO，媒体库应设置为/bucket名/类别名，例如，bucket的名字叫cloud，电影的分类文件夹名为movie，则媒体库路径为： / cloud/movie，最好的母集用s3fs挂载到/cloud/movie，欣赏就行。

启动程序并配置：Docker默认使用3000端口启动（群晖套件默认3003端口），默认密码用户：admin/password（docker需要参考教程提前映射好端口、下载目录、媒体库目录）。登录管理界面后，在设置中根据WEB页面中每个配置项的提示修改好配置并重启生效（基础设置中有标红星是必须要配置的，如TMDB APIKEY等），每个配置项后都有小问号，点击有详细的配置说明，推荐阅读。

3、设置媒体库服务器
支持Emby（推荐）、Jellyfin、Plex，设置媒体服务器后可以对本地资源进行判重避免重复下载，同时能标识本地已存在的资源：

在Emby/Jellyfin/Plex的Webhook插件中，设置地址为：http(s)://IP:PORT/emby、jellyfin、plex，用于接收播放通知（任选）
将Emby/Jellyfin/Plex的相关信息配置到”设置-》媒体服务器“中
如果启用了默认分类，需按如下的目录结构分别设置好媒体库；如是自定义分类，请按自己的定义建立好媒体库目录，分类定义请参考default-category.yaml分类配置文件模板。注意，开启二级分类时，媒体库需要将目录设置到二级分类子目录中（可添加多个子目录到一个媒体库，也可以一个子目录设置一个媒体库），否则媒体库管理软件可能无法正常搜刮识别。
电影

精选 华语电影 外语电影 动画电影

电视剧

国产剧 欧美剧 日韩剧 动漫 综艺 儿童

4、配置下载器及下载目录
支持qbittorrent（推荐）、transmission、aria2、115网盘、pikpak网盘等，右上角按钮设置好下载目录。

5、配置同步目录
目录同步可以对多个分散的文件夹进行监控，文件夹中有新增媒体文件时会自动进行识别重命名，并按配置的转移方式转移到媒体库目录或指定的目录中。
如将下载软件的下载目录也纳入目录同步范围的，建议关闭下载软件监控功能，否则会触发重复处理。
5、配置微信/Telegram/Slack/Synology Chat远程控制
配置好微信、Telegram、Slack或Synology聊天机器人后，可以直接通过移动端发送名字实现自动搜索下载，以及通过菜单控制程序运行。

微信消息及回调
配置消息主动代理
由于微信官方限制，2022年6月20日后创建的企业微信应用需要有固定的公网IP地址并加入IP白名单后才能接收到消息，使用有固定公网IP的代理服务器转发可解决该问题

如果使用Nginx搭建代理服务，需在配置中增加以下代理配置：
````
位置 /cgi-bin/gettoken {
  proxy_pass https://qyapi.weixin.qq.com；
}
位置/cgi-bin/消息/发送{
  proxy_pass https://qyapi.weixin.qq.com；
}
````

如使用Caddy搭建代理服务，需在配置中增加以下代理配置（` {upstream_hostport} `部分不是变量，不要改过去，原封不动复制粘贴即可）。
````
反向代理 https://qyapi.weixin.qq.com {
  header_up 主机 {upstream_hostport}
}
````

如果使用Traefik 搭建代理服务，需要额外配置：
````
loadBalancer.passHostHeader=false
````

注意：代理服务器仅适用于在微信中接收工具主动的消息，消息回调与代理服务器无关。
配置微信消息接收服务在企业微信自建应用管理页面-》API接收消息开启消息接收服务：

在微信页面生成Token和EncodingAESKey，并在NASTool设置->消息通知->微信中填入对应的输入项并保存。

重启 NAS 工具。

微信页面地址URL填写：http(s)://IP:PORT/wechat，点确定进行认证。

配置微信菜单控制，通过菜单远程控制工具运行，在https://work.weixin.qq.com/wework_admin/frame#apps应用菜单自定义页面按如下图所示维护好菜单，菜单内容为发送消息，消息内容随意。

一级菜单及一级菜单下的前几个子菜单顺序需要一模一样，在符合截图的示例项后可以自己添加其他二级菜单项。



Telegram Bot机器人
在NASTool设置中设置好本程序的外网访问地址，根据实际网络情况决定是否打开Telegram Webhook开关。
注意：WebHook受Telegram限制，程序运行端口需要设置为以下端口之一：443, 80, 88, 8443，且需要有以网络认证的Https证书；非WebHook模式时，不能使用NAStool内建的SSL证书功能。

在Telegram BotFather机器人中点击表维护好bot命令菜单（要选），菜单选择或输入命令运行应答服务，输入其他内容则启动聚合搜索。
松弛
详情参考频道说明
命令与功能对应关系

命令功能
/rss RSS 订阅
/ssa 订阅搜索
/ptt 下载文件转移
/ptr 自动删种
/pts 站点签到
/udt 系统更新
/tbl 清理转移服务器
/trh 清理RSS服务器
/rst 目录同步
/db 豆瓣想看
/utf 重新识别
Synology 聊天
消耗额外设置，注意非同一服务器架构的，还需要在基础设置->安全中调整IP地址限制策略。
6、配置索引器
配置索引器，以支持搜索站点资源：

本工具内建索引器目前已支持大部分主流PT站点及部分公开站点，建议启用内建索引器。
同时支持Jackett/Prowlarr，需额外搭建对应服务并获取API Key以及地址等信息，配置到设置->索引器->Jackett/Prowlarr中。
7、配置站点
本工具的电视剧订阅、资源搜索、站点数据统计、刷流、自动签到等功能均依赖于正确配置站点信息，需要在“站点管理->站点维护”中维护好站点RSS链接以及Cookie等。

其中站点RSS链接生成时请先选择影视类资源分类，并勾选副标题。

8、整理存量媒体资源
如果你的存量资源所在的目录与你目录同步中配置的源路径目的路径相同，则可以通过WEBUI或微信/Telegram的“目录同步”按钮触发全量同步。

如果不同则可以按以下说明操作，手动输入命令整理特定目录下的媒体资源：

说明：-d 参数为可选，如不输入自动区分电影/电视剧/分别存储到对应的媒体库目录中；-d 参数有输入时则不管类型，都往-d目录中转移。

Docker版本，修改机器上运行以下命令，nas-tools修改为你的docker名称，源目录和目的目录参数。
docker exec -it nas-tools sh
python3 /nas-tools/app/filetransfer.py -m link -s /from/path -d /to/path
群晖套件版本，ssh到后台运行以下命令，同样修改配置文件路径以及源目录、目的目录参数。
导出NASTOOL_CONFIG=/var/packages/NASTool/target/config/config.yaml
/var/packages/py3k/target/usr/local/bin/python3 /var/packages/NASTool/target/app/filetransfer.py -m link -s /from/path -d /to/path
本地直接运行的，cd到程序根目录，执行以下命令，修改配置文件、源目录和目的目录参数。
导出NASTOOL_CONFIG=config/config.yaml
python3 app/filetransfer.py -m link -s /from/path -d /to/path


### Docker镜像地址：

[ linyuan0213/nas-tools ] ( https://hub.docker.com/r/linyuan0213/nas-tools )

### 帮助

TG群：[ https://t.me/+UxUIoJMmH2YwYWE1 ] ( https://t.me/+UxUIoJMmH2YwYWE1 )
