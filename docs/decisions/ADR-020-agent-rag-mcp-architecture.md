# ADR-020: 智能 Agent RAG + MCP 架构

## Status

Proposed

## Date

2026-08-09

## Updated

2026-08-09（评审后修正：向量库默认改为 LanceDB + 可选 Qdrant；MCP 降级为可选适配层、默认关闭；整体裁剪为 MVP 优先；内部工具层按域重设计，MVP 17 工具；分层与依赖规则修正（端口下沉，禁反向依赖）；搜索/意图统一为单一意图端口 + 单一编排入口，删除重复流水线；记忆子系统（短程 DB + 长程向量）；反哺路径；MCP 双向候选评估；现代化对标补齐 SSE/async/fallback/evals/Langfuse/ContextBuilder）

---

## Context

### 现状盘点

项目已具备一套基于 `pydantic-ai` 的 Agent 基础（`src/app/agent/`）：

| 模块 | 职责 |
|------|------|
| `service.py` | `AgentService` 门面：provider 管理、缓存、重试、结构化输出 |
| `config.py` | `ProviderConfig` + `get_provider()` |
| `providers/` | `BaseProvider` + OpenAI / Ollama / Gemini 聊天提供方 |
| `agents/` | `MediaRecognizer`、`SearchIntentAgent`、`ChatAgent`、`QuestionAnswerAgent` |
| `tools/` | `ToolRegistry` + `ToolExecutor`（静态注册表，桥接业务 Service） |
| `prompts/` | media / search 提示词模板 |

已复用的基础设施：不可变 `AppContext` + 分模块 Builder（`app/di/`）、事件总线（`app/events/`）、缓存系统（`app/infrastructure/cache_system/`）、插件框架、RBAC。

### 核心约束（决定取舍）

- **自托管单节点 NAS 媒体工具**，默认 SQLite、Docker 单容器，个人 / 小团队使用
- Agent 是**辅助功能**，不是产品主线；运维成本与代码复杂度必须可控
- 设计原则：满足价值的最简方案，优先 MVP，避免过度工程化

### 相对主流 Agent + RAG 架构的缺口

| # | 缺口 | 现状 | 影响 |
|---|------|------|------|
| 1 | 无 RAG | 仅会话窗口历史，无 embedding / 向量库 / 检索 | 无法回答关于媒体库、配置、FAQ 的具体问题 |
| 2 | 工具调用仅一轮 | `ChatAgent.chat_with_tools` 仅支持单次工具调用 | 无法完成多步任务（检索 → 判断 → 下载/订阅） |
| 3 | 无记忆沉淀 | 仅最近 10 轮会话缓存 | 上下文理解有限 |
| 4 | 工具治理弱 | 工具未绑定 RBAC，危险操作无确认 | 权限风险 |

> 注：评审后明确 —— **MCP 不是本项目的核心缺口**（见 Decision §3），默认不引入。

---

## Decision

在 `src/app/agent/` 下扩展为**主流 Agent + RAG 架构**，MCP 作为**可选适配层**（默认关闭）。遵循项目既有约定：不可变 `AppContext` + Builder、事件驱动、复用 `pydantic-ai`（原生多步工具调用）、所有 import 置顶、ruff / pyright 校验。

### 1. 目标架构（MVP 优先）

```
┌────────────────────────────── 应用层 ──────────────────────────────┐
│  API Routers: chat / kb                                            │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌──────────────────── 对话 Agent（pydantic-ai） ─────────────────────┐
│  ChatAgent：多步工具调用循环（plan → act → observe → reflect）      │
│  工具集 = 内部 ToolExecutor 工具  +  kb_search（RAG 检索工具）      │
│  记忆 = 短程会话（DB 持久化 + 缓存热路径，详见 §5）                 │
│  结构化工具 = MediaRecognizer / SearchIntentAgent（复用现有）       │
└──────┬────────────────────────────────────────────┬───────────────┘
       ▼                                            ▼
┌─────────────────┐                       ┌──────────────────┐
│  RAG Pipeline   │                       │ 治理 Guardrails   │
│  Chunker        │                       │ 复用 RBAC 工具鉴权 │
│  Ingestor       │                       │ 危险操作需确认     │
│  Retriever(混合)│                       │ 脱敏 + 用量日志    │
│  Context        │                       └──────────────────┘
└──────┬──────────┘
       ▼
┌─────────────────────────────────────────────────────────────┐
│  VectorStore: LanceDB（默认，嵌入式） / Qdrant（可选）        │
│  Provider Layer: Chat + Embedding（Ollama / OpenAI / Gemini） │
└─────────────────────────────────────────────────────────────┘

可选（默认关闭）：
┌─────────────────────────────────────────────────────────────┐
│  MCP 适配层：MCP Server（对外暴露内部工具）/ MCP Client        │
└─────────────────────────────────────────────────────────────┘
```

**数据流（一次智能请求）**
`用户输入 → 会话上下文 → ChatAgent 工具循环（按需调用 kb_search 检索知识 / 调用内部工具执行动作，RBAC 鉴权 + 危险确认）→ 汇总输出 → 写会话记忆 + 用量日志`

### 2. 向量库选型（评审修正 ×2）

| 方案 | 模式 | 混合检索 | CPU 兼容 | 运维 | 结论 |
|------|------|---------|---------|------|------|
| **SQLite-vec + FTS5** | 嵌入式（复用现有 SQLite 基建） | FTS5 BM25（trigram 中文分词）+ vec KNN + Python RRF 融合 | ✅ 全平台（纯 C 扩展，无 SIMD 要求） | 零运维（单文件，随现有备份流程） | **默认** |
| **LanceDB** | 嵌入式 | 原生 FTS + 向量 + 混合 + 重排 | ⚠️ 预编译库需 **AVX2**（实测无 AVX2 机器 SIGILL，老 NAS CPU 中招） | 零运维 | **可选加速**（运行时检测，不支持则明确报错） |
| **Qdrant** | local 嵌入式 / server | ❌ 无原生 FTS scoring（BM25 需另拼）；local 模式官方定位 dev/test（暴力检索、无 HNSW、单写锁） | local 可跑（实测 1.3ms/2000 向量） | local 零运维；server 需额外容器 | **可选**（已有 Qdrant server / 大规模库用户） |

- 默认 **SQLite 混合检索**：本项目知识库为千级向量（docs 数百 chunk + 媒体库数千条目），暴力 KNN 毫秒级，HNSW 无意义；真正影响中文问答质量的是 BM25 全文检索——Qdrant 空白、FTS5 强项
- 可选 **LanceDB**：AVX2 机器上的加速选择（原生混合检索 + 重排）
- 可选 **Qdrant**：server 模式供进阶用户；不做默认因 ① 无原生 BM25 ② server 违反单容器约束 ③ local 模式 dev 级 ④ grpcio 重依赖
- 统一 `VectorStore` 抽象，按 `settings.agent.vector_store` 选择（`sqlite` 默认 / `lancedb` / `qdrant`）

### 3. MCP：是否服务化（评审修正）

**结论：默认不需要 MCP 服务化，降级为可选适配层、默认关闭。**

理由：

1. **内部工具抽象已足够**：`ToolRegistry` / `ToolExecutor` 已是干净边界，Agent 通过它调用全部内部能力，无需再包一层 MCP 协议
2. **MCP Server 价值低、风险高**：等于把已有 REST API 复制一份协议面，并把下载 / 删除 / 同步等破坏性操作暴露给任意外部客户端
3. **MCP Client 属小众**：媒体管理的主要价值来自内部工具（搜索 / 下载 / 订阅），而非外部通用工具
4. **主流 MCP 红利在异构 Agent 生态互通**，本项目是单一紧耦合内部 Agent，收益小、安全面大

因此：
- MCP 不做核心、不默认启用
- 若未来确有需求（如把媒体管理接入 Claude Desktop / IDE Agent），以**可选插件形式**提供 MCP Server 适配：**opt-in + token 鉴权 + RBAC + allow/deny 治理**，默认 `enabled: false`

### 4. 范围裁剪（评审修正）

为避免过度工程化，明确 MVP 与延后项：

| 能力 | 决策 | 说明 |
|------|------|------|
| 单对话 Agent + 多步工具循环 | **MVP** | 基于 pydantic-ai，替代原"Orchestrator + 4 专家子代理" |
| RAG 检索（LanceDB）+ `kb_search` 工具 | **MVP** | 核心价值 |
| 短程会话记忆（持久化 + 滚动摘要） | **MVP** | DB 存储 + token 预算 + 三维作用域（见详细设计 §5） |
| RBAC 工具鉴权 + 危险操作确认 | **MVP** | 轻量复用现有 RBAC，对话内确认，不建独立审批子系统 |
| 用量日志（token / 延迟） | **MVP** | 落 loguru |
| MediaRecognizer / SearchIntentAgent | **保留** | 作为结构化工具复用，非编排子代理 |
| 多代理编排（Orchestrator + 专家子代理） | **延后** | MVP 不需要 |
| 长程语义记忆（用户偏好 / 情节记忆） | **设计定稿，Phase 4 可选** | 见详细设计 §5，复用 LanceDB，默认关闭 |
| OpenTelemetry | **延后** | 用量日志先行 |
| 独立审批工作流子系统 | **延后** | 对话内确认即可 |

---

## 详细设计

### 0. 分层与依赖规则（评审修正）

#### 现状违规（实测）

| 类型 | 位置 | 说明 |
|------|------|------|
| 反向依赖 | `media/parser/llm.py:1` | media 组件层 import agent 层 `MediaRecognizer` |
| 反向依赖 | `services/search_web_service.py:11`、`services/system/info.py:9` | services 层 import `SearchIntentAgent` |
| 反向依赖 | `services/search_message_service.py:10` | services 层 import `AgentService` |
| 反向装配 | `di/builders/services_builder.py:299` | 将 `search_intent_agent` 注入 services |
| 跨层跳过 | `tools/handlers_media.py:7-10` | tools 直接 import `domain.*` / `media.models` / `infrastructure.cache_system` |
| 跨层跳过 | `tools/handlers_message_template.py:6`、`handlers_system_command.py:6` | tools import `message.templates` / `schemas.scheduler` |
| 循环依赖 | `agent/service.py` `set_tool_executor` + `coordinators_builder.py:143` | AgentService ↔ ToolExecutor 互持，靠后门注入解环 |
| 循环调用 | `tools/handlers_media.py` `deps["search_intent_agent"]` | tool → agent，而 agent → tool，成环 |
| 自相矛盾 | `tools/base.py` docstring | 自称"零依赖"，handlers 却大量越层 import |

#### 修正规则

1. **分层固定，只允许上层 → 下层**：

```
Layer 5: API Routers
Layer 4: Agent 层（service / agents / tools / rag / mcp）   ← 顶层能力
Layer 3: Services 业务服务层
Layer 2: Business Components（media / message / sites ...）
Layer 1: Domain（enums / models / ports 端口接口）
Layer 0: Infrastructure（events / cache / http）
```

2. **端口下沉（依赖倒置）**：下层需要的 LLM 能力抽象为 **Protocol 端口定义在下层**，agent 层实现端口，Builder 注入：
   - `media/parser/llm.py` 改为只依赖已有的 `BaseParser` 端口；`MediaRecognizer` 作为 `BaseParser` 实现注册进来
   - `services` 需要意图解析 → 定义 `IntentResolver` Protocol；`SearchIntentAgent` 实现之
   - `services` 需要对话 → 定义 `ChatPort` Protocol；`AgentService` 实现之
   - **禁止** services / media / domain 任何文件 `import app.agent.*`；**插件是能力消费方**（现状：`autosignin` 用 `QuestionAnswerAgent`、`autosub` 用 `translate_to_zh`），允许经 `PluginContext` 注入 agent 能力，不视为反向依赖
3. **tools 分层**：`tools/schemas/` 真零依赖（仅 jsonschema）；`tools/handlers/` 只依赖 **Services 门面**（经 `ToolContext` 注入），禁止直接 import `domain / media.models / schemas / message.templates / infrastructure`；所需 DTO 由 services 层提供
4. **解环**：`AgentService` 不再持有 `ToolExecutor`；Builder 单向装配：`ports 实现 → services → ToolContext/ToolExecutor → ChatAgent → AgentService(facade)`；删除 `set_tool_executor` 后门；工具 handler 内不再回调 agent（意图解析已由 `media_search` 内嵌流程或编排器负责）
5. **CI 防护**：引入 import-linter（或等效检查），契约化禁止下层 import `app.agent`

### 1. 搜索与意图统一（评审修正）

#### 现状重复（实测）

| 重复点 | 位置 | 说明 |
|------|------|------|
| 意图解析 ×4 | `agent/agents/search_intent.py`（LLM）、`search_web_service.py:58-90`（正则+LLM 双解析并存）、`search_orchestrator.py::_identify_media`（正则+TMDB）、`tools/handlers_media.py::media_search`（LLM 再来一遍） | 同一"查询→意图"四种实现，结果不一致 |
| 搜索编排 ×2+ | `search_web_service.search_medias_for_web`（294 行，**活跃**，由 `system/info.py:201` `WebSearchService` 调用）vs `search_orchestrator.orchestrate`（301 行，**死代码**——全库零调用方，docstring 声称的"合并三条路径"是未完成的迁移） | 一套在跑、一套未接线；`Searcher` 内还有与 orchestrator 重复的排序/入库/下载组件 |
| 工具绕过流水线 | `tools/handlers_media.py::media_search` 直接调 `indexer.search_by_keyword` | 无去重 / 排序 / 入库 / 进度，与 Web 搜索结果不一致 |
| 意图模型 ×3 | `SearchIntent`(pydantic) vs `get_keyword_from_string` 6 元组 vs message `_parse_intent` 字符串枚举 | 同一概念三种表示 |

#### 修正：单一意图端口 + 单一编排入口

1. **统一意图模型**：`SearchIntent`（pydantic：keywords / media_type / year / season / episode / raw_text）作为唯一表示，放 domain 层
2. **意图端口**：`IntentResolver` Protocol 定义在 domain；`IntentResolverChain`（services 层）：规则解析（`get_keyword_from_string`）→ LLM 增强（可选，端口注入）→ 归一化；`SearchIntentAgent` 改造为实现该端口，services 只依赖端口
3. **唯一编排入口**：**接线已存在的 `SearchOrchestrator`**（当前零调用方，实质是完成未完成的迁移）为搜索唯一流水线（识别 → 多关键词 → 并发 → 去重 → 排序 → 入库 → 可选下载）；**删除 `search_medias_for_web`（294 行）**；`WebSearchService`（`system/info.py`）/ 消息渠道 / Agent 工具统一构建 `SearchContext` 调用
4. **Searcher 收敛**：仅保留单关键词执行器；`sort_results` / `persist_results` / `batch_download` 归并到 orchestrator
5. **命令意图归位**：消息渠道 `_parse_intent`（DOWNLOAD/ASK/SUBSCRIBE）是命令路由而非搜索意图 → 明确为 CommandRouter，其搜索请求同样汇入 orchestrator
6. **工具零编排**：`media_search` 工具只调 `SearchService.search(query)` 门面，工具内不做识别 / 去重 / 排序

```
Web API ──┐
消息渠道 ──┼─▶ SearchService 门面 ─▶ SearchOrchestrator.orchestrate(SearchContext)
Agent 工具 ┘            ▲                      │
              IntentResolverChain       Searcher（单关键词执行）
              （规则 → LLM 端口）              ▼
                                         IndexerService
```

### 2. Provider 层扩展（`providers/`）

新增 embedding 能力，保留现有聊天 provider。

```python
# providers/base.py — 新增抽象
class BaseEmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
    @property
    def dimension(self) -> int: ...   # 由模型运行时获取，不硬编码
```

- `openai.py` / `ollama.py` / `gemini.py` 各自实现 `embed`，复用现有连接配置
- 本地首选 Ollama（如 `nomic-embed-text`），云端可选 OpenAI / Gemini
- embedding 结果接入 `lru_cache_with_ttl` 缓存

### 3. RAG Pipeline（新增 `rag/`）

```
rag/
├── models.py           # Chunk / ScoredChunk
├── chunker.py          # MarkdownChunker（标题分段 + 滑动窗口）
├── embedding.py        # EmbeddingService（分批 + 缓存）
├── vector_store.py     # VectorStore ABC（不导入任何实现，防循环导入）
├── sqlite_vec_store.py # SQLiteVecStore（默认：sqlite-vec + FTS5 trigram + Python RRF）
├── lancedb_store.py    # LanceDBStore（可选加速；无 AVX2 时 import 即 SIGILL，仅工厂惰性加载）
├── factory.py          # create_vector_store + 路径解析（settings.data_path）+ AVX2 预检
├── ingestor.py         # 知识库采集 + 索引构建 + 增量更新
├── retriever.py        # 混合检索 + 截断重排
└── namespaces.py       # 知识域命名空间
```

- **知识库来源**（贴合业务）
  - 媒体库元数据（`media_library_service`）→ 回答"库里有啥 / 某作品详情"
  - `docs/`（FAQ、配置、插件指南）→ 运维问答
  - 消息模板 / RSS 规则 / 站点配置 → 操作建议
- **命名空间**：`media_library` / `messages` / `faq` / `operations`，隔离检索范围
- **检索方式**：LanceDB 混合检索（FTS + 向量），可选重排；Qdrant 后端时用其混合 / 融合能力
- **检索暴露为工具**：`kb_search(query, namespace?)` 注册进 `ToolRegistry`，供 ChatAgent 在工具循环中按需调用（而非独立 QA Agent 管道）

### 4. Agent Core（重构 `agents/`，MVP 单 Agent）

```
agents/
├── chat_agent.py        # 重构：pydantic-ai 多步工具调用循环
├── media_recognizer.py  # 保留（结构化识别工具）
├── search_intent.py     # 保留（改造为 IntentResolver 端口实现）
├── question_answer.py   # 保留（autosignin 插件答题依赖）
└── memory/             # 记忆子系统，详见 §5
```

- **工具调用循环**：将 `ChatAgent.chat_with_tools` 单次调用重构为循环——LLM 输出工具请求 → 执行 → 结果回灌 → 直到最终回答（步数上限 `max_steps`，默认 8）
- **工具集** = 内部 `ToolExecutor` 工具 + `kb_search` 检索工具，统一经 `ToolRegistry.validate_and_execute`
- **优先用 pydantic-ai 的 `Agent`**（项目已依赖 `pydantic-ai>=1.107`），原生支持多步工具调用、结构化输出、会话；`AgentService` 作为门面保留

### 5. 记忆子系统（评审修正）

#### 现状问题（实测）

| 问题 | 位置 | 说明 |
|------|------|------|
| 仅内存存储 | `caches.py:237` `OpenAISessionCache` → `MemoryCacheAdapter` | 重启即丢，30d TTL 形同虚设 |
| 无作用域 | `chat_agent.py` 只传 `session_id` 字符串 | 无 user / channel 维度，跨渠道可能串会话 |
| 粗暴裁剪 | `MAX_HISTORY_MESSAGES=20` 固定条数 | 无 token 预算、无滚动摘要，长上下文丢失 |
| 魔法命令 | `#清除` 硬编码在 `chat_agent.py` | 非结构化控制 |
| 无 DB 模型 | `db/models/` 无会话表 | 会话无法持久化 / 审计 |
| 无长程记忆 | — | 用户偏好 / 历史完全不沉淀 |

#### 记忆分层

| 层 | 内容 | 存储 | 作用域 | 生命周期 |
|----|------|------|--------|---------|
| 短程（工作记忆） | 当前会话消息 + 滚动摘要 | DB 表 + 缓存热路径 | `(user_id, channel, session_id)` | TTL 30d，可清除 |
| 长程（语义记忆） | 用户偏好 / 事实（如"偏好 4K REMUX"） | LanceDB namespace `user_memory`（复用 §3 向量库，零新基建） | `user_id` | 无 TTL，用户可删 |
| 情节记忆（可选） | 历史会话摘要检索 | LanceDB 同上 | `user_id` | 可配置 |

#### 存储选型说明（为什么短程不用向量库）

- **短程会话状态**的访问模式是**精确、保序、追加式**读取最近 N 条消息；向量库是模糊语义匹配，会打乱语序、丢失精确内容，且每次读写都要过 embedding（延迟 + 成本）——不适合。主流框架（LangGraph checkpointer、MemGPT/Letta recall store）的会话状态一律用关系库 / KV
- **长程语义记忆**的访问模式是**模糊语义召回**（"用户喜欢什么画质？"），正是向量库的用途 → LanceDB namespace，复用 §3 基建
- 即：**会话状态用关系库（SQLite/MySQL/PG），语义召回用向量库（LanceDB）**，与 MemGPT / Mem0 的双层结构一致

#### 读写路径

- **读**：短程历史（DB 为准，缓存加速）+ 长程 top-k 检索（开启时）→ 组装进 system / context
- **写**：每轮追加消息；超 token 预算 → LLM 滚动摘要最早段（summary buffer，摘要消息固定头部保留）；会话结束 / 达阈值 → 异步事实抽取（事件总线，不阻塞对话）→ 长程库（opt-in）

#### 组件

```
agents/memory/
├── key.py         # MemoryKey(user_id, channel, session_id)
├── short_term.py  # ConversationStore：DB + 缓存双写，token 预算裁剪 + 滚动摘要
├── long_term.py   # SemanticMemory：LanceDB user_memory，事实 CRUD + top-k 检索
├── extractor.py   # 事实抽取（LLM，异步，opt-in）
└── summarizer.py  # 滚动摘要
```

#### DB 模型（新增，配 Alembic 迁移）

- `agent_conversation`：id / user_id / channel / session_id / summary / token_usage / created_at / updated_at
- `agent_message`：id / conversation_id / role / content / tool_calls / tokens / created_at

#### 治理

- 写入前脱敏（复用 §7）
- `memory_clear`（清会话）/ `memory_forget`（删长程事实）工具，write 级；替代 `#清除` 魔法字符串
- 长程记忆默认关闭（`agent.memory.long_term.enabled: false`），开启后事实用户可见、可查、可删

#### MVP 范围

短程持久化（DB）+ token 预算 + 滚动摘要 + 三维作用域 + `memory_clear`；长程语义记忆设计定稿、Phase 4 可选实现。

### 6. 内部工具层重设计（评审修正）

#### 现状问题

| 问题 | 说明 |
|------|------|
| 覆盖面窄 | 仅 6 个工具（search/download/subscribe/filter/system_command/message_template），系统能力面为 19 个路由域 / 30+ Service |
| 巨型枚举工具 | `system_command` 单工具塞 18 个 action，读写混杂（`scheduler_list` 与 `restart_server` 同级），LLM 选择困难、无法分级 |
| 反模式工具 | `resource_filter` 要求模型把资源列表完整传回参数，浪费 token 且易错；过滤应内置于 search 工具参数 |
| 双模式混杂 | `media_download` 模式1/模式2 条件必填，schema 对模型不友好，应拆分 |
| 返回契约不统一 | `data` 时而 str 时而 dict；"未找到"返回 `success=True` + str，错误语义混乱 |
| 无分级 | 查询 / 写 / 危险操作无区分，无法映射 RBAC 与确认 |
| prompt 拼装调用 | ChatAgent 靠解析文本 JSON 调用工具，非原生 function calling，单轮单工具、易解析失败 |
| deps 字典传递 | `ToolExecutor` 23 个位置参数 + dict，无类型、脆弱 |

#### 设计原则

1. **一动作一工具**（细粒度），禁止巨型枚举工具
2. **三级分级**：`read` / `write` / `dangerous`；write 需 RBAC 权限，dangerous 需对话内确认
3. **统一返回契约**：`ToolResult(success, data, error)`，`data` 恒为结构化 dict，失败恒走 `error`
4. **过滤 / 排序内置为 search 工具参数**，不做"模型传回列表"类工具
5. **原生 function calling**（pydantic-ai），支持多步循环与并行调用，替代 prompt JSON 解析
6. **双模式工具拆分**（如 `download_add_link` 与 `media_download`）
7. **deps 类型化**：`ToolContext` frozen dataclass，替代 dict
8. **结果大小控制**：列表类工具默认 limit + 摘要字段，避免爆 token

#### 工具全景（按域，标注分级）

**A. 媒体检索与元数据（read）**
- `media_search` 资源搜索（保留，修正返回结构；site / seeders / size / quality 过滤参数内置）
- `media_detail` TMDB 详情（标题 / 年份 / 类型 / 简介）
- `media_recommend` / `media_calendar`（可选）
- `kb_search` RAG 知识检索（见 RAG Pipeline）

**B. 下载管理**
- `download_list`（read）下载中任务 + 进度
- `download_add_link`（write）磁力 / 种子 / URL 下载
- `media_download`（write）搜索并下载最佳匹配
- `download_control`（write；remove 为 dangerous）start / stop / recheck / remove
- `downloader_status`（read）下载器状态 / 剩余空间 / 速度

**C. 订阅管理**
- `subscribe_add`（write）
- `subscribe_list`（read）含缺失集
- `subscribe_update` / `subscribe_delete`（write；delete 确认）
- `subscribe_history`（read）/ `subscribe_redo`（write）

**D. 媒体库（read）**
- `library_overview` 数量 / 空间 / 库列表
- `library_latest` / `library_history` 最新入库 / 播放历史
- `library_check` 某作品是否已入库 / 缺哪几集

**E. 整理与转移**
- `transfer_run`（write）手动整理
- `transfer_history` / `transfer_statistics`（read）
- `unknown_list`（read）/ `re_identify`（write）/ `unknown_delete`（dangerous）
- `sync_run`（write）/ `sync_paths`（read）

**F. 站点与索引器**
- `site_list` / `site_statistics`（read，上传下载量 / 分享率）
- `site_refresh` / `site_test`（write）
- `indexer_statistics`（read）

**G. 任务与调度**
- `scheduler_list`（read）/ `scheduler_run` / `scheduler_pause` / `scheduler_resume`（write）
- `rss_task_list`（read）/ `rss_task_run`（write）
- `brush_list`（read）/ `brush_delete`（dangerous）
- `torrent_remove_candidates`（read）/ `torrent_remove_run`（write）

**H. 系统**
- `system_status` / `system_logs`（read）
- `cache_clear` / `net_test`（write）
- `system_restart`（dangerous，确认）
- `message_send`（write）

**I. 消息模板（可选，低优先）**
- `message_template_get` / `message_template_update`

#### MVP 工具集（17 个，覆盖 80% 对话场景）

`media_search`、`media_detail`、`kb_search`、`download_add_link`、`media_download`、`download_list`、`download_control`、`downloader_status`、`subscribe_add`、`subscribe_list`、`subscribe_delete`、`library_check`、`transfer_run`、`scheduler_list`、`scheduler_run`、`system_status`、`memory_clear`

#### 工具代码组织

```
tools/
├── base.py            # ToolResult / BaseTool（+ level/permission）/ ToolRegistry
├── context.py         # ToolContext frozen dataclass（类型化依赖）
├── handlers/          # 按域拆分 handler：media.py download.py subscribe.py
│                      #   library.py transfer.py site.py scheduler.py system.py
└── schemas/           # 按域的工具 Schema 定义（同名注册）
```

### 7. 治理与可观测（轻量）

- **RBAC 绑定**：工具 `to_schema()` 增加 `permission` 字段；执行前经 `rbac_service` 鉴权
- **危险操作确认**：下载 / 删除 / 同步等写操作在对话中显式确认后执行（MVP 不建独立审批子系统）
- **脱敏**：日志 / 提示词中隐藏 api_key、cookie
- **用量日志**：检索命中、工具调用、耗时、token 成本落 loguru；OpenTelemetry 延后

### 8. 反哺路径：让系统更符合用户（评审补充）

Agent 不只是对话入口，其记忆 / 检索 / 意图能力应回流核心流程：

| 反哺点 | Agent 能力 → 系统触点 | 用户价值 |
|--------|----------------------|---------|
| 识别越用越准 | 长程记忆存用户纠正历史（unknown_list 手动修正）→ few-shot 注入 `MediaRecognizer` | 同一剧集 / 字幕组下次自动识别对 |
| 订阅决策个性化 | 长程偏好（画质 / 字幕组 / 站点）→ 自动调 `subscribe_add` 过滤与 `Searcher` 择优权重 | 不用每次重复说偏好 |
| 主动式服务 | 事件总线触发（订阅更新 / 下载完成 / 磁盘将满 / 分享率危险）→ Agent 生成摘要经 `message_send` 推送 | 从"人问系统"变"系统提醒人" |
| 自然语言配规则 | 用户口述 → Agent 生成过滤规则 / 刷流规则 / 识别词（`filter_service` / `brush_service` / `words_service`） | 告别手写规则语法 |
| 推荐贴合口味 | 播放历史（`library_history`）+ 记忆 → `media_recommendation` 重排 | 推荐真正符合口味 |
| 运维洞察 | Agent 读 `system_status` / `site_statistics` / 日志 → 周期健康报告 / 异常告警 | 分享率下降、磁盘预警早知道 |
| 意图理解一致 | `IntentResolverChain` 统一 Web / 消息 / Agent 三路搜索理解 | 任何入口自然语言都被正确理解 |
| 知识库自助 | `kb_search` 覆盖 docs / FAQ / 配置 → 应用内即时答疑 | 不用翻文档 |

支撑点：长程记忆（偏好沉淀）、事件总线（主动触发）、端口下沉（识别 / 意图反哺 services）、工具全景（执行能力）。
**MVP 落地**：订阅个性化 + 主动通知（事件触发 + message_send）；其余随长程记忆（Phase 4）逐步开放。

### 9. MCP 适配层（可选，默认关闭）

仅当 `agent.mcp.enabled: true` 时启用。分两个方向，定位均为**补充通道，不替代原生集成**：

```
mcp/
├── server.py     # 方向1：把内部工具以 MCP 协议暴露给外部 Agent（opt-in）
├── client.py     # 方向2：连接外部 MCP server，动态拉取 tools（插件化）
├── bridge.py     # MCP tool schema ⇄ ToolRegistry 桥接（命名空间 + 分级映射）
└── governance.py # token 鉴权 + RBAC + allow/deny
```

#### 方向1：MCP Server（对外暴露，默认关闭）

- 与 REST API 共用 `ToolExecutor` 与治理逻辑，不复制业务代码
- 破坏性工具默认 deny，需显式 allow；token 鉴权 + RBAC

#### 方向2：MCP Client（接入外部服务，插件化集成）

**定位：长尾通用能力的补充通道。** 核心域（下载器 / 媒体服务器 / 消息 / 索引器 / 站点）已有原生集成，不接 MCP 重复建设。

- **集成方式：走插件框架**——一个 MCP 连接 = 一个插件实例，安装 / 启用 / 配置 / 禁用复用 `plugin_framework` 生命周期与配置 UI
- **工具注册**：连接后动态发现工具，按命名空间注册进 `ToolRegistry`（`mcp__<server>__<tool>`），Schema 经 `bridge.py` 转换，统一走 §6 分级与 §7 治理（默认 write 级，危险需确认）

候选评估：

| MCP 服务 | 判断 | 原因 |
|----------|------|------|
| Web 搜索 / Fetch（Tavily / Brave / Fetch） | ✅ 值得 | 增强问答与媒体资讯检索，补 `WebSearchService` 短板 |
| Bangumi / TMDB 社区 MCP | ✅ 值得 | 动漫 / 影视元数据补充，与 `MediaInfoService` 互补 |
| 官方 Memory MCP（知识图谱） | 🟡 可选 | 可作长程记忆替代后端，但 §5 已有 LanceDB 方案 |
| qBittorrent / Transmission MCP | ❌ 不值得 | 已有原生下载器客户端 |
| Emby / Jellyfin / Plex MCP | ❌ 不值得 | 已有原生 `mediaserver` 客户端 |
| Telegram / Slack MCP | ❌ 不值得 | 已有原生消息客户端 |
| SQLite / 文件系统 MCP | ⚠️ 谨慎 | 安全面大，系统已有 file_index / media_file 服务 |

---

## 文件与目录变更清单

| 路径 | 动作 | 说明 |
|------|------|------|
| `src/app/agent/rag/` | 新增 | 分块 / 向量 / 检索 / 上下文（MVP） |
| `src/app/agent/agents/memory/` | 新增 | `key.py` / `short_term.py` / `long_term.py` / `extractor.py` / `summarizer.py`（§5） |
| `src/app/db/models/agent_memory.py` | 新增 | `agent_conversation` / `agent_message` 表 + Alembic 迁移 |
| `src/app/agent/providers/base.py` | 修改 | 加 `BaseEmbeddingProvider` |
| `src/app/agent/providers/{openai,ollama,gemini}.py` | 修改 | 加 embedding 方法 |
| `src/app/agent/tools/base.py` | 修改 | 加 `level` / `permission` 分级；统一 ToolResult 契约 |
| `src/app/agent/tools/` | 重构 | 按域拆分 schemas/handlers；新增 `context.py`（ToolContext）；拆 system_command；删 resource_filter；新增 `kb_search` 等 MVP 工具 |
| `src/app/domain/ports/` | 新增 | `SearchIntent` 统一模型 + `IntentResolver` / `ChatPort` Protocol（端口下沉） |
| `src/app/services/search_web_service.py` | 删除 | 294 行旧流水线；`WebSearchService`（`system/info.py`）改构建 `SearchContext` 调 orchestrator |
| `src/app/services/search_orchestrator.py` | 修改 | **接线为唯一搜索编排入口**（当前零调用方，死代码激活）；接入 `IntentResolverChain`；归并 `Searcher` 重复组件 |
| `src/app/services/search_message_service.py` | 修改 | `_parse_intent` 归位为 CommandRouter；搜索请求汇入 orchestrator |
| `src/app/agent/agents/search_intent.py` | 修改 | 改造为 `IntentResolver` 端口实现 |
| `src/app/agent/agents/chat_agent.py` | 修改 | 重构为多步工具循环 |
| `src/app/agent/service.py` | 修改 | 组合 RAG + 记忆 + 循环，加流式 |
| `src/app/agent/mcp/` | 新增（可选） | MCP 适配层（server/client/bridge/governance），默认关闭；client 侧经插件框架集成 |
| `src/app/di/builders/*.py` | 修改 | 注册 VectorStore / Retriever / Ingestor / 记忆 |
| `src/app/di/context.py` | 修改 | 增加 Agent RAG 字段 |
| `config/config.yaml.example` | 修改 | 加 `agent:` 配置块 |
| `src/api/routers/` | 新增 | `chat.py` `kb.py`（`mcp.py` 可选） |
| `src/app/agent/context.py` | 新增 | `ContextBuilder`：system + 记忆 + 检索 + 历史 分层组装（预算/优先级） |
| `tests/` | 新增 | RAG / 检索工具 / 工具循环单测；`tests/evals/` 黄金集（意图/检索/工具选择，CI 可选） |
| `docs/architecture.md` | 修改 | 补充 Agent RAG 章节 |

## 配置设计（`config.yaml.example` 新增 `agent:`）

```yaml
agent:
  enabled: true
  default_provider: ollama
  providers:
    ollama:
      api_url: http://localhost:11434
      model: qwen2.5:32b
    openai:
      api_key: ""
      api_url: ""
      model: gpt-4o
  embedding:
    provider: ollama          # ollama | openai | gemini
    model: nomic-embed-text
  vector_store: sqlite        # sqlite | lancedb | qdrant
  sqlite:
    path: ""                  # 留空 = {数据目录}/vectordb/kb.sqlite；相对路径基于数据目录解析（settings.data_path）
  lancedb:
    path: ""                  # 留空 = {数据目录}/vectordb/lancedb；需 AVX2 CPU，不支持则启动报错提示
  qdrant:
    mode: embedded            # embedded | server
    path: ./data/qdrant       # embedded 模式
    url: ""                   # server 模式
  rag:
    chunk_size: 800
    chunk_overlap: 100
    top_k: 6
    rerank_top_k: 3
    namespaces: [media_library, messages, faq, operations]
  fallback: []                 # provider 故障转移链，如 [ollama, openai]，空 = 不启用
  memory:
    max_steps: 8               # 工具循环步数上限
    short_term:
      store: db                # db | redis | memory
      max_tokens: 4000         # 超出触发滚动摘要
      ttl_days: 30
    long_term:
      enabled: false           # opt-in，默认关闭
      top_k: 5
      extraction: on_session_end  # on_turn_end | on_session_end
  mcp:
    enabled: false             # 默认关闭，opt-in
    token: ""                  # 启用后必填
    allow: []                  # 默认空 = 全 deny，需显式放行
    deny: ["media_download.*", "sync.*", "delete.*"]
```

## DI 组装（Builder 侧）

沿用 `app/di/builders/` 分层组装，新增 `agent_builder.py`：

```python
# app/di/builders/agent_builder.py
def build_agent(infra, facades, services) -> AgentObjects:
    vector_store = build_vector_store(settings.agent)   # lancedb / qdrant
    embedding = EmbeddingService(provider=get_embedding_provider())
    retriever = Retriever(vector_store=vector_store)
    ingestor = Ingestor(chunker=Chunker(), embedding=embedding, store=vector_store)
    memory = ConversationStore(           # 短程：DB + 缓存双写 + 滚动摘要
        repo=AgentConversationRepo(), cache=OpenAISessionCache, summarizer=Summarizer(...)
    )
    semantic_memory = SemanticMemory(     # 长程（可选）：LanceDB user_memory
        store=vector_store, enabled=settings.agent.memory.long_term.enabled
    )
    register_kb_search_tool(retriever)                  # 注册 kb_search 工具
    chat_agent = ChatAgent(...)                         # 多步工具循环
    return AgentObjects(vector_store=..., retriever=..., ingestor=..., memory=..., chat_agent=...)
```

事件侧：订阅媒体库 / 订阅 / 插件变更事件，触发 `ingestor` 增量刷新对应命名空间。

---

## 测试策略

- `tests/unit/agent/`：chunker、vector_store（LanceDB 内存 / 临时目录）、retriever（mock embedding）、`kb_search` 工具、工具循环（mock provider）
- `tests/integration/agent/`：RAG 端到端（docs 入库 → 检索 → ChatAgent 回答）
- 沿用现有 `tests/conftest.py`（内存数据库 + mock 配置）
- 校验命令：`uv run ruff check .`、`uv run pyright src/ tests/`、`uv run pytest tests/ -v`

---

## 实施路线

| Phase | 内容 | 交付 |
|-------|------|------|
| 1 | Provider 扩展：`BaseEmbeddingProvider` + 3 提供方 embedding；`VectorStore` 抽象 + **LanceDB** 适配器 | embedding / 向量库可独立使用 |
| 2 | RAG 最小闭环：`chunker → ingestor → retriever` + `kb_search` 工具；docs + 媒体库元数据入库；`kb.py` API | 知识库检索可用 |
| 3 | 搜索/意图统一 + 工具层重构 + ChatAgent 多步循环（async + SSE 流式 + ContextBuilder + provider fallback）+ 短程记忆（DB 持久化 / token 预算 / 滚动摘要 / `memory_clear`）；RBAC + 危险确认；用量日志 | 智能对话 Agent 可用（MVP 17 工具） |
| 4 | （可选）长程语义记忆（LanceDB `user_memory` + 异步事实抽取 + `memory_forget`）；（可选）MCP 适配层 + `mcp.py` API；（可选）Qdrant 适配器；（可选）Langfuse 接入 / evals 黄金集 / 查询改写 | 个性化记忆 / 外部工具互通 / 现代化增强（opt-in） |
| 延后 | 多代理编排（Graph 状态机）/ OpenTelemetry / 独立审批流 | 按需再做 |

每步独立交付，可用 `uv run pytest tests/ -v` 验证。

---

## 附录：现代化对标（2025-2026 主流实践）

| 主流实践（代表） | 本设计 | 状态 |
|------------------|--------|------|
| 原生 function calling + 多步循环（OpenAI / pydantic-ai / LangGraph） | pydantic-ai Agent 循环 | ✅ 已对齐 |
| Agentic RAG：检索即工具，循环内可多次检索 | `kb_search` 在工具循环内可反复调用 | ✅ 已对齐 |
| 混合检索 + 重排（LanceDB / Qdrant 原生） | §3 | ✅ 已对齐 |
| 双层记忆：会话状态(关系库) + 语义记忆(向量)（MemGPT / Mem0） | §5 | ✅ 已对齐 |
| 端口 / 适配器分层、依赖倒置（Clean Architecture） | §0 | ✅ 已对齐 |
| MCP 双向 + 治理 | §9 可选 | ✅ 已对齐 |
| Human-in-the-loop 确认 | 危险操作对话确认 | ✅ 已对齐 |
| 流式输出（SSE token 流） | 见下方补齐 1 | ⚠️ 补齐 |
| 异步优先（async 全链路，FastAPI 契合） | 见下方补齐 2 | ⚠️ 补齐 |
| Provider 故障转移（litellm 式 fallback） | 见下方补齐 3 | ⚠️ 补齐 |
| 评估体系（黄金集 + 回归） | 见下方补齐 4 | ⚠️ 补齐 |
| 可观测性：Langfuse（自托管）/ OTel GenAI 语义约定 | 见下方补齐 5 | ⚠️ 补齐 |
| 上下文工程：ContextBuilder 形式化组装 | 见下方补齐 6 | ⚠️ 补齐 |
| 查询改写 / HyDE（RAG 增强） | — | 🟡 Phase 4 |
| Graph 编排（LangGraph 状态机） | 已明确延后 | 🟡 有规划 |

### 对标补齐项

1. **流式输出**：Chat API 走 SSE（复用项目已有 SSE 模式，如 `/download/events`、`/system/search/progress`）；pydantic-ai `run_stream` 原生支持 token 流 + 工具事件流
2. **异步优先**：Agent 层全链路 async（`AsyncHttpClient` 已存在；pydantic-ai 原生 async）；同步 Service 经 `thread_executor` 桥接，不阻塞事件循环
3. **Provider 故障转移**：`AgentService` 支持 `fallback_providers` 链（主失败→次），配 `agent.fallback: [ollama, openai]`；与现有缓存/重试叠加
4. **评估体系**：`tests/evals/` 黄金集——意图解析准确率（规则 vs LLM 链）、`kb_search` 检索命中率、工具选择正确率；CI 可选跑（非阻塞），防回归
5. **可观测性**：用量日志先行（MVP）；预留 **Langfuse**（自托管）接入点——trace = 一次对话，span = 检索/工具/LLM 调用；不上 OTel 全家桶
6. **上下文工程形式化**：`ContextBuilder` 统一组装 `system prompt + 长程记忆 top-k + kb 检索结果 + 会话历史（含滚动摘要）`，每层独立预算与优先级，替代散落的字符串拼接

## Consequences

### 正面影响

1. 问答类功能具备知识检索能力，回答准确度显著提升（核心价值）
2. 多步工具循环支持复杂任务（检索 → 判断 → 下载 / 订阅）
3. LanceDB 嵌入式零运维，原生混合检索，契合自托管单节点
4. 治理复用 RBAC，危险操作需确认，权限风险可控
5. 范围收敛为 MVP，复杂度与运维成本可控
6. MCP 可选化，避免默认引入安全面

### 负面影响

1. 引入新依赖：`lancedb`（默认）、可选 `qdrant-client` / `mcp`
2. embedding / 向量存储增加资源开销（嵌入式可控）
3. MCP 默认关闭，若需要外部 Agent 互通需手动启用并配置治理

### 缓解措施

- 向量库默认 LanceDB 嵌入式，零运维、可按需升级 Qdrant
- 治理走配置（allow / deny），MCP 默认 `enabled: false` 且 `allow: []`
- 工具循环设 `max_steps` 上限，避免失控
- 所有新增依赖纳入 `pyproject.toml`，勿改 `requirements.txt`；通过 `just safety` / `bandit` 安全检查
