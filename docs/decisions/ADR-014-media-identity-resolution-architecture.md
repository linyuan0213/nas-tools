# ADR-014: 媒体身份解析与匹配架构（分词→识别→匹配→重映射）

## Status

Proposed（v2，已按可行性评审修订）

## Date

2026-07-25

## Context

### 问题背景

搜索识别链在长期演进中以「字符串匹配」隐式完成「作品身份解析」，导致每次修复一个问题就引入新问题。2026-07-25 一天内的真实事故序列：

1. **穹庐下的魔女**：英文名 `Jaadugar: A Witch in Mongolia` 与 TMDB 条目名（`天幕のジャードゥーガル`）无法比对 → 全部「识别出错」，有效 0
2. **攻壳机动队（2026)**：SAC_2045 / ARISE / Stand Alone Complex / 1995 电影全部被误配到 2026 新剧
3. **750 条泛词搜索**：识别风暴打爆 TMDB 限流，90 秒无结果
4. **缓存键共享**：`v2_攻壳机动队_S2_E12` 把 SAC_2045 和 2026 新剧汇成一组，先入者带偏全组
5. **解析层丢信息**：`prepare_title` 丢弃斜杠前中文名、AKA 截断丢区分信息、`中字` 标签污染直通

### 根因分析

**作品身份（Work Identity）不是一等公民。** 剧名、别名、子系列、版本、季集结构全部糊在字符串比较里：

```
现状（隐式身份解析）:
  标题 → 解析器 → 名字字符串 → [和目标的字符串比来比去] → 对/错
                                    ↑
  "攻壳机动队" 指向哪个作品？这不是字符串问题，是身份问题。
```

已落地的修复（共识仲裁、别名扩充、缓存键隔离、严格匹配、直通三分流）都有效，但它们是**启发式规则的堆叠**：每个新命名变体、每个同名系列都可能成为下一个 bug。需要把这些被验证正确的思想沉淀为**数据模型和分层管线**。

### 可行性约束（评审修订）

- **TMDB 无 TV 系列关系 API**：`episode_groups` 仅是单剧内部的集顺序变体（DVD 序/播出序），不能表达 SAC→2nd GIG→SAC_2045 这类跨作品关系。跨作品关系边的唯一可靠机器来源是 **Bangumi relations**，辅以手工补充表。
- **Bangumi relations 端点未集成**：现有 `Bangumi` 类仅有 `calendar`/`detail`，需新增 `v0/subjects/{id}/relations` 调用（纳入 P1）。
- **别名索引是「见过即缓存」，不是全量库**：冷启动作品必须回退外部解析，性能声明按此修正（见「性能设计」）。

## 目标

1. **正确性**：同名系列（franchise/sub-series）不再误配，身份解析显式化、可解释、可测试
2. **速度**：已索引作品热路径零网络调用，P95 搜索延迟 < 40s（含慢站熔断）
3. **覆盖**：支持常见 PT/BT 站点与字幕组命名习惯，且可通过配置扩展而非改代码
4. **可演进**：失败样本自动沉淀，识别能力随使用单调增长

### 非目标

- 不重写索引器抓取层（HtmlSearcher/ApiSiteSearcher 保持现状）
- 不改变订阅/RSS 的业务语义（只替换其内部的识别匹配实现）
- 不引入新的外部数据库服务（复用 Redis + SQLite/MySQL）
- 不做豆瓣解析通道（douban ID 本期不纳入直通，见 3.2 备注）

## 核心设计

### 1. 总体分层

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. 分词层 ReleaseParser                                           │
│    标题/描述 → ParsedRelease（结构化，字段带置信度）                │
├──────────────────────────────────────────────────────────────────┤
│ 2. 元数据层 MediaIdentityGraph（元数据拆分的核心）                  │
│    Work / Alias / Franchise / EditionGraph / AliasIndex          │
│    Redis（长TTL） + 进程内 LRU，访问时按需构建                      │
├──────────────────────────────────────────────────────────────────┤
│ 3. 识别层 IdentityResolver                                        │
│    ParsedRelease → IdentityResolution { work_id, confidence }    │
│    直通快路径（目标已知时的别名判等）也在本层                       │
├──────────────────────────────────────────────────────────────────┤
│ 4. 匹配层 TargetMatcher                                           │
│    work_id 相等 + EditionGraph 距离 → 匹配/拒绝（带原因）           │
├──────────────────────────────────────────────────────────────────┤
│ 5. 重映射层 EpisodeRemapper                                       │
│    发布组编号 → 规范编号（绝对集/合并季/SP/合集包展开）              │
└──────────────────────────────────────────────────────────────────┘
                              ↕
┌──────────────────────────────────────────────────────────────────┐
│ 反馈环 FeedbackLoop                                               │
│    miss → 语料 → 新命名规则；成功解析 → 新别名回写索引（防污染）    │
└──────────────────────────────────────────────────────────────────┘
```

### 2. 数据模型

#### 2.1 ParsedRelease（分词层输出）

```python
@dataclass
class NameCandidate:
    text: str            # 原始名称
    lang: str            # cn / en / ja / romaji / unknown
    script: str          # latn / hans / hant / jpan
    source: str          # pattern / title / description / aka / subtitle
    confidence: float    # 见下方映射表

@dataclass
class ParsedRelease:
    names: list[NameCandidate]
    year: str | None     # 与现有链路一致用 str，识别层内部转 int
    season: int | None
    episode: int | None
    episode_end: int | None
    edition_markers: list[str]   # SAC_2045 / ARISE / 剧场版 / OVA / 第二季 ...
    quality: dict                # 分辨率/编码/音轨/字幕/平台
    group: str | None            # 发布组
    is_season_pack: bool
```

**confidence 具体映射**（可复现，下游评分依赖）：

| source | confidence | 说明 |
|--------|-----------|------|
| pattern（命名模式库命中） | 0.95 | 人工规则，最可信 |
| description（描述提取中文名） | 0.90 | 站点编辑填写 |
| title-anitopy | 0.75 | 动漫解析器 |
| title-regex | 0.70 | 正则影视解析器 |
| aka（AKA 后段） | 0.85 | 官方别名 |
| id-link（IMDb/TMDB/BGM 链接） | 1.00 | 直接身份证据 |

**关键约束**：`edition_markers` 是消歧的关键证据，**必须保留为结构化字段，绝不允许清洗进名称字符串**。本轮事故中 `SAC_2045` 被 `clean_name` 当垃圾剥掉，是误配的根源之一。

#### 2.2 Work / Alias / Franchise（元数据拆分）

```python
@dataclass
class Alias:
    text: str
    lang: str            # zh-Hans / zh-Hant / en / ja / romaji
    kind: str            # official / translation / romanization / fan
    source: str          # tmdb:alternative_titles / tmdb:translations / bgm / learned

@dataclass
class Work:
    source: str          # tmdb / bgm
    work_id: int
    media_type: str      # tv / movie / anime（遵循 ADR-009 类型统一策略）
    year: int | None
    official_titles: list[str]
    aliases: list[Alias]
    franchise_key: str | None   # 所属虚拟 franchise 节点

@dataclass
class Franchise:
    """虚拟系列节点 —— 「攻壳机动队」作为概念在 TMDB/BGM 都不是条目，
    EditionGraph 需要一个虚拟根承载跨作品关系。"""
    key: str             # 归一化名或手工指定，如 "ghost-in-the-shell"
    name: str
    members: list[tuple[str, int]]  # [(source, work_id)]
```

别名按 `kind` 拆分存储的意义：**匹配策略按 kind 分级**，不再用一个 compare 函数通吃：

| kind | 匹配策略 |
|------|---------|
| official | 归一化后精确相等 |
| translation | 归一化后精确相等 |
| romanization | 归一化相等 + 音译变体表（Jādūgar↔Jaadugar） |
| fan（学成） | 仅作证据参与评分，**不可单独确定身份** |

#### 2.3 EditionGraph（系列/版本关系）

```
Franchise: ghost-in-the-shell（虚拟节点）
├── Movie 1995 (tmdb:movie/9323)
├── Stand Alone Complex (tmdb:tv/xxx)      ← relation: 续作/系列
│   ├── 2nd GIG                            ← relation: 续作
│   └── Solid State Society (OVA)          ← relation: 番外
├── ARISE                                  ← relation: 衍生
├── SAC_2045 ── SAC_2045 S2                ← relation: 续作
├── The New Movie 2015
└── 攻壳机动队 (2026)                      ← relation: 新作/重启
```

- **节点**：Franchise（虚拟）或 Work；**边**：`sequel` / `spinoff` / `special` / `remake` / `compilation`
- **数据源（按优先级）**：
  1. **Bangumi relations**（`GET /v0/subjects/{id}/subjects`，本期新增集成）——动漫领域覆盖最好的跨作品关系来源
  2. **手工补充表** `config/edition_overrides.yaml`——长尾/国产/真人剧
  3. TMDB movie `collection`（仅电影合集可用，TV 无此能力；**不使用 episode_groups 表达跨作品关系**，它只用于 3.5 重映射的集序）
- 存储：Redis `identity:v1:edition:{source}:{work_id}` + 反向索引 `identity:v1:franchise:{key}`；全部 key 带 `v1` 版本前缀以便 schema 演进双读

#### 2.4 AliasIndex（本地别名索引）

```
identity:v1:alias:{md5(normalized_text)} → [{source, work_id, kind, lang}]
```

- normalized_text = `handler_special_chars(text).upper().strip()`（与现有归一化一致）；key 用 md5 避免超长与多语言字符问题
- **别名→多作品是常态**（`攻壳机动队` 映射 10 个 work_id）：索引返回的是**候选集合**，本身不定身份；集合 >1 时必须进入识别层的年份/edition 消歧流程（3.2 第 3-4 步）
- 写入时机：Work 详情首次拉取时、外部解析成功时（学成，受限）、手工/规则补充时

#### 2.5 IdentityResolution（识别层输出）

```python
@dataclass
class IdentityResolution:
    work: Work | None
    confidence: float          # 0.0-1.0
    evidence: list[str]        # ["alias:Tenmaku no Jaadugar", "year:2026", "edition:SAC_2045"]
    rejected: list[tuple[Work, str]]  # 被淘汰的候选及原因（可解释性）
    status: str                # HIT / NOT_FOUND / ERROR
```

### 3. 分层职责

#### 3.1 分词层 ReleaseParser

输入：种子标题 + 描述 + 站点名。输出：ParsedRelease。

处理链（有序，先赢）：

1. **命名模式库**（已有 `config/naming_patterns.yaml`）：字幕组/站点格式，命中最可信
2. **anitopy + 动漫规则**（已有，含中文名恢复、英前中后、release_group 跳过）
3. **正则影视解析器**（已有）
4. **description 特征提取**：中文短语、IMDb/TMDB/BGM 链接（ID 直通证据）
5. **edition 标记抽取**：独立正则扫描（SAC_2045、ARISE、2nd GIG、第X季、剧场版、OVA…），写入 `edition_markers` 而非并入名称

改动要点：
- 现有 `_clean_name` 的「清洗」语义改为「字段拆分」：质量词进 `quality`，版本词进 `edition_markers`，**名称只保留名称**
- AKA 继续解析（已修复）并将 AKA 后段作为独立 NameCandidate（source=aka）

#### 3.2 识别层 IdentityResolver

```
输入 ParsedRelease
  │
  ├─ 0. 直通快路径（目标已知 = 搜索/订阅场景）:
  │     组内名称 ⊆ 目标别名集（AliasIndex 判等，非模糊字符串比较）
  │     → 全部命中 → 直接落目标 work_id，零外部调用
  │     → 零重叠 → 本地排除（候选与目标无关）
  │     → 部分重叠 → 进入完整流程
  │
  ├─ 1. ID 直通: description 提取到 tmdb/imdb/bgm 链接
  │     → 直接定位 Work（最高置信）
  │     注: douban 链接本期不做（无 douban→Work 解析器，避免半吊子映射）
  │
  ├─ 2. 别名索引: 每个 NameCandidate 查 AliasIndex
  │     → 候选 work_id 集合 + 命中别名（证据）
  │     → 未命中任何候选 → 第 5 步外部解析
  │
  ├─ 3. 版本下钻: edition_markers 非空时
  │     → 候选落到同一 Franchise 后，沿 EditionGraph 导航到子版本
  │     → 例: franchise(ghost-in-the-shell) + marker SAC_2045
  │            → 落地 SAC_2045 work，而非 2026 新剧
  │
  ├─ 4. 候选评分: 集合 >1 或下钻后仍多候选时
  │     score = Σ(名称置信度 × kind 权重) × 年份一致 × 版本一致
  │     → 最高分且超阈值 → HIT；否则 NOT_FOUND（记录 rejected 原因）
  │
  ├─ 5. 外部解析（冷启动）: TMDB/BGM search
  │     → 阻塞式限流（已有 rate_limit_timeout）
  │     → 并发预算: max_workers=2，tmdb 2.5/s，bgm 1/s
  │     → 结果回写 AliasIndex（学成，受防污染策略约束，见 §5）
  │
  └─ 输出 IdentityResolution
```

与现有代码的关系：`MediaService.identify_groups` 的「多名共识 + 冲突采信最具体名」是第 4 步的雏形；`BatchIdentifier` 的「三分流」是第 0 步的雏形。本设计把它们统一到**带证据和置信度的模型**里，且大部分查询在本地索引完成。

#### 3.3 匹配层 TargetMatcher

```
matched = (resolution.work.work_id == target.work_id)
        and edition_distance(resolution.work, target) == 0
        and 年份/类型/季集/规则过滤通过
```

- 同 franchise 不同 edition → 拒绝，原因可解释（`子系列 SAC_2045 ≠ 目标 2026`）
- **匹配层只有 ID 判等与图距离，没有名称比较**；所有名称不确定性（含直通快路径的别名判等）都在识别层消化
- 类型兼容性遵循 ADR-009（media-type-unification）的统一策略

#### 3.4 重映射层 EpisodeRemapper

- 发布组编号 → 规范编号：绝对集（anime [12]）、合并季（S1+S2+SP 包）、OVA/SP 编号、合集包展开（全集 → episode range）
- 数据源：TMDB episode_groups（集序变体的正确用途）、Bangumi 集数列表、手工映射表
- XEM（thexem.de）作为**可选**第三方映射源：默认关闭，开启失败时静默降级到前两者
- 现有 `EpisodeMapper`（动漫合并季/绝对集）并入本层统一实现

### 4. 性能设计

| 路径 | 条件 | 成本 |
|------|------|------|
| 直通快路径 | 目标已知（搜索/订阅），别名已索引 | 零网络，毫秒级 |
| 热路径 | 已索引作品（重搜/常见番） | 分词 + Redis O(1) + 图查询，毫秒级 |
| 冷路径 | 未见过的作品/别名 | 外部解析，限流内；结果回写，**同作品第二次起转热路径** |
| 取数 | 站点×关键词并行 + 单站 30s 熔断 | 上界 ≈ 30s + 流水线 |

**明确的边界**：别名索引是「见过即缓存」。泛词搜索中未索引的非目标作品仍会产生外部解析调用——「零 TMDB」只在**目标及其 franchise 已索引**后成立（验收标准按此表述）。冷启动批量场景的耗时上界 = 组数 × 名称数 / (2.5/s × 2 workers)，由三级缓存语义（HIT 3600s / NOT_FOUND 600s / ERROR 不缓存）控制重试风暴。

### 5. 反馈环（含防污染）

- **MissCollector**（已有）：快速名称不匹配 / 未匹配样本落 `data/identify_misses.jsonl`
- **学成机制**：外部解析成功后，`查询名 → work_id` 回写 AliasIndex，`kind=fan`。防污染约束：
  - fan 别名**仅作评分证据，不可单独确定身份**（数据模型 2.2 已约束）
  - 同一映射被独立命中 ≥2 次才从 fan 升格为 translation
  - 发现错配（人工/冲突报告）时按 `md5(normalized_text)` 单条逐出
- **规则沉淀**：miss 样本 → `naming_tool.py misses` 复审 → 新命名规则入 YAML + 回归测试
- **EditionGraph 补充**：冲突案例（同名不同作）审核后写入 `config/edition_overrides.yaml`

### 6. 与现有组件的映射

| 新组件 | 复用/迁移 | 新建 |
|--------|----------|------|
| ReleaseParser | 命名模式库、anitopy/regex 解析器、description 提取、AKA 修复 | 字段拆分（edition/quality 结构化）、ID 链接提取器、confidence 映射 |
| MediaIdentityGraph | `get_all_names`（别名获取）、Redis 缓存设施 | Work/Alias/Franchise 模型、AliasIndex、**Bangumi relations 集成** |
| IdentityResolver | 共识仲裁、限流短路、三级缓存语义、直通三分流 | 索引查询、版本下钻、评分模型 |
| TargetMatcher | tmdb_id 判等、过滤链 | EditionGraph 距离、可解释拒绝 |
| EpisodeRemapper | EpisodeMapper | 编号习惯映射、包展开、XEM 可选源 |
| FeedbackLoop | MissCollector、naming_tool | 学成回写（防污染）、edition_overrides |

## 集成方案（四期，每期独立交付可回滚）

依赖关系：**P2 依赖 P1 的索引与 Bangumi relations 端点；P3 依赖 P2 的 Resolution 契约；P4 依赖 P2 的回写通路。** 每期由独立灰度开关控制，回退即关开关回旧路径。

### P1 — 元数据层（地基）

- 定义 `Work/Alias/Franchise/EditionGraph` 数据模型与 Redis schema（`identity:v1:*`）
- **新增 Bangumi relations 集成**（`GET /v0/subjects/{id}/subjects`）
- `AliasIndex` 构建器：TMDB detail（alternative_titles/translations）+ BGM subject(+relations)
- `get_all_names` 等现有调用切到读 AliasIndex（外部行为不变）
- 灰度开关：`laboratory.identity_index`
- 验收：别名查询不再产生重复 TMDB 请求（索引命中日志可证）

### P2 — 识别层（核心）

- `IdentityResolver`：直通快路径 → ID 直通 → 索引查询 → 版本下钻 → 评分 → 外部解析回写
- EditionGraph 构建器（Bangumi relations + `config/edition_overrides.yaml`）
- `BatchIdentifier.identify` 内部改调 Resolver（外部契约不变）
- 灰度开关：`laboratory.identity_resolver`
- 验收：本轮三个事故场景（穹庐下的魔女 / GITS-2026 / 750 泛词）全对

### P3 — 重映射与匹配

- `EpisodeRemapper`：合并 EpisodeMapper + 发布组编号习惯 + 包展开
- `TargetMatcher` 替换 match_filter 的 tmdb 比对段（保留其余过滤逻辑）
- 灰度开关：`laboratory.target_matcher`
- 验收：合并季/绝对集/OVA 场景回归全过

### P4 — 反馈环与站点扩展

- 学成回写 AliasIndex（含防污染升格/逐出）；miss 样本周报复审机制
- 站点维度命名规则下沉到站点 JSON 配置（命名模式库按站点分流）

## 验收集（必须全部通过）

1. **穹庐下的魔女**：FROGWeb/MWeb/CHDWEB/字幕组全格式 → tmdb 288971，有效资源数 ≥ 修复后基线
2. **攻壳机动队（2026)**：SAC/SAC_2045/ARISE/1995/2004/2015 全部排除，仅 2026 新剧条目命中
3. **泛词 750 条**：P95 < 40s；**目标 franchise 索引完成后**，重搜识别阶段零 TMDB 调用；误配率 0
4. **AKA 格式**：`Ghost in the Shell AKA ... Stand Alone Complex` → SAC 不误配 2026；`肖申克 AKA 月黑高飞` → 中文别名正常提取
5. **回归**：既有 1361 测试全过 + 新增验收集测试

## 风险与回滚

| 风险 | 缓解 |
|------|------|
| EditionGraph 数据不全（新番无关系边） | 无边时退化为现有共识仲裁；学成机制逐步补边 |
| AliasIndex 冷启动空转 | 未命中自动落回现有 identify_groups 路径，结果回写 |
| Bangumi 不可用/限流 | relations 拉取失败静默降级为「无图」状态，不阻塞识别 |
| 评分模型误判 | 保留 `evidence/rejected` 可解释日志，阈值可配置，灰度开关一键回退 |
| fan 别名污染 | 仅作证据、命中≥2 次升格、单条逐出路径（见 §5） |
| Redis schema 演进 | key 带 `v1` 版本前缀，迁移期双读 |

## 决策

**采用本架构，按 P1→P4 渐进实施。** 不是重写：把本轮补丁中被验证正确的思想（共识、别名、隔离、消歧、熔断）沉淀为数据模型和分层管线；现有管线在迁移完成前持续工作，每期独立可回滚。
