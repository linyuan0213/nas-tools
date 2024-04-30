# NAS媒体库管理工具

### 新增
- 支持 Jackett 和 Prowlarr 索引器
- 支持 Aria2 下载器
- 支持新版馒头刷流和下载
- 3.3.0 以上版本通过 gunicorn 部署，并且依赖redis，其他版本安装请自行安装redis，docker 3.2.6及以下版本需要重新拉取新镜像

### 馒头站点维护

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


### 验证码识别

安装 docker 镜像 [linyuan0213/nas-tools-ocr](https://hub.docker.com/r/linyuan0213/nas-tools-ocr) 

使用 docker-compose 参考 docker/compose.yml 文件

在 nas-tools 设置 > 基础设置 > 实验室 里添加 部署的 ocr 容器网址，格式：http://127.0.0.1:9300

### 插件

- 自定义识别词

  	tmdb id获取：[tmdb](https://www.themoviedb.org/?language=zh-CN) 网站搜索关键词，打开相关电影复制url对应数字id， 如 https://www.themoviedb.org/movie/693134-dune-part-two?language=zh-CN tmdb id 为693134


  - 通用识别词维护：

    	编辑 [通用识别词](https://pad.xcreal.cc/p/通用识别词) 添加关键词
    	
    	格式如下：
    	
    		屏蔽：被替换词
    	
    		替换：被替换词@@替换词
    	
    		替换+集偏移：被替换词@@替换词@@前定位词@@后定位词@@集偏移
    	
    		集偏移：前定位词@@后定位词@@集偏移

  - 电影识别词维护：

    	编辑 [电影识别词](https://pad.xcreal.cc/p/电影识别词) 添加关键词
    	
    	格式如下：
    	
    		屏蔽：tmdb id@@被替换词
    	
    		替换：tmdb id@@被替换词@@替换词
    	
    		替换+集偏移：tmdb id@@被替换词@@替换词@@前定位词@@后定位词@@集偏移
    	
    		集偏移：tmdb id@@前定位词@@后定位词@@集偏移

  - 电视识别词维护：

    	编辑 [电视识别词](https://pad.xcreal.cc/p/电视识别词) 添加关键词

       格式同电影识别词

  - 动漫识别词维护：

    	编辑 [动漫识别词](https://pad.xcreal.cc/p/动漫识别词) 添加关键词

       格式同电影识别词

  

    **如果有好用的识别词，请共同维护**

  

### 开启公开站点

在 config.yaml 的 laboratory 添加 ```show_more_sites: true```

### Docker 镜像地址：

[linyuan0213/nas-tools](https://hub.docker.com/r/linyuan0213/nas-tools)

### 帮助

TG群： [https://t.me/+UxUIoJMmH2YwYWE1](https://t.me/+UxUIoJMmH2YwYWE1)