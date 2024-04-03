# NAS媒体库管理工具

### 新增

- 支持 Jackett 和 Prowlarr 索引器
- 支持 Aria2 下载器
- 支持新版馒头刷流和下载

### 馒头站点维护

- 添加 User-Agent

- cookie 和 令牌 二选一，建议使用令牌

  1. cookie 获取

     1. 按下F12
     2. 点击Network 
     3. 刷新网页查看Network界面的变化 
     4. 点击Network界面下的Headers 
     5. 找到Cookie并复制后面内容

  2. 令牌获取

     打开馒头 控制台 > 实验室 > 存取令牌 > 建立存取令牌

     1. 复制令牌到 nas-tools 站点维护
     2. 添加请求头参数 格式：{"x-api-key": "xxxx"}

### 开启公开站点

在 config.yaml 的 laboratory 添加 ```show_more_sites: true```

### Docker 镜像地址：

[linyuan0213/nas-tools](https://hub.docker.com/r/linyuan0213/nas-tools)