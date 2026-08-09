COMMANDS = {
    "/ptt": "下载文件转移",
    "/ptr": "自动删种",
    "/sub": "订阅监控",
    "/rst": "目录同步",
    "/utf": "重新识别",
    "/clr": "清理缓存",
    "/udt": "重启",
    "/sta": "站点数据统计",
}

# /rss、/ssa 不再是独立命令（与 /sub 语义重复），仅作为文本搜索语法前缀保留
# （如 "/rss 进击的巨人" 触发媒体搜索）

WECHAT_MENU = [
    {"name": "下载", "commands": ["/ptt", "/ptr", "/sub"]},
    {"name": "同步", "commands": ["/rst", "/utf"]},
    {"name": "管理", "commands": ["/clr", "/udt", "/sta"]},
]

# 插件命令将自动追加到"管理"分组（微信菜单最多5个子按钮）
WECHAT_PLUGIN_GROUP = "管理"
