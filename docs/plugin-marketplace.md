# 远程插件市场设计文档（Plugin Marketplace）

> 目标：让插件具备“从远程 URL 获取 / 安装 / 更新 / 管理”的能力，支持第三方插件市场源；同步完善插件 `category`/`tags` 标签体系与前端市场页体验。

## 1. 背景与目标

现状：插件通过本地 zip（`registry.install`）或内置插件目录安装，无在线发现/更新渠道；`manifest.category` 自由文本、`tags` 无规范，前端缺少统一筛选与呈现。

本方案要解决：

1. **发现**：增加“插件市场”页，从已配置的市场源浏览、搜索、筛选插件；
2. **安装/更新**：一键安装第三方插件，检测并提示版本更新；
3. **第三方市场规范**：发布一份开放的市场索引 + 插件包规范，任何人可搭建自己的插件源（静态托管即可）；
4. **安全**：内容哈希校验、可选的发布者签名、URL 源白名单/信任管理、安装沙箱约束；
5. **标签完善**：定义标准 `category` 词表与推荐 `tags` 词表，约束 manifest 与市场索引，支撑分类浏览和打标展示。

## 2. 术语

| 术语 | 含义 |
|---|---|
| 插件源（Market Source） | 一个远程 URL，指向市场索引文件 |
| 市场索引（market index） | 目录式索引：根 `catalog.json` 目录清单 + `plugins/<id>.json` 单插件详情 |
| 插件包（plugin package） | zip，包含 `manifest.json` + 前后端代码/资源 |
| 发布者签名 | 可选的 Ed25519 签名，用于验证插件包与索引未被篡改 |

## 3. 插件包与发布规范

### 3.1 包结构（zip）

```
demo-plugin@1.0.0.zip
├── manifest.json
├── backend/            # 可选：python 插件后端（backend.entry 指向）
├── frontend/           # 可选：前端组件/页面资源
└── (静态资源…)
```

### 3.2 manifest 关键字段（含标签完善）

与现有 `PluginManifest` 兼容，`category/tags` 改为受约束字段：

```json
{
  "manifest_version": "1.0",
  "id": "demo_plugin",
  "name": "示例插件",
  "version": "1.0.0",
  "author": "xxx",
  "author_url": "https://github.com/xxx",
  "description": "…",
  "category": "automation",        // 见 7.1 分类词表
  "tags": ["autosignin", "site"],  // 见 7.2 标签词表（仅允许词表内或命名空间标签）
  "min_app_version": "4.16.0",     // 兼容性门槛（semver，主版本需一致）
  "backend": { "entry": "…", "tools": [], "permissions": [] },
  "frontend": { "routes": [], "settings": {}, "slots": [] }
}
```

### 3.3 包校验元数据（发布到市场索引时附带）

- `sha256`：zip 文件内容哈希（必填，安装前强校验）；
- `signature`（可选）：对 `sha256` 的 Ed25519 签名，配合“签名公钥指纹”的信任源启用严格校验；
- `size`：字节数；
- `download_url`：zip 下载地址（可为相对路径）。

### 3.4 命名、内置共存与覆盖策略

**来源身份模型**

| 来源类型 | 是否可删 | 说明 |
|---|---|---|
| 内置（builtin） | 不可删，可禁用 | 随 App 版本发布，等价“官方源”的本地版本 |
| 本地安装（zip） | 可卸载 | 无来源跟踪，无法自动更新 |
| 市场源（market） | 可移除 | 第三方或官方在线源，支持发现/更新 |

**同名/同 id 规则（覆盖语义）**

- `plugin_id` 全局唯一归属：同一 id 同一时刻只允许被**一个来源**拥有；
- **第三方默认不得覆盖内置或已装的其他来源插件**：同 id 冲突时安装被拒，并展示“占用者/来源/版本/覆盖后果”；
- 仅两种允许路径：
  1. 官方源在**同一 id** 上发布新版本 → 属正常更新，自动放行；
  2. 用户主动处置（先卸载/删除占用方，或使用“强制替代”危险确认）→ 记录覆盖历史，可一键回滚；
- 内置插件不允许被覆盖后删除（卸载即恢复内置版本）。

**能力冲突（不同 id 但占用同一能力位）**

插件注册时会占用：消息渠道 `type`、Agent 工具 `name`（内置工具优先）、菜单 `code`、hook 事件位、下载/媒体客户端类型等。默认策略：**安装前做能力冲突检测 → 冲突者拒绝并提示“由 xx 占用”**；提供“强制启用（由最新启用者接管）”危险开关，仅 Web 管理端可操作，UI 需高亮冲突风险。

## 4. 市场索引规范（第三方市场开放协议）

第三方市场 = 任意可静态托管文件的站点/对象存储。**标准只保留“目录式”一种形态**：仓库里每个插件一份独立元数据，根目录由构建工具生成轻量 `catalog.json`；客户端先取目录清单，再按需拉取单插件详情。这样插件多了既不会出现巨大的手改 JSON，也方便多人协作与增量更新。

### 4.1 标准目录布局

```
market/
├─ catalog.json               # 目录清单（由 CLI/CI 生成，保持最小）
├─ plugins/
│  ├─ demo_plugin.json        # 每个插件一份元数据（作者唯一需要维护的文件）
│  ├─ another_plugin.json
│  └─ …
└─ dist/                      # 可选：zip 包产物（也可外链对象存储）
   └─ demo_plugin@1.0.0.zip
```

**catalog.json（根文件，`source_url` 指向它）**：只含市场信息与“id → 详情文件路径”小表，便于高频同步与缓存：

```json
{
  "market_version": "1.0",
  "id": "mymarket",
  "name": "我的插件源",
  "homepage": "https://example.com",
  "plugins": [
    { "id": "demo_plugin", "path": "plugins/demo_plugin.json", "updated_at": "2026-09-04T00:00:00+08:00" }
  ],
  "updated_at": "2026-09-04T00:00:00+08:00"
}
```

**plugins/<id>.json（作者直接维护）**：单条插件完整元数据：

```json
{
  "id": "demo_plugin",
  "name": "示例插件",
  "summary": "一句话介绍",
  "description": "长描述（支持 Markdown）",
  "category": "automation",
  "tags": ["autosignin", "site"],
  "author": { "name": "xxx", "url": "https://github.com/xxx" },
  "icon": "…", "license": "MIT",
  "version": "1.0.0",
  "channel": "stable",
  "min_app_version": "4.16.0",
  "screenshots": ["https://…/s1.png"],
  "changelog": "v1.0.0 发布",
  "download_url": "dist/demo_plugin@1.0.0.zip",
  "sha256": "…",
  "signature": "…",
  "size": 102400
}
```

**可选 versions.json（plugins/<id>/versions.json）**：保留历史版本列表（version/changelog/sha256/download_url），供更新回滚；缺省时仅最新版可装。

### 4.2 客户端行为约定

- 同步只读 `catalog.json`（小表）→ 得到“有哪些插件”与更新时间；列表页可直接展示（摘要字段可缓存）；
- 进入详情页才按需 GET `plugins/<id>.json`，做本地缓存并带 `ETag / Last-Modified` 增量刷新；
- 校验与兜底：`id` 冲突（内置已存在）标记不可安装；`version/sha256/download_url` 缺失视为坏记录跳过；`min_app_version > 当前版本` 禁止安装并提示升级 App。

### 4.3 作者工作流（不需要手改大 JSON）

- 每插件一份 `plugins/<id>.json`（或在插件仓库内维护后整体发布）；
- 官方 CLI `nexus-market build`：扫描 `plugins/` → 校验（字段齐全、manifest 一致、category/tags 合法）→ 自动计算 zip 的 `sha256/size` → 生成/更新 `catalog.json`；
- 接入 GitHub Actions / Gitee Pages：push 插件即自动构建并发布，`catalog.json` 永远由 CI 生成，仓库成员只改自己的插件文件。

## 5. 恶意插件防护与验证流程

防恶意插件不是单一校验，而是“**多级门禁**”串联：任一阶段不通过即终止安装，且允许隔离运行与事后处置。安装/更新统一走下面的流水线（`install(plugin, mode="audit"|"normal")` 也供“预检模式”用）。

### 5.1 验证流水线（安装门禁）

```
① 源可信度评估
   - 源是否为官方/已验证源；来源域名评分与历史（违规次数）
   - 可选“仅信任已签名源”策略（public_key 已配置才允许安装该源插件）
② 索引/包完整性
   - sha256 强校验；已配置签名源 → Ed25519 签名校验（含索引与 zip）
   - version 单调性校验（禁止降级/版本伪造）；min_app_version 大版本匹配
③ 静态扫描（SAST，zip 解压到临时沙箱目录后执行）
   - 路径穿越 / 符号链接 / 超包目录文件 → 拒绝
   - 文件类型白名单（py/js/vue/json/css/png/svg/ttf…）与单包大小上限
   - Python：AST 解析（py_compile）+ 禁 API 命中检测：
     eval/exec/compile、__import__/importlib 动态导入、pickle.loads、
     subprocess/os.system/os.popen/shell 调用、socket/raw 网络、
     requests/httpx/urllib 直连且域名不在 manifest 声明域、
     shutil.rmtree/os.remove 越权路径、读写 plugins/config/secret 之外路径
   - JS/前端：禁外链脚本加载、禁 eval/Function 构造
   - 密钥扫描：命中 sk-/api_key/token/私钥等模式 → 拒绝（复用 scripts/scan_secrets.py 规则）
   - 内置文件覆盖检查：不允许覆盖其他插件/系统文件
④ 权限与行为清单（机器可读）
   - backend.permissions 必须声明白名单内权限；未声明却调用 → 安装后拦截
   - backend.tools 按 Agent 分级展示并纳入确认流
   - hooks/调度项/settings 字段做 schema 校验，禁止未声明入口
⑤ 人工确认（危险安装门禁）
   - Web 端展示：来源域 + 作者/签名指纹 + 权限清单 + 工具清单 + 哈希
   - 提供【扫描报告】入口供查看 ③ 的明细；不通过直接禁用“安装”按钮
⑥ 运行时隔离（安装后）
   - PluginSandbox 注入最小服务面；backend 调用限时/限资源
   - 沙箱网络：默认拒绝出站；manifest 声明 allowed_hosts 时按域名放行
   - 写操作仅允许其插件数据目录与显式 config 白名单键
⑦ 事后监控与处置
   - 运行审计（调用、工具执行、hook、网络目标）写入 plugin logs
   - 异常触发“隔离”（禁用 + 保留数据）+ 通知
```

### 5.2 预检 / 隔离运行

- **audit（预检）模式**：只完成 ①–④ 并出报告，不落盘启用，便于市场页“安全预览”；
- **quarantine（隔离）**：来源不可信或扫描有告警时默认安装为禁用态，用户可查看报告后“信任并启用”或卸载。

### 5.3 黑名单、吊销与可信发布者

- 本端维护 `PLUGIN_BLOCKLIST`（`id`/`sha256`/来源），命中即禁止安装/自动停用；
- 支持**吊销列表**：官方源可下发 `revoked`（含受影响版本与 sha256），同步时自动比对并停用；
- 已验证源可给插件打 `verified` 徽标（由源声明 + 本端指纹校验后展示），未验证插件在 UI 上明确标注“未验证”。

### 5.4 验证相关新增接口

| 接口 | 说明 |
|---|---|
| GET `/api/plugin/market/plugins/{id}/audit` | 预检扫描报告（无需安装） |
| POST `/api/plugin/market/plugins/{id}/report` | 举报恶意/问题插件（附理由） |
| GET `/api/plugin/market/meta` | 分类/标签/权限/可信源策略元数据（前端驱动） |

> 前端“安全预览”即调用 audit：先看到“扫描通过 + 声明了哪些权限/工具”，确认后才真正安装。

## 6. 后端设计

### 6.1 数据模型

新增 `PLUGIN_MARKET_SOURCE`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | 主键 |
| source_id | str | 市场 id（索引里的 `id`） |
| name | str | 展示名 |
| url | str | 索引 URL |
| public_key | str/None | 可选签名公钥（Ed25519 hex） |
| enabled | bool | 是否启用（停用=前端隐藏该源） |
| auto_update | bool | 是否自动拉取更新 |
| last_sync_at | datetime/None | 最近同步时间 |
| created_at / updated_at | datetime | 时间戳 |

复用/扩展 `PLUGIN_MANIFEST`（增加 `source_id`、`installed_from`、`download_url`、`package_sha256` 列，用于识别来源与后续更新）。标签完善后 `PLUGIN_MANIFEST.TAGS` 存规范后的 tags 列表。

### 6.2 服务层：`PluginMarketService`

```
sync_source(source)            # 拉索引 → 写缓存/内存
list_market_plugins(source_id, filters)   # 搜索/分类/标签/排序
list_installed()               # 本地已装（含内置、本地、市场来源）
compare(installed, remote)     # 计算可更新/冲突/兼容状态
install(plugin, mode)         # 走 5.1 验证门禁：audit 预检 / normal 安装 / 隔离安装
update(plugin_id)             # 保留配置合并安装新版本（同样过验证门禁）
uninstall(plugin_id)           # 卸载并保留来源记录可重装
remove_source(source_id)
refresh_all(auto_update_sources)  # 供后台定时任务（每 6h）调用
```

后台定时：复用现有 scheduler 任务机制新增 `market_sync` 任务，按 `auto_update` 拉取更新，命中可更新插件后发通知（走现有消息渠道）。

### 6.3 API 设计（前缀 `/api/plugin/market`）

| 方法/路径 | 说明 | 权限 |
|---|---|---|
| GET `/api/plugin/market/sources` | 市场源列表 | `plugin:view` |
| POST `/api/plugin/market/sources` | 添加源（body: name/url/public_key） | `plugin:manage` |
| PUT `/api/plugin/market/sources/{id}` | 编辑源（enabled/auto_update/public_key） | `plugin:manage` |
| DELETE `/api/plugin/market/sources/{id}` | 移除源 | `plugin:manage` |
| POST `/api/plugin/market/sources/{id}/sync` | 立即同步 | `plugin:view` |
| GET `/api/plugin/market/plugins?source=&keyword=&category=&tag=&sort=` | 浏览（可跨源合并浏览） | `plugin:view` |
| GET `/api/plugin/market/plugins/{id}` | 插件详情（含 changelog/截图） | `plugin:view` |
| GET `/api/plugin/market/status` | 安装态对比（installed/updatable/conflict） | `plugin:view` |
| POST `/api/plugin/market/install` | 安装（body: id/version，返回 zip 直链时后端代下载） | `plugin:manage` |
| POST `/api/plugin/market/update` | 更新到最新 | `plugin:manage` |
| POST `/api/plugin/market/uninstall` | 卸载（走既有 uninstall 语义） | `plugin:manage` |

响应统一 `{code,msg,data}`（与现有 API 约定一致），安装/更新/卸载为异步任务 + 轮询任务状态，或同步返回后由插件操作日志跟踪。

### 6.4 更新检测与升级流程

**检测时机与提示**

- 每个源同步后即与本机已装插件比对（关联键 = `source_id + plugin_id`），得到：`not_installed / installed_current / update_available / update_required(不兼容或冲突) / downgrade(本地版本更高)`；
- 比对结果写入本地缓存（源索引的最新版本常驻内存/轻量表），因此**离线或未打开市场页时也能显示“可更新 n”徽标**；
- 触发点：打开市场页、手动“立即同步”、`auto_update` 定时任务（默认每 6h）、外部推送（支持发通知：“2 个插件可更新”）；
- 版本比较使用语义化版本 `major.minor.patch[-prerelease]`，禁止降级；默认只跟踪 `stable` 渠道，源可在版本元数据声明 `channel: stable|beta`（beta 默认关闭，需用户开启后才提示）。

**升级步骤（与安装同一条验证流水线）**

1. 拉取最新包元数据（详情 / `versions.json`，含 changelog）；
2. 过 §5 门禁（源可信 + 签名/哈希 + SAST + 权限声明）；
3. **备份**：旧版本包归档 + 配置导出到临时区；
4. 停用旧版本（保留配置与数据目录，不删除）；
5. 安装新版本（`registry.install`），并做**配置迁移**：合并新旧 settings——新字段并入、被删除字段丢弃、类型不匹配给出提示；`backend.tools` / 菜单按新 manifest 重建；
6. **冒烟验证**：沙箱重载、manifest 可解析、backend 实例化成功、工具/菜单无冲突；
7. 成功 → 启用新版本并刷新“我的插件”计数；失败 → **自动回滚**到备份并还原配置，把原因写入插件日志并发通知；
8. 更新全程记录插件操作日志，支持**一键回滚到上一版本**（本地备份或源 `versions.json`）。

**并发与使用中约束**

- 插件有正在运行的 hook/任务时，更新任务先排队等待其结束（或提示“插件运行中，稍后更新”）；
- 更新期间该插件标记 `installing`，防止重复触发；
- 更新会重建沙箱实例，属“短时不可用”，页面上展示进度状态。

**更新相关补充接口**

| 接口 | 说明 |
|---|---|
| GET `/api/plugin/market/status` | 批量返回各插件安装态（含 update_available） |
| POST `/api/plugin/market/update` | 更新单个到最新（过验证门禁） |
| POST `/api/plugin/market/update-all` | 一键更新全部可更新项（逐项报告，单项失败不阻塞其余） |
| GET `/api/plugin/market/plugins/{id}/versions` | 历史版本与 changelog（供选择回滚） |
| POST `/api/plugin/market/plugins/{id}/rollback` | 回滚到指定版本（本地有备份或源有 versions 时） |

## 7. 标签体系完善

### 7.1 `category` 标准词表（manifest 必填之一）

| category | 含义 | 示例 |
|---|---|---|
| `media` | 媒体库/刮削/整理 | 硬链接助手 |
| `downloader` | 下载器相关 | qB 助手、迅雷 |
| `subscription` | 订阅/RSS | 自动订阅增强 |
| `automation` | 自动任务/刷流/签到 | autosignin、刷流策略 |
| `notification` | 消息通知渠道 | 钉钉、飞书、TG |
| `network` | 网络/内网穿透/代理 | wework 换 IP |
| `ai` | AI 能力 | Agent 工具插件 |
| `utility` | 工具/杂项 | 数据迁移、备份 |

> 兼容策略：`category` 为自由值时视为 `utility`，并在导入时给出提示；新提交/市场索引强制枚举。

### 7.2 `tags` 推荐词表（两级：功能 + 集成对象）

功能类：`autosignin` `brush` `rss` `notification` `scraper` `hardlink` `agent_tool` `sync` `backup` `stats` `security`

集成对象类：`site` `mikan` `tmdb` `douban` `feishu` `telegram` `wechat` `dingtalk` `slack` `qbittorrent` `transmission` `emby` `jellyfin` `plex` `chrome` `mysql` `sqlite`

- manifest 里 tags 建议 1–6 个，至少包含一个功能类；
- 标签词表随主版本演进（`docs/plugin-tags.md` 维护），索引端仍可带自定义标签，但前端“标签筛选”只聚合词表内标签，自定义标签仅展示不参与筛选（保证 UI 整洁）；
- 校验规则：未知标签不阻断安装，仅警告并降级为普通展示标签。

### 7.3 前端表现

- **分类**：市场首页顶部/侧栏分类磁贴（图标 + 分类名 + 插件数），高亮当前分类；
- **标签**：详情与卡片上以胶囊徽标展示（分类主色 = 主题主色，功能标签用中性色，集成标签用差异化色，全部取自主题 CSS 变量，不用硬编码色值）；
- **排序/搜索**：支持“最新 / 最近更新”（依据 `catalog.json` 的 `updated_at` 与版本），关键词匹配 `name/id/summary/author/tags`。

## 8. 前端设计

### 8.1 路由与信息架构

```
/plugin/market            # 市场（发现/浏览）
/plugin/market/sources    # 源管理（抽屉或子页）
/plugin/market/my         # 我的插件（内置/本地/市场来源分组管理）——可与“插件管理”合并入口
```

- 顶部统一“插件”父菜单，市场、我的插件、Agent 工具入口并列；市场页内顶栏再收敛「搜索、管理源、刷新、我的插件」动作，保持两级即可不臃肿；
- 移动端：tab 收进抽屉/底部导航，网格 1 列，详情全屏抽屉，操作按钮不隐藏可触达。

### 8.2 页面组成与组件树（市场页）

```
PluginMarketPage
├─ MarketTopBar        # 搜索(300ms 防抖) | 刷新(旋转反馈) | 管理源入口 | “我的插件”入口
├─ CategoryRail        # 横滑 chips：全部 + category 磁贴(图标/名称/计数)，高亮当前
├─ TagFilterRow        # 可选：功能类 tag 多选胶囊（数据来自 /market/meta）
├─ SortSelect          # 排序：最新 | 最近更新（均依据 catalog 的 updated_at/version）
├─ PluginGrid
│  └─ PluginCard
│     ├─ Icon(48) + verified/未验证角标
│     ├─ 名称/一句话/作者
│     ├─ category 徽标 + tags 胶囊（≤3 个 + n）
│     ├─ 版本 | min_app 兼容标记 | 更新时间
│     └─ 状态区：[安装] [更新] [已安装] [卸载](确认) ｜ 更新/安装进度
└─ PluginDetailDrawer
   ├─ 头图/截图轮播
   ├─ 长描述（Markdown 渲染）与 changelog
   ├─ 元信息卡：来源/作者/license/大小/sha256 短值/category/tags
   ├─ 安全卡：audit 报告摘要 + “查看完整扫描报告”
   ├─ 权限/工具清单：backend.permissions、Agent 工具(分级/危险高亮)
   └─ 操作区：[安装并启用][仅安装(隔离)] [更新][回滚版本] 各自危险确认
```

### 8.3 我的插件页

- 分组 Tab：**内置 / 本地 / 市场来源**（每组显示 id、来源、版本、启用状态、更新时间）；
- 行内操作：启用/禁用、设置（插件自有 settings 表单）、查看 Agent 工具、卸载（来源可重装）、**回滚**（有历史时）；
- 顶部汇总条：“n 个可更新 · m 个隔离（含告警）· k 个冲突”，点击直达对应筛选；
- “全部更新”按钮：逐项执行并实时回报每一项成功/失败（失败不阻塞，最后汇总）。

### 8.4 源管理（Sources）

- 列表卡片：名称/id/URL/启停开关/自动更新开关/签名公钥指纹/最近同步时间与错误；
- 添加源表单：URL 预校验（http(s)、非私网）+ 尝试拉取 catalog 预览市场名与插件数；
- 移除源：提示将不再提示更新（已装插件保留并可手动更新/卸载），需确认；
- 同步状态徽标：成功 ✓ / 失败 ✕（tooltip 显示原因）/ 同步中 spinner。

### 8.5 关键交互与状态机

**安装/更新主流程（与后端 audit 门禁一致）**
1. 点击安装 → 调 `/audit` 展示**安全预览**：扫描结果摘要（命中规则数/等级）+ 来源/作者/指纹/哈希 + 权限与工具清单；
2. 用户点“确认安装” → 后台任务执行（下载→验证→解压→SAST→权限→落盘启用），按钮变“安装中 xx%”（轮询任务状态或 SSE 事件）；
3. 结果：成功 → 卡片转“已安装/可打开”；失败 → 抽屉内联展示失败阶段与原因 + “重试/查看报告”；
4. 扫描存在告警：默认进入**隔离安装**（“仅安装不启用”），卡片带黄色“隔离”徽标，点击可查看报告后“信任并启用”。

**状态机（每张卡片）**

```
idle
 ├─ installing(下载/验证) → success | failed
 ├─ enabled/disabled（已装态）
 ├─ updating → success(自动回滚至旧版若失败)
 ├─ isolated(告警隔离) ──信任──▶ enabled
 └─ conflict(同名/能力占用) ──强制替代(危险)──▶ enabled
```

**可更新提示**：卡片右上角“New”点标 + 顶部汇总；打开市场/我的插件即刷新 `/status`（本地缓存可离线显示）；详情 changelog diff 高亮本次版本。

**危险与确认**：安装第三方、强制替代、覆盖同名、回滚均为确认操作；确认弹层展示“后果清单 + 指纹哈希”，颜色用危险色（主题变量）。

### 8.6 视觉、主题与动效

- 全部颜色取自主题 CSS 变量（`hsl(var(--…))`），禁止硬编码色值：主操作=primary、危险=destructive、隔离/告警=warning、验证通过=success、中性=border/muted-foreground；
- 图标统一 `IconifyIcon` + `lucide:` 前缀：安装 `download`、更新 `refresh-cw`、卸载 `trash-2`、验证 `badge-check`、隔离 `shield-alert`、冲突 `triangle-alert`、市场 `store`；
- 卡片默认描边悬浮上浮 + 主色描边；分类磁贴与空态配轻量过渡动效；更新/安装进度用细进度条；reduce-motion 时降级；
- 列表骨架屏、图片失败占位、Markdown 溢出安全（白名单渲染，禁脚本）。

### 8.7 数据、缓存与对接

- 新增 `market` 模块：TS 类型与后端 DTO 对齐（`MarketSource/PluginMeta/MarketStatus/ScanReport/…`），并补 `backend.tools` 等扩展字段到现有插件类型；
- 请求按“列表（含 catalog 缓存）→ 详情懒加载 → 状态轮询”分层：`/sources`、`/plugins?…`、`/plugins/{id}`、`/status`、`/meta`、任务进度；
- 列表与详情缓存带 `ETag` 思想（后端给 `updated_at`，前端按版本失效）；搜索/排序在本地对已拉取的 catalog 做（源不大），插件多时后端分页；
- 事件驱动：后端同步/更新完成事件刷新“我的插件”计数与可更新徽标。

### 8.8 空态 / 错误态 / 可访问性

- 空态：无源/无插件/搜索无结果分别给插图 + 行动引导（“添加市场源”）；
- 错误态：网络失败展示重试与“查看源同步详情”入口；单源失败不影响其他源展示；
- 可访问性：按钮有 aria-label、进度有 role=progressbar、Markdown 列表语义化、确认弹层可键盘/焦点管理；移动端目标点击区 ≥44px。

## 9. 版本与演进

1. 主版本 `manifest_version` 不变（向后兼容，`tools/category/tags` 为增量字段）；
2. 后端按 `min_app_version` 大版本匹配拒绝安装不兼容插件；
3. 迁移：`plugin:view/manage` 权限已存在，仅新增数据表（Alembic 迁移）与市场服务/API/前端页；
4. 首发建议官方内置一个示例源（含 2–3 个示例插件）用于演示与验收。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 恶意插件包 / 供应链投毒 | 多级门禁：签名源+sha256、SAST 静态扫描、权限声明校验、预检报告、隔离安装、运行沙箱出站白名单；支持吊销列表与黑名单即时停用 |
| 更新被劫持（恶意新版本） | 更新同样走 5.1 全流程；版本单调性校验；可对高危源开启“仅签名源”策略；更新后可回滚旧版本 |
| 升级引入回归/损坏 | 备份 + 冒烟验证 + 失败自动回滚 + 手动一键回滚；运行中的任务结束后才更新 |
| 源不可用/版本漂移 | 失败重试与降级展示；`last_sync_at` 状态可见；自动更新可关闭 |
| 与内置插件同名 | 内置优先；冲突项标记不可安装，给出改名建议 |
| 前端分类随词表演进 | 词表由后端 API 下发（`/market/meta`），前端渲染驱动，不发版也能新增分类 |

## 11. 文档引用

- 插件接入 Agent 工具：`docs/agent-plugin-tools.md`
- 词表维护：`docs/plugin-tags.md`（随本设计落地时新增）
- 主题/图标/移动端规范：`~/.kilo/rules/05-frontend-theme-guidelines.md`（前端工程内部约束）

## 12. 审计待办清单（实施前需补全）

- [ ] **权限映射与回收**：`backend.permissions` → RBAC 权限码/菜单的自动创建、安装回滚与卸载时的权限清理；菜单 `code` 唯一性冲突策略落地为“能力冲突检测”规则引擎
- [ ] **签名体系细节**：签名内容约定（对 sha256 hex 签名）、官方公钥轮换与吊销列表同步协议、`PLUGIN_BLOCKLIST` 的结构与本地导入/导出
- [ ] **静态扫描实现归属**：SAST 规则清单仓库化（可随版本发布增删规则）、误报“人工豁免”流程、audit 报告 JSON Schema（前端直接渲染）
- [ ] **插件状态机**：`available/installing/isolated/enabled/disabled/error` 与任务队列（防重复安装、更新排队）、多源同步并发锁与节流
- [ ] **多源同名策略**：同一插件出现在多个源时展示/更新优先级规则（固定“先安装源为主”，允许切换来源需卸载重装）
- [ ] **官方市场/审核运营**：第三方上架门槛（id 命名保留前缀如 `nexus_*`、license/icon/screenshot 校验）、恶意举报处理流、`verified` 授予标准
- [ ] **本地插件接入版本跟踪**：本地 zip 安装后可选择“关联到某市场源”从而获得更新
- [ ] **UI 细节定稿**：见 §8（路由/组件树/状态机/视觉/缓存均已细化），排序仅“最新/最近更新”，不引入安装量统计与上报
- [ ] **双端与 App 版本联动**：插件含前端资源时与主前端版本兼容声明；提示“升级 App 才能更新该插件”
- [ ] **官方示例源与验收**：内置 2–3 个示例插件 + 一个示例源端到端演示；验收用例覆盖 安装/更新/回滚/隔离/冲突/恶意包拒绝
- [ ] **配额与清理**：下载缓存/备份/回滚包的磁盘配额与定期清理策略

## 13. 实施拆分建议（纵切）

1. 后端：源 CRUD + `catalog.json` 同步 + 安装链路（含 §5 门禁骨架） + 状态/审计表（Alembic）
2. 安全：签名校验 + SAST 规则引擎 + audit 报告 API + 黑名单/吊销
3. 更新：compare/update/rollback/versions + 定时同步 + 通知
4. 前端：市场页（浏览/详情/安装）+ “我的插件”分组 + 源管理抽屉 + 预检报告渲染
5. 运营：示例源 + CLI `nexus-market build` + 官方源发布与 `verified` 流程
