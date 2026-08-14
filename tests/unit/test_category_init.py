"""CategoryInitializer 默认分类导入行为测试"""

from typing import cast

from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.services.category_init import CategoryInitializer


class _FakeRepo:
    def __init__(self, entities):
        self._entities = entities
        self.saved = []

    def get_all(self):
        return self._entities

    def save(self, **kwargs):
        self.saved.append(kwargs)


class _FakeEntity:
    media_type = "movie"
    name = "x"
    sort_order = 1
    is_default = 0
    rules = {}


def _run(monkeypatch, settings_marker, entities=None, template_exists=True, yaml_data=None):
    repo = _FakeRepo(entities or [])
    marker = {}

    monkeypatch.setattr(CategoryInitializer, "_seeded", lambda self: settings_marker)
    monkeypatch.setattr(CategoryInitializer, "_mark_seeded", lambda self: marker.update({"saved": True}))
    monkeypatch.setattr("app.services.category_init.os.path.exists", lambda _p: template_exists)

    class _FakeYAML:
        def load(self, _f):
            return yaml_data if yaml_data is not None else {}

    monkeypatch.setattr("app.services.category_init.ruamel.yaml.YAML", lambda: _FakeYAML())

    CategoryInitializer(repo=cast(CategoryConfigRepositoryAdapter, repo)).run()
    return repo, marker


def test_skips_when_data_exists(monkeypatch):
    """数据库已有分类时不导入默认值"""
    repo, _ = _run(monkeypatch, settings_marker=False, entities=[_FakeEntity()])
    assert repo.saved == [], "已有数据时不应导入默认值"


def test_seeds_defaults_on_fresh_install(monkeypatch):
    """全新安装（空库 + 未初始化标记）导入默认值并记录标记"""
    repo, marker = _run(
        monkeypatch,
        settings_marker=False,
        template_exists=True,
        yaml_data={"movie": {"动画电影": {"genre_ids": "16"}, "外语电影": None}},
    )
    assert len(repo.saved) == 2, "全新安装应导入默认分类"
    assert marker.get("saved"), "导入后应记录初始化标记"


def test_skips_when_empty_but_already_seeded(monkeypatch):
    """已初始化过但当前为空（用户主动清空）→ 不重新导入默认值，防止重启还原"""
    repo, marker = _run(monkeypatch, settings_marker=True, template_exists=True)
    assert repo.saved == [], "用户清空后不应重新导入默认值"
    assert not marker.get("saved"), "已初始化过且为空时不应再写标记"


def test_skips_when_template_missing(monkeypatch):
    """模板文件缺失时不导入"""
    repo, _ = _run(monkeypatch, settings_marker=False, template_exists=False)
    assert repo.saved == []
