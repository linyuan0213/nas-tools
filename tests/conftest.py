"""测试全局配置与 Fixtures"""

import os
import tempfile

# 必须在导入任何项目模块之前设置 — 使用临时文件避免污染仓库
_test_config = os.path.join(tempfile.gettempdir(), "nexus_media_test_config.yaml")
os.environ["NEXUS_MEDIA_CONFIG"] = _test_config
os.environ["DATABASE__TYPE"] = "sqlite"
# 隔离应用数据库：默认指向 data/user.db，全量测试会 drop_all 真实库，这里强制用临时文件
os.environ["DATABASE__SQLITE_PATH"] = os.path.join(
    tempfile.gettempdir(), "nexus_media_test_user.db"
)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    """提供内存 SQLite 引擎"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(engine):
    """每个测试函数独立的数据库会话"""
    from app.db.models import Base

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def mock_config(monkeypatch):
    """提供隔离的 mock 配置"""

    class _MockConfig:
        def __init__(self):
            self._config = {
                "app": {"web_host": "0.0.0.0", "web_port": 3000, "rmt_tmdbkey": "test_key"},
                "database": {"type": "sqlite", "sqlite_path": ":memory:"},
            }

        def get_config(self, key, default=None):
            keys = key.split(".")
            val = self._config
            for k in keys:
                val = val.get(k, {})
            return val if val != {} else default

    return _MockConfig()
