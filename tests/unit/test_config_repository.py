"""ConfigRepository._execute_raw 单元测试"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from app.db.models import CONFIGFILTERRULES
from app.db.repositories.config_repository import ConfigRepository

SQL_FILE = Path(__file__).parents[2] / "src/app/db/data/init_filter.sql"


class _TestableConfigRepository(ConfigRepository):
    """测试用 Repository，复用同一个 session 避免事务隔离问题。"""

    def __init__(self, session):
        self._test_session = session
        super().__init__()

    @contextmanager
    def session(self):
        yield self._test_session


@pytest.fixture
def repo(db_session):
    return _TestableConfigRepository(db_session)


class TestExecuteRaw:
    def test_sql_with_non_capturing_group_executes(self, repo, db_session):
        """含 (?:…) 非捕获分组的 SQL 不应被 text() 误解析为绑定参数"""
        repo._execute_raw("INSERT INTO CONFIG_FILTER_GROUP (ID,GROUP_NAME,IS_DEFAULT,NOTE) VALUES (1002,'中字','1','')")
        repo._execute_raw(
            "INSERT INTO CONFIG_FILTER_RULES (ID,GROUP_ID,ROLE_NAME,PRIORITY,INCLUDE,EXCLUDE,SIZE_LIMIT,NOTE) "
            "VALUES (10034,'1002','4k中字','1','(?:简体|繁體|中字)\n4k|2160p','','1,30','')"
        )
        row = db_session.query(CONFIGFILTERRULES).filter_by(ID=10034).first()
        assert row is not None
        assert "(?:简体" in row.INCLUDE

    def test_init_filter_sql_statements_execute(self, repo, db_session):
        """init_filter.sql 全部 INSERT 语句应可逐条执行（回归：bind parameter '简体'）"""
        count = 0
        for stmt in SQL_FILE.read_text(encoding="utf-8").split(";\n"):
            stmt = stmt.strip()
            if stmt and "INSERT" in stmt.upper():
                repo._execute_raw(stmt)
                count += 1
        assert count > 0
        assert db_session.query(CONFIGFILTERRULES).filter_by(GROUP_ID=1002).count() == 3
