---
title: 消息通知模板使用指南
description: NAStool 消息通知模板配置和使用说明
date: 2026-03-26
---

# 消息通知模板使用指南

## 概述

NAStool 的消息通知系统支持自定义模板功能，允许用户为不同类型的消息通知自定义标题和内容格式。使用 Jinja2 模板引擎，您可以灵活地控制消息的显示方式，支持富文本、emoji 等丰富的消息格式。

## 功能特性

- **支持多种消息类型**：下载开始、入库完成、订阅成功等
- **Jinja2 模板语法**：支持变量、过滤器、条件判断等高级功能
- **丰富的自定义过滤器**：`filesize`、`datetime`、`default`、`yesno`、`truncatestr`、`striptags`
- **向后兼容**：未配置模板时使用默认消息格式
- **每个客户端独立配置**：不同的消息通知渠道可以有不同的模板
- **emoji 支持**：模板中可以直接使用 emoji 表情符号

## 配置方法

### 1. 进入消息通知设置

1. 打开 NAStool 网页界面
2. 点击左侧菜单的"设置"
3. 选择"消息通知"选项卡
4. 点击"新增消息通知"或编辑现有的消息通知客户端

### 2. 配置模板

在消息通知配置模态框中，展开"模板配置"区域：

1. 点击"模板配置"旁边的展开图标
2. 在文本区域中输入 JSON 格式的模板配置
3. 点击"重置为默认模板"可以快速获取示例模板
4. 点击"保存"应用配置

### 3. 模板配置格式

模板配置使用 JSON 格式，结构如下：

```json
{
  "消息类型": {
    "title": "标题模板",
    "text": "内容模板"
  }
}
```

## 支持的消息类型

| 消息类型 | 对应功能 | 可用变量 |
|---------|---------|---------|
| `download_start` | 开始下载 | `item`, `in_from`, `download_setting_name`, `downloader_name` |
| `transfer_finished` | 入库完成 | `media_info`, `in_from`, `exist_filenum`, `category_flag` |
| `rss_success` | 订阅成功 | `media_info`, `in_from` |
| `download_fail` | 下载失败 | `item`, `error_msg` |
| `transfer_fail` | 转移失败 | `path`, `count`, `text` |
| `site_message` | 站点消息 | `title`, `text` |
| `brushtask_added` | 刷流任务添加 | `title`, `text` |
| `brushtask_remove` | 刷流任务删除 | `title`, `text` |
| `brushtask_pause` | 刷流任务暂停 | `title`, `text` |
| `mediaserver_message` | 媒体服务器消息 | `title`, `text` |
| `auto_remove_torrents` | 自动删种 | `title`, `text` |
| `user_statistics` | 用户统计 | `title`, `text` |
| `site_signin` | 站点签到 | `title`, `text` |
| `custom_message` | 自定义消息 | `title`, `text` |

## 模板语法

### 基本变量

使用双花括号 `{{ }}` 插入变量：

```jinja2
{{ item.get_title_ep_string() }} 开始下载
```

### 过滤器

使用管道符 `|` 应用过滤器：

```jinja2
大小：{{ item.size|filesize }}
```

#### 内置过滤器

| 过滤器 | 说明 | 示例 |
|-------|------|------|
| `filesize` | 格式化文件大小（如 1.5M、2.0K） | `{{ size \| filesize }}` |
| `datetime` | 格式化日期时间 | `{{ timestamp \| datetime('%Y-%m-%d %H:%M') }}` |
| `default` | 设置默认值 | `{{ value \| default('未知') }}` |
| `yesno` | 布尔值转换为是/否 | `{{ hit_and_run \| yesno('是','否') }}` |
| `truncatestr` | 截断字符串 | `{{ text \| truncatestr(100, '...') }}` |
| `striptags` | 去除 HTML 标签 | `{{ html \| striptags }}` |

### 控制结构

支持 Jinja2 的所有控制结构：

```jinja2
{% if item.site == "测试站点" %}
来自测试站点
{% else %}
来自其他站点
{% endif %}
```

### 转义字符

在模板中使用换行符等特殊字符：

```jinja2
第一行\n第二行
```

### Emoji 支持

模板中可以直接使用 emoji 表情符号：

```jinja2
🎬 {{ title }} 开始下载
✅ {{ title }} 已入库
📌 {{ title }} 已添加订阅
```

常用 emoji 推荐：
- 🎬 电影/视频相关
- 📺 电视剧
- 📌 订阅/固定
- ✅ 完成/成功
- ⬇️ 下载
- 💾 大小/存储
- 📦 质量/资源
- 🌐 站点
- 🧲 种子
- 🌱 做种
- ⚡️ 促销
- 🚨 H&R
- ⭐ 评分

## 示例模板

### 下载开始模板（富文本格式）

```json
{
  "download_start": {
    "title": "🎬 {{ title_ep_string|default(item.get_title_ep_string()) }} 开始下载 ⬇️",
    "text": "🌐 站点：{{ site|default(item.site)|default('未知') }} ｜ 💾 大小：{{ size_str|default(item.size|filesize) }}\\n📦 质量：{{ resource_type|default(item.get_resource_type_string())|default('未知') }}\\n\\n🧲 种子：{{ org_string|default(item.org_string)|truncatestr(50) }}\\n🌱 做种：{{ seeders|default(item.seeders)|default(0) }} ｜ ⚡️ 促销：{{ volume_factor|default(item.get_volume_factor_string())|default('未知') }} ｜ 🚨 H&R：{{ hit_and_run|default(item.hit_and_run)|yesno('是','否') }}"
  }
}
```

效果示例：
```
🎬 测试剧集 (2024) S01E05 开始下载 ⬇️
🌐 站点：测试站点 ｜ 💾 大小：1002.54M
📦 质量： WEB-DL 2160p

🧲 种子：Test.Show.2024.S01E05.2160p...
🌱 做种：12 ｜ ⚡️ 促销：免费 ｜ 🚨 H&R：否
```

### 下载开始模板（简洁格式）

```json
{
  "download_start": {
    "title": "{{ title_ep_string|default(item.get_title_ep_string()) }} 开始下载",
    "text": "站点：{{ site|default(item.site) }}\\n大小：{{ size_str|default(item.size|filesize) }}\\n质量：{{ resource_type|default(item.get_resource_type_string())|default('未知') }}"
  }
}
```

### 入库完成模板（富文本格式）

```json
{
  "transfer_finished": {
    "title": "✅ {{ media_info.get_title_string() }} 已入库",
    "text": "⭐ {{ media_info.get_vote_string() }}\\n📺 类型：{{ media_info.type.value }}\\n📦 质量：{{ media_info.get_resource_type_string()|default('未知') }}\\n💾 大小：{{ media_info.size|filesize }}"
  }
}
```

### 订阅成功模板（富文本格式）

```json
{
  "rss_success": {
    "title": "📌 {{ media_info.get_title_string() }} 已添加订阅",
    "text": "⭐ {{ media_info.get_vote_string() }}\\n📺 类型：{{ media_info.type.value }}\\n📅 年份：{{ media_info.year|default('未知') }}"
  }
}
```

## 可用变量详解

### download_start 变量

**简化变量（推荐使用）**：

| 变量名 | 说明 | 示例 |
|-------|------|------|
| `title` | 媒体标题 | 仙逆 |
| `year` | 年份 | 2023 |
| `season` | 季（Sxx格式） | S01 |
| `episode` | 集（Exx格式） | E130 |
| `site` | 站点名称 | 观观 |
| `size` | 文件大小（字节） | 1051234567 |
| `size_str` | 格式化后的大小 | 1002.76M |
| `seeders` | 做种数 | 12 |
| `peers` | 下载者数 | 3 |
| `org_string` | 原始种子名称 | 仙逆.Renegade.Immortal.2023.S01E130.2160p.WEB-DL |
| `description` | 描述（已去除HTML标签） | 种子描述信息... |
| `description_raw` | 原始描述（含HTML） | <p>种子描述...</p> |
| `resource_type` | 资源类型字符串 | WEB-DL 2160p |
| `volume_factor` | 促销因子字符串 | 免费 |
| `hit_and_run` | 是否Hit&Run（布尔值） | false |
| `user_name` | 用户名 | admin |
| `page_url` | 详情页URL | https://site.com/torrent/123 |
| `vote_average` | 评分 | 8.5 |
| `star_string` | 评分星号字符串 | ★★★★☆ (8.5) |
| `title_ep_string` | 标题+季集字符串 | 仙逆 (2023) S01E130 |
| `title_string` | 标题+年份字符串 | 仙逆 (2023) |
| `in_from` | 下载来源对象 |  |
| `in_from.value` | 来源值（搜索/RSS/订阅等） | 搜索 |
| `download_setting_name` | 下载设置名称 | 默认设置 |
| `downloader_name` | 下载器名称 | Transmission |

**完整对象访问**：

- `item`：下载项完整对象，可访问所有属性和方法：
  - `item.title`、`item.year`、`item.site`、`item.size` 等所有字段
  - `item.get_title_ep_string()`：获取标题和集数字符串
  - `item.get_star_string()`：获取评分星号字符串
  - `item.get_resource_type_string()`：获取资源类型字符串
  - `item.get_volume_factor_string()`：获取促销因子字符串

**使用示例**：

```jinja2
{# 使用简化变量 #}
{{ title_ep_string }}
{{ size_str }}
{{ site|default('未知站点') }}

{# 使用完整对象 #}
{{ item.get_title_ep_string() }}
{{ item.size|filesize }}
{{ item.site|default('未知站点') }}
```

### transfer_finished 变量

- `media_info`：媒体信息对象，可直接访问以下字段：
  - `title`：标题
  - `year`：年份
  - `type`：媒体类型对象
    - `type.value`：类型值（"电影"或"电视剧"）
  - `vote_average`：评分
  - `category`：分类
  - `size`：文件大小（字节）
  - `resource_type`：资源类型
  
  也可调用以下方法：
  - `media_info.get_title_string()`：获取标题字符串
  - `media_info.get_vote_string()`：获取评分字符串
  - `media_info.get_resource_type_string()`：获取资源类型字符串

- `in_from`：转移来源
  - `in_from.value`：来源值

- `exist_filenum`：已存在的文件数（整数）
- `category_flag`：二级分类开关（布尔值）

### rss_success 变量

- `media_info`：媒体信息对象（同上）
- `in_from`：订阅来源
  - `in_from.value`：来源值

## 常见问题

### 1. 模板不生效怎么办？

- 检查模板 JSON 格式是否正确
- 确认消息类型名称拼写正确
- 检查变量名是否正确
- 查看系统日志是否有模板渲染错误

### 2. 如何恢复默认模板？

点击"重置为默认模板"按钮，或手动删除模板配置后保存。

### 3. 可以为不同的消息客户端设置不同的模板吗？

是的，每个消息通知客户端都可以独立配置自己的模板。

### 4. 模板支持哪些高级功能？

支持 Jinja2 的所有功能，包括：
- 变量和表达式
- 过滤器和测试
- 条件判断（if/elif/else）
- 循环（for）
- 宏和包含

### 5. 模板配置保存失败？

- 检查 JSON 格式是否正确
- 确保没有语法错误
- 查看浏览器控制台是否有错误信息

## 最佳实践

1. **先测试后应用**：配置模板后，先使用"测试"功能验证模板是否正确渲染
2. **保持简洁**：模板不宜过于复杂，确保消息清晰易读
3. **备份配置**：重要的模板配置建议备份
4. **逐步迁移**：可以先为最常用的消息类型配置模板，逐步完善

## 更新日志

- **2026-03-15**：首次发布消息通知模板功能
  - 支持 Jinja2 模板引擎
  - 内置 filesize 过滤器
  - 支持多种消息类型
  - 提供默认模板示例