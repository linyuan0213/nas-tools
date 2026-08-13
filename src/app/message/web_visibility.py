"""内置 Web 消息可见性规则 — 唯一事实源（内存 Python 谓词 + DB SQL 表达式）

规则：全局消息（user_id 为空）所有用户可见 + 本人消息。
两个实现（内存热路径 / DB 查询）都从这里派生，避免两处各写一份导致漂移。
"""


def is_visible(row_user_id, current_user: str) -> bool:
    """Python 谓词：row 的 user_id 是否对 current_user 可见"""
    return not row_user_id or row_user_id == current_user


def visible_sql(column, user_id: str):
    """对应 SQLAlchemy 表达式（与 is_visible 同规则）"""
    return (column == "") | (column == user_id)
