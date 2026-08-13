"""Agent evals 运行器 — 黄金集回归

- intent: 意图解析黄金集（规则链，纯确定性，CI 常跑）
- retrieval: 检索黄金集（混合检索命中断言，需建库 + mock embedding）
- tool_select: 工具选择黄金集（基于规则的启发式代理，真实对话由 LLM 决策）

运行：`uv run pytest tests/evals/ -v`
"""

from dataclasses import dataclass

import pytest

from app.agent.providers.base import BaseEmbeddingProvider, ProviderConfig
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.models import Chunk
from app.agent.rag.retriever import Retriever
from app.agent.rag.sqlite_vec_store import SQLiteVecStore
from app.services.search_intent_resolver import IntentResolverChain


@dataclass(frozen=True)
class IntentCase:
    query: str
    keywords_contains: tuple[str, ...] = ()
    media_type: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    is_specific: bool | None = None


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    namespace: str | None = None
    expected_source: str = ""
    expected_keyword: str = ""


@dataclass(frozen=True)
class ToolSelectCase:
    question: str
    expected_tool: str


INTENT_CASES: list[IntentCase] = [
    IntentCase("电影 流浪地球 2019", keywords_contains=("流浪地球",), year=2019, is_specific=True),
    IntentCase(
        "权力的游戏 第2季 第3集",
        keywords_contains=("权力的游戏",),
        media_type="tv",
        season=2,
        episode=3,
        is_specific=True,
    ),
    IntentCase(
        "动漫 进击的巨人 第一季",
        keywords_contains=("进击的巨人",),
        media_type="tv",
        season=1,
        is_specific=True,
    ),
    IntentCase("三体", keywords_contains=("三体",), is_specific=False),
    IntentCase("看电影", keywords_contains=("看电影",), is_specific=False),
    IntentCase("流浪地球", keywords_contains=("流浪地球",), is_specific=False),
    IntentCase("电视剧 白夜追凶 2022", keywords_contains=("白夜追凶",), media_type="tv", year=2022, is_specific=True),
    IntentCase("宫崎骏 电影", keywords_contains=("宫崎骏",), is_specific=False),
    IntentCase("", keywords_contains=(), is_specific=False),
]

RETRIEVAL_CASES: list[RetrievalCase] = [
    RetrievalCase("如何配置下载器", "faq", "docs/downloaders.md", "下载器"),
    RetrievalCase("qb 连接参数", "faq", "docs/downloaders.md", "qBittorrent"),
    RetrievalCase("下载器 qBittorrent 连接参数", "faq", "docs/downloaders.md", "qBittorrent"),
    RetrievalCase("刷流规则怎么配", "faq", "docs/sites.md", "刷流"),
    RetrievalCase("下载完成通知模板", "messages", "message_template/download_start", "模板"),
    RetrievalCase("电影订阅最佳实践", "faq", "docs/subscription.md", "订阅"),
    RetrievalCase("媒体库整理转移", "faq", "docs/library_management.md", "整理"),
    RetrievalCase("索引器添加", "faq", "docs/indexers.md", "索引器"),
]

TOOL_SELECT_CASES: list[ToolSelectCase] = [
    ToolSelectCase("当前系统状态怎么样", "system_status"),
    ToolSelectCase("我在下载什么", "download_list"),
    ToolSelectCase("下载器在线吗", "downloader_status"),
    ToolSelectCase("订阅 流浪地球", "subscribe_add"),
    ToolSelectCase("取消订阅 权力的游戏", "subscribe_delete"),
    ToolSelectCase("库里有没有 流浪地球", "library_check"),
    ToolSelectCase("怎么配置刷流规则", "kb_search"),
    ToolSelectCase("下载这个磁力链接", "download_add_link"),
    ToolSelectCase("有哪些定时任务", "scheduler_list"),
]


def rule_route_tool(question: str) -> str:
    """基于规则的启发式路由（eval 用；真实对话由 LLM 决策）"""
    q = question.lower()
    if any(k in q for k in ("取消订阅", "退订", "删除订阅")):
        return "subscribe_delete"
    if any(k in q for k in ("订阅", "追更")):
        return "subscribe_add"
    if any(k in q for k in ("怎么配置", "怎么用", "什么意思", "报错", "模板", "文档")):
        return "kb_search"
    if any(k in q for k in ("磁力", "链接", "种子 url")):
        return "download_add_link"
    if any(k in q for k in ("下载什么", "下载进度", "下载到哪")):
        return "download_list"
    if any(k in q for k in ("下载器在线", "下载器状态", "磁盘还剩")):
        return "downloader_status"
    if any(k in q for k in ("库里有", "缺哪集")):
        return "library_check"
    if "定时任务" in q or "调度" in q:
        return "scheduler_list"
    if any(k in q for k in ("系统状态", "系统负载", "cpu")):
        return "system_status"
    return "media_search"


class _EvalEmbedding(BaseEmbeddingProvider):
    def __init__(self):
        super().__init__(ProviderConfig(name="eval", api_key="", api_url="", model="m"), "m")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [[float(hash(t) % 1000) / 1000.0, 0.1, 0.2] for t in texts]
        if vectors and self._dimension is None:
            self._dimension = 3
        return vectors

    def is_available(self):
        return True


_DOCS = {
    "docs/downloaders.md": (
        "下载器配置 下载器设置：添加和管理下载客户端。qBittorrent（推荐）与 Transmission "
        "的连接参数：地址、用户名、密码、下载目录。"
    ),
    "docs/subscription.md": "电影订阅最佳实践 添加订阅：标题、年份、季。追更订阅会在新资源发布时自动搜索下载。",
    "docs/library_management.md": (
        "媒体库整理 整理转移：把下载目录的文件按类型、年份、季集整理入库到媒体库，支持硬链接与移动。"
    ),
    "docs/indexers.md": "索引器 索引器负责连接 PT 站点搜索资源，可配置多个索引器提升搜索速度。",
    "docs/sites.md": "站点与刷流 刷流中心：刷流规则（选种/删种/停种）与刷流任务（引用规则，Cron 周期执行）。",
    "docs/transfer.md": "转移任务 手动整理：源目录到目标目录，操作类型 copy/link/move。",
}


@pytest.fixture
def indexed_retriever(tmp_path):
    store = SQLiteVecStore(str(tmp_path / "eval_kb.sqlite"))
    embedding = EmbeddingService(_EvalEmbedding())
    retriever = Retriever(embedding, store, top_k=6, rerank_top_k=3)
    for source, text in _DOCS.items():
        chunk = Chunk(id=source, text=text, namespace="faq", source=source)
        vec = embedding.embed_query(text)
        assert vec is not None
        store.upsert("faq", [chunk], [vec])
    msg_chunk = Chunk(
        id="message_template/download_start",
        text="下载开始模板：标题 {标题} 开始下载，内容含站点/大小/质量。",
        namespace="messages",
        source="message_template/download_start",
    )
    vec = embedding.embed_query(msg_chunk.text)
    assert vec is not None
    store.upsert("messages", [msg_chunk], [vec])
    yield retriever
    store.close()


class TestIntentEval:
    @pytest.mark.parametrize("case", INTENT_CASES, ids=lambda c: c.query[:20])
    def test_intent_golden(self, case):
        intent = IntentResolverChain().resolve(case.query)
        for kw in case.keywords_contains:
            assert kw in intent.keywords, f"{case.query!r}: 期望关键词 {kw!r} 未命中"
        if case.media_type is not None:
            assert intent.media_type == case.media_type, f"{case.query!r}: 类型不匹配"
        if case.year is not None:
            assert intent.year == case.year, f"{case.query!r}: 年份不匹配"
        if case.season is not None:
            assert intent.season == case.season, f"{case.query!r}: 季不匹配"
        if case.episode is not None:
            assert intent.episode == case.episode, f"{case.query!r}: 集不匹配"
        if case.is_specific is not None:
            assert intent.is_specific == case.is_specific, f"{case.query!r}: specific 标志不匹配"


class TestRetrievalEval:
    @pytest.mark.parametrize("case", RETRIEVAL_CASES, ids=lambda c: c.query[:20])
    def test_retrieval_golden(self, indexed_retriever, case):
        result = indexed_retriever.search(case.query, case.namespace)
        if not case.expected_source:
            assert not result.hit or not result.citations
            return
        assert result.hit, f"{case.query!r}: 未命中任何文档"
        sources = [c["source"] for c in result.citations]
        msg = f"{case.query!r}: 期望来源 {case.expected_source} 未命中，实际 {sources[:3]}"
        assert case.expected_source in sources, msg


class TestToolSelectEval:
    @pytest.mark.parametrize("case", TOOL_SELECT_CASES, ids=lambda c: c.question[:16])
    def test_tool_select_golden(self, case):
        assert rule_route_tool(case.question) == case.expected_tool
