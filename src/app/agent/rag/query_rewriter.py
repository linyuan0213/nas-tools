"""查询改写 — 领域同义词/缩写扩展（提升 FTS 召回）

原理：中文 FTS 用 trigram 硬匹配，"下载器" 与 "qBittorrent/transmission" 互不命中；
对查询做领域术语扩展，把同义词/常用别名并入 FTS 检索词，显著提高召回。
仅作用于全文检索串；向量检索使用原文（保持语义纯净）。
"""

import re

_QUERY_EXPANSION: dict[str, str] = {
    "下载器": "下载器 下载客户端 qbittorrent transmission 客户端 连接",
    "刷流": "刷流 保种 做种 选种 删种 停种",
    "订阅": "订阅 追更 收藏 关注 追剧",
    "转移": "转移 整理 入库 硬链接 移动 刮削",
    "索引器": "索引器 站点 搜索 抓取",
    "通知": "通知 消息 推送 提醒 模板",
    "模板": "模板 消息 格式 内容",
    "qb": "qb qbittorrent",
    "emby": "emby jellyfin 媒体服务器",
    "磁盘": "磁盘 空间 剩余 容量",
    "站点": "站点 pt 分享率 上传量 下载量",
}

_ALIAS_REPLACE: dict[str, str] = {
    "qb": "qBittorrent",
}


def rewrite_query(query: str) -> str:
    """扩展查询串（仅 FTS 用）"""
    if not query:
        return query
    expanded = query
    # 别名替换（如 qb → qBittorrent），仅整词匹配避免破坏词内含别名的查询
    for alias, full in _ALIAS_REPLACE.items():
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        if pattern.search(expanded) and full not in expanded:
            expanded = pattern.sub(full, expanded)
    # 同义词扩展（原文已含同义词则不重复加）
    additions: list[str] = []
    for term, synonyms in _QUERY_EXPANSION.items():
        if term.lower() in query.lower():
            # 只追加查询中尚未出现的扩展词
            missing = [s for s in synonyms.split() if s.lower() not in query.lower()]
            if missing:
                additions.extend(missing)
    if additions:
        expanded = f"{expanded} {' '.join(additions)}".strip()
    return expanded
