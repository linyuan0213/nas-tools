"""Web 消息仓储已读/未读逻辑测试"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.repositories.web_message_repository import WebMessageRepository
from app.db.session import SessionManager


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    manager = SessionManager()
    manager._engine = engine
    manager._factory = sessionmaker(bind=engine, expire_on_commit=False)
    WebMessageRepository._session_manager = manager
    yield WebMessageRepository()
    engine.dispose()


def test_unread_and_mark_read(repo):
    uid = "u-read-test"
    id1 = repo.add_message(uid, "notify", "标题1", "内容1")
    id2 = repo.add_message(uid, "notify", "标题2", "内容2")
    repo.add_message("other", "notify", "别人", "不看")

    assert repo.unread_count(uid) == 2
    assert repo.unread_count("other") == 1

    # 标记部分已读
    repo.mark_read(uid, [id1])
    assert repo.unread_count(uid) == 1

    # 全部已读
    repo.mark_read(uid)
    assert repo.unread_count(uid) == 0

    # 已读字段随 dict 返回
    items = repo.history(uid)
    by_id = {i["id"]: i for i in items}
    assert by_id[id1]["read"] is True
    assert by_id[id2]["read"] is True
    assert by_id[id1]["id"] == id1
