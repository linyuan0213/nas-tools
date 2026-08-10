# Agent RAG MVP 详细设计（实施级）

> 配套文档：`docs/decisions/ADR-020-agent-rag-mcp-architecture.md`（架构决策）
> 本文档是 **Phase 1-3（MVP）** 的实施级设计：文件、类、签名、接线顺序、迁移、API 契约、测试。
> 范围之外（Phase 4）：长程记忆、MCP、Qdrant、Langfuse、Graph 编排。

---

## 0. 实施总览与依赖顺序

```
Phase 1: providers 扩展 + VectorStore(LanceDB)      → 纯新增，零风险
Phase 2: RAG Pipeline + kb_search 工具 + kb API      → 依赖 Phase 1
Phase 3: 搜索/意图统一 + 工具层重构 + ChatAgent 循环
         + 短程记忆(DB) + chat API                   → 依赖 Phase 1/2（kb_search）
```

每一步验收：`uv run ruff check .` && `uv run pyright src/ tests/` && `uv run pytest tests/ -v`

**新依赖**（`uv add`）：`lancedb`；dev 组加 `import-linter`（可选）。不引入其他库（FTS/混合检索用 LanceDB 原生）。

---

## 1. 配置层（Phase 1 前置）

`config/config.yaml.example` 新增 `agent:` 块（与 ADR 配置设计一致），运行时经 `settings.get("agent")` 读取（现有模式，无需改 pydantic-settings）：

```yaml
agent:
  enabled: false                # 默认关闭，用户显式开启
  default_provider: ollama
  fallback: []                  # provider 故障转移链，如 [ollama, openai]
  providers:
    ollama: { api_url: http://localhost:11434, model: qwen2.5:32b }
    openai: { api_key: "", api_url: "", model: gpt-4o }
  embedding:
    provider: ollama            # ollama | openai | gemini
    model: nomic-embed-text
  vector_store: lancedb
  lancedb: { path: ./data/vectordb }
  rag:
    chunk_size: 800
    chunk_overlap: 100
    top_k: 6
    rerank_top_k: 3
    namespaces: [media_library, messages, faq, operations]
  memory:
    max_steps: 8
    short_term: { store: db, max_tokens: 4000, ttl_days: 30 }
```

`src/app/agent/config.py` 扩展：

```python
@dataclass
class EmbeddingConfig:
    provider: str
    model: str

def get_embedding_config() -> EmbeddingConfig | None: ...
def get_fallback_providers() -> list[ProviderConfig]: ...
def get_rag_config() -> dict: ...        # chunk_size/top_k/namespaces...
def get_memory_config() -> dict: ...     # max_steps/short_term...
```

---

## 2. Provider 扩展（Phase 1）

### `src/app/agent/providers/base.py`（修改）

```python
class BaseEmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int: ...           # 首次 embed 后缓存，不硬编码

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @abstractmethod
    def is_available(self) -> bool: ...
```

### 各 provider 实现要点

| Provider | API | 备注 |
|----------|-----|------|
| `ollama.py` | `POST {api_url}/api/embed`，body `{model, input: [...]}` | 批量一次请求 |
| `openai.py` | `POST {api_url}/v1/embeddings`，body `{model, input}` | 复用现有 client |
| `gemini.py` | `embedContent`（批量 `batchEmbedContents`） | 复用现有 client |

- 复用现有 `ProviderConfig`（api_key/api_url/proxy/timeout）
- embedding 结果经 `lru_cache_with_ttl` 缓存（`EmbeddingService` 层做，见 §3）
- `AgentService._create_provider` 旁新增 `_create_embedding_provider(config)`

---

## 3. RAG Pipeline（Phase 2，`src/app/agent/rag/`）

模块结构（已实现部分标注 ✅）：

```
rag/
├── models.py           ✅ Chunk / ScoredChunk
├── chunker.py          ✅ MarkdownChunker（标题分段 + 滑动窗口）
├── embedding.py        ✅ EmbeddingService（分批 + 缓存）
├── vector_store.py     ✅ VectorStore ABC（不导入任何实现，防循环导入）
├── sqlite_vec_store.py ✅ SQLiteVecStore（默认）
├── lancedb_store.py    ✅ LanceDBStore（可选，仅工厂惰性加载）
├── factory.py          ✅ create_vector_store + resolve_store_path + AVX2 预检
├── ingestor.py         # 知识库采集 + 索引构建 + 增量更新
└── retriever.py        # 混合检索 + 截断重排
```

### 3.1 数据模型（`rag/models.py`）

```python
@dataclass(frozen=True)
class Chunk:
    id: str                 # f"{namespace}:{source}:{seq}" 的 sha1
    text: str
    namespace: str          # faq / messages / media_library / operations
    source: str             # 文件路径或业务来源标识
    metadata: dict          # 标题、更新时间等

@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
```

### 3.2 `rag/vector_store.py`

```python
class VectorStore(ABC):
    @abstractmethod
    def upsert(self, namespace: str, chunks: list[Chunk], vectors: list[list[float]]) -> int: ...
    @abstractmethod
    def delete_by_source(self, namespace: str, source: str) -> int: ...   # 增量刷新用
    @abstractmethod
    def hybrid_search(self, query: str, vector: list[float],
                      namespace: str | None, top_k: int) -> list[ScoredChunk]: ...
    @abstractmethod
    def count(self, namespace: str | None = None) -> int: ...
```

**`SQLiteVecStore`（默认）**实现：
- 单文件 `{settings.data_path}/vectordb/kb.sqlite`（路径解析规则：配置留空 → 数据目录默认；相对路径 → 基于 `settings.data_path`；绝对路径 → 原样），三张表：
  - `kb_chunks(id TEXT PK, namespace, source, text, metadata JSON)` — 主表
  - `kb_fts` — FTS5 虚表，`tokenize='trigram'`（中文 CJK 支持，SQLite≥3.34），content 关联主表
  - `kb_vec` — `vec0` 虚表（`id TEXT PK, vector float[dim]`），维度运行时确定（重开库时从存量向量恢复）
- 混合检索：FTS5 `bm25()` top N + vec KNN top N → Python RRF 融合（k=60）→ top_k
- **降级模式**：embedding 不可用时 chunk 按纯文本入库（只进 FTS），查询 `vector=None` 走纯 BM25；FTS 查询构建 = 拉丁整词 + CJK 3 字滑窗 OR 连接（trigram 短语要求连续匹配，整句查询会零命中）
- 无 SIMD 要求，全 CPU 可跑（实测依据：LanceDB 在无 AVX2 机器 SIGILL）

**`LanceDBStore`（可选加速）**：import 时 try/except + 运行时探测；不可用时 `RuntimeError("lancedb 需要 AVX2 CPU，请改用 vector_store: sqlite")`。每 namespace 一张表，`create_fts_index("text")`，原生 hybrid + `RRFReranker`。

**`QdrantStore`（可选）**：server 模式优先；local 模式仅小规模。无原生 BM25，hybrid 退化为纯向量检索（文档注明）。

### 3.3 `rag/chunker.py`

```python
class MarkdownChunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 100): ...
    def split(self, text: str, source: str, namespace: str) -> list[Chunk]: ...
    # 按 ## 标题切段 → 超长按滑动窗口再切 → 保留标题路径进 metadata
```

### 3.4 `rag/embedding.py`

```python
class EmbeddingService:
    def __init__(self, provider: BaseEmbeddingProvider, batch_size: int = 32): ...
    @property
    def dimension(self) -> int: ...
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # 分批 + lru_cache_with_ttl 缓存（key=sha1(model+text)）
```

### 3.5 `rag/ingestor.py`

```python
class KnowledgeIngestor:
    def __init__(self, chunker, embedding, store, loaders: list[KnowledgeLoader]): ...

class KnowledgeLoader(ABC):                   # 每来源一个 loader
    namespace: str
    @abstractmethod
    def load(self) -> Iterable[tuple[str, str]]: ...   # (source, text)
```

MVP loaders：
| Loader | namespace | 内容 |
|--------|-----------|------|
| `DocsLoader` | `faq` | `docs/*.md`（排除 decisions/assets） |
| `MessageTemplateLoader` | `messages` | `app/message/templates.DEFAULT_MESSAGE_TEMPLATES` |
| `MediaLibraryLoader` | `media_library` | 媒体库条目（标题/年份/类型/简介），经 `MediaLibraryService` |
| `OperationsLoader` | `operations` | `docs/` 中配置/运维类文档子集 |

- 全量 `reindex(namespace?)`；增量：`refresh_source(namespace, source)`（delete_by_source + upsert）
- 事件接线：订阅媒体库同步完成 / 插件配置变更事件 → 调 `refresh_source`（`agent_builder` 中注册）

### 3.6 `rag/retriever.py`

```python
class Retriever:
    def __init__(self, embedding: EmbeddingService, store: VectorStore, cfg: dict): ...
    def search(self, query: str, namespace: str | None = None) -> RetrievalResult:
        # embed_query → store.hybrid_search(top_k) → 截断 rerank_top_k
        # 返回 {chunks: [...], citations: [{source, snippet}], confidence}
```

### 3.7 `kb_search` 工具（Phase 2 交付物之一）

Schema（`tools/schemas/kb.py`）：`{query: str, namespace?: str}`，level=read。
Handler：调 `Retriever.search`，返回 `{chunks: [...], citations: [...]}`，超长截断（每 chunk ≤500 字符）。

### 3.8 API（`src/api/routers/kb.py`）

- `POST /agent/kb/reindex {namespace?}` — 全量/分域重建（管理员）
- `GET /agent/kb/status` — 各 namespace 文档数/更新时间

---

## 4. Domain 端口（Phase 3 前置，`src/app/domain/interfaces/`）

沿用现有 `domain/interfaces/` 约定（不放 `domain/ports/`）：

```python
# domain/interfaces/intent.py
class SearchIntent(BaseModel):
    keywords: str = ""
    media_type: str | None = None      # movie | tv | anime
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    raw_text: str = ""
    is_specific: bool = False

class IntentResolver(Protocol):
    def resolve(self, text: str) -> SearchIntent: ...

# domain/interfaces/chat.py
class ChatPort(Protocol):
    @property
    def ready(self) -> bool: ...
    def ask(self, question: str, session_id: str, user_id: str) -> str: ...
```

改造点：
- `SearchIntentAgent` → 实现 `IntentResolver`（`parse()` 改名/适配为 `resolve()`）
- `media/parser/llm.py` → 删除 `from app.agent...` import，`LLMParser` 只依赖 `BaseParser`；`MediaRecognizer` 在 `facades_builder` 中包装为 `BaseParser` 注入
- `system/info.py` / `search_web_service.py` 的 `SearchIntentAgent` 类型注解 → `IntentResolver | None`
- `search_message_service.py` 的 `AgentService` 依赖 → `ChatPort`
- import-linter 契约：禁止 `app.services`/`app.media`/`app.domain` import `app.agent`；插件豁免

---

## 5. 搜索/意图统一（Phase 3）

### 5.1 IntentResolverChain（`src/app/services/search_intent_resolver.py`）

```python
class IntentResolverChain:
    def __init__(self, llm_resolver: IntentResolver | None): ...
    def resolve(self, text: str) -> SearchIntent:
        # 1. 规则：StringUtils.get_keyword_from_string(text) 6 元组 → SearchIntent
        # 2. LLM 增强（llm_resolver 非空且规则结果 is_specific=False 时）：
        #    llm_resolver.resolve(text)，仅填充规则未识别的字段，不覆盖
        # 3. 归一化返回
```

### 5.2 接线 SearchOrchestrator（当前死代码激活）

`search_orchestrator.py` 修改：
- 构造函数加 `intent_resolver: IntentResolver`
- `_identify_media` 改为：先 `intent_resolver.resolve(ctx.keyword)` → 用 SearchIntent 构造 `media_service.get_media_info` 入参（替代内部 `get_keyword_from_string` 直调）
- 归并 `Searcher` 重复组件：orchestrator 复用 `SearchResultDeduplicator` / `SearchResultProcessor.sort_results` / `persist_results`（删除自己的 `_sort_results` 私有重复实现，统一排序键）

### 5.3 删除旧流水线

- `system/info.py` `WebSearchService.__init__`：默认 `search_fn` 从 `partial(search_medias_for_web, ...)` 改为调 orchestrator（构建 `SearchContext`，`search_type=SearchType.WEB`，`persist=True`）；保持 `WebSearchResultDTO` 契约不变
- 删除 `src/app/services/search_web_service.py` 整文件（含 `_MEDIA_IDENT_CACHE`——识别缓存改挂 `MediaService` 层或 cache_system）
- `search_message_service.py`：`_parse_intent` 保留为 CommandRouter（DOWNLOAD/ASK/SUBSCRIBE），其搜索路径改走 orchestrator；ASK 路径走 `ChatPort`

### 5.4 Searcher 收敛

`search_service.py`：保留 `search_medias`（单关键词执行）、`search_one_media`（订阅流程，MVP 不动）；删除/移交与 orchestrator 重复的排序/入库逻辑。

---

## 6. 工具层重构（Phase 3）

### 6.1 `tools/base.py`（修改）

```python
class ToolLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    DANGEROUS = "dangerous"

@dataclass
class ToolResult:
    success: bool
    data: dict | list | None = None     # 恒结构化，禁裸 str
    error: str = ""
    need_confirm: bool = False          # dangerous 工具首次调用返回 True

class BaseTool(ABC):
    name: str
    description: str
    parameters: dict
    level: ToolLevel = ToolLevel.READ
    permission: str = ""                # 映射 RBAC 权限码
```

### 6.2 `tools/context.py`（新增）

```python
@dataclass(frozen=True)
class ToolContext:
    media_service: MediaService
    search_service: SearchService       # 门面，内含 orchestrator
    downloader_core: DownloaderCore
    download_service: DownloadService
    subscribe_service: SubscribeService
    media_library_service: MediaLibraryService
    filetransfer_service: FileTransferService
    scheduler_service: SchedulerService
    system_info_service: SystemInfoService
    retriever: Retriever
    conversation_store: ConversationStore
    rbac_service: RBACService
    event_bus: EventBus
    # 仅 MVP 17 工具所需的最小集合，非全量 23 个
```

### 6.3 执行器（`tool_executor.py` 重写）

- 注册表：`name → (tool_schema, handler: Callable[[ToolContext, ...], ToolResult])`
- 执行顺序：参数校验 → RBAC 鉴权（`tool.permission`，经 `rbac_service` + 当前 user）→ `level==DANGEROUS` 且未带 `confirmed=True` → 返回 `ToolResult(need_confirm=True)` → 调 handler
- 删除 `set_tool_executor` 后门：`ChatAgent` 直接持有 `ToolExecutor`，`AgentService` 不再经手

### 6.4 MVP 17 工具 → 服务方法映射

| 工具 | level | 服务方法 |
|------|-------|---------|
| `media_search` | read | `SearchService.search(query)`（orchestrator，session_id=`agent:{user}`） |
| `media_detail` | read | `MediaInfoService.get_media_info_detail` |
| `kb_search` | read | `Retriever.search` |
| `download_add_link` | write | `DownloadService.download_from_link` |
| `media_download` | write | `Searcher.search_one_media`（SearchType.API） |
| `download_list` | read | `DownloadService.get_downloading_with_media_info` |
| `download_control` | write/dangerous(remove) | `DownloaderCore.start/stop/recheck/delete_torrents` |
| `downloader_status` | read | `DownloaderCore.get_status` + `get_free_space` |
| `subscribe_add` | write | `SubscribeService.add_rss_subscribe` |
| `subscribe_list` | read | `get_subscribe_movies` / `get_subscribe_tvs` + 缺失集 |
| `subscribe_delete` | write(确认) | `SubscribeService.delete_subscribe` |
| `library_check` | read | `DownloaderCore.check_exists_medias` + `MediaLibraryService` |
| `transfer_run` | write | `FileTransferService.transfer_manually` |
| `scheduler_list` | read | `SchedulerService.get_jobs` |
| `scheduler_run` | write | `SchedulerService.run_job` |
| `system_status` | read | `SystemInfoService.get_system_info` |
| `memory_clear` | write | `ConversationStore.clear(key)` |

文件组织：`tools/schemas/{media,download,subscribe,library,transfer,scheduler,system,memory,kb}.py` + `tools/handlers/` 同名对应。

---

## 7. 短程记忆（Phase 3）

### 7.1 DB 模型（`src/app/db/models/agent_memory.py`）

```python
class AgentConversation(Base):
    __tablename__ = "agent_conversation"
    id: Mapped[int]              # 主键
    user_id: Mapped[str]
    channel: Mapped[str]         # web | telegram | wechat | slack ...
    session_id: Mapped[str]
    summary: Mapped[str]         # 滚动摘要
    token_usage: Mapped[int]
    created_at / updated_at
    # 唯一约束 (user_id, channel, session_id)

class AgentMessage(Base):
    __tablename__ = "agent_message"
    id / conversation_id(FK, cascade delete) / role / content / tool_calls(JSON, nullable) / tokens / created_at
```

- Alembic 迁移：`uv run alembic revision --autogenerate -m "add agent memory tables"`（走 `scripts/` 现有流程）
- 仓储适配器：`db/repositories/agent_conversation_repository.py`（沿用现有 repository 适配器模式）

### 7.2 `agents/memory/`（新增）

```python
# key.py
@dataclass(frozen=True)
class MemoryKey:
    user_id: str
    channel: str
    session_id: str

# short_term.py
class ConversationStore:
    def __init__(self, repo, cache: OpenAISessionCache, summarizer, max_tokens: int): ...
    def load(self, key: MemoryKey) -> list[dict]: ...        # cache miss → DB → 回写缓存
    def append(self, key, role: str, content: str, tokens: int, tool_calls=None): ...
    def history_for_llm(self, key) -> list[dict]: ...
        # summary 消息（若有）+ 最近消息，按 max_tokens 截断；超预算触发 summarize
    def clear(self, key: MemoryKey): ...                     # 删 DB + 缓存

# summarizer.py
class Summarizer:
    def __init__(self, svc): ...   # 依赖 AgentService.chat，低温度
    def summarize(self, old_summary: str, messages: list[dict]) -> str: ...
```

---

## 8. ChatAgent 与上下文组装（Phase 3）

### 8.1 `src/app/agent/context.py`（新增）

```python
class ContextBuilder:
    def __init__(self, memory: ConversationStore, retriever: Retriever | None): ...
    def build(self, key: MemoryKey, question: str) -> list[dict]:
        # system prompt（含工具使用规则 + "知识类问题无 kb_search 时禁止编造"）
        # + [summary] + 历史（token 预算内）
        # 检索不走自动注入——由 LLM 经 kb_search 工具自主调用（Agentic RAG）
```

### 8.2 `chat_agent.py`（重构）

- 基于 `pydantic_ai.Agent`：tools 从 `ToolRegistry.list_tools()` 动态注册（schema 转换）；`max_steps` 限制循环
- 工具调用 → `ToolExecutor.execute(name, args, user)`；`need_confirm=True` → 中断循环，返回确认请求给前端
- `chat_with_tools` 保留同名签名（消息渠道兼容），内部走新循环；`#清除` 魔法字符串删除，改 `memory_clear`
- 流式：`run_stream` → 逐 chunk yield；工具调用事件单独 yield `{"type":"tool_call",...}`
- Fallback：主 provider 异常 → 按 `agent.fallback` 链重试（每 provider 一次，叠加缓存/重试）
- 异步：对外暴露 async 接口；同步 Service 经 `thread_executor` 包装调用

---

## 9. API（Phase 3，`src/api/routers/chat.py`）

| 端点 | 说明 |
|------|------|
| `POST /agent/chat` | SSE 流式对话：请求 `{question, session_id}`，响应 `text/event-stream`：`token` / `tool_call` / `confirm_required` / `done` 事件 |
| `POST /agent/chat/confirm` | 危险操作确认：`{session_id, confirm_token, approved}` → 继续执行 |
| `POST /agent/chat/clear` | 清会话（等价 `memory_clear`） |

- 沿用 `AppContext` Depends 模式；SSE 参考现有 `/download/events` 实现
- 权限：登录即可（chat）；dangerous 工具经确认流

---

## 10. DI 接线（`src/app/di/builders/`）

新增 `agent_builder.py`，调用顺序（`context_builder.py` 内）：

```
build_infrastructure()
→ build_facades():  MediaRecognizer(包装为 BaseParser)、SearchIntentAgent(实现 IntentResolver)
→ build_services(): 注入端口（llm_parser / intent_resolver / chat_port）
                    SearchOrchestrator 接线（intent_resolver 注入）
→ build_agent(infra, facades, services):
    embedding_provider → EmbeddingService
    LanceDBStore → Retriever / KnowledgeIngestor（+事件订阅）
    AgentConversationRepo → ConversationStore → ContextBuilder
    ToolContext → ToolExecutor → ChatAgent
→ build_coordinators(): 删除 ToolExecutor 旧装配与 set_tool_executor 后门
→ AppContext 增加字段：retriever / ingestor / conversation_store / chat_agent / tool_executor
```

---

## 11. 测试计划

| 层 | 用例 |
|----|------|
| unit | chunker 边界（空文档/超长/标题嵌套）；LanceDBStore upsert/hybrid_search（临时目录）；IntentResolverChain（规则优先/LLM 补充/LLM 失败降级）；ToolResult 契约；ToolExecutor 分级与确认流；ConversationStore（内存 DB）预算截断与摘要触发 |
| integration | 检索闭环：docs 入库 → kb_search 返回引用；搜索闭环：`SearchContext` → orchestrator → 入库（mock indexer）；chat 闭环：mock provider 多步工具循环 |
| evals（可选 CI） | `tests/evals/`：意图黄金集（20 条）、工具选择黄金集（17 工具各 1-2 条） |

---

## 12. 风险与注意

1. **lancedb 原生 FTS 中文分词**：默认 tokenizer 对中文一般；MVP 可接受，后续可换 jieba/自定义
2. **orchestrator 激活风险**：死代码可能位过期——Phase 3 第一步先跑通其单测/对齐 `Searcher` 接口，再切换调用方
3. **插件兼容**：autosignin/autosub 直接 new `QuestionAnswerAgent(svc)`/`translate_to_zh`——AgentService 门面签名保持不变，插件零改动
4. **消息渠道兼容**：`chat_with_tools(question, session_id)` 签名保持；session_id 内部包装为 MemoryKey(channel=渠道, user_id=...)
5. **SQLite 默认部署**：agent 表随主库（SQLite/MySQL/PG）走 `database_factory`，无额外配置
