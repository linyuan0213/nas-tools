"""Agent 知识库 Router — RAG 索引管理与检索"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_knowledge_ingestor, get_retriever, require_permission
from app.agent.rag.namespaces import Namespace
from app.utils.response import fail, success

router = APIRouter()


class ReindexRequest(BaseModel):
    namespace: str | None = None


class SearchRequest(BaseModel):
    query: str
    namespace: str | None = None


@router.post("/kb/status")
def kb_status(
    _: Any = Depends(require_permission("agent:view")),
    ingestor: Any = Depends(get_knowledge_ingestor),
):
    """知识库状态：各命名空间块数"""
    if ingestor is None:
        return fail(msg="Agent RAG 未启用")
    return success(data={"namespaces": ingestor.status()})


@router.post("/kb/reindex")
def kb_reindex(
    req: ReindexRequest,
    _: Any = Depends(require_permission("agent:manage")),
    ingestor: Any = Depends(get_knowledge_ingestor),
):
    """重建知识库索引（可指定命名空间）"""
    if ingestor is None:
        return fail(msg="Agent RAG 未启用")
    if req.namespace and not Namespace.valid(req.namespace):
        return fail(msg=f"未知命名空间: {req.namespace}")
    stats = ingestor.reindex(req.namespace)
    return success(data={"indexed": stats})


@router.post("/kb/search")
def kb_search(
    req: SearchRequest,
    _: Any = Depends(require_permission("agent:view")),
    retriever: Any = Depends(get_retriever),
):
    """知识库检索（调试用，正常由 Agent 工具循环调用）"""
    if retriever is None:
        return fail(msg="Agent RAG 未启用")
    if req.namespace and not Namespace.valid(req.namespace):
        return fail(msg=f"未知命名空间: {req.namespace}")
    result = retriever.search(req.query, req.namespace)
    return success(data={"hit": result.hit, "citations": result.citations})
