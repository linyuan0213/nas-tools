# ADR-019: 替换 anitopy — 自研统一解析引擎

## Status

Proposed

## Date

2026-07-26

---

## Context

### anitopy 现状

| 属性 | 值 |
|------|------|
| 版本 | 2.1.1（2022-07-24） |
| 上游 | [igorcmoura/anitopy](https://github.com/igorcmoura/anitopy) 90 commits，基于已停维的 C++ [Anitomy](https://github.com/erengy/anitomy) |
| 类型标注 | 无（所有 import 带 `# type: ignore`） |
| 返回类型 | 无类型 `dict` |
| 支持范围 | 仅动漫命名格式，不支持电视剧/电影 |
| 中文格式 | 不原生支持 dmhy/mikan/baha 中文命名规范 |

### 项目集成情况

anitopy 在项目中 4 个调用点，3 个文件：

| 文件 | 行号 | 调用 | 用途 |
|------|------|------|------|
| `anime/__init__.py` | 49 | `anitopy.parse(title)` | 原始标题解析 |
| `anime/__init__.py` | 51 | `anitopy.parse(prepared_title)` | 预处理后解析 |
| `anime/name_parser.py` | 33 | `anitopy.parse("[ANIME]" + title)` | 名称提取失败时的 hack 重试 |
| `anitopy_adapter.py` | 11 | `anitopy.parse(title)` | BaseParser 适配器封装 |

### 当前架构问题

#### 1. 两条独立解析管线

```
meta_info(title)
     |
_is_anime()? ──Yes──→ parse_anime_title() ──→ anitopy.parse()  ──→ MediaInfo
     |                    (anime/)
     No
     |
parse_video_title() ──→ token-by-token regex ──→ MediaInfo
  (video/)
```

分发由 `_is_anime()` 启发式函数控制，依赖标题中的方括号模式、字幕组标签等脆弱信号。一旦误判，就会走到错误的解析管线，产生错误的 MediaInfo。

#### 2. anitopy 输出不足以满足需求

项目在 anitopy 之上堆积了大量修补代码：

| 修补模块 | 行数 | 作用 |
|----------|------|------|
| `prepare_title()` | 65 行 | 预处理：去站点标签、文件大小、修复 `[4K]` 等标记 |
| `_supplement_bracket_content()` | 58 行 | 回收 anitopy 未消费的方括号内容用于名称补全 |
| `recover_cn_name()` | 17 行 | 从预处理前 anitopy 结果恢复丢失的中文名 |
| 额外的正则匹配 | `__init__.py:80` | 自行匹配 WEB-DL/BluRay/HDTV 等来源 |

需要解析两次标题（原始 + 预处理后）来弥补信息丢失，说明 anitopy 对上下文不感知。

#### 3. 类型不安全且无扩展性

- 所有 anitopy import 均使用 `# type: ignore`
- anitopy 返回无类型 `dict`，字段键字符串字面量散布在多个文件中
- 新增规则需要修改 C++ Anitomy 源码（不可行）
- `AnitopyAdapter.parse()` 置信度写死 0.75，无法根据输入质量动态调整

---

## Decision

### 自研 `UnifiedParser` 替换 anitopy

用一个纯 Python 统一解析引擎合并当前 `anime/` 和 `video/` 两条管线，消除`_is_anime()` 分发。

### 核心原则

1. **无外部解析依赖** — 不再依赖 anitopy 或任何第三方命名解析库
2. **声明式规则引擎** — 每条提取规则是独立的 `ExtractionRule`，可组合、可测试、可扩展
3. **内容自推断** — 媒体类型由解析结果推断，不依赖外部启发式分发
4. **完全类型安全** — 所有接口带完整类型标注，通过 pyright strict 检查
5. **向后兼容** — 现有 `BaseParser` / `ParserResult` / `MediaInfo` 接口不变

### 架构

```
src/app/media/parser/
├── base.py                      # BaseParser / ParserResult（不变）
├── unified/                     # 统一解析引擎
│   ├── __init__.py              # UnifiedParser 主入口
│   ├── types.py                 # 内部类型定义（Element, ParseContext 等）
│   ├── context.py               # ParseContext：解析过程中的可变上下文
│   ├── preprocessor.py          # prepare_title() — 合并 anime/prepare.py + video 预处理
│   ├── element_extractor.py     # 规则编排器
│   ├── name_extractor.py        # 名称提取：中/英/日 分层优先级
│   └── type_inferrer.py         # 媒体类型推断
│
├── unified/rules/               # 声明式规则库
│   ├── __init__.py
│   ├── base.py                  # ExtractionRule 基类
│   ├── season_rules.py          # 季数：S01、Season 1、第1季
│   ├── episode_rules.py         # 集数：E01、EP01、[01]、第1集、第十集
│   ├── year_rules.py            # 年份：2008、(2008)、[2008]
│   ├── resolution_rules.py      # 分辨率：1080p、4K、2160p、1280x720
│   ├── codec_rules.py           # 编码：H.264、HEVC、AAC、FLAC、DTS
│   ├── source_rules.py          # 来源：WEB-DL、BluRay、HDTV、DVDRip
│   ├── group_rules.py           # 制作组/字幕组：[Group]、@Group
│   └── episode_title_rules.py   # 集标题："Tiger and Dragon"
│
├── adapters/                    # 适配器层
│   ├── __init__.py
│   ├── unified_adapter.py       # UnifiedParser → BaseParser 适配器
│   └── anitopy_adapter.py       # 保留（标记 deprecated → Phase 5 移除）
│
├── naming_patterns.py           # 保留：YAML 命名模式库（最高优先级命中）
├── _metainfo.py                 # meta_info() 改用 UnifiedParser
├── regex.py                     # RegexParser 改用 UnifiedAdapter
├── llm.py                       # 保留不变
├── token_adapter.py             # 保留不变
│
├── anime/                       # 逐步弃用 → Phase 5 移除 import
└── video/                       # 逐步弃用 → Phase 5 移除 import
```

### 规则引擎设计

#### ExtractionRule

```python
from dataclasses import dataclass, field
from typing import Any, Callable, Pattern

@dataclass
class ExtractionRule:
    name: str
    pattern: Pattern[str]
    priority: int                      # 越大越优先，同优先级先匹配先消费
    extract: Callable[[re.Match, str], dict[str, Any]]
    consumes: bool = True              # 匹配后是否消费（从文本移除）
    confidence: float = 0.9            # 匹配置信度
    stop: bool = False                 # 匹配后是否停止本类别后续规则
```

#### RuleEngine

```python
@dataclass
class RuleEngine:
    rules: list[ExtractionRule]               # 按 priority desc 排序

    def extract(self, text: str) -> list[ExtractedElement]:
        """顺序应用规则，消费已匹配文本，返回提取到的元素列表"""
```

#### ExtractedElement

```python
@dataclass
class ExtractedElement:
    category: str          # "season", "episode", "year", "resolution", ...
    value: Any             # 提取的值（int | str | list）
    confidence: float      # 本条规则的置信度
    rule_name: str         # 匹配的规则名
    span: tuple[int, int]  # 在原始文本中的位置
```

### 集数规则设计（核心示例）

集数是标题解析中最复杂的维度，因其格式极其多样。规则按优先级排列：

| 优先级 | 规则名 | Pattern | 示例输入 | 提取 |
|--------|--------|---------|----------|------|
| 100 | `sxxexx` | `[Ss](\d+)[Ee](\d+)` | `S01E05` | season=1, episode=5 |
| 95 | `season_ep_keyword` | `Season\s*(\d+)\s*Episode\s*(\d+)` | `Season 1 Episode 5` | season=1, episode=5 |
| 90 | `bracket_range` | `\[(\d+)[-~](\d+)\]` | `[01-08]` | episode=[1,8] (range) |
| 85 | `dash_ep_range` | `\b(\d+)[-~](\d+)\b(?!p)` | `01-08` (后无 'p') | episode=[1,8] |
| 80 | `single_bracket_ep` | `\[(\d{1,4})(?:v\d+)?\]` | `[05]`, `[01v2]` | episode=5 |
| 75 | `ep_prefix` | `\bEP?(\d{1,4})\b` | `EP05`, `P01` | episode=5 |
| 70 | `chinese_ep` | `第\s*(\d+)\s*[集话話期]` | `第5集` | episode=5 |
| 65 | `chinese_number_ep` | `第([一二三四五六七八九十百]+)集` | `第十集` | episode=10 (cn2an) |
| 60 | `dash_or_tilde_ep` | `\s[-~]\s*(\d{1,4})\b` | ` - 05` | episode=5 |
| 55 | `hash_ep` | `#(\d{1,4})\b` | `#05` | episode=5 |
| 50 | `bare_episode` | `\b(0?[1-9]\d{0,3})\b` | `05 ` (需上下文确认为集数) | episode=5 |
| 45 | `chinese_range_ep` | `[第]?([一二三][十]?)([-~至])([一二三][十]?)[集话話期]` | `十二至十五集` | episode=[12,15] |

**规则消费机制**：高优先级规则匹配成功后，其文本片段被标记为 "consumed"，低优先级规则不再处理该片段。这避免了 `S01E05` 中的 `05` 被低优先级的 `bare_episode` 二次匹配。

### 名称提取策略

名称是解析中最复杂的维度。采用**分层优先级**设计：

```
Layer 1: 命名模式库 (YAML)
  └→ 确定性匹配 → 直接返回 cn_name + en_name
  └→ 来源: naming_patterns.py（已存在，保留不变）

Layer 2: 斜杠分隔格式 (dmhy / mikan)
  └→ "中文 / English / 日文" 格式
  └→ 识别每段语言属性 → 分派为 cn_name / en_name / jp_title

Layer 3: 方括号内容分析
  └→ [字幕组] Title [其他标签] 格式
  └→ 识别第一个非元数据方括号内容为名称

Layer 4: 自由文本分析
  └→ 移除已消费元素后的剩余文本
  └→ 中文连续片段 → cn_name
  └→ 英文连续片段 → en_name（排除已知元数据 token）
  └→ 日文假名检测 → jp_title（用于 TMDB 匹配）

Layer 5: 降级恢复
  └→ prepare_title 前原始文本中的中文名
  └→ episode_title 补回短中文名
```

### 类型推断

不依赖外部标记，基于解析结果综合推断：

```
if 命名模式库命中而且 type 字段已设置 → 直接使用

else if 有集数且集数格式为动漫典型（如 [01] 方括号单级）:
    if 有制作组标记 and 名称匹配动漫模式 → ANIME
    else if 名称含中文 and 无 SxxExx 格式 → ANIME
    else → TV

else if 有 SxxExx 或 Season X 或 第X季:
    → TV

else if 有年份 + 分辨率 + 无任何集数标记:
    → MOVIE

else if 有资源来源 (BluRay/WEB-DL 等) + 无集数:
    → MOVIE

else:
    → TV (默认)
```

### 数据流

```
UnifiedParser.parse("[喵萌奶茶屋] 鬼灭之刃 / Kimetsu no Yaiba [08][WebRip 1080p HEVC AAC]")
    │
    │ Phase 1 — 预处理
    ├── prepare_title(title)
    │   ├── 去除站点标签: [喵萌奶茶屋] → 保留，非站点标签
    │   ├── 修复: [4K] → 2160p (无此项)
    │   ├── 去除文件大小 (无此项)
    │   └── → "鬼灭之刃 / Kimetsu no Yaiba [08][WebRip 1080p HEVC AAC]"
    │
    │ Phase 2 — 元素提取
    ├── extract_elements(title)
    │   ├── 集数规则: [08] → episode=8, priority=80, consumed
    │   ├── 分辨率规则: 1080p → resolution=1080p, priority=80, consumed
    │   ├── 来源规则: WebRip → source=WEB-DL, priority=90, consumed
    │   ├── 视频编码: HEVC → video_codec=HEVC, priority=70, consumed
    │   ├── 音频编码: AAC → audio_codec=AAC, priority=70, consumed
    │   └── consumed_spans: [(pos:42-46), (pos:47-52), (pos:38-44), ...]
    │
    │ Phase 3 — 名称提取
    ├── extract_name(title, consumed_spans)
    │   ├── 移除 consumed 文本段 → "鬼灭之刃 / Kimetsu no Yaiba"
    │   ├── 检测到 "/" 分隔
    │   ├── 左侧 "鬼灭之刃" is_all_chinese → cn_name
    │   └── 右侧 "Kimetsu no Yaiba" is_non_chinese → en_name
    │
    │ Phase 4 — 类型推断
    ├── infer_type(elements, cn_name)
    │   ├── has_episode=True, season_count=0
    │   ├── cn_name contains "之" → anime pattern
    │   └── → type=ANIME
    │
    │ Phase 5 — 组装
    └── → ParserResult(
            title_cn="鬼灭之刃",
            title_en="Kimetsu no Yaiba",
            episode=8,
            resource_pix="1080p",
            resource_type="WEB-DL",
            video_encode="HEVC",
            audio_encode="AAC",
            type=ANIME,
            confidence=0.92   # 动态计算: Σ(规则置信度) / 规则数
          )
```

---

## Consequences

### 正向

1. **消除外部依赖** — 移除 `anitopy` 包（约 40KB），不再受上游停维影响
2. **统一解析管线** — 一条路径处理所有媒体类型，消除 `_is_anime()` 分发
3. **类型安全** — 全部 Python 类型标注，通过 pyright strict
4. **可测试** — 每条规则独立测试；规则组合可通过添加/移除规则覆盖各种场景
5. **可扩展** — 新增命名格式只需添加对应的 `ExtractionRule`，不影响其他规则
6. **动态置信度** — 基于实际匹配规则的置信度加权计算，而非写死
7. **集数解析增强** — 新增中文数字（第十集）、hash 格式（#05）、EP 前缀等支持
8. **原生中文支持** — 内置中文字幕组格式（dmhy/mikan/baha/ANi）解析

### 逆向

1. **开发成本** — 预计 5-7 天实现 + 测试
2. **迁移风险** — 解析行为可能与 anitopy 有细微差异，需要回归测试覆盖
3. **规则维护** — 新规则持续积累，需要定期整理去重

### 中性

1. `anime/` 和 `video/` 子包会逐步弃用但保留兼容期，避免大爆炸式切换
2. 命名模式库（YAML）保留不变，作为最高优先级命中路径

---

## Implementation Plan

### Phase 1: 规则引擎基础设施（1-2 天）

- [ ] 创建 `src/app/media/parser/unified/rules/` 包
- [ ] 实现 `ExtractionRule`、`ExtractedElement`、`RuleEngine`
- [ ] 实现集数规则（episode_rules.py）
- [ ] 实现季数规则（season_rules.py）
- [ ] 实现年份规则（year_rules.py）
- [ ] 实现分辨率规则（resolution_rules.py）
- [ ] 实现编码规则（codec_rules.py）
- [ ] 实现来源规则（source_rules.py）
- [ ] 每个规则文件独立单元测试

### Phase 2: 名称提取器 + 预处理（1-2 天）

- [ ] 实现 `unified/preprocessor.py` — 合并 `anime/prepare.py` 和 `video/` 预处理逻辑
- [ ] 实现 `unified/name_extractor.py` — 五层优先级名称提取
- [ ] 集成 `naming_patterns.py` 为 Layer 1
- [ ] 迁移 `_supplement_bracket_content` 为 Layer 3
- [ ] 迁移 `recover_cn_name` 为 Layer 5
- [ ] 单元测试：覆盖所有现有 `test_anime_parser.py` 场景

### Phase 3: 统一解析器 + 类型推断（1 天）

- [ ] 实现 `unified/element_extractor.py` — RuleEngine 编排
- [ ] 实现 `unified/type_inferrer.py` — 媒体类型推断
- [ ] 实现 `UnifiedParser` 主类（Phase 1-5 串联）
- [ ] 集成测试：对比 anitopy 输出

### Phase 4: 集成替换（1 天）

- [ ] 创建 `adapters/unified_adapter.py` — UnifiedParser → BaseParser
- [ ] `_metainfo.py` 的 `meta_info()` 切换到 UnifiedParser
- [ ] `regex.py` 的 `RegexParser` 切换到 UnifiedAdapter
- [ ] 移除 `_is_anime()` 分发逻辑
- [ ] 集成测试：全链路 `meta_info()` 输出对比

### Phase 5: 清理与文档（1 天）

- [ ] 移除 `anitopy` 依赖（pyproject.toml + uv.lock）
- [ ] 移除 `anitopy_adapter.py`
- [ ] 移除 `# type: ignore` 标记
- [ ] `anime/` 和 `video/` 改为 re-export → `unified/`
- [ ] 全量回归测试
- [ ] 更新 `docs/architecture.md`

---

## Rollback Plan

如果在 Phase 4 集成测试中发现解析质量显著下降：

1. 保留 `anitopy_adapter.py` 作为 fallback adapter（仅需注释标记 deprecated 改为 active）
2. `RegexParser` 支持 parser 切换配置项
3. 通过 feature flag `UNIFIED_PARSER_ENABLED` 控制新旧管线

---

## Related

- [ADR-014: 媒体身份解析与匹配架构](./ADR-014-media-identity-resolution-architecture.md) — 本 ADR 的解析层是 ADR-014 身份解析链的基础
- [ADR-009: 媒体类型统一](./ADR-009-media-type-unification.md)
- [anitopy GitHub](https://github.com/igorcmoura/anitopy) — 上游项目（已停维）

---

## References

- 解析器当前架构：`src/app/media/parser/anime/` + `src/app/media/parser/video/`
- 命名模式库：`src/app/media/parser/naming_patterns.py`
- 现有测试：`tests/unit/test_anime_parser.py`、`tests/unit/test_video_parser.py`
