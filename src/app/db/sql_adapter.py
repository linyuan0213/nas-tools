"""
SQL 语句适配器模块
处理不同数据库之间的 SQL 语法差异
"""

import re
import threading

from sqlalchemy import Engine

from app.db.database_factory import DatabaseFactory
from app.db.engine import get_engine

# =============================================================================
# SQL 适配器（延迟初始化避免循环导入）
# =============================================================================

_sql_adapter = None
_sql_adapter_lock = threading.Lock()


def get_sql_adapter():
    """获取 SQL 适配器实例 - 线程安全"""
    global _sql_adapter
    if _sql_adapter is None:
        with _sql_adapter_lock:
            if _sql_adapter is None:
                _sql_adapter = SQLAdapter(get_engine())
    return _sql_adapter


class SQLAdapter:
    """SQL 语句适配器类"""

    def __init__(self, engine: Engine | None = None):
        """
        初始化 SQL 适配器

        :param engine: SQLAlchemy Engine，如果为None则从配置中获取
        """
        if engine is None:
            engine = get_engine()
        self.engine = engine
        self.is_sqlite = DatabaseFactory.is_sqlite(engine)
        self.is_mysql = DatabaseFactory.is_mysql(engine)
        self.is_postgresql = DatabaseFactory.is_postgresql(engine)

    def adapt_sql(self, sql: str) -> str:
        """
        适配 SQL 语句到当前数据库类型

        :param sql: 原始 SQL 语句
        :return: 适配后的 SQL 语句
        """
        if not sql or not sql.strip():
            return sql

        sql = sql.strip()

        # 处理 INSERT OR IGNORE
        sql = self._adapt_insert_or_ignore(sql)

        # 处理 DELETE WHERE 1
        sql = self._adapt_delete_where(sql)

        # 处理 REPLACE INTO
        sql = self._adapt_replace_into(sql)

        # 处理 AUTOINCREMENT / AUTO_INCREMENT
        sql = self._adapt_autoincrement(sql)

        # 处理字符串连接
        sql = self._adapt_concat(sql)

        return sql

    def _adapt_insert_or_ignore(self, sql: str) -> str:
        """
        适配 INSERT OR IGNORE 语句

        SQLite: INSERT OR IGNORE INTO
        MySQL: INSERT IGNORE INTO
        PostgreSQL: INSERT INTO ... ON CONFLICT DO NOTHING
        """
        # 匹配 INSERT OR IGNORE INTO table (columns) VALUES (...)
        pattern = r"^INSERT\s+OR\s+IGNORE\s+INTO\s+(.+)$"
        match = re.match(pattern, sql, re.IGNORECASE | re.DOTALL)

        if not match:
            return sql

        rest = match.group(1).rstrip().rstrip(";")

        if self.is_mysql:
            return f"INSERT IGNORE INTO {rest.replace(chr(34), '`')}"
        elif self.is_postgresql:
            return f"INSERT INTO {rest} ON CONFLICT DO NOTHING"
        else:
            # SQLite 保持原样
            return sql

    def _adapt_delete_where(self, sql: str) -> str:
        """
        适配 DELETE WHERE 1 语句

        SQLite/MySQL: DELETE FROM table WHERE 1
        PostgreSQL: DELETE FROM table WHERE TRUE 或直接 DELETE FROM table
        """
        # 匹配 DELETE FROM table WHERE 1
        pattern = r"^(DELETE\s+FROM\s+\w+)\s+WHERE\s+1\s*$"
        match = re.match(pattern, sql, re.IGNORECASE)

        if not match:
            # 也尝试匹配 delete from table where 1
            pattern2 = r"^(delete\s+from\s+\w+)\s+where\s+1\s*$"
            match = re.match(pattern2, sql)
            if not match:
                return sql

        if self.is_postgresql:
            # PostgreSQL 使用 WHERE TRUE 或省略 WHERE 子句
            return f"{match.group(1)} WHERE TRUE"
        else:
            return sql

    def _adapt_replace_into(self, sql: str) -> str:
        """
        适配 REPLACE INTO 语句

        MySQL: REPLACE INTO
        SQLite: REPLACE INTO (也支持)
        PostgreSQL: INSERT INTO ... ON CONFLICT UPDATE
        """
        # REPLACE INTO 在 MySQL 和 SQLite 中都支持
        # PostgreSQL 需要特殊处理
        if not self.is_postgresql:
            return sql

        # PostgreSQL: 将 REPLACE INTO 转换为 INSERT ON CONFLICT
        # 这是一个简化处理，复杂的 REPLACE 可能需要更多逻辑
        pattern = r"^REPLACE\s+INTO\s+(.+)$"
        match = re.match(pattern, sql, re.IGNORECASE)

        if not match:
            return sql

        # 简单返回原 SQL，因为 REPLACE INTO 在 PostgreSQL 中不支持
        # 实际使用时应该使用 UPSERT 语法
        return sql

    def _adapt_autoincrement(self, sql: str) -> str:
        """
        适配 AUTOINCREMENT 关键字

        SQLite: AUTOINCREMENT (只能用于 INTEGER PRIMARY KEY)
        MySQL: AUTO_INCREMENT
        PostgreSQL: SERIAL 或 GENERATED ALWAYS AS IDENTITY
        """
        if self.is_mysql:
            return sql.replace("AUTOINCREMENT", "AUTO_INCREMENT")
        elif self.is_postgresql:
            # PostgreSQL 需要更复杂的处理
            # 简单替换可能在 CREATE TABLE 时不够
            return sql
        else:
            return sql

    def _adapt_concat(self, sql: str) -> str:
        """
        适配字符串连接操作符

        SQLite/PostgreSQL: ||
        MySQL: CONCAT() 或 || (取决于 sql_mode)
        """
        # 目前保持原样，因为大多数情况使用 ORM
        return sql

    def get_limit_clause(self, limit: int, offset: int = 0) -> str:
        """
        获取 LIMIT 子句

        :param limit: 限制数量
        :param offset: 偏移量
        :return: LIMIT 子句
        """
        if offset > 0:
            if self.is_postgresql or self.is_sqlite:
                return f"LIMIT {limit} OFFSET {offset}"
            else:
                # MySQL 也支持 LIMIT offset, count
                return f"LIMIT {offset}, {limit}"
        return f"LIMIT {limit}"

    def get_current_timestamp(self) -> str:
        """
        获取当前时间戳函数

        :return: 数据库特定的当前时间戳函数
        """
        if self.is_postgresql:
            return "CURRENT_TIMESTAMP"
        elif self.is_mysql:
            return "NOW()"
        else:
            return "datetime('now')"

    def get_random_function(self) -> str:
        """
        获取随机数函数

        :return: 数据库特定的随机数函数
        """
        if self.is_postgresql:
            return "RANDOM()"
        elif self.is_mysql:
            return "RAND()"
        else:
            return "RANDOM()"

    def get_date_format(self, column: str, format_str: str) -> str:
        """
        获取日期格式化表达式

        :param column: 列名
        :param format_str: 格式字符串
        :return: 数据库特定的日期格式化表达式
        """
        if self.is_postgresql:
            # PostgreSQL: TO_CHAR
            pg_format = (
                format_str.replace("%Y", "YYYY")
                .replace("%m", "MM")
                .replace("%d", "DD")
                .replace("%H", "HH24")
                .replace("%i", "MI")
                .replace("%s", "SS")
            )
            return f"TO_CHAR({column}, '{pg_format}')"
        elif self.is_mysql:
            # MySQL: DATE_FORMAT
            return f"DATE_FORMAT({column}, '{format_str}')"
        else:
            # SQLite: strftime
            return f"strftime('{format_str}', {column})"


def adapt_sql_for_engine(sql: str, engine: Engine | None = None) -> str:
    """
    全局函数：适配 SQL 语句

    :param sql: 原始 SQL 语句
    :param engine: SQLAlchemy Engine，如果为None则复用全局单例引擎
    :return: 适配后的 SQL 语句
    """
    adapter = SQLAdapter(engine if engine is not None else get_engine())
    return adapter.adapt_sql(sql)
