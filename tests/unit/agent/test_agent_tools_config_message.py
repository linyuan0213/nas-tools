"""系统配置 / 消息渠道 agent 工具测试"""

import json
from typing import cast

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.config import config_get, config_set
from app.agent.tools.handlers.config_manifest import config_apply_manifest
from app.agent.tools.handlers.downloader import downloader_config_get, downloader_config_save
from app.agent.tools.handlers.indexer import indexer_config_get, indexer_config_save
from app.agent.tools.handlers.library_sync import (
    media_library_dir_add,
    media_library_dirs_get,
    sync_path_list,
    sync_path_save,
)
from app.agent.tools.handlers.mediaserver import mediaserver_config_save, mediaserver_list
from app.agent.tools.handlers.message import (
    message_channel_types,
    message_client_delete,
    message_client_list,
    message_client_save,
)
from app.agent.tools.handlers.scraper import scraper_config_get, scraper_config_save


def _data(result) -> dict:
    assert isinstance(result.data, dict)
    return result.data


def _ctx(mcs=None, dc=None, msc=None, ics=None, scs=None, pfs=None, mcsvc=None, sync=None):
    return cast(
        ToolContext,
        ToolContext(
            search_orchestrator=None,
            searcher=None,
            download_service=None,
            downloader_core=dc,
            subscribe_service=None,
            media_service=None,
            media_info_service=None,
            filetransfer_service=None,
            scheduler_service=None,
            system_info_service=None,
            event_bus=None,
            message_client_service=mcs,
            media_server_config_service=msc,
            indexer_config_service=ics,
            system_config_service=scs,
            plugin_framework_service=pfs,
            media_config_service=mcsvc,
            sync_service=sync,
        ),
    )


class _MessageSvc:
    def __init__(self, clients=None):
        self.clients = clients or {}
        self.deleted = []
        self.saved = []

    def get_client(self, cid=None):
        return self.clients

    def delete_client(self, cid):
        self.deleted.append(cid)
        return True

    def upsert_client(self, **kwargs):
        self.saved.append(kwargs)


class _FakeSettings:
    _data = {
        "media": {"movie_path": "/movie", "tmdb_language": "zh"},
        "app": {"web_port": 3000, "login_password": "secret123"},
        "pt": {"download_order": "seeder"},
    }

    @classmethod
    def get(cls, node=None):
        if not node:
            return cls._data
        return cls._data.get(node, {})


def _patch_config(monkeypatch, result_dto=None):
    import app.agent.tools.handlers.config as m

    monkeypatch.setattr(m, "settings", _FakeSettings)

    from app.schemas.system import ConfigUpdateResultDTO

    dto = result_dto or ConfigUpdateResultDTO(success=True, test_mode=False)
    monkeypatch.setattr(m.ConfigUpdateService, "update_config", staticmethod(lambda data: dto))


class TestConfigGet:
    def test_invalid_section_rejected(self):
        result = config_get(_ctx(), section="database")
        assert not result.success
        assert "不允许" in result.error

    def test_valid_section_masked(self, monkeypatch):
        _patch_config(monkeypatch)
        result = config_get(_ctx(), section="app")
        assert result.success
        assert _data(result)["app"]["login_password"] == "***"
        assert _data(result)["app"]["web_port"] == 3000


class TestConfigSet:
    def test_requires_confirm(self, monkeypatch):
        _patch_config(monkeypatch)
        result = config_set(_ctx(), config={"media.tmdb_language": "en"})
        assert result.need_confirm

    def test_confirmed_writes(self, monkeypatch):
        _patch_config(monkeypatch)
        result = config_set(_ctx(), config={"media.tmdb_language": "en"}, confirmed=True)
        assert result.success

    def test_secret_field_rejected(self, monkeypatch):
        _patch_config(monkeypatch)
        result = config_set(_ctx(), config={"app.login_password": "x"}, confirmed=True)
        assert not result.success
        assert "敏感" in result.error

    def test_unknown_key_rejected(self, monkeypatch):
        _patch_config(monkeypatch)
        result = config_set(_ctx(), config={"media.not_a_key": "x"}, confirmed=True)
        assert not result.success
        assert "未知" in result.error


class TestMessageClients:
    _CLIENTS = {
        1: {"name": "TG", "type": "telegram", "enabled": 1, "config": json.dumps({"bot_token": "abc", "chat_id": "1"})}
    }

    def test_list_masks_secret(self):
        result = message_client_list(_ctx(mcs=_MessageSvc(self._CLIENTS)))
        assert result.success
        item = _data(result)["items"][0]
        assert item["name"] == "TG"
        assert item["config"]["bot_token"] == "***"
        assert item["config"]["chat_id"] == "1"

    def test_channel_types(self):
        result = message_channel_types(_ctx())
        assert result.success
        types = {c["type"] for c in _data(result)["channels"]}
        assert "telegram" in types
        assert "webhook" in types

    def test_save_requires_confirm(self):
        svc = _MessageSvc()
        result = message_client_save(_ctx(mcs=svc), name="TG", ctype="telegram", config={"bot_token": "x"})
        assert result.need_confirm
        assert svc.saved == []

    def test_save_confirmed(self):
        svc = _MessageSvc()
        result = message_client_save(
            _ctx(mcs=svc), name="TG", ctype="telegram", config={"bot_token": "x"}, confirmed=True
        )
        assert result.success
        assert svc.saved[0]["name"] == "TG"
        assert svc.saved[0]["ctype"] == "telegram"

    def test_save_unknown_type(self):
        svc = _MessageSvc()
        result = message_client_save(_ctx(mcs=svc), name="X", ctype="qq", config={"token": "x"})
        assert not result.success
        assert "不支持" in result.error

    def test_delete_requires_confirm(self):
        svc = _MessageSvc(self._CLIENTS)
        result = message_client_delete(_ctx(mcs=svc), cid=1)
        assert result.need_confirm
        assert svc.deleted == []

    def test_delete_confirmed(self):
        svc = _MessageSvc(self._CLIENTS)
        result = message_client_delete(_ctx(mcs=svc), cid=1, confirmed=True)
        assert result.success
        assert svc.deleted == [1]


class _DownloaderCore:
    def __init__(self, confs):
        self.confs = confs
        self.updated = []
        self.default = None

    def get_downloader_conf(self, did=None):
        if did is not None:
            return self.confs.get(str(did))
        return self.confs

    def update_downloader(self, **kwargs):
        self.updated.append(kwargs)
        return True

    def set_default_downloader_id(self, did):
        self.default = did
        return True


_DL_CONFS = {
    "1": {
        "id": "1",
        "name": "Test",
        "type": "qbittorrent",
        "enabled": 1,
        "transfer": 1,
        "only_nexus_media": 1,
        "match_path": 1,
        "rmt_mode": "link",
        "is_default": True,
        "config": {"host": "192.168.1.1", "port": 8889, "username": "admin", "password": "secret"},
        "download_dir": [],
    }
}


class TestDownloaderConfig:
    def test_get_masks_password(self):
        dc = _DownloaderCore(_DL_CONFS)
        result = downloader_config_get(_ctx(dc=dc))
        assert result.success
        item = _data(result)["items"][0]
        assert item["config"]["password"] == "***"
        assert item["config"]["host"] == "192.168.1.1"

    def test_save_requires_confirm(self):
        dc = _DownloaderCore(_DL_CONFS)
        result = downloader_config_save(_ctx(dc=dc), did=1, config={"password": "new"})
        assert result.need_confirm
        assert dc.updated == []

    def test_save_confirmed_merges(self):
        dc = _DownloaderCore(_DL_CONFS)
        result = downloader_config_save(_ctx(dc=dc), did=1, config={"password": "new"}, confirmed=True)
        assert result.success
        assert dc.updated
        saved = dc.updated[0]
        assert saved["config"]["password"] == "new"
        assert saved["config"]["host"] == "192.168.1.1"  # 未修改字段保留

    def test_save_not_found(self):
        dc = _DownloaderCore(_DL_CONFS)
        result = downloader_config_save(_ctx(dc=dc), did=99, config={"host": "x"}, confirmed=True)
        assert not result.success
        assert "不存在" in result.error


class _MediaServerSvc:
    def __init__(self, servers=None):
        self.servers = servers or {}
        self.saved = []

    def get_media_servers_info(self):
        return {"servers": self.servers, "default_server": next(iter(self.servers), None)}

    def save_config(self, data):
        self.saved.append(data)
        from app.schemas.system import MediaServerConfigResultDTO

        return MediaServerConfigResultDTO(success=True, msg="ok")


_MS = {
    "emby": {
        "id": 1,
        "name": "emby",
        "enabled": 1,
        "is_default": 1,
        "config": {"host": "192.168.1.1", "port": 8096, "apikey": "secret-key", "schema": "emby"},
    }
}


class TestMediaserver:
    def test_list_masks_secret(self):
        svc = _MediaServerSvc(_MS)
        result = mediaserver_list(_ctx(msc=svc))
        assert result.success
        item = _data(result)["items"][0]
        assert item["config"]["apikey"] == "***"
        assert item["config"]["host"] == "192.168.1.1"

    def test_save_requires_confirm(self):
        svc = _MediaServerSvc(_MS)
        result = mediaserver_config_save(_ctx(msc=svc), name="emby", config={"port": 8097})
        assert result.need_confirm
        assert svc.saved == []

    def test_save_confirmed_merges(self):
        svc = _MediaServerSvc(_MS)
        result = mediaserver_config_save(_ctx(msc=svc), name="emby", config={"port": 8097}, confirmed=True)
        assert result.success
        assert svc.saved[0]["type"] == "emby"
        assert svc.saved[0]["port"] == 8097
        assert svc.saved[0]["host"] == "192.168.1.1"  # 保留未改字段

    def test_save_not_found(self):
        svc = _MediaServerSvc(_MS)
        result = mediaserver_config_save(_ctx(msc=svc), name="plex", config={"host": "x"}, confirmed=True)
        assert not result.success
        assert "不存在" in result.error


class _IndexerSvc:
    def __init__(self, configs=None):
        self.configs = configs or [{"client_id": "jackett", "enabled": 1, "config": {"host": "x", "api_key": "k"}}]
        self.saved = []

    def get_all_configs(self):
        return self.configs

    def get_config(self, client_id):
        for c in self.configs:
            if c["client_id"] == client_id:
                return c
        return None

    def save_config(self, data):
        self.saved.append(data)
        from app.schemas.system import IndexerConfigResultDTO

        return IndexerConfigResultDTO(success=True, msg="ok", code=0)


class _SystemCfgSvc:
    def __init__(self, scraper=None):
        self.store = {}
        if scraper is not None:
            self.store["UserScraperConf"] = scraper
        self.set_calls = []

    @staticmethod
    def _k(key):
        return key.value if hasattr(key, "value") else key

    def get(self, key=None):
        return self.store.get(self._k(key))

    def set(self, key, value):
        self.store[self._k(key)] = value
        self.set_calls.append((self._k(key), value))


class TestIndexer:
    def test_get_masks_secret(self):
        svc = _IndexerSvc()
        result = indexer_config_get(_ctx(ics=svc))
        assert result.success
        item = _data(result)["items"][0]
        assert item["config"]["api_key"] == "***"
        assert item["config"]["host"] == "x"

    def test_save_requires_confirm(self):
        svc = _IndexerSvc()
        result = indexer_config_save(_ctx(ics=svc), client_id="jackett", enabled=True, config={"api_key": "n"})
        assert result.need_confirm
        assert svc.saved == []

    def test_save_confirmed_merges(self):
        svc = _IndexerSvc()
        result = indexer_config_save(
            _ctx(ics=svc), client_id="jackett", enabled=True, config={"api_key": "n"}, confirmed=True
        )
        assert result.success
        assert svc.saved
        assert svc.saved[0]["enabled"] == 1
        assert svc.saved[0]["jackett.host"] == "x"
        assert svc.saved[0]["jackett.api_key"] == "n"


class TestScraper:
    def test_get_masks(self):
        svc = _SystemCfgSvc({"scraper_nfo": {"tmdb_api_key": "k"}, "scraper_pic": {"fanart": "1"}})
        result = scraper_config_get(_ctx(scs=svc))
        assert result.success
        assert _data(result)["scraper_nfo"]["tmdb_api_key"] == "***"
        assert _data(result)["scraper_pic"]["fanart"] == "1"

    def test_save_requires_confirm(self):
        svc = _SystemCfgSvc()
        result = scraper_config_save(_ctx(scs=svc), config={"scraper_nfo": {"a": "1"}})
        assert result.need_confirm
        assert svc.set_calls == []

    def test_save_confirmed(self):
        svc = _SystemCfgSvc()
        result = scraper_config_save(_ctx(scs=svc), config={"scraper_nfo": {"a": "1"}}, confirmed=True)
        assert result.success
        assert svc.set_calls == [("UserScraperConf", {"scraper_nfo": {"a": "1"}})]


class _PluginSvc2:
    def __init__(self):
        self.enabled = []
        self.disabled = []
        self.saved = []

    def enable(self, pid):
        self.enabled.append(pid)

    def disable(self, pid):
        self.disabled.append(pid)

    def save_config(self, pid, cfg):
        self.saved.append((pid, cfg))


class TestConfigApplyManifest:
    def _full_ctx(self):
        dc = _DownloaderCore(_DL_CONFS)
        ms = _MediaServerSvc(_MS)
        ix = _IndexerSvc()
        scs = _SystemCfgSvc()
        mc = _MessageSvc()
        pl = _PluginSvc2()
        return _ctx(mcs=mc, dc=dc, msc=ms, ics=ix, scs=scs, pfs=pl), pl

    def test_empty_manifest_rejected(self):
        ctx, _ = self._full_ctx()
        result = config_apply_manifest(ctx, manifest={})
        assert not result.success
        assert "为空" in result.error

    def test_invalid_section_errors(self):
        ctx, _ = self._full_ctx()
        result = config_apply_manifest(ctx, manifest={"config": {"security.jwt_secret": "x"}})
        assert not result.success
        assert "敏感" in result.error or "不允许" in result.error

    def test_requires_confirm_with_preview(self):
        ctx, _ = self._full_ctx()
        manifest = {"message_clients": [{"name": "TG", "type": "telegram", "config": {"bot_token": "x"}}]}
        result = config_apply_manifest(ctx, manifest=manifest)
        assert result.need_confirm
        assert "消息通知" in _data(result)["summary"]

    def test_confirmed_applies_all(self):
        ctx, pl = self._full_ctx()
        manifest = {
            "message_clients": [{"name": "TG", "type": "telegram", "config": {"bot_token": "x"}}],
            "plugins": [{"plugin_id": "autosignin", "action": "enable"}],
        }
        result = config_apply_manifest(ctx, manifest=manifest, confirmed=True)
        assert result.success
        assert _data(result)["ok"] == 2
        assert _data(result)["failed"] == 0

    def test_confirmed_partial_failure_reported(self):
        ctx, pl = self._full_ctx()
        manifest = {
            "downloaders": [{"id": 99, "host": "x"}],  # 不存在 → 失败
            "plugins": [{"plugin_id": "autosignin", "action": "disable"}],  # 成功
        }
        result = config_apply_manifest(ctx, manifest=manifest, confirmed=True)
        assert not result.success
        assert _data(result)["ok"] == 1
        assert _data(result)["failed"] == 1
        assert "下载器不存在" in _data(result)["results"][0]["message"]


class TestIsDefaultInManifest:
    def test_downloader_is_default(self):
        dc = _DownloaderCore(_DL_CONFS)
        ctx = _ctx(dc=dc)
        result = config_apply_manifest(
            ctx, manifest={"downloaders": [{"id": 1, "is_default": True, "host": "1.2.3.4"}]}, confirmed=True
        )
        assert result.success
        assert dc.default == "1"
        assert dc.updated[0]["config"]["host"] == "1.2.3.4"

    def test_mediaserver_top_level_default(self):
        ms = _MediaServerSvc(_MS)
        result = config_apply_manifest(
            _ctx(msc=ms),
            manifest={"mediaservers": [{"name": "emby", "is_default": True, "config": {"port": 8097}}]},
            confirmed=True,
        )
        assert result.success
        assert ms.saved[0]["type"] == "emby"
        assert ms.saved[0]["is_default"] == 1
        assert ms.saved[0]["port"] == 8097


class _MediaDirSvc:
    def __init__(self, cfg=None):
        self.cfg = cfg or {"movie_path": ["/m"], "movie_backend": []}
        self.calls = []

    def get_config(self):
        return self.cfg

    def add_path(self, *a):
        self.calls.append(("add", a))

    def remove_path(self, *a):
        self.calls.append(("remove", a))


class _SyncSvc:
    def __init__(self, paths=None):
        if paths is None:
            paths = {
                "1": {
                    "source": "/a",
                    "dest": "/b",
                    "operation": "copy",
                    "src_backend": "local",
                    "dst_backend": "local",
                    "rename": 0,
                    "enabled": 1,
                }
            }
        self.paths = paths
        self.saved = []

    def get_sync_paths(self, sid=None):
        return self.paths

    def add_or_edit_sync_path(self, **kw):
        self.saved.append(kw)


class TestLibraryDirsAndSync:
    def test_media_dirs_get(self):
        result = media_library_dirs_get(_ctx(mcsvc=_MediaDirSvc()))
        assert result.success
        assert _data(result)["items"][0]["type"] == "movie"

    def test_media_dir_add_confirm_and_apply(self):
        svc = _MediaDirSvc()
        result = media_library_dir_add(_ctx(mcsvc=svc), path_type="movie", path="/m2")
        assert result.need_confirm
        result = media_library_dir_add(_ctx(mcsvc=svc), path_type="movie", path="/m2", confirmed=True)
        assert result.success
        assert svc.calls == [("add", ("movie", "/m2", ""))]

    def test_media_dir_invalid_type(self):
        result = media_library_dir_add(_ctx(mcsvc=_MediaDirSvc()), path_type="xx", path="/m")
        assert not result.success

    def test_sync_list(self):
        result = sync_path_list(_ctx(sync=_SyncSvc()))
        assert result.success
        assert _data(result)["items"][0]["source"] == "/a"

    def test_sync_save_confirm_and_apply(self):
        svc = _SyncSvc()
        result = sync_path_save(_ctx(sync=svc), source="/a", dest="/b", mode="copy")
        assert result.need_confirm
        result = sync_path_save(_ctx(sync=svc), source="/a", dest="/b", mode="copy", confirmed=True)
        assert result.success
        assert svc.saved[0]["mode"] == "copy"
        assert svc.saved[0]["src_backend"] == "local"

    def test_sync_save_bad_mode(self):
        svc = _SyncSvc()
        result = sync_path_save(_ctx(sync=svc), source="/a", mode="weird")
        assert not result.success


class TestDownloaderAddNoId:
    def test_add_new_downloader_via_manifest(self):
        dc = _DownloaderCore({})
        result = config_apply_manifest(
            _ctx(dc=dc),
            manifest={
                "downloaders": [
                    {
                        "name": "QB新",
                        "type": "qbittorrent",
                        "host": "1.2.3.4",
                        "port": 8889,
                        "username": "a",
                        "password": "p",
                    }
                ]
            },
            confirmed=True,
        )
        assert result.success
        added = dc.updated[0]
        assert added["did"] is None
        assert added["name"] == "QB新"
        assert added["dtype"] == "qbittorrent"
        assert added["config"]["host"] == "1.2.3.4"

    def test_new_downloader_missing_type_rejected(self):
        dc = _DownloaderCore({})
        result = config_apply_manifest(_ctx(dc=dc), manifest={"downloaders": [{"name": "X"}]}, confirmed=True)
        assert not result.success
        assert "name 与 type" in result.error
