# Nexus Media - 多功能媒体库管理工具

[![CI](https://github.com/linyuan0213/nexus-media/actions/workflows/ci.yml/badge.svg)](https://github.com/linyuan0213/nexus-media/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/linyuan0213/nexus-media)](https://hub.docker.com/r/linyuan0213/nexus-media)
[![Telegram Group](https://img.shields.io/badge/Telegram-Group-blue)](https://t.me/+UxUIoJMmH2YwYWE1)

Nexus Media 是一个功能强大的媒体库管理工具，提供自动化追剧、资源下载、文件整理和订阅管理等功能，适合PT用户和影视爱好者使用。

## 文档目录

### 安装部署
- [安装指南](docs/installation.md) - Docker 和 Docker Compose 安装说明
### 使用配置
- [基础配置](docs/configuration.md) - 系统基础设置详解
- [AI 助手](docs/agent.md) - 消息中心对话式操作全系统
- [资源搜索与探索](docs/search.md) - 搜索、探索与媒体详情
- [站点配置](docs/sites.md) - PT 站点添加、签到与刷流
- [过滤规则](docs/filter_rules.md) - 资源筛选规则组配置
- [下载管理](docs/download_management.md) - 下载器、下载设置、自动删种
- [下载器配置](docs/downloaders.md) - QB/TR/迅雷等下载器详细配置
- [媒体服务器配置](docs/media_servers.md) - Emby/Jellyfin/Plex/FnOS 配置
- [目录同步](docs/directory_sync.md) - 媒体目录同步与转移
- [媒体库](docs/media_library.md) - 媒体库管理与识别
- [媒体整理](docs/media_organization.md) - 识别历史、文件管理、未识别处理
- [RSS 订阅](docs/rss.md) - 电影/电视剧订阅管理
- [索引器配置](docs/indexers.md) - 内建/Jackett/Prowlarr 索引器配置
- [通知渠道配置](docs/notifications.md) - 通知渠道配置详解
- [消息通知模板](docs/message_templates.md) - 通知渠道与模板配置
- [服务与调度](docs/service.md) - 服务面板与调度任务
- [存储后端](docs/storage.md) - 本地/WebDAV/SMB/S3 等存储后端
- [用户与权限](docs/users.md) - 用户/角色/API Key 管理

### 插件
- [插件使用](docs/plugins.md) - 内置插件配置（签到、CookieCloud 等）
- [插件开发](docs/plugin_development_guide.md) - 插件开发完整指南

### 开发
- [本地开发](docs/development.md) - 开发环境搭建与项目结构

### 其他
- [常见问题](docs/faq.md) - 安装、识别、下载等常见问题
- [版本历史](docs/changelog.md) - 版本更新记录

## 主要功能

- **AI 助手**：消息中心对话式操作，支持资源搜索、订阅、下载与知识库问答，可展示思考过程
- **自动下载**：支持多种PT站点资源自动下载
- **媒体管理**：自动识别和整理媒体文件
- **订阅系统**：RSS自动订阅和手动订阅
- **刷流功能**：支持多种PT站点自动刷流
- **插件系统**：可扩展的功能插件

## 支持站点
- 站点适配需求请在[nexus-media-sites项目](https://github.com/linyuan0213/nexus-media-sites)提issues
- 如需新增站点支持，请在[nexus-media-sites项目](https://github.com/linyuan0213/nexus-media-sites)提issues

## 贡献指南

- [CONTRIBUTING.md](CONTRIBUTING.md) — 分支模型、提交规范、代码规范
- [架构文档](docs/architecture.md) — 后端模块分层与数据流

## 支持与帮助
- 问题反馈: [GitHub Issues](https://github.com/linyuan0213/nexus-media/issues)
- 交流群组: [Telegram群组](https://t.me/+UxUIoJMmH2YwYWE1)
- 文档贡献: 欢迎提交 Pull Request 改进文档

## 许可证

本项目采用 [MIT License](LICENSE.md) 开源协议
