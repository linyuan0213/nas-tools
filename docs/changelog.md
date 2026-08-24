# 版本历史

## v4.8.3 (2026-08-24)

### 特性
- **Agent 网页搜索**：新增 web_search 工具，通过内置 Chrome 搜索 Google/Bing/Baidu，主引擎不可达时自动降级
- **站点资源每页数量**：`page_size` 透传站点请求，前端选择值直达站点

### 修复
- **首次加载请求超时**：启动初始化移入后台线程，未就绪时快速返回 503，前端自动退避重试、就绪后自动恢复；指纹同步与图片代理同步调用移入线程池，不再独占事件循环；路由初始化失败兜底服务不可用页，插件资源加载增加超时与退避；瞬时网络故障不再误踢登录
- **高清杜比（hddolby）搜索**：API 改用 application/json 提交、剔除空数组参数、Content-Type 去 charset，修复非空分类返回 500、每页仅 10 条分页失效与空关键词浏览回归
- **站点资源分页**：返回 `has_more`（前端不再用幽灵 +1 计数），API 站每页数量按站点实际参数名（pageSize/size 等）覆盖
- **转移历史去重加固**：仅信任源路径存在的历史记录，目标存在性检查支持存储后端
- **索引器统计竞态**：`last_error` 共享实例属性被并发搜索污染，成功搜索被误记失败

### 安全
- **nexus-chrome VNC_PASSWORD 必填**：禁止使用默认密码，未设置时 compose 启动报错提示

## v4.8.2 (2026-08-18)

### 特性
- **铃铛未读角标可关闭**：通知弹窗新增「未读角标」开关（localStorage 持久化），关闭后隐藏铃铛红色数字/圆点，通知列表功能不受影响

### 修复
- **移动端指纹保护**：站点已由桌面端指纹设置时，移动端提交仅同步独立画像（`user_{id}_mobile`），不设置默认画像、不覆盖站点 UA/请求头，避免 PC/移动指纹交替触发站点风控（API 返回 `site_skipped`/`site_skip_reason` 标识）
- **自动化浏览器污染指纹**：前端跳过 `navigator.webdriver` / HeadlessChrome 等自动化/无头浏览器提交，防止测试会话覆盖真实浏览器指纹

## v4.8.1 (2026-08-18)

### 修复
- **浏览器指纹未写入站点 UA/高级请求头**：指纹同步误写入索引器配置表（`INDEXER_SITE_CONFIG.DEFAULT_SETTINGS`），而运行时站点请求、索引器搜索与前端维护页读取的站点配置表（`CONFIG_SITE`）未生效；现改为写入站点配置表（`NOTE.ua` / `NOTE.headers` / `HEADERS` 列），启用状态取自索引器配置，仅覆盖 UA 相关键、保留用户自定义认证头
- **UA 重复展示**：指纹 UA 仅写入站点「认证信息-User-Agent」字段，高级请求头不再重复写入 User-Agent（保留 sec-ch-ua / Accept / Sec-Fetch-* 等 Client Hints）
- **移动端指纹覆盖桌面端**：站点已由桌面端指纹设置时，移动端提交仅同步独立画像（`user_{id}_mobile`），不设置默认画像、不覆盖站点 UA/请求头，避免 PC/移动指纹交替触发站点风控（API 返回 `site_skipped`/`site_skip_reason` 标识）
- **自动化浏览器污染指纹**：前端跳过 `navigator.webdriver` / HeadlessChrome 等自动化/无头浏览器提交，防止测试会话覆盖真实浏览器指纹

## v4.8.0 (2026-08-18)

### 特性
- **Agent 推理强度与思考模式**：全局配置 `agent.reasoning_effort`（low/high/max，默认 high）与 `agent.disable_thinking`，统一作用于对话、媒体识别、意图解析、记忆抽取等所有 LLM 调用；聊天按次覆盖（推理强度下拉 + 深度思考开关），OpenAI 兼容/Ollama/Gemini 均映射原生推理参数，模型不支持时自动剥离降级
- **前端 CI 提速**：去掉 windows 矩阵、pnpm 缓存改为 PR 也写入

### 修复
- **4.7.0 启动失败**：浏览器指纹路由 `request: Request | None` 参数使 FastAPI 构建路由时报 `Invalid args for response field`，应用无法启动（现改为必选 `Request`）

## v4.7.0 (2026-08-18)

### 特性
- **Agent 工具扩充至 40 个**：新增下载历史、站点状态、订阅详情、刷流状态、数据总览、转移历史、用户 RSS、知识库状态、索引器统计、删种/存储状态、识别词管理（增删改）、插件运行
- **浏览器指纹注入站点**：指纹 UA 与高级请求头更新到站点配置，区分 API / HTML 站点（Accept、Sec-Fetch-*、Client Hints）
- **Agent 多轮上下文恢复**：历史会话重新加载，修复"可以/继续"无法接续上文
- **索引器统计细化**：超时/HTTP 失败正确计入失败（原全部计成功），耗时精确到秒级小数；首页新增成功/失败/耗时组合图
- 启动 ASCII Banner（Spring Boot 风格）

### 修复
- 订阅下载动漫入库失败：转移时从父目录名/下载历史 SE 提取集号兜底；转移失败不再误报成功
- 站点高级请求头保留用户自定义认证头（仅覆盖 UA 相关键）

## v4.6.3 (2026-08-16)

### 修复
- **订阅续订断点推导**：从订阅起点推导续订点（支持中途订阅——订阅从第 N 集开始跟踪时，历史只有 N 之后的集，现从 N 数起而非从第 1 集），`current_ep` 随转移/刷新同步推进（首个待下载集），历史推导只向前不倒退，避免重新订阅重复下载已转移剧集
- **订阅进度显示**：转移完成事件同步推进 `current_ep`（此前只更新缺失集数 `lack`，`current_ep` 停在订阅创建值导致前端进度显示卡住）
- **Telegram 消息 HTML 转义**：媒体通知改用 `parse_mode=HTML` + 转义，文件名/番号中的 `_ [ ] ~ #` 等特殊字符不再触发 Telegram 400 "can't parse entities"、也不再显示原始符号
- **Telegram 发布通知渲染**：GitHub Release 通知的 changelog（markdown）转 Telegram 兼容 HTML（加粗、列表圆点、代码等宽、链接可点击），不再显示原始 markdown 符号
- **站点维护部分编辑保留认证**：维护页只编辑部分字段时，未携带的 cookie/headers/api_key 等保留存量，不再被覆盖清空
- **内置索引器站点资源接口异常**：`list()` 路径 `last_error` 未初始化导致 `/api/site/sites/resources` 报错
- **星空站点签到**：star-space 访问首页即签到（服务端自动），补签配置（`p_index/index.php` + 登录态判定），修复签到失败

## v4.6.2 (2026-08-14)

### 修复
- **中文名缺失**：TMDB detail 返回英文名时，中文名现从 `translations`（zh-CN/zh/zh-TW）兜底提取（原仅查 `alternative_titles`），并放宽 `update_tmdbinfo_cn_title` 触发条件匹配所有中文语言配置（zh-CN/zh-Hans 等），下载/入库通知正确显示中文标题
- **TMDB 缓存版本化**：`TMDBCache` key 增加 `TMDB_CACHE_VERSION`，中文名补全逻辑变更后旧缓存（存英文名）自动作废重建，避免 7 天 TTL 内持续显示英文标题
- **订阅搜索站点回退**：订阅未配置 `search_sites` 时回退默认订阅设置的站点（原空列表覆盖 → 0 站点搜索），RSS 未配置 `rss_sites` 时同样回退默认而非轮询全部站点
- **Agent 会话并发竞态**：`get_or_create` 并发创建同一会话时撞唯一约束，现捕获 `IntegrityError` 回滚重查，消除偶发 500
- **消息通知模板兜底**：Web 等客户端无模板配置或空模板（`{}`）时回退默认模板，内置消息页入库/下载通知正确显示 emoji（此前纯文本）
- **搜索进度失败站点汇总**："搜索完成"文本现附带失败站点（错误/超时）汇总
- **集数补全**：`total_episodes` 从解析集信息补全（单集=1、多集范围=差+1），修复"共 0 集"显示
- **前端刷新状态**：订阅卡片点击"刷新"后轮询拉取列表（最多 5 次），"搜索中"状态及时显示，无需手动刷新页面；消息中心单图通知改为企业微信图文卡片样式（图片横幅 + 文字区，固定最大宽度）

## v4.6.1 (2026-08-14)

### 特性
- **Web 消息未读轻量接口**：新增 `GET /api/agent/message/unread`（未读列表 + 未读数单请求），通知栏下拉不再拉全量历史
- **配置热重载全面覆盖**：保存配置即生效，无需重启——
  - **Agent RAG / 知识库 / 长程记忆**：embedding / vector_store / rag / memory 配置变更时自动重建（`agent_reload`），废弃原"必须重启才可用"
  - **Agent LLM Provider**：default_provider / providers 的 api_key / api_url / model 变更热刷新
  - **定时任务**：`pt.ptrefresh_date_cron`、`subscribe.queue_interval`、`media.mediasync_interval` / `sync_transfer_interval`、agent 记忆 ttl 等变更时自动重注册默认定时任务
  - **媒体服务器类型切换**：emby ↔ jellyfin 切换无需重启（连接参数本就懒读生效）
  - ConfigReloader 支持快照对比（仅实际变更才重建）+ 失败隔离（单步骤失败不影响其他）

### 修复
- **ConfigReloader**：修复重建步骤返回 `None` 时覆盖上下文字段的 bug（媒体服务器被置空导致定时任务重注册级联失败），仅非 None 时赋值
- **搜索季解析**：支持英文季/集格式（`S02` / `S2` / `Season 2` / `S02E06` / `E06`），修复搜索只返回 S01 的问题（此前仅识别中文"第X季"）

### 其他
- 知识库自动更新 handler 改为可重入注册（配置热重载重复调用不会重复订阅事件）

## v4.6.0 (2026-08-13)


### 特性
- **AI 助手（消息中心）**：基于 pydantic-ai 重构 Agent 引擎——多步工具循环、推理内容实时 SSE 推送、工具调用事件流式下发（同名工具多次调用时步骤正确配对）、思考过程面板支持
- **Web 消息通道**：通知/回复持久化到 `AGENT_WEB_MESSAGE`（刷新/重启后恢复），内置消息中心页面
- **Agent 记忆**：会话/消息/长程语义记忆模型与迁移（`AGENT_CONVERSATION` / `AGENT_MESSAGE` / `AGENT_WEB_MESSAGE`）
- 知识库 ingest handler 与内置文档读取接口
- 已下载记录返回季集信息（`season_episode` 字段）

### 修复
- **媒体识别**：移除发布组剥离列表误伤真实片名的 `sparks`；抽取 `_post_process` 公共后处理统一 `identify`/`identify_batch`/`identify_files`，消除"识别测试正常但转移识别错"的路径差异；副标题英文名仅在主标题缺失时采用，避免无意义目录名覆盖真实标题
- **下载优先规则**：`_dedup`、搜索展示排序、RSS 订阅初步排序统一尊重「做种数优先/站点优先」设置，做种数优先时做种数提到站点顺序前
- **刷流**：等待时间规则改用进种时长并覆盖 Pending/Queued 等待态（原用未活动时间导致等待种子永不触发删种）
- **浏览器**：挑战检测收敛为强特征并与 nexus-chrome 服务端对齐，修复普通页面文案（正在/请稍候/由 Cloudflare 提供）误判导致的 120s 空轮询
- **测试环境**：`DATABASE__SQLITE_PATH` 配置真正生效，测试改用隔离临时库（修复全量测试清空真实 `data/user.db` 的问题）

### 其他
- 代码规范：统一将延迟导入移至文件顶部（ruff PLC0415）
- DEBUG 模式默认关闭，生产环境不暴露 `/docs` API 文档
- 文档全面完善：新增 AI 助手、过滤规则、资源搜索、服务与调度、存储后端、用户与权限等文档页，更新全部截图（敏感信息打码）

## v4.6.0 (2026-08-13)

### 特性
- **AI 助手（消息中心）**：基于 pydantic-ai 重构 Agent 引擎——多步工具循环、推理内容实时 SSE 推送、工具调用事件流式下发（同名工具多次调用时步骤正确配对）、思考过程面板支持
- **Web 消息通道**：通知/回复持久化到 `AGENT_WEB_MESSAGE`（刷新/重启后恢复），内置消息中心页面
- **Agent 记忆**：会话/消息/长程语义记忆模型与迁移（`AGENT_CONVERSATION` / `AGENT_MESSAGE` / `AGENT_WEB_MESSAGE`）
- 知识库 ingest handler 与内置文档读取接口
- 已下载记录返回季集信息（`season_episode` 字段）

### 修复
- **媒体识别**：移除发布组剥离列表误伤真实片名的 `sparks`；抽取 `_post_process` 公共后处理统一 `identify`/`identify_batch`/`identify_files`，消除"识别测试正常但转移识别错"的路径差异；副标题英文名仅在主标题缺失时采用，避免无意义目录名覆盖真实标题
- **下载优先规则**：`_dedup`、搜索展示排序、RSS 订阅初步排序统一尊重「做种数优先/站点优先」设置，做种数优先时做种数提到站点顺序前
- **刷流**：等待时间规则改用进种时长并覆盖 Pending/Queued 等待态（原用未活动时间导致等待种子永不触发删种）
- **浏览器**：挑战检测收敛为强特征并与 nexus-chrome 服务端对齐，修复普通页面文案（正在/请稍候/由 Cloudflare 提供）误判导致的 120s 空轮询
- **测试环境**：`DATABASE__SQLITE_PATH` 配置真正生效，测试改用隔离临时库（修复全量测试清空真实 `data/user.db` 的问题）

### 其他
- 代码规范：统一将延迟导入移至文件顶部（ruff PLC0415）
- DEBUG 模式默认关闭，生产环境不暴露 `/docs` API 文档
- 文档全面完善：新增 AI 助手、过滤规则、资源搜索、服务与调度、存储后端、用户与权限等文档页，更新全部截图（敏感信息打码）

## v4.5.0 (2026-08-08)

### 特性
- 重命名格式：新增独立「重命名」配置入口（配合前端芯片式格式构建器），后端新增字段目录 / 格式校验 / 实时预览 API（`GET/POST /api/media/name_format/*`）；格式串支持可选片段语法 `{field:模板}`（字段为空时整段消失），新增 `source`（片源）/`media_type`（类型）/`category`（分类）占位符
- 浏览器指纹：支持登录同步真实浏览器指纹画像，后台流程（站点定时刷新 / RSS 自动化等无用户上下文场景）复用该指纹；`render_normalize` 从 `browser_mode` 抽取独立模块
- 转移：`{en_title}` / `{episode_title}` 占位符在真实转移路径（`MediaExistenceChecker`）正确渲染，与设置页预览一致

### 修复
- 识别：公开站站点标记（`[EZTVx.to]`、`www.UIndex.org`、裸域名水印等）在 UnifiedParser 前置剥离，转移与媒体搜索入口行为一致，不再抢占片名；`meta_info` 清洗正则补齐常见短顶级域
- 识别：自定义识别词（屏蔽 / 替换 / 集偏移）接入转移识别链路（`identify` / `identify_batch` / `identify_files`），与 `meta_info` 一致，命中时输出 info 日志
- 订阅：RSS 轮询懒更新 TMDB 总集数（优先季详情集数，规避主详情 `episode_count` 滞后），订阅自动补齐新增集
- 订阅：订阅完成后保留下载历史，重新订阅不再重复下载已完成的剧集（洗版订阅除外，仍允许升级重下）

### 其他
- HTTP 客户端迁移至 httpx2（httpx 分支续作，API 兼容）；项目改为源码运行（移除打包构建配置，`run.py` 注入 `src` 路径，pytest 配置 `pythonpath`）

### 测试
- 新增重命名格式渲染/校验/路径预览、识别词接入转移链路、站点标记剥离、meta_info 站点标记回归测试；全量测试通过（2200+）

## v4.4.5 (2026-08-04)

### 特性
- 文件管理器：新增目录创建（`POST /media/dir/mkdir`）、文件批量移动/复制（`/media/files/move`、`/media/files/copy`）、文件下载（`GET /media/file/download`）与上传（`POST /media/file/upload`）接口；`MediaFileService` 抽取 `_resolve_backend` 统一后端解析，新增文件名安全校验与批量操作部分失败聚合

### 修复
- 识别：`search_tv_by_season` 首轮命中校验目标季存在，修复同名真人剧抢占动漫条目（如《更衣人偶坠入爱河》S02 误识别为日韩剧）
- 识别：multi search 降级由「取首个名称命中」改为按名称/季/体量评分选优，稳定区分同名条目
- 识别：集名粘连修复剥离前缀中的发布组方括号与末尾年份，修复年份粘入片名导致 TMDB 查不到（如 `KAIJU.GIRL.CARAMELISE.2026`）
- 识别：元数据 token 补充 `ASSx2/SSAx2` 字幕轨标记，修复 `[WebRip 1080p HEVC-10bit AAC ASSx2]` 整段被误作片名
- 识别：前置发布组括号支持多组联合发布（`[Studio A&GroupB]`）及 fansub/raws/kissaten 特征词的带空格组名（如 `[Studio GreenTea&LoliHouse]`）
- 转移：修复字幕语言正则字符类缺失闭括号导致 `PatternError` 中断字幕转移
- 转移：目标字幕已存在且大小不一致时改用序号标签（`.1`/`.2`…），不再对已存在路径硬链接报 `File exists`；单条字幕失败不再中断主文件与其他字幕转移
- 转移：字幕/音轨转移新增 `dst_backend` 参数，目标判断与写入均走 StorageBackend（远程存储 link 自动降级 copy），与主文件转移路径一致

### 前端
- 文件管理：页面对齐真实文件管理器交互重设计
- 订阅：搜索页/详情页订阅确认弹窗「编辑」按钮无效修复，打开编辑弹窗前拉取默认订阅设置预填
- 订阅：编辑弹窗先加载站点选项再填表单，修复默认订阅站点（rss_sites/search_sites）被空选项过滤清空

### 测试
- 新增字幕/音轨转移本地与远程后端用例 11 例、按季搜索季校验与四例解析回归用例；全量测试通过（2100+）

## v4.4.4 (2026-08-03)

### 修复
- 初始化：`_execute_raw` 改用 `exec_driver_sql` 原样下发 SQL，修复正则非捕获分组 `(?:简体|…)` 被 `text()` 误解析为绑定参数导致默认过滤规则初始化失败、「中字」规则组（1002）从未创建的问题（自 v4.4.1 起）；`init_filter.sql` 的 NOTE 列 NULL 改为空串以兼容严格模式数据库
- 过滤规则：`get_filterrules` 弃用按 NULL 结尾的正则文本解析，改为 SQLAlchemy 内存引擎执行后读回结构化数据，修复 `/api/filter/rules` 报 `list index out of range`
- 删种：任务更新由「先删后插」改为原子 UPDATE，修复更新失败产生重复任务、任务 ID 每次变更导致调度任务反复重建的问题；tid 对应记录不存在时回退为新增
- 删种：预览接口无符合条件种子时返回空列表而非错误，前端不再误报红色错误提示
- 删种：候选筛选中分享率/做种时间/平均上传速度为 0 时不再参与过滤（原 `is not None` 判定使 0 值条件误生效）；候选列表站点列改用注册域名展示（去除 tracker 子域）
- 插件：刷新媒体库/Webhook 订阅事件名 `media.transfered` 修正为实际发布的 `media.transfer_finished`，修复入库后媒体库从不刷新、Webhook 收不到转移完成通知
- 插件：种子标记 PT 判定改为查询并遍历全部 tracker（原仅判定首个 tracker 且限 5 条）

### 前端
- 下载：自动删种任务页面整体重构，卡片式布局与刷流规则页统一，条件标签差异化配色，卡片底部操作栏（执行/预览/编辑/删除）+ 启用开关快捷切换，新增/编辑弹窗分组表单与字段帮助提示

### 测试
- 新增过滤规则初始化执行、规则组解析、删种任务原子更新回归测试；全量测试通过（2100+）

## v4.4.3 (2026-08-03)

### 修复
- 识别：`name_extractor` 不再把字幕标签（`[JPSC_JPTC]`/`[SRT]` 等）当作片名，纯数字括号（集号）不再被当成标题
- 识别：新增罗马数字季标解析（`Ⅲ`/`III` → 对应季数），修复 `Mushoku Tensei Ⅲ` 类命名识别为 S01 而非正确季
- 识别：`compare_tmdb_names` 子串匹配阈值由 0.95 放宽至 0.85，兼容动漫罗马音标题的 `-kun/-chan/-san` 后缀
- 识别：multi-search 降级新增英文名/全部别名比对（`_match_tmdb_candidate`），修复英文标题匹配不到中文 TMDB 名的问题（如 The King of Devil Beasts → 克雷瓦提斯）
- 识别：`identify_files` 补全 `set_tmdb_info` 调用、改用完整 TMDB detail（含 origin_country/genres），修复动漫类型误判为 tv、剧集/电影分类落到根目录的问题
- 识别：`set_tmdb_info` 兼容 TMDB `genres` 字段（原仅读 `genre_ids`），修复部分动漫因缺 genre_ids 被识别为 tv
- 识别：电影分类改用 movie 规则（`rule_map.get("movie")`），修复电影被归入 anime 规则导致分类为空、入库到 Movie 根目录（现正确进动画/华语/外语电影子目录）
- 转移：`_do_transfer_file` 结合转移历史去重（tmdb+季+集），修复目标路径规则变化导致已入库剧集重复入库
- 转移：已存在（转移历史/目标文件已存在）不再计为失败，且不再进入消息聚合，修复「入库失败」误报与重复推送「已入库」消息
- 转移：`total_episodes` 按识别季集数正确设置，修复多集转移消息显示单集（`S01 E04`）而非「共 N 集」
- 转移：黑名单插入去重，避免定时转移每周期重复插入导致表膨胀
- 转移：聚合目录多条下载记录同属一部剧时使用其 TMDB 提示，修复聚合目录无法识别
- 目录同步：`_do_transfer` 支持处理文件夹内媒体文件（含真实媒体文件时），修复文件夹下载（如单集文件夹）不自动转移
- 签到：新增 FRDS（朋友）专属签到配置，访问首页 `index.php` 即完成签到（该站无 `attendance.php`），修复误走通用 fallback 的 `attendance.php` 导致 404「请检查站点连通性」

### 文档
- 修正安装文档端口（前端 8080 / 后端 3000:8080）、Redis 配置（移除 redis.conf 挂载，改为实际命令）、数据库配置与迁移机制、目录挂载（NEXUS_MEDIA_DATA、/media）
- 新增开箱即用的简单 docker-compose 示例（前后端+Redis+MySQL 推荐版 / 仅前后端 SQLite 体验版）
- 同步修正 docker/readme.md、development.md、notifications.md、faq.md 中的端口引用

### 测试
- 全量测试通过（2118 passed）；新增字幕标签剥离、罗马数字季标、批量识别类型判定等回归测试

## v4.4.2 (2026-08-02)

### 修复
- 匹配：识别缓存命中时用当前解析重建资源字段（org_string/发布组/分辨率/音视频），不再返回首次缓存种子的过期资源字段。TMDB 身份（tmdb_id/名称/年份/海报）仍来自缓存避免重复查 TMDB
- 识别：名称识别测试 `name_test` 用 `cache=False`，始终返回当前输入的资源字段，避免展示首次缓存的错误资源信息
- 解析：剥离 FRDS `mUHD` 源标记（`name_extractor._META_TOKEN_RE` 新增 `muhd`），修复 `Green.Book...mUHD-FRDS.mkv` 识别为 `Green Book Muhd`（名称残留 → TMDB 搜不到）
- 解析：多括号标题（中/英/日 + 发布注释）的方括号层提取不再被自由文本层覆盖（`_extract_free_text` 仅填充缺失名称），修复 `[剧场版 鬼灭之刃...][自壓(付相關專輯)]` 取成发行注释
- 前端：服务面板 → 新增缓存管理弹窗（`GET/POST /system/caches`），列出各缓存键数/占用/命中率统计，支持单个或全部清理
- 前端：缓存管理弹窗改为内联面板 NModal `v-model:show`（修复子组件 `:show` 导致弹窗内联渲染在页面底部）
- 前端：服务面板整体重构，使用 `tabler-theme.css` 颜色系统（统计卡片加图标 + 服务卡片彩色标记 + Tabler 阴影/圆角/过渡）
- 前端：名称识别测试 `nameTestApi` 支持 `subtitle` 参数，传 description 提高多语言标题命中率
- 前端：未识别列表识别弹窗先打开再请求（加载动画可见），修复加载期间无动画
- 前端：`discovery/index.vue` 推荐项跳转搜索页字段 `mediaType` → `media_type`，修复类型字段引用错误
- 前端：订阅（影视/剧集）页面移除未使用的 `startSearchSSE` 解构，修复 typecheck 报错
- 签到：浏览器签到直接访问签到页 `attendance.php`（不再首页+点击）；等待签到页 WAF/雷池挑战清除后判定；串行化浏览器签到（消除并发竞争）
- 签到：`browser_transport` 关闭时删除对应 chrome 会话；docker-compose 缩短 chrome SESSION_TTL 为 30 分钟

### 特性
- 搜索：新增 `GET /search/progress/{session_id}` SSE 进度流，WEB 搜索进度按会话隔离推送
- 系统：新增 `GET /system/caches`（缓存列表与统计）、`POST /system/caches/clear`（按名或全部清理缓存）

### 测试
- 全量测试通过（2116 passed）；新增 mUHD 剥离、多括号标题不覆盖、批量识别拉丁名直通回归测试

## v4.4.1 (2026-08-01)

### 修复
- 匹配：媒体 en_name 不再被日文/中文原名污染（`set_tmdb_info` 仅存拉丁名），缺拉丁名时补取 TMDB 英文标题，修复日漫（如克雷瓦提斯）搜索词缺英文名导致中字资源搜不到
- 匹配：批量识别在 match_media 已知时，拉丁名（英文名）严格匹配即直通，不再因短中文名前缀被「全名共识」否决（修复中英双名种子误拒）
- 签到：浏览器签到改为直接访问签到页 `attendance.php`（GET 即完成签到），不再首页查找+点击，且等待签到页自身 WAF/雷池挑战清除后再判定，修复「已签到却误报失败」
- 签到：串行化浏览器签到（模块级锁），消除并发启动多个浏览器会话导致的 WAF 挑战超时误报
- 签到：`_PAGE_WAIT_TIMEOUT` 由 120s 放宽到 180s，给慢挑战更多余量
- 订阅：订阅搜索始终自动下载，不再受「搜索后自动下载」开关影响；WEB/手动搜索仍按开关决定
- 过滤：中字过滤规则重写，覆盖简体/繁體/中字/国语/国配/双语/CHS/CHT/内封中字等更全字幕标记，避免动漫中字资源漏过
- 浏览器会话：HTTP 浏览器 transport 关闭时删除对应 chrome 会话，避免 `audiences:xxx` 等会话长时间残留（配合缩短 chrome SESSION_TTL）

### 特性
- 搜索：新增 `GET /search/progress/{session_id}` SSE 进度流，WEB 搜索进度按会话隔离推送
- 站点资源：资源列表支持 TMDB 识别（前端「识别」按钮，复用 `/media/name_test`），资源列表服务附加解析级识别字段
- 前端：站点资源列表每个资源新增「识别」按钮，点击弹窗显示完整识别结果（名称/tmdbid/海报/季集/年份/资源质量）

### 热修复（4.4.1 hotfix）
- 未识别列表：识别弹窗改为先打开再请求（加载动画可见），修复「识别测试」加载期间无加载动画

### 测试
- 全部通过；新增批量识别拉丁名直通、en_name 补全等测试

## v4.4.0 (2026-07-31)

### 特性
- 搜索：新增 `SearchOrchestrator` + `SearchContext`，统一 Web/交互式/订阅三条搜索路径
- 搜索：SSE 进度推送 `GET /search/progress/{session_id}`，前端不再轮询，进度按 session 隔离
- 解析：统一解析器替换 anitopy（ADR-019），合并动漫/影视解析为单一流程
- 数据库：下载历史/订阅描述迁移 TEXT，转移历史新增种子字段与索引

### 修复
- 搜索：`search_medias_for_web` 异常保护 try/finally，后台线程异常不再导致进度卡死
- 搜索：进度跨 session 串扰导致 SSE 提前返回，`get_progress` 改为 per-session 键 + 全局详细进度双读
- 搜索：豆瓣详情失败降级回退标题识别，不再炸掉整个搜索
- 解析：`~...~` 日文副标题提取为 episode_title，不再污染 cn_name
- 解析：剔除【生】【附日字】等全角元数据标签
- 解析：后缀剥词保护剩余标题词，修复 `A Ma` 等短标题被剥空
- 解析：片假名/平假名标题（如 ブラックトリック）判为 anime
- 解析：标题含 H264/x264 视频编码时不再误判为纯音频
- 匹配：en_name 精确/子串命中时校验 cn_name 衍生词（特别篇/OVA），拦截攻壳系列噪声
- 搜索：修复 `search_year` 未定义变量、`remap` 缺少 `end_episode` 参数

### 热修复（4.4.0 hotfix）
- 转移：`_lookup_download_record` 对目录/父目录聚合下载记录增加计数判断，杜绝整目录错误套用单个 TMDBID（批量误识别为同一剧）
- 解析：季集号（SxxExx）后的集标题切分为 episode_title，不再并入主标题（`Medalist.S02E09.It.Begins` → Medalist）
- 解析：预处理器不再剥离含空格的英文片名括号（`[Silent_Witch]` → 不再误判为 "12"）
- 解析：移除 `watch` 元数据 token 误判（`Witch Watch` 不再被剥词）
- 识别：修复 `identify_files` 去重 key 与组装 key 格式不一致，逐文件 TMDB 识别结果不再丢失
- 转移：标题有效性防呆——纯数字、过短、TMDBID=0 的识别结果拒绝入库，进未识别列表
- 转移：自动同步（监控/目录同步）不再覆盖媒体库已存在文件，仅手动转移可覆盖
- 转移：转移成功后无条件更新未识别状态，未识别列表不再残留
- 转移：`/api/sync/unknown/delete` 支持 `ids` 字段（前端批量删除未识别）
- 消息：`transfer_finished` 通知模板补充季集显示（单集 `S01 E05`、多集 `S01 共N集`）
- 签到：配置浏览器自动化的站点无专用 handler 时直接走浏览器签到，修复 HTTP 过盾失败误报
- 订阅：编辑订阅不再清空已配置的站点/集数（更新时 None 字段保留原值），修复站点设置刷新后消失
- 过滤：默认过滤规则改为幂等补齐（每次启动执行 INSERT OR IGNORE），新增独立「中字」分组（1002）
- 下载：HTML 站点种子下载始终携带站点 cookie（sign 预签名启发式仅对 API 站点生效），修复天空/HDSky 下载失败
- 搜索：WEB 搜索未显式指定站点时应用默认订阅设置的 search_sites（默认为空则不搜索）
- 搜索：`_filter_indexers` 站点过滤空列表 → 不搜索（订阅未配置站点不再搜全站）
- 订阅：新增订阅时空数组也应用默认订阅设置的站点；已有订阅站点为空时搜索回退默认设置
- 前端：消息通知模板「重置」仅恢复默认模板，不再清空用户渠道配置/推送开关，修复重置崩溃

### 测试
- 2114 项全部通过；新增统一解析器、真实标题、动漫标题、集标题切分、订阅更新保留字段等测试

## v4.3.16 (2026-07-24)

### 修复
- 匹配：`quick_name_match` 类型互斥 — MOVIE 种子不再匹配 TV/ANIME 订阅
- 匹配：`SequenceMatcher` 收紧（0.8→0.86, 0.7→0.75）防同名衍生（如 SAC_2045 匹配 2026 剧集）
- 匹配：CJK `_cn_simplify` 分级阈值 — 全中文后缀含衍生词（剧场版/特别篇/OVA）→高阈值 0.65，含英文字母（SAC/GIG/TV）→高阈值 0.65，纯元数据（简繁内封字幕）→低阈值 0.4
- 匹配：英文名 `mn in mmn` 通过时检查 cn_name 是否含英文字母后缀，防止 SAC/ARISE/GIG 等绕过
- 匹配：低置信（仅中文名）`quick_name_match` 通过后仍走 TMDB 识别，`match_filter` 中 TMDB 未识别时拒绝而非回调
- 匹配：`org_string` 兜底检测 `[Movie]` 标签，补解析器遗漏的类型判定
- 匹配：`_EDITION_MARKERS` 词表（剧场版/特别篇/总集篇/特别版/OVA/OAD）强制高阈值
- 匹配：非 CJK `_cn_simplify` 子串加最小比率 ≥0.5，防极端短名误入长名
- 解析：`init_episode` 排除 `^\d+bit$`，防止 `10bit`/`8bit` 被解析为 S01 E10/E08
- TMDB：`cn_name`/`en_name` 按字符类型判定而非绑定 `original_language`，`en_name` 不再受 `ja`/`zh` 影响
- TMDB：新增 `get_tmdb_zh_title(language="zh-CN")` 自动填充中文标题
- 订阅：搜索时懒更新 TMDB 总集数 — 延迟更新的剧集自动同步到订阅，防止提前完成
- 转移：`existence_checker` 文件扫码名称匹配改为多语言子串（cn_name/en_name/title）
- 转移：已下载检测新增 `TRANSFER_HISTORY` DB 查询优先，按 tmdb_id+season 查已转移剧集，跳过文件名语言匹配

### 测试
- 新增 39 个 `TestQuickNameMatch` 用例覆盖攻壳机动队全系列（SAC/ARISE/INNOCENCE/GIG/剧场版/特别篇/2026全集）+ Chainsmoker Cat

## v4.3.15 (2026-07-23)

### 修复
- TMDB：`search_tv`/`_fuzzy_match` 多候选匹配从「取第一个 anime」改为综合评分（名称相似度 + 关键词重叠 + 季号匹配 + 已完结加权），解决同名衍生作品被新版覆盖的问题
- TMDB：无集号标记时自动交叉搜索 TV/Movie，用 `_fetch_allnames` + 综合评分比较选出最优类型
- TMDB：`search_multi_infos` 降级路径增加 `compare_tmdb_names` 名称校验，不再盲取第一个类型匹配的条目
- 解析：动漫名清洗增加年份（1900-2030）和批量关键词（Complete/全集/合集/Season N）剥离，解决搜索名过长导致 TMDb 返回 0 结果的问题
- 下载：`add_torrent_and_get_id` 种子已在 qBittorrent 时返回真实 hash 而非 `"EXISTS"`，不再跳过历史写入导致下载页不可见
- 订阅：`is_exists_download_history_by_tmdb`（不限 STATE）改为 `is_completed_by_tmdb`（仅 STATE=completed），已删除/失败的种子允许重新下载

### 优化
- 解析：原始标题含批量关键词（`COMPLETE/全集/合集/BATCH/PACK/SEASON`）时跳过跨类型 Movie 搜索，减少不必要的 API 调用
- 下载：文件列表 ≥3 个递进编号文件判定为 TV，1 个文件判定为 Movie，类型不一致时输出 warn

### 测试
- 新增 `TestScoreFuzzyMatch`：综合评分 6 个维度（精确匹配、模糊区分、季号加分/惩罚、已完结、关键词重叠）
- 新增 `TestBatchKeywordsRE`：12 种批量关键词模式匹配
- 新增 `TestInferTypeFromFiles`：文件列表类型推断 13 种模式

## v4.3.14 (2026-07-22)

### 修复
- 签到：修复浏览器回退逻辑对已有专用 handler 的站点（如 FreeFarm）仍然触发 Chrome 回退的问题，增加 `is_dedicated` 判断和 `get_chrome_server_url()` 可用性检查
- 签到：浏览器挑战等待检测加入雷池 WAF 特征（`slg-bg`、`slg-box`、`雷池`、`安全拦截`），避免误判为页面已加载
- 签到：修复 `QuestionAnswerAgent.ready` 在 AI 服务未配置时 `None.ready` 空指针崩溃

## v4.3.13 (2026-07-22)

### 修复
- 签到：修复 API 响应中 `\uXXXX` Unicode 转义导致 `already_markers`/`success_markers` 匹配失败的问题（如 pterclub 猫站签到成功却被判定为失败）
- 签到：修复 `_http.py` 中 `config.get("success_markers") or DEFAULT` 把显式空列表 `[]` 当作 falsy 回退到默认标记的问题，导致 homepage-only 站点（ssd/春天、tnode/ZhuQue）永远无法匹配
- 签到：修复 HDSky/FreeFarm/Opencd/Tjupt 等 handler 签到 URL 使用 `signurl`（仅有域名），缺少各自的签到页路径（`/showup.php`、`/attendance.php` 等），导致签到请求发送到错误的 URL
- 签到：修复 HDSky handler 签到失败时错误提示为 "未获取到验证码"（实际已获取），改为显示服务器实际返回消息
- 签到：修复 FreeFarm handler `_check_cookie("login.php")` 误判 cookie 失效（页面正常也包含该字样），改为检查登录表单特征（`type="password"` 等）
- 签到：修复 Browser signin handler 固定 `time.sleep(10/15)` 等待 Cloudflare 五秒盾不可靠的问题，改为动态轮询等页面稳定（最长 120s）
- 签到：修复 U2/Tnode handler 硬编码域名（`u2.dmhy.org`、`zhuque.in`），改为从 `ctx.site_url` 动态推导
- 签到：修复 `_api.py` / `_wrap_auth` 使用 api_key 时手动拼接 `{header_name: api_key}` header 而非使用 `ApiKeyAuth` 认证类
- 签到：修复 `_types.py`（BakatestQaHandler）和 `hdsky.py` 中 `cookies=CookieAuth._parse_cookies(cookie)` 裸传 cookies，改为 `auth=CookieAuth(cookie)`
- 签到：新增 HDUpt 签到 handler、新增 hhanclub/ssd 签到配置、删除已停运的 hdchina handler 及站点配置

- RSS：修复 TTG/Ourbits/Zhuque/Starspace 等 handler 将 `cookies=ctx.cookie` raw string 传 `httpx.Client.request()` 导致 cookie 未生效、请求被拒绝（报 "请检查站点连通性"）
- RSS：修复 MTeam handler 误用 `ctx.headers` 取 API key（实际在 `ctx.api_key` 独立字段），改为 `ApiKeyAuth`
- RSS：修复 YemaPT handler 站点定义配置为 cookie 认证但不传 `CookieAuth`、只读 `ctx.headers` 的问题
- RSS：修复 `_api.py` marker 匹配同样存在 Unicode 转义失败的问题
- RSS：修复 `_api.py` api_key 认证手动拼接 header 而非使用 `ApiKeyAuth`，且未从站点定义 `api.auth.header_name` 回退获取 header 名
- RSS：MTeam/TTG/YemaPT/HDHome 从专用 handler 改为纯配置驱动的泛型 handler
- RSS：新增 rousi RSS 配置（Bearer 认证 + API endpoint）
- RSS：修复 `_api.py` `_resolve_auth` 未从站点定义获取 auth header_name 回退的问题

### 清理
- 删除已停运站点 hdchina（handler + 站点配置）
- nexus-chrome：修复 `Session.close_tab()` 吞掉 `tab.close()` 异常导致孤儿 tab 累积；添加 CDP `Target.CloseTarget` 回退关闭

## v4.3.12 (2026-07-22)

### 修复
- 插件中心：修复 `PluginRegistry.scan()` 每次请求都扫描内置插件并写入数据库，导致"已安装插件"页面加载慢/超时的问题；改为 60 秒节流，且 manifest 未变化时跳过数据库写入，保留热更新能力
- 启动速度：将 `plugin_sandbox.load_all()`、插件菜单同步、消息客户端初始化/菜单刷新从 lifespan 同步执行改为后台异步任务，缩短 `app.state.ready` 为 `true` 前的 503 窗口，减少前后端连接不上的情况
- 消息交互：修复 `MessageCommandHandler` 只识别 `/ptr` `/ptt` 等精确斜杠命令，中文"订阅""搜索""下载"及 `/rss` `/ssa` 等订阅类命令被当作插件命令或漏到无响应分支的问题；现在统一路由到 `MessageSearchService` 并立即回复"正在搜索/订阅"
- 刮削：修复 `Scraper._scrape_tv` / `_scrape_movie` 所有步骤共用一个 try/except，任意一步（douban API、TMDB 季详情、fanart 图片下载等）抛异常即终止整条刮削，导致 TV/动漫即使元数据配置已全开，下载完成转移后仍没有任何 NFO/图片生成；现在每个步骤独立 try/except 容错，单步失败只记日志不影响其他刮削输出
- HTTP 图片下载：修复 `HttpClient.request` 中用 `or` 短路表达式 pop `raise_exception`，`raise_for_status` 的默认 `True` 使 `or` 右侧永远不执行，导致 `raise_exception` 参数泄露到 `httpx.Client.request()` 引发 `TypeError`；改为分别 pop 后逻辑或

### 测试
- 新增 `PluginRegistry.scan` 节流与 manifest 未变化跳过写入的单元测试
- 新增 `message_webhook` 企业微信文本消息与 click 菜单事件路由的单元测试
- 新增 `Scraper` 配置热加载回归测试

## v4.3.11 (2026-07-22)

### 修复
- 消息客户端：修复 `active_interactive_clients` 用字符串 `search_type` 作为 key，但 Telegram / 微信 / Slack / Synology Chat 的 Webhook 与 `MessageDispatcher` 使用 `SearchType` 枚举查询，导致所有交互式客户端都匹配不到、提示未配置的问题
- 企业微信消息：修复 `GET /wechat` 与 `POST /wechat` 只读取 `signature` 参数，而加密模式下企业微信实际发送 `msg_signature`，导致 URL 验证/消息接收签名验证失败的问题
- 消息交互：修复 `message_webhook` 处理消息时创建 `MessageCommandHandler` 未传入 `thread_executor`，导致搜索/订阅命令被提交到线程池后未执行、用户发送消息无响应的问题
- 下载通知：修复搜索结果合并到原匹配媒体时 `TmdbLookup.merge_media_info` 没有复制 `poster_path`/`backdrop_path`/`fanart_*` 等图片字段，导致下载通知的 `media_info` 缺失图片、使用 TMDB 占位图的问题
- 文件识别：修复 `MediaService.identify_files` 批量识别文件时，从 TMDB 查回的结果没有写入 `poster_path`/`backdrop_path` 的问题
- 订阅匹配：修复 `SubscribeMatcher` 中电影种子在 `rss_movies` 不匹配后仍可能落入电视剧订阅匹配的问题，导致订阅电视剧却下载到同名电影资源（RSS 订阅同样走此匹配器，同步修复）

### 测试
- 新增 `message_webhook` 路由企业微信 `msg_signature` / `signature` 参数兼容的单元测试
- 新增 `TmdbLookup.merge_media_info` 图片字段合并的单元测试
- 新增 `SubscribeMatcher` 电影/电视剧订阅类型隔离的单元测试

## v4.3.10 (2026-07-21)

### 修复
- RBAC 登录日志：用户不存在时 `user_id` 由 `0` 改为 `NULL`，并允许 `RBAC_USER_LOGIN_LOGS.USER_ID` 为 nullable，修复外键约束失败导致登录异常报 `IntegrityError`
- 企业微信消息：代理地址 `default_proxy` 缺少 scheme 时自动补全为 `https://`，修复 `unknown url type` 错误
- 企业微信消息：新增 `GET /wechat` URL 验证与 `POST /wechat` 消息接收，支持 Token 签名校验和 AES 加密消息解密，返回 `success` 响应
- Telegram：新增 `secret_token` 配置，支持 Telegram 官方 `X-Telegram-Bot-Api-Secret-Token` 头部验证；同时修复 webhook 模式下 `_webhook_url` 从未被赋值的 bug
- 消息客户端：修复 `delete_message_client` 返回 `None` 导致 API 返回失败、前端无法删除消息客户端的问题
- 消息客户端：修复 `upsert_client` 修改时删除旧记录再插入新记录导致 ID 变化、产生重复客户端的问题，改为存在 `cid` 时直接更新原记录
- 消息客户端：修复 `ClientManager._ensure_loaded()` 只加载一次、不刷新已有客户端 `interactive`/`enabled` 状态的问题，导致开启交互后仍提示 `WeChat client not configured`

### 数据库迁移
- 新增迁移：将 `RBAC_USER_LOGIN_LOGS.USER_ID` 改为 nullable

### 测试
- 新增 `WeChat` 代理地址规范化、URL 验证、消息解析/解密单元测试
- 新增 `Telegram` Webhook URL 构造与 `secret_token` 单元测试

### 修复
- 自动删种：修复 `filter_status` 按下载器支持状态校验导致 `Stopped` 等全局状态保存失败的问题
- 自动删种：修复 `RemoveStrategy.from_dict` 未将字符串状态转换为 `TorrentStatus` 枚举，导致状态过滤不生效的问题

### 测试
- 新增 `TorrentRemoverService` 与 `RemoveStrategy` 状态校验/转换单元测试

## v4.3.8 (2026-07-20)

### 修复
- 删除任务：`TORRENT_REMOVE_TASK.NOTE` 列改为 nullable，修复插入时 `NOT NULL constraint failed` 错误
- 自动签到：前端历史记录请求文件路径从 `signin_history.json` 修正为 `history.json`，解决签到历史页面空白问题

## v4.3.7 (2026-07-20)

### 修复
- IYUU 自动辅种：补充 `run()` 方法，支持调度任务/插件框架手动立即执行
- 系统日志：初始加载与 SSE 本地缓存上限从 200 条提升到 1000 条
- 自动签到：403/HTML/468 回退浏览器逻辑细化，异常时自动回退浏览器；Bakatest 问答路径类型加固；API 站点也允许使用通用 HTTP 回退
- TorrentMark 插件：manifest 配置项缺失逗号格式修复

## v4.3.6 (2026-07-19)

### 修复
- IYUU 辅种：站点引擎解析下载链接（genDlToken/api/HTML 统一）、`sites` 留空不辅种、`start_torrents` 补 `downloader_id`
- 刷流 `DOWNLOAD_ID` 为空时跳过入库（修复 NOT NULL 约束）
- CookieCloud 混合认证站点 cookie 校验改用 HTML 登录态
- 自动转移做种：下载器选择改多选、`progress` 判准修正、路径容错
- 下载联动删除：`PluginContext.read_plugin_data` 跨插件恢复转种/辅种完整清理
- 自动签到：403/HTML/468 自动回退浏览器、U2 handler 大小写匹配、chdbits xpath 空结果守卫
- `PluginContext.read_plugin_data` 跨插件数据读取 API
- speedlimiter / torrentmark manifest 补 `downloaders` 字段

## v4.3.5 (2026-07-19)

### 修复
- RateLimitEngine 限流解析支持 `1/2s`/`1/30s` 等分数间隔格式
- RateLimitEngine token_bucket 路径补 `timeout>0` 阻塞循环（Redis/Memory 双后端统一）
- Redis 限流后端 backend_rate 修正（不再乘 1000，Lua 脚本内部已处理 ms→s 转换）
- Redis 后端 NOSCRIPT 异常重载脚本重试
- IYUU 默认限流调整为 `1/30s`（匹配 reportExisting ~1 次/分钟的限制，避免触发冷却封禁）

## v4.3.4 (2026-07-19)

### 修复
- IYUU reportExisting JSON body 发送方式修复（缺少 `sid_list`）
- IYUU API 默认限流从 `5/s` 调整为 `1/2s`，避免服务端限流

## v4.3.3 (2026-07-18)

### 新增
- 插件自定义 API 框架：`PluginContext.register_api(path, handler)` + 通用调度路由 `GET/POST /plugins/{id}/api/{path}`，支持插件声明式注册自定义接口，按 HTTP method 控制 view/manage 权限，sandbox 卸载时自动清理
- IYUU 自动辅种插件绑定站点功能：前端鉴权页面（`frontend/index.mjs` DI render 组件，列表+行内输入+持久化徽章），后端 API（bindable_sites/bind_site）+ `bound_sites.json` 持久化记录；辅种任务 IYUU API 与站点级限流；manifest 补充 downloaders/sites 配置项
- IYUU 自动辅种插件适配当前服务层架构：`add_torrent`/`exists_torrents` 改为通过下载器客户端实例调用；种子下载链接补全 host+schema、剥离凭证占位符；`_can_seeding` TorrentStatus 枚举判定；`_resolve_local_site` 支持 HTML 站点定义按名称匹配本地配置
- Depth Studio（dstudio.me）与 Sunny（sunnypt.top）站点 HTML 配置（NexusPHP table 模板，分类 401-409）

### 修复
- CookieCloud 混合认证站点（api_key/bearer 类型）cookie 校验失败：改为按站点认证类型分流——纯 cookie/csrf 走引擎 test_connection，api_key/bearer 走 HTML 首页登录态校验
- 刷流已存在于下载器的种子（qb EXISTS 分支 DOWNLOAD_ID 为 None）插入 `SITE_BRUSH_TORRENTS` 触发 NOT NULL 约束，改为跳过入库

### 测试
- 新增 CookieCloud 插件校验、IYUU 插件（辅种+绑定+解析）、插件 API 注册表与调度路由、刷流入库测试（4 个测试文件，全量 1187 通过）

## v4.3.2 (2026-07-18)

### 新增
- 下载器设置支持浏览选择目录：新增 `/download/downloaders/browse_dirs` 端点，通过下载器 API 读取默认保存路径、分类路径及已有种子保存路径；下载保存目录从下载器浏览选择，Nexus Media 访问目录支持本地/存储后端浏览选择
- 下载器客户端新增 `list_remote_dirs` 能力：qBittorrent（默认保存路径 + 分类路径 + 种子路径）、Transmission（会话目录 + 种子路径）、Aria2（全局下载目录）

### 修复
- 修复目录同步保存后目的目录丢失、点击编辑变新增一列的问题（前端请求字段 `id`/`target` 与后端契约 `sid`/`dest` 不一致）
- 修复目录同步列表目的目录、同步方式、目标后端显示不正确的问题（读取字段与后端返回 `dest`/`operation`/`dst_backend_id` 不一致）
- 修复服务面板同步目录列表为空的问题

### 测试
- 新增下载器 `list_remote_dirs` 单元测试与 `browse_dirs` 路由测试

## v4.3.1 (2026-07-16)

### 新增
- 探索页媒体卡片新增类型、国家/地区、语言元数据标签展示
- 探索页支持类型、地区、语言筛选，Bangumi 数据补默认元数据以支持筛选
- 刮削设置新增配置持久化：读取/保存到数据库 `system_dict`
- 后端新增 `/system/config/scraper` 读取与 `/system/config/scraper/save` 写入端点

### 优化
- 推荐服务统一解析豆瓣 overview 和 TMDB 元数据并按白名单过滤
- 完善 `media_metadata` 领域模块：统一类型、国家/地区、语言映射与聚合

### 修复
- 修复 Bangumi 推荐数据缺失 genres/countries/languages 导致筛选为空
- 修复豆瓣 overview 解析演员名混入类型的问题
- 修复 HDDolby API 分页请求 content-type 格式
- 修复 btschool 站点配置 int 字段导致的 Jinja 渲染错误

## v4.3.0 (2026-07-15)

### 重构
- 自动签到（autosignin）插件站点驱动重构：签到 URL 从站点引擎动态读取，不再硬编码；新增配置驱动流程，支持 API、HTTP 和浏览器自动化三种通用签到方式（ADR-018）
- 自动生成 RSS（autogenrss）插件重构：内置站点生成器迁移到插件本地 handler 与注册表模式

### 新增
- 新增通用 HTTP 签到配置回退 `__fallback_http__.json`
- 新增 `haidan`、`hares`、`hdarea`、`pterclubnet`、`yemapt` 等站点签到配置
- 新增 `crabpt`、`railgunpt`、`xingtan` 站点定义配置
- 新增 `hdchina`、`ttg`、`u2` 动态 token/表单处理 handler

### 优化
- 统一浏览器自动化传输：`HttpClient` 在 `is_browser` 模式下直接通过 `BrowserModeConfig` 访问浏览器，上层无需额外分支
- 优化自动签到日志输出，包含站点解析、handler 选择、失败详情和重试名称
- Docker 构建优化：使用 `uv sync --frozen --no-cache --no-install-package nexus-media` 避免构建挂起
- 容器服务命名规范化：`nexus-media-chrome` → `nexus-chrome`、`nexus-media-ocr` → `nexus-verify`
- 实验室设置页布局优化：服务开关与地址输入成对展示，禁用态随开关联动

### 修复
- 修复 M-Team `localStorage` 域名解析从硬编码 `m-team.io` 改为实际站点域名
- 修复 CookieCloud `localStorage` 同步同时兼容 `dict` 和 `list` 格式
- 修复 `btschool` 签到路径和成功判定（`index.php?action=addbonus` + 不存在 “每日签到” 按钮）
- 修复 `rousi` 签到使用 `x-sign-token` 认证头
- 修复签到历史文件路径为 `history.json`
- 修复失败站点自动进入重试列表逻辑，避免 `retry_keyword` 误过滤
- 修复站点 ID 识别日志显示正确的定义 ID（`audiences`、`m-team`、`rousi`、`btschool`）
- 修复 Plex 客户端若干 pyright 类型报错（空值访问、返回类型不一致）

### 测试
- 新增 autosignin API/HTTP handler 测试、配置存储测试
- 新增 autogenrss 插件测试
- 新增 OCR 基础设施测试


### 优化
- 统一浏览器自动化传输：`HttpClient` 在 `is_browser` 模式下直接通过 `BrowserModeConfig` 访问浏览器，上层无需额外分支
- 优化自动签到日志输出，包含站点解析、handler 选择、失败详情和重试名称
- Docker 构建优化：使用 `uv sync --frozen --no-cache --no-install-package nexus-media` 避免构建挂起
- 容器服务命名规范化：`nexus-media-chrome` → `nexus-chrome`、`nexus-media-ocr` → `nexus-verify`
- 实验室设置页布局优化：服务开关与地址输入成对展示，禁用态随开关联动

### 修复
- 修复 M-Team `localStorage` 域名解析从硬编码 `m-team.io` 改为实际站点域名
- 修复 CookieCloud `localStorage` 同步同时兼容 `dict` 和 `list` 格式
- 修复 `btschool` 签到路径和成功判定（`index.php?action=addbonus` + 不存在 “每日签到” 按钮）
- 修复 `rousi` 签到使用 `x-sign-token` 认证头
- 修复签到历史文件路径为 `history.json`
- 修复失败站点自动进入重试列表逻辑，避免 `retry_keyword` 误过滤
- 修复站点 ID 识别日志显示正确的定义 ID（`audiences`、`m-team`、`rousi`、`btschool`）
- 修复 Plex 客户端若干 pyright 类型报错（空值访问、返回类型不一致）

### 测试
- 新增 autosignin API/HTTP handler 测试、配置存储测试
- 新增 autogenrss 插件测试
- 新增 OCR 基础设施测试
- 新增 `ocr_server_enabled` 远程 provider 测试

## v4.2.8 (2026-07-11)

### 新增
- 网页自动化（浏览器过盾）原生集成到 `HttpClient`：站点开启 `chrome` 开关后，抓取请求自动经 Chrome 服务器过盾（Cloudflare / 五秒盾 / 雷池）并复用 Cookie，上层调用点无需改动（ADR-017）
- 新增站点级 `browser_render` 开关：可选返回浏览器渲染后的 DOM（适配 JS 前端渲染站点），渲染 HTML 解析前自动剥离 tbody 归一化，现有直接子选择器规则无需修改
- 新增 `BrowserSession` / `AsyncBrowserSession` 交互式浏览器会话客户端，用于签到等多步流程（navigate / click / input / execute / fetch）
- 实验室配置新增 `chrome_enabled` 全局开关（站点级仍需单独开启 `chrome`）

### 优化
- 签到（autosignin）、企业微信 IP 变更、自动生成 RSS 等插件改用新的 `BrowserSession` 交互客户端
- 索引器透传 `chrome` / `browser_render` 站点配置，浏览器模式判定不再依赖全局 Chrome 探活
- `HttpClientConfig` 默认超时提升，适配浏览器过盾耗时

### 修复
- 修复 Alembic 迁移 `oxrva77k36j6` 父节点挂接错误导致迁移链分叉出多个 head，`alembic upgrade head` 失败、迁移无法执行
- `DOWNLOAD_SETTING.NOTE` 列改为可空，避免下载设置备注为空时写入失败
- 备份时 `config.yaml` 不存在（纯环境变量运行）导致备份中断，改为存在才复制
- 移除失效的旧 `ChromeClient`（仍在调用已下线的 `/tabs` 接口）

## v4.2.7 (2026-07-10)

### 修复
- 修复刷流删种规则所有 lambda 被调用时缺少 `rv` 参数（`rule_value` 未传入 `check_func`），导致删种功能完全不生效
- 修复删种规则 `values` 字典缺少 `hr` 键，HR 规则在 and 模式下错误阻止所有删种
- 修复 `check_range_rule` 非数字规则值导致 `ValueError`，单条种子异常影响整批删种处理
- 修复停种任务无异常守卫，单条种子异常会杀死整个停种调度周期
- 修复 `avg_upspeed` 倍数错误（`1024**3` → `1024`），用户配置的 KB/s 阈值被放大百万倍，平均上传速度删种/停种规则永不生效
- 修复 `dateutil.parser` 隐式导入依赖其他模块加载顺序

### 测试
- 新增 `BrushRuleEngine` 单元测试 114 条，覆盖 `check_range_rule` / `check_remove_rule` / `check_stop_rule` / `check_rss_rule` / 解析格式化
- 新增跨天时间段测试 10 条（如 `22:00-06:00`），验证刷流时间段跨天逻辑正确

## v4.2.6 (2026-07-08)

### 修复
- 修复文件名开头方括号中文剧名被误删（如 `[虚颜]` 只剩英文名，导致刮削匹配错误影片）
- 修复修改用户名导致权限丢失，支持修改用户名；编辑资料不再因空角色列表清空角色
- 修复 CookieCloud 同步后站点测试/搜索仍使用规范域名而非用户配置域名
- 修复 API 站点（M-Team/Zhuque）测试连接空 body 导致误报
- 修复菜单设置与插件菜单重启后被重置为默认
- 修复订阅卡片悬停闪烁、右边缘截断、移动端末尾卡片偏大
- 修复 Bangumi/TMDB 网页搜索/图片下载器等境外请求未走代理
- 修复代理在 socks5 及 https 键配置时调用方取不到
- 修复 cookiecloud 站点去重（按站点 id 保留最后一条并防止重复新增），同步结果标注具体域名

### 新增
- 订阅 TMDB 信息贯穿下载/转移/刮削全链路，文件转移与刮削可直接使用订阅时确认的 TMDB 身份，避免依赖文件名解析
- 菜单管理增加「重置到初始状态」功能，支持恢复误修改的内置菜单
- 菜单新增 IS_BUILTIN 字段区分内置与用户自建菜单；删除内置菜单后记录墓碑，重启不重建

### 优化
- 代理配置归一化：`app.proxies` 中 `http`/`https` 任一键配置即全局生效，支持 socks5/socks5h

## v4.2.5 (2026-07-08)

### 新增
- 站点维护新增「批量测试」：可勾选站点后并发测试连通性，展示成功率、延时与失败原因
- CookieCloud 同步支持域名择优：在同步域名 / 当前签到域名 / 配置别名中，按可用性、稳定性（成功率）与延时自动选择最优域名（带迟滞防抖）

### 修复
- 媒体详情「已订阅」显示具体订阅的季；探索 / 详情 / 资源搜索页多季电视剧支持追加与管理订阅（勾选订阅、取消勾选退订）
- 修复多季订阅退订不生效（季号存储格式 `S01` 与前端 `1` 不匹配导致删除条件不命中）
- 资源搜索：切换页面再返回时恢复当前搜索进度与结果，而非展示上一次的旧结果；修复「正在搜索」标题为空
- 资源搜索海报卡片点击进入媒体详情，不再直接触发搜索
- 站点测试连接、搜索、详情页链接改用用户配置的站点域名（签到域名 / 别名），不再固定使用站点规范域名
- 修复 API 站点（M-Team / Zhuque 等）测试连接误报密钥失效 / 连接失败：POST 空 body 改为发送 `{}`，登录判定兼容 `code` / `status` 成功响应
- 用户管理修改用户名后权限丢失：编辑资料不再因空角色列表清空角色；支持修改用户名；修复邮箱校验属性名错误
- CookieCloud 站点去重（按站点定义 id 保留最后一条并防止重复新增），同步结果标注具体域名，仅在 Cookie 实际变化时记为「已更新」，新增站点优先级递增避免重复

### 优化
- 媒体库首页接口并发获取媒体数量 / 播放历史 / 空间 / 媒体库 / 继续观看 / 最新入库，显著降低耗时并放宽前端超时
- 资源搜索 1000+ 结果卡顿优化：分组分页渲染（默认 30 条，可加载更多），折叠分组不渲染
- 「更多推荐」页卡片统一为通用媒体卡片
- 订阅季选择框改为从左到右自适应网格；修复电视剧订阅管理页卡片竖排、订阅卡片悬停闪烁、右边缘悬浮面板被截断、移动端末尾卡片偏大等布局问题
- 移除重复站点配置 `ptchdbits.json`，并入 `chdbits` 的域名别名

## v4.2.4 (2026-07-07)

### 新增
- 电影/电视剧订阅支持「只订阅免费」：订阅可设置仅匹配免费/促销资源

### 修复
- 修复免费/促销状态识别错误，避免非免费资源被误判

## v4.2.3 (2026-07-07)

### 修复
- 修复 M-Team RSS 订阅下载失败：预签名下载链接（dlv2 的 `sign` 参数自带认证）不再附加站点 API Key，避免被当作 API 认证返回 JSON 错误；enclosure 链接过期时自动用详情页 tid 重新申请新链接重试
- 修复插件框架加载时从未注册 manifest 声明的事件钩子，导致 `on_hook`（`plugin.config_changed` 等）全部失效
- 修复 RBAC 角色查询在 session 关闭后访问懒加载关系触发 `DetachedInstanceError` 刷屏日志，改为 `selectinload` 预加载
- 修复搜索进度任务完成后返回 0 导致前端轮询无法结束
- 修复搜索结果制作组为空时显示空按钮，改为显示"未知"
- 修复媒体搜索有结果时仍显示"未找到相关媒体"空状态
- 修复多站点做种数据解析（hhanclub/hdsky/star-space/织梦等 NexusPHP 站点）：自动检测表头列索引、支持 JS 分页、用户详情页汇总提取、修复字符串逐字符遍历导致的 IP 统计错误

### 新增
- 内置索引器关键字搜索支持自动翻页（最多 5 页），修复海贼王等长剧集只能获取首页 100 条数据的问题
- 新增「站点分享率监控」插件：定时检查各站点分享率，低于阈值发送通知，自动排除第三方索引器
- 新增「Tracker 管理」插件：批量替换下载器中种子的 tracker 地址，支持正则匹配
- 应用层 DNS 映射：`HttpClient`/`AsyncHttpClient` 支持 `host_mapping` 及全局映射注册，请求时动态解析无需重建连接池
- `customhosts` 插件改为应用层 DNS 映射，无需 root 权限修改 `/etc/hosts`
- `PluginContext` 新增 `get_plugin_config`/`set_plugin_config` 跨插件配置 API
- 下载器客户端补充 tracker 增删改方法
- 站点详细数据对无上传下载的不活跃站点整行降低透明度标识

### 优化
- `cloudflarespeedtest` 替换 hosts 前检查域名是否 Cloudflare 托管，避免非 CF 站点 SSL 握手失败
- 预签名下载链接判断改为配置驱动（`download.presigned`）
- 插件质量统一整改（18 个）：手动运行绕过启用检查、移除「立即运行一次」冗余开关、补充协作式线程停止
- 下载器/站点 API 支持 `source` 过滤，排除第三方索引器站点
- 更新项目依赖

## v4.2.2 (2026-07-06)

### 修复
- 修复插件首次启用菜单不加载：`RBACMenu.to_dict()` 在 session 关闭后访问 `children` 触发 `DetachedInstanceError`，异常被静默吞掉导致角色菜单分配失败。改为 `object_session(self) is not None` 检查
- 修复 `HttpClient` / `AsyncHttpClient` keep-alive 模式下连接复用导致远程返回陈旧数据
- 修复 `CookieCloud` 插件 `re.match` → `re.search` 关键词匹配失效、同步时未正确遍历所有站点、域名别名匹配不完整
- 修复站点 favicon 下载时未处理连接超时导致引擎初始化阻塞
- 修复站点图标缓存 key 未区分域名导致不同站点图标错乱
- 修复 `IndexerSiteConfig` 缺少适配器导致刷流取种异常
- 修复图片代理路由 `/img` 缺少去重逻辑导致重复下载
- 修复字符串工具 `SPLIT_CHARS` 缺少 `★` 分隔符导致剧集标题识别失败
- 修复搜索进度在任务完成后返回 0 导致前端轮询永不结束：`ProgressTracker.get_process()` 在 `end()` 后因 `enable=False` 返回 `None`，改为始终返回已有进度详情
- 修复种子限速参数（上传/下载/分享率/做种时间）为 `None` 时 `float(None)` 报错导致下载记录入库失败
- 修复种子促销因子（`uploadvolumefactor`/`downloadvolumefactor`）为空字符串时 `float("")` 报错导致搜索结果过滤异常
- 修复搜索结果 `media_type` 使用 `display_name`（如 "TV Show"）而非 `value`（如 "TV"）导致前端类型筛选失败
- 修复 WEB 搜索同步阻塞请求线程导致前端超时，改为后台线程池异步执行

### CI
- 修复 Telegram 发布通知中 changelog 含未转义 HTML 标签导致消息发送失败

### 优化
- 数据库连接池大幅缩减：`pool_size` 50→10、`max_overflow` 100→10、`pool_recycle` 3600s→1800s，容器内存从 ~782MB 降至 ~480MB（-39%）
- `SceneChecker` 识别不区分大小写，支持 `★08(abema先行版)★` 等特殊格式的集号提取
- NFO 生成器支持 `&lt;uniqueid&gt;` 写入 TMDB/IMDB ID
- 媒体刮削器支持海报多图下载并写入 NFO
- Docker Compose 所有服务添加日志轮转（`max-size: 10m, max-file: 3`），防止日志撑爆磁盘

### 新增
- 前端 Docker 镜像新增 `BACKEND_HOST` / `BACKEND_PORT` 环境变量，支持独立 `docker run` 部署时动态指定后端地址
- Docker 部署文档：修正后端镜像描述（Debian 非 Alpine），新增前端单独部署章节，统一 `installation.md` 与 `docker/readme.md`

## v4.2.1 (2026-07-05)

### 修复
- CookieCloud 插件重构：修复 `re.match` → `re.search` 黑/白名单关键词匹配失效；移除错误的 `test_connection` 条件门，始终同步云端 cookie；`HttpClient` 改用 `with` 上下文管理器防止连接池泄漏；域名别名支持（`_find_matching_sites` 遍历所有匹配站点而非仅第一条）
- 修复 `BrushTaskRepositoryAdapter` 缺少 `insert_brush_event` 导致刷流进种异常
- 修复 qBittorrent 已存在种子时 `DownloadPipeline` 返回空 `download_id` 导致误报"下载失败"：区分真实错误（retmsg 有内容）和 EXISTS 情况（retmsg 为空）
- 修复 `RSS_RULE` / `REMOVE_RULE` 列 VARCHAR(255) 溢出为 TEXT：JSON 规则超过 255 字符时报 `Data too long`
- 修复删除刷流任务时未清理对应的 `BRUSH_EVENT_LOG` 事件日志

### 新增
- 刷流事件日志详细原因：进种时记录匹配的选种规则（免费/2X免费/体积符合/发布时间符合等）+ 种子即时状态（免费标记/HR/做种数/体积）
- 刷流未进种事件日志（skip）：被选种规则拒绝时记录具体拒绝原因
- 刷流事件日志支持跳转种子详情页：新增 `TORRENT_URL` 列，前端种子名渲染为可点击链接
- 刷流种子记录新增 `PAGE_URL` 列：删种/停种时也能获取种子详情页 URL

## v4.2.0 (2026-07-04)

### 新增
- 订阅质量/分辨率支持多选：编辑订阅和默认设置弹窗改为 NSelect multiple，后端过滤支持逗号分隔值
- 订阅添加/更新后自动触发即时队列搜索（SUBSCRIBE_ADD 事件处理器）
- 下载页面显示种子大小（card + list 两视图）
- ERROR 状态订阅自动重试：每 5 次队列搜索周期恢复一次
- 订阅卡片/详情弹窗新增质量（紫色）和分辨率（青色）标签，9 类标签全部使用独立 HSL 色值

### 优化
- 搜索并行化：`_search_movies` / `_search_tvs` 改用 ThreadPoolExecutor（5 workers）并发处理
- 协调器锁 TTL 从 14400s 降至 300s，新增后台守护线程自动续期（每 60s 延长 300s）
- 策略全局锁 TTL 从 1800s 降至 300s，新增 `strategy_lock` 上下文管理器自动续期
- 监控器运行时间持久化：`SystemConfig` 存储 `_last_queue_run / _last_rss_run / _last_search_run`，避免重启全量搜索洪峰
- `monitor.run()` 移除 `wait(tasks)` 阻塞，改为非阻塞提交 + `_running_tasks` 去重
- 质量/分辨率 tag 改为独立色值：规则(rose) / 洗版(amber) / 质量(purple) / 分辨率(cyan) / 制作组(mint) / 包含(green) / 排除(rose) / 订阅站(blue) / 搜索站(slate)
- 发现页"编辑"入口预加载订阅默认设置

### 修复
- 修复订阅默认设置未应用到订阅：电影页 `res?.data` 误判，后端仅在字段为 None 时回填默认
- 修复协调器锁存在性检查的竞态：`try_acquire` 移到 `check_exists_medias` 前面
- 修复协调器锁 key 对空 TMDB ID 共享风险：降级链 `tmdb_id → rssid → title:year`
- 修复 M-Team 中文搜索失效：`language` 改为 `zh`
- 修复订阅重新下载被旧历史阻塞：`filter_downloaded` 改用 `is_completed_by_tmdb`
- 修复 qBittorrent 批量获取种子属性时单个异常导致整体列表丢失：逐条 try/except
- 修复下载页面 `v-html` XSS 警告：tooltip 改用文本插值
- 修复 `rssid` 类型不一致：前后端统一改为 `int`
- 修复前端质量/分辨率格式化：`formatRestype` / `formatPix` 大小写不敏感映射

### 变更
- 默认订阅设置弹窗重构：复用 `SubscribeEditModal` 同款分段布局 + 站点卡片样式
- 订阅历史页改为横向卡片 + 电影/剧集筛选 tab
- 创建共享图片工具 `utils/image.ts`（`getImgUrl` / `handleImageError` / `fallbackImage`）
- 创建共享过滤选项 `utils/subscribe.ts`（`restypeOptions` / `pixOptions` / `splitMultiSelect` / `joinMultiSelect`）

## v4.1.13 (2026-07-02)

### 重构
- 插件前端 UMD → DI 模式：插件改为 `export default function(host)` 接收宿主注入的 Vue/IconifyIcon/API，不再依赖 import map / CDN / window 全局变量
- 索引器配置从 `SYSTEM_DICT` 迁移到 `INDEXER_CONFIG` 专用表，与 Downloader/MediaServer 保持一致

### 修复
- 修复视频标题解析 CRC 标签 `[EE32E859]` 被误判为集号 E859
- 修复内置索引器站点名大小写不匹配导致站点不显示（Jackett "Mikan" vs 引擎 "MiKan"）
- 修复禁用第三方索引器后其站点仍在 `/api/site/sites`、`/api/download/indexers` 等接口中出现
- 修复禁用第三方索引器后其站点仍参与搜索
- 修复令牌自动续期漏洞：过期 JWT 不再自动签发新令牌
- 修复 `SystemUtils.execute` 使用 `shell=True` 导致命令注入风险
- 修复 `ConfigRepository.execute` 暴露原始 SQL 执行接口
- 修复 TransferPipeline 刮削使用下载源路径而非目标路径
- 修复 DownloadMonitor 预热与正常检查使用不同过滤器
- 修复下载器标签排序硬编码 "NEXUS_MEDIA" 而未使用 PT_TAG 常量
- 修复 Scraper/FileTransferService `settings.get()` 链式调用无 None 保护导致 AttributeError
- 修复 cleanup_service 解析 SEASON_EPISODE 时 `int("01E05")` 崩溃
- 修复 StorageUsage 组件 usedPercent 类型为字符串触发 Vue prop 警告
- 修复用户列表 API 缺失 is_superadmin 字段，角色加载失败静默吞异常
- 修复 transfer_repository 跨 session 查-插竞态条件
- 修复插件依赖注入缺失：PluginSandbox 未注入 searcher/downloader/subscribe 等服务
- 修复 `_do_run_plugin` 重复手动加载模块导致缺少依赖注入
- 修复插件历史页面每次需禁用启用后才显示：refreshSidebarMenus 清除动态路由后未重载插件
- 修复下载失败静默：fire-and-forget 线程异常不再吞掉，push DOWNLOAD_FAILED 到 SSE 队列
- 修复 DownloadedCore._get_downloader_lock 竞态：改为双层检查+模块级锁
- 修复 DownloadedCore.transfer 锁范围过窄，扩展至完整转移循环
- 修复 pipeline.insert_download_history DB 写入失败导致流水线崩溃
- 修复字幕下载 ThreadExecutor Future 丢弃，添加带标题的异常日志
- 修复 download_event_queue 无限内存增长：Queue() → Queue(maxsize=1000)
- 修复 find_hardlinks 返回 raw [] 而非 CommonResponse
- 修复 torrentleech.json page_url 缺少 domain 字段映射
- 修复 CORS allow_origins=["*"]+allow_credentials=True 违反规范
- 修复 db_session_cleanup 死亡中间件（body 为空）
- 修复 search_repository SQLite 非原子 INSERT：改用 sqlite_insert+on_conflict_do_update
- 修复 SubscribeAddPayload 歧义联合类型：__post_init__ 归一化 str→int/list/bool
- 修复 lifespan 无异常处理导致静默启动失败，每步 try/except+log.error
- 修复后端根路径 / 直接报错：添加友好提示 JSON 返回 app/version/message
- 修复前端版本号未显示：package.json 同步至 4.1.13，关于页面展示前端版本
- 修复 TransferLineChart 渐变色语法非法：改用 hsla 格式
- 修复 StorageUsage usedPercent 类型为字符串触发 Vue prop 警告
- 修复 GaugeChart 未注册：echarts.ts 导入 GaugeChart
- 修复首页图表面板 ECharts CSS 变量无法渲染：改用硬编码+useChartTheme 主题切换

### 变更
- 首页图表全面升级：堆叠面积图/环形图/仪表盘/玫瑰图/水平柱状图/渐变柱状图
- 首页+媒体库图表配色统一：入库趋势/媒体库分布采用暖橙-蓝-粉配色
- 新增 16 色调色板共享常量 `chartColors.ts`
- 新增暗色模式支持：`useChartTheme` composable 监听主题切换
- 新增存储空间 ECharts 仪表盘（阈值绿→橙→红）
- 站点做种分布恢复玫瑰图
- 媒体库最近动态改为时间线样式
- 媒体库存储卡片重设计：大号百分比 + 进度条 + mt-auto 撑满高度
- 用户管理操作按钮改为下拉菜单
- 站点统计 近7天流量增量/上传量分布 位置调换

### 安全
- 令牌自动续期漏洞修复：过期 token 返回空 payload，不再自动续期
- 命令注入修复：`SystemUtils.execute` 改用 `shlex.split` + `shell=False`
- 原始 SQL 暴露修复：`execute` 重命名为 `_execute_raw` 标记为仅初始化使用
- 登录端点限速：`/api/auth/login` 5次/分钟/IP

### 新增
- Jackett/Prowlarr 索引器支持启用/禁用开关
- 站点统计卡片颜色优化，8 张卡片使用独立色值
- 数据库外键约束：CONFIGFILTERRULES/CONFIGCATEGORYRULE/CUSTOMWORDS/APIKEYLOG
- 数据库索引：DOWNLOADER(ENABLED,TYPE)/CONFIGSYNCPATHS(ENABLED)/SITEBRUSHTORRENTS(DOWNLOAD_ID)/SEARCHRESULTINFO(SEEDERS)/SITEUSERINFOSTATS(USERNAME)
- 事件系统：异步事件类型注入 (DOWNLOAD_STARTED/DOWNLOAD_FAILED/SUBSCRIBE_FINISHED)

### 变更
- 插件前端文件名 `index.umd.js` → `index.mjs`
- 用户管理卡片操作按钮改为下拉菜单模式
- 插件路由从绝对路径改为相对路径，支持 generateAccess 重载后自动恢复
- RBAC 用户查询全部改为 selectinload 链式预加载角色/权限/菜单
- subscribe/system handler 添加 payload isinstance 防御检查

## v4.1.12 (2026-07-01)

### 修复
- 修复刷流一直不进种：`resolve_torrent_attr` 硬编码 POST 导致 rousi/tnode 的 GET 端点失败
- 修复 `get_tid_by_url` 忽略 `site.tid_pattern`，导致 rousi UUID TID 提取失败
- 修复刷流、订阅匹配、下载三条链路中 `api_key`/`bearer_token` 丢失，导致 API 站点认证失败
- 修复 `Torrent.save_torrent_file` 硬编码 `CookieAuth`，忽略站点实际认证类型
- 修复 `_build_auth` 缺少 `ApiKeyAuth` 对象，CSRF 认证缺少 `CookieAuth`
- 修复 `resolve_torrent_attr` 数值型 free 值与配置字符串比较失败，改为 `float()` 数值比较
- 修复 mteam 刷流 302 参数错误：`data=body`(dict) 被 httpx form-encode，mteam API 接受 form-encoded 而非 JSON
- 修复 `POST /api/brush/tasks/run` 同步阻塞超时，改为 `ThreadExecutor` 后台执行
- 修复 `get_downloading_torrents` 只查询 `status="downloading"` 导致暂停种子被排除，改为多状态列表
- 修复 `detail_page_url` 未配置时 HTML 种子的详情页解析失败，新增引擎兜底（用 torrent_url）
- 修复 `rss_free` 字符串 `"N"` truthy 误判，改为布尔比较
- 修复受众页面结构变化导致 free XPath 不匹配（实际是 `detail_page_url` 缺失）
- 修复暂停任务仍执行删种/停种，新增状态检查
- 修复删种集合差逻辑导致暂停种子被误删，改为一次 `get_torrents` 全量查询
- 修复 `RULE_ID` Integer 列存 JSON 字符串报错，改为三个独立 FK 列替代
- 修复手动删种后保种体积不更新阻止进种，RSS 检查前先清理

### 新增
- `torrent_attr` 配置新增 `body_format` 字段，区分 POST 请求体格式
- rousi/mteam 站点配置新增 `2xfree_key`/`2xfree_value`，支持 FREE_2X 检测
- 75 个 NexusPHP 站点补上 `detail_page_url`
- SITE_BRUSH_RULE 新增 `TYPE` 列（rss/remove/stop），规则按类型独立创建和管理
- SITE_BRUSH_TASK 新增 `RSS_RULE_ID`/`REMOVE_RULE_ID`/`STOP_RULE_ID` 三列，刷流任务可分别选择三种规则
- `/download/tasks` 新增分页参数 `page`/`page_size`，返回 `{items, total}`
- 下载器批量操作端点：`/tasks/batch/start`、`/tasks/batch/stop`、`/tasks/batch/remove`
- 下载任务响应新增 `labels`/`category` 字段
- `_fetch_page` 支持 API 站点的 `_build_auth` 认证

### 变更
- `_build_auth` 统一三种认证类型的 auth 对象创建（`ApiKeyAuth` / `BearerAuth` / `CookieAuth`）
- `resolve_torrent_attr` / `engine_download` 统一 Content-Type 处理
- `get_downloading_torrents` 改用 `TorrentStatus` 列表过滤（qBittorrent/Aria2/Thunder 统一）
- `category` 从 list 转为 string 传递给前端
- 删除 `RULE_ID` 列，迁移为三个独立 FK 列 + Alembic 迁移
- `_load_rules_from_template` 支持三个独立规则 ID 加载

### 前端
- 通知统一使用 `useAppNotification`（duration:3000），修复永不消失问题
- 正在下载页新增分页、批量选择/暂停/开始/删除、标签/分类彩色 badge、状态 badge
- 海报 TMDB URL 直转 `/img/tmdb/` 路径，绕过 301 重定向
- 刷流规则页重构：Type Tab 三栏分离、面板式卡片、类型彩色标签
- 刷流任务表单：三列独立规则选择器，移除旧合并选择器

## v4.1.11 (2026-06-30)

### 新增
- 统一索引器站点管理：引入 `INDEXER_SITE_CONFIG` 表，内置索引器按站点级 `enabled` 过滤，支持 `BuiltinIndexerEnabled` 总开关
- 启动时自动创建公开（BT）内置站点（0Magnet / 1377x / ACG.RIP / 动漫花园 / MiKan / Nyaa），优先级 100~105
- `INDEXER_SITE_CONFIG` 新增 `DEFAULT_SETTINGS` 列（JSON），预留 BT 站点默认搜索设置
- 新增 `IndexerSiteConfigRepository`、`IndexerSiteConfigRepositoryAdapter`、`IndexerSiteConfigEntity` 等基础设施
- 站点维护页新增搜索启用开关（集成到编辑弹窗功能开关），BT 站点隐藏刷流/统计/解析开关
- 卡片底部标签栏展示所有已启用功能（含搜索/字幕/标签）

### 修复
- 搜索入库 299→74 丢失：改为 dialect 无关批量 UPSERT + session 清理，对齐 `(PAGEURL, SITE, SEARCH_SESSION_ID)` 唯一索引
- `USER_LEVEL` NULL 导致 `IntegrityError (1048)`：默认化为空字符串
- 搜索事件 `**SearchStartPayload` 解包报错：添加 `isinstance` 检查
- 自动创建 BT 站点 `signurl` 双重 `https://`：判断 domain 是否已含协议

### 清理
- 移除 `show_more_sites`（实验室→展示更多站点）后端和前端所有相关代码
- 索引器页面移除内置站点多选框，改为单一总开关
- 移除前端"默认搜索索引器"选择器
- `builtin.py` 清理未使用的 `settings`/`IndexerConf` import，补上漏掉的 `DownloadRepository`

### 前端
- 站点卡片 BT/PT 标签按引擎定义 `site_public` 显示，不随 cookie 变化

### 数据库迁移
- `c4d5e6f7a8b9`: 新增 `INDEXER_SITE_CONFIG.DOWNLOAD_SETTING` 列
- `ee2445e35880`: 新增 `INDEXER_SITE_CONFIG.DEFAULT_SETTINGS` 列，从 `UserIndexerSites` 迁移历史数据

### 新增测试
- `test_search_repository.py`: 搜索入库回归测试（299 条全量插入、去重、session 替换）
- `test_indexer_site_config_repository.py`: 索引器站点配置仓储测试
- `test_site_service_get_sites_merge.py`: 站点服务合并逻辑测试

## v4.1.10 (2026-06-29)

### 构建
- Dockerfile 支持 `UV_INDEX_URL` 构建参数，便于构建时自定义 PyPI 镜像源
- 修复 builder 阶段 `uv sync --no-install-project` 导致项目包未安装的问题

### 前端
- 重新设计我的媒体库页面，统一卡片、存储与活动列表视觉风格
- 重构基础设置页面信息架构并改为标签页布局，优化表单层级
- 统一媒体详情页视觉风格，拆分 HeroSection/CastList/FactPanel 等组件
- 优化站点列表卡片视觉设计与操作按钮可访问性
- 重构站点资源卡片与列表：精简海报占位、统一标签语义色、新增 Dolby/HDR 标签类型
- 重构站点统计图表为独立组件，对齐 dashboard/home 实现，修复 tooltip 闪烁与 StatTable 数据引用导致的重绘
- 刷流任务页面重构：改用行内开关与更多操作下拉，移除冗余“已停用”状态选项，调整规则卡片视觉
- 站点编辑弹窗为 API Key / Bearer Token 输入关闭浏览器自动填充
- 全局通知默认时长恢复组件默认，避免通知过早消失
- 资源标签使用更鲜明的语义色变量

### 数据库迁移
- 无需迁移

## v4.1.9 (2026-06-26)

### 修复
- `brushtask_interval` 字段类型错误：API 模型定义为 `int`，前端传 cron 表达式字符串 `"*/30 * * * *"` 导致 422 解析失败，改为 `int | str` + 双格式校验（≥5 分钟 / 5 位 cron）
- 错误日志不到 SSE：`LOG_BUFFER` 容量仅 200 条，启动和运行时高频日志将 error 挤出队列，增大到 2000

### 新增
- KamePT 站点配置：支持 NexusPHP HTML 模式的 KamePT（CosAV/音声/游戏 CG）

### 数据库迁移
- 无需迁移

## v4.1.8 (2026-06-24)

### 修复
- 转移事件处理器 TypeError：`DownloadCompletedPayload(**event.payload)` 对 dataclass 实例用 `**` 解包崩溃，事件总线静默吞异常导致下载完成→转移链路从未触发
- 下载监控多工厂实例缓存不同步：`DownloadCore`/`DownloaderCore`/`DownloadMonitor` 各持有独立 `DownloadClientFactory` 实例，CRUD 后只刷新前两个，`DownloadMonitor` 工厂永不过期
- 下载器 `download_dir` 不生效：`DOWNLOAD_DIR` DB 列为空时直接取空值，忽略 `config.download_dir` JSON 中的实际配置，导致 `get_download_dir_info` 匹配失败、`match_path` 全部跳过
- `only_nexus_media` 标签隔离：pipeline 未将 `PT_TAG` 注入种子标签，监控按 `NEXUS_MEDIA` 过滤时找不到已完成种子
- 磁力链接 `save_path` 始终为空：`_stage_post` 对 magnet 链接显式设 `save_dir=None`
- 图片代理 `/img?url=` 斜杠重定向死循环：前端 nginx 301 加斜杠，Starlette 307 去斜杠互斥，双路由注册消除重定向
- 订阅电影/电视剧 INSERT 失败：`KEYWORD`/`FILTER_ORDER`/`FILTER_RESTYPE` 等可选列为 `NOT NULL` 但传 `None`，仓库层统一空值默认化
- 索引器切换后订阅站点列表不更新：`/download/indexers` 固定返回内置站点，改为 `get_user_indexers()` 随当前激活索引器变化
- 过滤引擎拒绝纯音频文件匹配视频订阅（FLAC/MP3/OST 等）
- 索引器统计插入时自动清理 7 天前旧数据

### 前端
- 探索页面无限滚动卡死：首屏数据加载期 IntersectionObserver 触发被 loading guard 拦截后不再重新触发
- 订阅编辑模态框切换索引器后已保存站点未过滤，旧站点名残留

### 数据库迁移
- 无需迁移

## v4.1.7 (2026-06-23)

### 修复
- API 站点数据刷新无响应：`api_key`/`bearer_token` 贯穿整个用户信息获取调用链，修复 M-Team/Rousi/TNode 等 API 站点的站点数据刷新静默返回 0 条的问题
- Bearer Token 认证重复前缀：`_build_auth` 中 BearerAuth 构造时剥离已添加的 `Bearer ` 前缀，修复 Rousi 等 Bearer 认证站点返回 401
- Rousi 站点配置：`user_info.profile` 端点 query 参数从 URL path 移到 `params` 对象，修复方括号被 URL 编码后服务器不识别的问题
- `DOWNLOADER.DOWNLOAD_DIR` 列 `VARCHAR(255)` 过短导致下载器配置保存报错，改为 `TEXT`
- `SITE_STATISTICS_HISTORY` 和 `SITE_USER_INFO_STATS` 中无默认值列添加 `server_default`，修复 `bulk_insert_mappings` 遇 `None` 值时 MySQL NOT NULL 约束报错
- 刷流任务状态变更统一使用 `BrushTaskState` 枚举，修复 `Y/N/S` 魔法字符串不一致
- 文件转移路径解析 `get_format_dict`/`get_movie_dest_path`/`get_tv_dest_path` 的 `media_service` 参数改为可选，修复无媒体服务时路径格式化报错
- 进度跟踪器 `finish()` 方法补充设置 value=100 和完成文本
- 新增 `GET /download/torrent-remove-tasks/seed-statuses` 端点，返回种子状态中英文列表
- 删种任务种子状态输入框改为多选下拉列表，支持中文显示
- 修复 TMDB 黑名单和搜索文件两处 API 路径重复 `/api/` 前缀的问题
- 区分 `Paused`（已暂停）和 `Stopped`（已停止）的中文标签，避免下拉列表重复
- 修复识别历史统计字段大小写不匹配（`MovieNums` → `movie_nums`）导致 `reduce` 报错
- 修复下载目录分类未推送到下载器：类型匹配支持中英文，`category` 推分类 `label` 推标签
- 新增站点「拾刻」www.ptskit.org（NexusPHP）
- M-Team 添加 description 字段（概述），详情页域名改为 kp.m-team.cc
- HTML 站点解析支持用户配置的别名域名（domain_aliases）
- 修复站点 tag 字段返回字符串导致前端开关状态不正确，pipeline 改用 name 作为下载器标签
- 索引器统计启动不再清空，查询加 24 小时时间过滤，前端添加 24h 标签

### 数据库迁移
- `d5e6f7a8b9c0`：`DOWNLOADER.DOWNLOAD_DIR` 列类型调整为 `TEXT`
- `e6f7a8b9c0d1`：`SITE_STATISTICS_HISTORY.USER_LEVEL` 和 `SITE_USER_INFO_STATS.USER_LEVEL` 添加默认值 `''`
- `f6f7a8b9c0d1`：`SITE_USER_INFO_STATS` 和 `SITE_STATISTICS_HISTORY` 中无默认值的数值/字符串列批量添加 `server_default`

## v4.1.6 (2026-06-23)

### 修复
- 媒体类型识别统一使用 `MediaType.from_string`，支持 `Movie/Series/show/TV` 等别名
- fnOS 媒体库同步：`get_items` 在 API 按库过滤返回空时回退到全量获取后本地过滤，修复同步无数据
- fnOS 客户端：修复 `fetch_all_pages` 中响应数据覆盖请求 payload 的变量遮蔽问题
- 功能开关统一为布尔值：站点 note 中的 `parse/proxy/chrome/subtitle/tag/message/public` 读取写入均使用布尔值
- 修复部分更新 `rss_enable/brush_enable/statistic_enable` 时清除未传入开关的问题，改为增量更新
- 修复 `/sites/detail` 接口返回原始实体数据而非缓存计算后状态的问题

### 重构
- 新增 `SiteUseType` 枚举（RSS=D, BRUSH=S, STATISTIC=T），替代 `D/S/T` 魔法字符串
- 新增 `SwitchState` 枚举（ON=Y, OFF=N），替代 `Y/N` 魔法字符串
- 新增 `UserRssTaskUseType` 枚举（DOWNLOAD=D, SUBSCRIBE=R, SEARCH=S）
- 刷流任务状态统一使用已有的 `BrushTaskState` 枚举（RUNNING=Y, STOPPED=S, DISABLED=N）
- 删除 `SiteEntity` 中未使用的 dead code 属性
- Alembic 迁移：将 `CONFIG_SITE.NOTE` 中旧 `Y/N` 字符串开关转换为布尔值

### 前端
- 站点编辑页：note 开关直接发送布尔值，不再转 `Y/N` 字符串
- 站点类型选择器改用 `NSwitch`，form.public 改为布尔值
- 删除 `parseNoteBool` 兼容函数
- 修复 `NNotificationProvider` 的 extraneous non-props attributes 警告
## v4.1.5 (2026-06-22)

### 修复
- 媒体服务器配置保存兼容无前缀字段，修复前端保存配置时返回“配置为空”
- 豆瓣网络连通性测试改为调用真实豆瓣 API，避免直接访问根路径被误报异常
- 修复媒体服务器配置更新时 `NOTE` 为 `null` 导致 MySQL `IntegrityError` 的问题
- 内置索引器识别 API Key / Bearer Token 认证的站点（如 M-Team），不再因缺少 cookie/headers 被过滤
- 内置索引器匹配站点 `domain_aliases`，修复 M-Team 等使用别名域名配置的站点不显示的问题
- 内置索引器收集 API 站点定义，修复 API 认证站点（如 M-Team）被排除的问题
- IndexerConf 传递 `api_key`/`bearer_token` 到 API 搜索器，修复 M-Team 搜索 401
- 下载链接解析和下载流水线传递 `api_key`/`bearer_token`，修复 API 站点下载认证
- 代理配置支持 http / https / socks5 三种协议
- 下载流水线失败时补上 SSE 事件推送，种子下载失败时直接推送 SSE
- 下载历史存在判断改用 `downloader+download_id` 唯一键，修复任务列表重复和重复插入
- 种子文件名优先取 `filename*=` 头，避免中文 ISO-8859-1 编码报错
- torrent URL 下载时设置 `media_info.enclosure`，避免 `ENCLOSURE` 为 null 报错
- 下载任务列表按 `downloader+download_id` 去重，不再显示重复记录
- 站点维护功能开关支持独立 `rss_enable/brush_enable/statistic_enable` 布尔字段

## v4.1.4 (2026-06-21)

### 修复
- 网络连通性测试耗时为 0：`NetTestService` 改为在 HTTP 请求完成后计算耗时，并改用 `total_seconds()` 避免超过 1 秒时数值错误
- 消息客户端模板保存失败：`MESSAGE_CLIENT.TEMPLATES` 列从 `VARCHAR(255)` 改为 `TEXT`，兼容长 JSON 模板
- FnOS 媒体服务器配置项错误：配置表单从错误的 `Api Key` 改为正确的 `用户名 / 密码`，并添加迁移将已有 `api_key` 值迁移到 `username`

### 数据库迁移
- `89c719931b5f`：`MESSAGE_CLIENT.TEMPLATES` 列类型调整为 `TEXT`
- `1ee439ce9b6d`：FnOS 媒体服务器配置 `api_key` 迁移为 `username`

## v4.1.3 (2026-06-18)

### 下载事件 SSE 推送
- `DownloadStartedPayload` 增加 `download_id` 字段
- `DOWNLOAD_STARTED` 事件从流水线入口移至 `_stage_add` 成功后发布，避免 fetch/resolve 失败时误报
- 新增 `download_event_queue` 模块级 `queue.Queue` 作为事件通道
- handler 推送 `download.started` / `download.failed` / `download.completed` 事件到队列
- 新增 `GET /api/download/events` SSE 端点，权限 `download:view`

### 站点资源内置索引器
- `/api/download/indexers` 始终返回内置索引器站点列表，不受索引器切换影响
- `IndexerService` 新增 `get_builtin_user_indexers()` 方法

### 修复 MySQL NOT NULL 兼容性
- `CONFIG_SITE.EXCLUDE`、`SIZE` 添加 ORM 默认值，修复新增站点 500
- `SITE_USER_INFO_STATS.JOIN_AT`、`EXT_INFO` 等列添加 ORM 默认值，修复统计更新 500
- `site_service.update_site` 异常分支添加 `log.error` 和 `msg`，不再吞掉错误信息
- `site_repository.update_site_user_statistics` 中 `JOIN_AT=None` 时写入空字符串

## v4.1.2 (2026-06-16)

### 刷流修复
- 缓存线程安全：`_torrents_cache` 加 `threading.Lock` 防止并发下载重复种子
- 删种前用 `get_torrents` 确认种子离开下载器，避免边缘状态误删记录导致孤儿
- 删种失败不再标记为已删除
- 新任务不触发全量 `start_service()`，缓存在 `delete_brushtask` 未命中时回退查 DB

### 订阅修复
- RSS 自动订阅事件处理器已注册到 DI，功能恢复可用
- 删除订阅时同步清理 `SubscribeTorrents` 种子记录，重新订阅可正常下载
- `truncate_rss_episodes` 只清除非活跃订阅的剧集进度
- TOCTOU 并发防重复插入订阅
- 状态字符串统一替换为 `SubscribeState` 枚举
- 状态设为 SEARCHING 移到协调锁之后，消除异常窗口

### 测试修复
- 测试配置改用临时文件 + SQLite，不再依赖外部 MySQL 服务器

### 数据库兼容性
- 14 处 String=Integer 类型比较加 cast 适配 PostgreSQL
- MySQL ENCLOSURE 索引加前缀长度，避免 VARCHAR(8192) 超限
- `ConfigRepository.execute` 适配 SQLAlchemy 2.0 `text()`
- `drop_table` SQL 注入修复
- SQL 适配器 MySQL 双引号转反引号

### 其他修复
- `get_secret_key` 保存后 `reload` 确保同次运行不生成多个密钥
- `_brush_tasks` 先停旧 job 再 pop，消除竞态窗口
- auth router 清除重复标签，prefix 统一到 `include_router`
- 清理绞杀式迁移相关注释
- 后端 nginx 加兜底路由代理 `/docs` 等非 API 路径

### 依赖
- `python-jose` 替换为 `PyJWT[crypto]`，消除 `ecdsa` 安全告警

## v4.1.1 (2026-06-16)

### 部署修复
- **ConfigReloader 重构**：改为工厂模式重建实例，而非 reset()，tmdb_client 热重载时清除 Redis 缓存
- **settings.save 合并**：修复保存时只保留 database 节点导致其他配置（TMDB key 等）丢失
- **配置保存触发重载**：/config/update 自动调用 ConfigReloader.reload()
- **NOGROUP 根治**：RedisMessageQueue dispatch 循环幂等创建消费组
- **static 目录持久化**：跟随 NEXUS_MEDIA_DATA 落到 /data/static
- **过滤规则初始化**：首次启动从 init_filter.sql 导入默认规则，INSERT OR IGNORE 防覆盖
- **TMDB 异常降级**：get_tmdb_new_movies/tvs 捕获异常返回 []，不抛 500

## v4.1.0 (2026-06-15)

### 部署优化
- **Docker Compose 三模式部署**：支持基础模式（前端+后端+Redis+MySQL/PostgreSQL）、完整模式（+OCR+Chrome）、仅前后端模式（SQLite）
- **默认基础 MySQL 模式**：执行 `docker compose up -d` 即可启动
- **统一数据库环境变量**：Docker 与代码统一使用 `DATABASE__*` 格式读取配置
- **Redis 默认命令启动**：移除对 `./config/redis.conf` 文件挂载的依赖
- 数据库升级到 MySQL 8.4 / PostgreSQL 17-alpine

### 性能优化
- **数据库查询性能**: 消除 `site_repository` / `transfer_repository` N+1 查询；为 `SUBSCRIBE_MOVIES` / `SUBSCRIBE_TVS` / `CONFIG_USER_RSS` / `SITE_BRUSH_TORRENTS` / `TRANSFER_HISTORY` / `TRANSFER_UNKNOWN` 添加索引；`subscribe_repository` 用单次 `first()` 替代 `.all()` + 循环
- **HTTP 客户端连接池复用**: `HttpClient` / `AsyncHttpClient` 按配置复用底层 `httpx.Client` / `httpx.AsyncClient`，相同代理/头/超时/认证/SSL 配置共享连接池
- **缓存系统**: `RedisStore.hgetall` 改为单次 `hgetall`；`MemoryCacheAdapter` 仅在存在监听器时触发 `CacheEvent`，避免高频空转
- **消息队列**: `MessageQueueFactory` 单例实现线程安全，避免重复创建队列
- **下载完成监控**: `DownloadMonitor` 改为增量检查，后续轮询只拉取新增任务；qBittorrent 使用 `sync/maindata` 增量接口获取 completed 任务，减少数据传输与 per-torrent API 调用
- **图片代理**: 下载逻辑全面异步化，使用 `AsyncHttpClient` 连接池与 `asyncio.gather` 并发下载，替代 `ThreadPoolExecutor`
- **JSON 序列化**: 高频路径统一使用 `JsonUtils`（`orjson` 为主，stdlib 为 fallback）

### 问题修复
- **EventBus 注册**: 修复 DI 容器创建的 `EventBus` 与 `@on_event` handler 注册脱节的问题；`SystemLifecycleService` 现在从 DI 接收真实 `EventBus`
- **认证**: 移除 `SessionMiddleware` 与 session 认证兼容层，API 统一使用 JWT/Token 认证
- **消息通知图片**: 添加诊断日志定位图片丢失问题；修复 `_get_script_path` 依赖注入错误

### 依赖与质量
- 升级 `redis` / `cryptography` / `pydantic-ai` / `granian` / `python-multipart` / `openai` / `google-genai` / `boto3` / `beautifulsoup4` / `qbittorrent-api` / `ruff` 等依赖
- 引入 `orjson` / `uvloop`；启用 `httpx` HTTP/2
- 新增 Alembic 迁移 `e9d9eaed8d5c` 补充查询索引
- 安全扫描: `just bandit` / `just safety` 均通过
- 测试: 1195 个测试通过，覆盖率 `36%`；新增事件系统异常隔离与异步投递测试

## v4.0.0 (2026-06-09)

**4.0.0 是 Nas-Tools 的全新重构版本，涵盖后端架构、前端框架、部署运行和代码质量的全面升级。**

### 架构重构
- 项目重命名为 **Nexus Media**，全面替换旧品牌标识
- 项目结构标准化为 `src/` layout，统一 `get_project_root()` 消除硬编码路径
- 架构分层重构：消除 `helper/` 层、解除循环依赖、基础设施统一归位
- 全面重构 DI 容器，引入 `ConfigReloader` 集中热重载，消灭 `NEXUS_MEDIA_CONFIG` 硬性依赖
- 统一 Repository 适配层，移除 `MediaDb` 直接数据库操作，拆分 `engine/session/transaction` 模块
- 拆分超大服务文件：`filetransfer_service.py` / `message.py` / `scheduler_core.py` / `rss_service.py`
- 消息通知、下载器、索引器、媒体服务器模块重构为插件化扩展架构
- 缓存事件系统整合到 EventBus，移除旧 `task_queue/reliable_message_queue`
- 移除 10+ 个类的 `SingletonMeta`（`Rss` / `IyuuHelper` / `CookiecloudHelper` / `IndexerHelper` / 豆瓣相关类等）

### 新增功能
- 自动签到插件重构为**声明式配置架构**：删除 21 个旧站点硬编码实现，支持“自定义 handler > 声明式配置 > 通用匹配”三层分发
- 站点模块迁移到 **SiteCache / SiteResolver / SiteFaviconService** 领域架构，写操作后缓存自动刷新
- 新增 **分布式锁** 实现，覆盖 RSS 下载、插件安装/卸载、站点刷新、订阅搜索、删种、媒体库同步、转移等场景
- 引入 `tenacity` 替换手写重试，实现 API **速率限制器**
- 图片代理与缓存优化，支持 TMDB / 豆瓣 / Bangumi / 媒体库内网图片
- HTTP 客户端重构：中间件集成、配置修复、异步线程安全
- 日志支持 **JSON 结构化输出**，兼容 ELK；gunicorn access log 每日轮转 + 自动清理
- 服务器由 uvicorn/gunicorn 迁移至 **Granian**，统一 `run.py` 入口
- 新增 ADR-007 ~ ADR-013 架构决策记录

### 前端升级
- 前端框架升级至 **vben v5.7.0**（应用版本同步至 **4.0.0**）
- vue-router 生产环境改为 **history** 模式
- 前端目录 `views/rss/` 统一迁移为 `views/subscription/`，与后端路由对齐
- 前端 Nginx 增加 `/api/`、`/img`、`/docs`、`/openapi.json`、`/ws` 反向代理
- 修复设置按钮点击无反应、头像更新不生效、153 处 TypeScript 类型错误

### 部署与运行
- Docker 镜像升级至 **`python:3.14-slim-trixie`**，弃用 Alpine
- nginx 内部端口改为 **8080**，healthcheck 检查 nginx 而非直连 Granian
- docker-compose 增加独立 **migration** 服务，backend 设 `SKIP_MIGRATION=true`，避免 alembic 并发冲突
- 修复 SQLite 下历史迁移脚本的 `no such table`、`ALTER CONSTRAINT` 等兼容性问题
- 新增 `.dockerignore` 和运行时目录排除，缩减镜像体积
- 修复 nginx `merge_slashes` 导致 `/img` 代理 URL 双斜杠丢失

### 配置与连接
- 迁移配置到 **pydantic-settings**，建立分层异常体系，完善 OpenAPI 文档
- 新增 `RedisConfig` 配置模型，支持环境变量 `REDIS__HOST` / `REDIS__PORT` / `REDIS__PASSWORD` / `REDIS__DB`
- 修复 `settings.py` 中数值配置字段类型（`str` → `int`）导致的 pydantic 校验错误
- 新增 `.env.example` 环境变量模板，重写以对齐 pydantic-settings 字段

### 代码质量
- 新增 CI 质量门禁、pre-commit hooks、justfile 任务运行器
- 全部非测试文件完成**空安全加固**，消除 111 处 null access
- 全部 `reportArgumentType` 清零，227 处类型窄化
- 95 处 `reportIncompatibleMethodOverride` 基类/子类签名对齐
- 重构测试体系，删除不可用旧测试，新建 41 个可运行测试
- 使用 `just` 替代 Makefile，统一 `uv run` 工作流

## v3.7.0 (2025-04-01)

### 新增功能
- 支持迅雷下载器
- 支持Rousi站点（API v1接口）
- 新增自动重启插件
- 新增消息模板
- 搜索结果支持分页浏览（输入 n/p 翻页）
- 支持直接从搜索结果中选择下载

### 功能优化
- 优化数据库性能（使用连接池、WAL模式）
- 优化HTTP工具类（添加连接池和重试策略）
- 优化自动签到插件（跳过BT站点）
- 优化馒头站点仿真登录
- 优化Web界面交互体验
- 添加消息模板配置支持

### 问题修复
- 修复Aria2状态显示拼写错误
- 修复下载器返回值格式问题
- 修复authorization请求头处理问题

## v3.6.9 (2025-12-01)

### 新增功能
- 支持馒头仿真登录
- 支持自由农场签到
- 刷流支持下载付费种子

### 功能优化
- 签到流程优化
- 增加仿真签到延时
- 优化搜索速度
- 重启时重置订阅状态

### 问题修复
- 修复微信插件初始化问题
- 修复观众做种数据
- 修复飞牛图片显示问题
- 修复猫站签到
- 修复chrome服务找不到一直报错
- 修复transmission状态显示
- 修复http工具类
- 修复tags没有配置时无法添加任务

## v3.6.8 (2025-08-22)

### 新增功能
- 支持飞牛媒体服务器

### 功能优化
- 憨憨支持H&R
- 优化调度

### 问题修复
- 修复下载器标签排序问题
- cf优选插件下载路径错误
- 订阅下载重复
- 黑名单条目无法删除

## v3.6.7 (2025-06-15)

### 新增功能
- 新增PTGTK站点支持
- Server酱支持TAG和图片
- 增加TMDB黑名单功能

### 功能优化
- 优化索引器搜索速度
- TMDB缓存优化
- 站点维护增加图标LOGO

### 问题修复
- 修复订阅搜索暂停问题
- 修复HDSky生成RSS失败

## v3.6.6 (2025-05-20)

### 新增功能
- 新增RSS自动生成插件
- 自动备份插件支持WebDAV和Samba
- 支持唐门、雨、财神等新站点

### 功能优化
- Emby媒体库同步插件支持原生webhook
- 企业微信插件支持二维码扫码登录

## v3.6.5 (2025-04-10)

### 问题修复
- 修复馒头模拟登录失效
- 修复观众站点资源访问失败
- 修复Prowlarr下载失败

## v3.6.4 (2025-03-25)

### 功能优化
- 支持OpenAI自定义模型
- 支持HHCLUB备用域名

### 问题修复
- 修复天空种子列表获取问题
- 修复冰淇淋副标题显示问题

## 历史版本

完整版本历史请查看[GitHub发布页面](https://github.com/linyuan0213/nexus-media/releases)

> 注意：建议始终使用最新版本以获得最佳体验和安全更新
