"""
Config Repository
Handles configuration related database operations.
Includes: Message Client, Torrent Remove Task, Downloader, User RSS, Filter Rules
"""

import time

from sqlalchemy import Integer, cast, text

from app.db.models import (
    CONFIGCATEGORY,
    CONFIGCATEGORYRULE,
    CONFIGFILTERGROUP,
    CONFIGFILTERRULES,
    CONFIGMEDIA,
    CONFIGRSSPARSER,
    CONFIGUSERRSS,
    DOWNLOADER,
    MEDIASERVER,
    MESSAGECLIENT,
    TORRENTREMOVETASK,
    USERRSSTASKHISTORY,
)
from app.db.repositories.base_repository import BaseRepository
from app.utils.json_utils import JsonUtils


class ConfigRepository(BaseRepository):
    """
    配置仓储
    处理消息客户端、自动删种策略、下载器、自定义RSS、过滤规则的数据库操作
    """

    # ==================== Message Client ====================

    def delete_message_client(self, cid: int | None) -> int:
        """
        删除消息服务器

        Args:
            cid: 客户端ID
        """
        if not cid:
            return 0
        with self.session() as db:
            return db.query(MESSAGECLIENT).filter(int(cid) == MESSAGECLIENT.ID).delete()

    def get_message_client(self, cid: int | None = None) -> list[MESSAGECLIENT]:
        with self.session() as db:
            if cid:
                return db.query(MESSAGECLIENT).filter(int(cid) == MESSAGECLIENT.ID).all()
            return db.query(MESSAGECLIENT).all()

    def insert_message_client(
        self,
        name: str,
        ctype: str,
        config: str,
        switches: list,
        interactive: int,
        enabled: int,
        note: str = "",
        templates: str | None = None,
    ) -> int:
        client = MESSAGECLIENT(
            NAME=name,
            TYPE=ctype,
            CONFIG=config,
            SWITCHES=JsonUtils.dumps(switches),
            INTERACTIVE=int(interactive),
            ENABLED=int(enabled),
            NOTE=note,
            TEMPLATES=JsonUtils.dumps(templates) if templates else None,
        )
        with self.session() as db:
            db.add(client)
            db.flush()
            return int(client.ID)

    def update_message_client(
        self,
        cid: int,
        name: str,
        ctype: str,
        config: str,
        switches: list,
        interactive: int,
        enabled: int,
        note: str = "",
        templates: str | None = None,
    ) -> int:
        """更新消息客户端配置，返回客户端 ID."""
        with self.session() as db:
            client = db.query(MESSAGECLIENT).filter(int(cid) == MESSAGECLIENT.ID).first()
            if not client:
                return 0
            client.NAME = name
            client.TYPE = ctype
            client.CONFIG = config
            client.SWITCHES = JsonUtils.dumps(switches)
            client.INTERACTIVE = int(interactive)
            client.ENABLED = int(enabled)
            client.NOTE = note
            client.TEMPLATES = JsonUtils.dumps(templates) if templates else None
            db.flush()
            return int(client.ID)

    def check_message_client(
        self,
        cid: int | None = None,
        interactive: int | None = None,
        enabled: int | None = None,
        ctype: str | None = None,
    ) -> None:
        """
        设置消息客户端状态

        Args:
            cid: 客户端ID
            interactive: 是否交互
            enabled: 是否启用
            ctype: 类型
        """
        with self.session() as db:
            if cid and interactive is not None:
                db.query(MESSAGECLIENT).filter(int(cid) == MESSAGECLIENT.ID).update({"INTERACTIVE": int(interactive)})
            elif cid and enabled is not None:
                db.query(MESSAGECLIENT).filter(int(cid) == MESSAGECLIENT.ID).update({"ENABLED": int(enabled)})
            elif not cid and int(interactive or 0) == 0 and ctype:
                db.query(MESSAGECLIENT).filter(MESSAGECLIENT.INTERACTIVE == 1, ctype == MESSAGECLIENT.TYPE).update(
                    {"INTERACTIVE": 0}
                )

    # ==================== Torrent Remove Task ====================

    def delete_torrent_remove_task(self, tid: int | None) -> None:
        """
        删除自动删种策略

        Args:
            tid: 任务ID
        """
        if not tid:
            return
        with self.session() as db:
            db.query(TORRENTREMOVETASK).filter(int(tid) == TORRENTREMOVETASK.ID).delete()

    def get_torrent_remove_tasks(self, tid: int | None = None) -> list[TORRENTREMOVETASK]:
        """
        查询自动删种策略

        Args:
            tid: 任务ID

        Returns:
            删种策略列表
        """
        with self.session() as db:
            if tid:
                return db.query(TORRENTREMOVETASK).filter(int(tid) == TORRENTREMOVETASK.ID).all()
            return db.query(TORRENTREMOVETASK).order_by(TORRENTREMOVETASK.NAME).all()

    def update_torrent_remove_task(
        self,
        tid: int,
        name: str,
        action: int,
        interval: int,
        enabled: int,
        samedata: int,
        only_nexus_media: int,
        downloader: str,
        config: dict,
        note: str | None = None,
    ) -> bool:
        """
        更新自动删种策略

        Args:
            tid: 任务ID
            其余参数同 insert_torrent_remove_task

        Returns:
            是否更新成功（任务不存在时返回 False）
        """
        if not tid:
            return False
        with self.session() as db:
            count = (
                db.query(TORRENTREMOVETASK)
                .filter(int(tid) == TORRENTREMOVETASK.ID)
                .update(
                    {
                        TORRENTREMOVETASK.NAME: name,
                        TORRENTREMOVETASK.ACTION: int(action),
                        TORRENTREMOVETASK.INTERVAL: int(interval),
                        TORRENTREMOVETASK.ENABLED: int(enabled),
                        TORRENTREMOVETASK.SAMEDATA: int(samedata),
                        TORRENTREMOVETASK.ONLY_NEXUS_MEDIA: int(only_nexus_media),
                        TORRENTREMOVETASK.DOWNLOADER: downloader,
                        TORRENTREMOVETASK.CONFIG: JsonUtils.dumps(config),
                        TORRENTREMOVETASK.NOTE: note,
                    }
                )
            )
            return count > 0

    def insert_torrent_remove_task(
        self,
        name: str,
        action: int,
        interval: int,
        enabled: int,
        samedata: int,
        only_nexus_media: int,
        downloader: str,
        config: dict,
        note: str | None = None,
    ) -> None:
        """
        设置自动删种策略

        Args:
            name: 名称
            action: 动作
            interval: 间隔
            enabled: 是否启用
            samedata: 相同数据处理
            only_nexus_media: 仅Nexus Media
            downloader: 下载器
            config: 配置
            note: 备注
        """
        with self.session() as db:
            db.add(
                TORRENTREMOVETASK(
                    NAME=name,
                    ACTION=int(action),
                    INTERVAL=int(interval),
                    ENABLED=int(enabled),
                    SAMEDATA=int(samedata),
                    ONLY_NEXUS_MEDIA=int(only_nexus_media),
                    DOWNLOADER=downloader,
                    CONFIG=JsonUtils.dumps(config),
                    NOTE=note,
                )
            )

    # ==================== Downloader ====================

    def update_downloader(
        self,
        did: int | None,
        name: str,
        enabled: int,
        dtype: str,
        transfer: int,
        only_nexus_media: int,
        match_path: int,
        rmt_mode: str,
        config: str,
        download_dir: str,
    ) -> None:
        """
        更新下载器

        Args:
            did: 下载器ID
            name: 名称
            enabled: 是否启用
            dtype: 类型
            transfer: 是否转移
            only_nexus_media: 仅Nexus Media
            match_path: 匹配路径
            rmt_mode: 转移模式
            config: 配置
            download_dir: 下载目录
        """
        with self.session() as db:
            if did:
                db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).update(
                    {
                        "NAME": name,
                        "ENABLED": int(enabled),
                        "TYPE": dtype,
                        "TRANSFER": int(transfer),
                        "ONLY_NEXUS_MEDIA": int(only_nexus_media),
                        "MATCH_PATH": int(match_path),
                        "RMT_MODE": rmt_mode,
                        "CONFIG": config,
                        "DOWNLOAD_DIR": download_dir,
                    }
                )
            else:
                db.add(
                    DOWNLOADER(
                        NAME=name,
                        ENABLED=int(enabled),
                        TYPE=dtype,
                        TRANSFER=int(transfer),
                        ONLY_NEXUS_MEDIA=int(only_nexus_media),
                        MATCH_PATH=int(match_path),
                        RMT_MODE=rmt_mode,
                        CONFIG=config,
                        DOWNLOAD_DIR=download_dir,
                    )
                )

    def delete_downloader(self, did: int | None) -> None:
        """
        删除下载器

        Args:
            did: 下载器ID
        """
        if not did:
            return
        with self.session() as db:
            db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).delete()

    def check_downloader(
        self,
        did: int | None = None,
        transfer: int | None = None,
        only_nexus_media: int | None = None,
        enabled: int | None = None,
        match_path: int | None = None,
    ) -> None:
        """
        设置下载器状态

        Args:
            did: 下载器ID
            transfer: 是否转移
            only_nexus_media: 仅Nexus Media
            enabled: 是否启用
            match_path: 匹配路径
        """
        if not did:
            return
        with self.session() as db:
            if transfer is not None:
                db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).update({"TRANSFER": int(transfer)})
            elif only_nexus_media is not None:
                db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).update(
                    {"ONLY_NEXUS_MEDIA": int(only_nexus_media)}
                )
            elif match_path is not None:
                db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).update({"MATCH_PATH": int(match_path)})
            elif enabled is not None:
                db.query(DOWNLOADER).filter(int(did) == DOWNLOADER.ID).update({"ENABLED": int(enabled)})

    def get_downloaders(self) -> list[DOWNLOADER]:
        """
        查询下载器

        Returns:
            下载器列表
        """
        with self.session() as db:
            return db.query(DOWNLOADER).all()

    # ==================== User RSS ====================

    def get_userrss_tasks(self, tid: int | None = None) -> list[CONFIGUSERRSS]:
        """
        查询自定义RSS任务

        Args:
            tid: 任务ID

        Returns:
            任务列表
        """
        with self.session() as db:
            if tid:
                return db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).all()
            else:
                return db.query(CONFIGUSERRSS).order_by(CONFIGUSERRSS.STATE.desc()).all()

    def delete_userrss_task(self, tid: int | None) -> None:
        """
        删除自定义RSS任务

        Args:
            tid: 任务ID
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).delete()

    def update_userrss_task_info(self, tid: int | None, count: int) -> None:
        """
        更新自定义RSS任务处理计数

        Args:
            tid: 任务ID
            count: 处理数量
        """
        if not tid:
            return
        with self.session() as db:
            db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).update(
                {
                    "PROCESS_COUNT": CONFIGUSERRSS.PROCESS_COUNT + count,
                    "UPDATE_TIME": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                }
            )

    def update_userrss_task(self, item: dict) -> None:
        """
        更新或插入自定义RSS任务

        Args:
            item: 任务信息字典
        """
        with self.session() as db:
            if item.get("id") and self.get_userrss_tasks(item.get("id")):
                db.query(CONFIGUSERRSS).filter(int(item.get("id") or 0) == CONFIGUSERRSS.ID).update(
                    {
                        "NAME": item.get("name"),
                        "ADDRESS": JsonUtils.dumps(item.get("address")),
                        "PARSER": JsonUtils.dumps(item.get("parser")),
                        "INTERVAL": item.get("interval"),
                        "USES": item.get("uses"),
                        "INCLUDE": item.get("include"),
                        "EXCLUDE": item.get("exclude"),
                        "FILTER": item.get("filter_rule"),
                        "UPDATE_TIME": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                        "STATE": item.get("state"),
                        "SAVE_PATH": item.get("save_path"),
                        "DOWNLOAD_SETTING": item.get("download_setting"),
                        "RECOGNIZATION": item.get("recognization"),
                        "OVER_EDITION": int(item.get("over_edition") or 0)
                        if str(item.get("over_edition") or "").isdigit()
                        else 0,
                        "SITES": JsonUtils.dumps(item.get("sites")),
                        "FILTER_ARGS": JsonUtils.dumps(item.get("filter_args")),
                        "NOTE": JsonUtils.dumps(item.get("note")),
                    }
                )
            else:
                db.add(
                    CONFIGUSERRSS(
                        NAME=item.get("name"),
                        ADDRESS=JsonUtils.dumps(item.get("address")),
                        PARSER=JsonUtils.dumps(item.get("parser")),
                        INTERVAL=item.get("interval"),
                        USES=item.get("uses"),
                        INCLUDE=item.get("include"),
                        EXCLUDE=item.get("exclude"),
                        FILTER=item.get("filter_rule"),
                        UPDATE_TIME=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                        STATE=item.get("state"),
                        SAVE_PATH=item.get("save_path"),
                        DOWNLOAD_SETTING=item.get("download_setting"),
                        RECOGNIZATION=item.get("recognization"),
                        OVER_EDITION=item.get("over_edition"),
                        SITES=JsonUtils.dumps(item.get("sites")),
                        FILTER_ARGS=JsonUtils.dumps(item.get("filter_args")),
                        NOTE=JsonUtils.dumps(item.get("note")),
                        PROCESS_COUNT="0",
                    )
                )

    def check_userrss_task(self, tid: int | None = None, state: str | None = None) -> None:
        """
        设置自定义RSS任务状态

        Args:
            tid: 任务ID
            state: 状态
        """
        if state is None:
            return
        with self.session() as db:
            if tid:
                db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).update({"STATE": state})
            else:
                db.query(CONFIGUSERRSS).update({"STATE": state})

    def insert_userrss_mediainfos(self, tid: int | None = None, mediainfo: object | None = None) -> None:
        """
        插入自定义RSS媒体信息

        Args:
            tid: 任务ID
            mediainfo: 媒体信息
        """
        if not tid or not mediainfo:
            return
        with self.session() as db:
            taskinfo = db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).all()
            if not taskinfo:
                return

            mediainfos = JsonUtils.loads(taskinfo[0].MEDIAINFOS) if taskinfo[0].MEDIAINFOS else []
            tmdbid = str(mediainfo.tmdb_id)  # type: ignore[union-attr]
            season = int(mediainfo.get_season_seq())  # type: ignore[union-attr]

            for media in mediainfos:
                if media.get("id") == tmdbid and media.get("season") == season:
                    return

            mediainfos.append(
                {"id": tmdbid, "rssid": "", "season": season, "name": getattr(mediainfo, "title", "") or ""}
            )

            db.query(CONFIGUSERRSS).filter(int(tid) == CONFIGUSERRSS.ID).update(
                {"MEDIAINFOS": JsonUtils.dumps(mediainfos)}
            )

    def insert_userrss_task_history(self, task_id: int, title: str, downloader: str) -> None:
        """
        增加自定义RSS订阅任务的下载记录

        Args:
            task_id: 任务ID
            title: 标题
            downloader: 下载器
        """
        with self.session() as db:
            db.add(
                USERRSSTASKHISTORY(
                    TASK_ID=task_id,
                    TITLE=title,
                    DOWNLOADER=downloader,
                    DATE=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                )
            )

    def get_userrss_task_history(self, task_id: int) -> list[USERRSSTASKHISTORY]:
        """
        查询自定义RSS订阅任务的下载记录

        Args:
            task_id: 任务ID

        Returns:
            历史记录列表
        """
        if not task_id:
            return []
        with self.session() as db:
            return (
                db.query(USERRSSTASKHISTORY)
                .filter(task_id == USERRSSTASKHISTORY.TASK_ID)
                .order_by(USERRSSTASKHISTORY.DATE.desc())
                .all()
            )

    # ==================== RSS Parser ====================

    def get_userrss_parser(self, pid: int | None = None) -> CONFIGRSSPARSER | None | list[CONFIGRSSPARSER]:
        """
        获取自定义RSS解析器

        Args:
            pid: 解析器ID

        Returns:
            解析器列表或单个解析器
        """
        with self.session() as db:
            if pid:
                return db.query(CONFIGRSSPARSER).filter(int(pid) == CONFIGRSSPARSER.ID).first()
            else:
                return db.query(CONFIGRSSPARSER).all()

    def delete_userrss_parser(self, pid: int | None) -> None:
        """
        删除自定义RSS解析器

        Args:
            pid: 解析器ID
        """
        if not pid:
            return
        with self.session() as db:
            db.query(CONFIGRSSPARSER).filter(int(pid) == CONFIGRSSPARSER.ID).delete()

    def update_userrss_parser(self, item: dict) -> None:
        """
        更新或插入自定义RSS解析器

        Args:
            item: 解析器信息字典
        """
        if not item:
            return
        with self.session() as db:
            if item.get("id") and self.get_userrss_parser(item.get("id")):
                db.query(CONFIGRSSPARSER).filter(int(item.get("id") or 0) == CONFIGRSSPARSER.ID).update(
                    {
                        "NAME": item.get("name"),
                        "TYPE": item.get("type"),
                        "FORMAT": item.get("format"),
                        "PARAMS": item.get("params"),
                    }
                )
            else:
                db.add(
                    CONFIGRSSPARSER(
                        NAME=item.get("name"),
                        TYPE=item.get("type"),
                        FORMAT=item.get("format"),
                        PARAMS=item.get("params"),
                    )
                )

    # ==================== Filter Rules ====================

    def get_config_filter_group(self, gid: int | None = None) -> list[CONFIGFILTERGROUP]:
        """
        查询过滤规则组

        Args:
            gid: 组ID

        Returns:
            规则组列表
        """
        with self.session() as db:
            if gid:
                return db.query(CONFIGFILTERGROUP).filter(int(gid) == CONFIGFILTERGROUP.ID).all()
            return db.query(CONFIGFILTERGROUP).all()

    def get_config_filter_rule(self, groupid: int | None = None) -> list[CONFIGFILTERRULES]:
        """
        查询过滤规则

        Args:
            groupid: 组ID

        Returns:
            规则列表
        """
        with self.session() as db:
            if not groupid:
                return (
                    db.query(CONFIGFILTERRULES)
                    .order_by(CONFIGFILTERRULES.GROUP_ID, cast(CONFIGFILTERRULES.PRIORITY, Integer))
                    .all()
                )
            else:
                return (
                    db.query(CONFIGFILTERRULES)
                    .filter(int(groupid) == CONFIGFILTERRULES.GROUP_ID)
                    .order_by(CONFIGFILTERRULES.GROUP_ID, cast(CONFIGFILTERRULES.PRIORITY, Integer))
                    .all()
                )

    def add_filter_group(self, name: str, default: str = "N") -> None:
        """
        新增规则组

        Args:
            name: 组名
            default: 是否默认
        """
        if default == "Y":
            self.set_default_filtergroup(0)
        group_id = self.get_filter_groupid_by_name(name)
        with self.session() as db:
            if group_id:
                db.query(CONFIGFILTERGROUP).filter(int(group_id) == CONFIGFILTERGROUP.ID).update(
                    {"IS_DEFAULT": default}
                )
            else:
                db.add(CONFIGFILTERGROUP(GROUP_NAME=name, IS_DEFAULT=default))

    def get_filter_groupid_by_name(self, name: str) -> int | str:
        """
        根据名称获取规则组ID

        Args:
            name: 组名

        Returns:
            组ID
        """
        with self.session() as db:
            ret = db.query(CONFIGFILTERGROUP.ID).filter(name == CONFIGFILTERGROUP.GROUP_NAME).first()
            if ret:
                return ret[0]
            else:
                return ""

    def set_default_filtergroup(self, groupid: int) -> None:
        """
        设置默认的规则组

        Args:
            groupid: 组ID
        """
        with self.session() as db:
            db.query(CONFIGFILTERGROUP).filter(int(groupid) == CONFIGFILTERGROUP.ID).update({"IS_DEFAULT": "Y"})
            db.query(CONFIGFILTERGROUP).filter(int(groupid) != CONFIGFILTERGROUP.ID).update({"IS_DEFAULT": "N"})

    def delete_filtergroup(self, groupid: int) -> None:
        """
        删除规则组

        Args:
            groupid: 组ID
        """
        with self.session() as db:
            db.query(CONFIGFILTERRULES).filter(groupid == CONFIGFILTERRULES.GROUP_ID).delete()
            db.query(CONFIGFILTERGROUP).filter(int(groupid) == CONFIGFILTERGROUP.ID).delete()

    def delete_filterrule(self, ruleid: int) -> None:
        """
        删除规则

        Args:
            ruleid: 规则ID
        """
        with self.session() as db:
            db.query(CONFIGFILTERRULES).filter(int(ruleid) == CONFIGFILTERRULES.ID).delete()

    def insert_filter_rule(self, item: dict, ruleid: int | None = None) -> None:
        """
        新增或更新规则

        Args:
            item: 规则信息字典
            ruleid: 规则ID（可选）
        """
        with self.session() as db:
            if ruleid:
                db.query(CONFIGFILTERRULES).filter(int(ruleid) == CONFIGFILTERRULES.ID).update(
                    {
                        "ROLE_NAME": item.get("name") or "",
                        "PRIORITY": item.get("pri") or "",
                        "INCLUDE": item.get("include") or "",
                        "EXCLUDE": item.get("exclude") or "",
                        "SIZE_LIMIT": item.get("size") or "",
                        "NOTE": item.get("free") or "",
                    }
                )
            else:
                db.add(
                    CONFIGFILTERRULES(
                        GROUP_ID=item.get("group"),
                        ROLE_NAME=item.get("name") or "",
                        PRIORITY=item.get("pri") or "",
                        INCLUDE=item.get("include") or "",
                        EXCLUDE=item.get("exclude") or "",
                        SIZE_LIMIT=item.get("size") or "",
                        NOTE=item.get("free") or "",
                    )
                )

    # ==================== Media Server ====================

    def get_media_servers(self, sid: int | None = None) -> list[MEDIASERVER]:
        """
        查询媒体服务器配置

        Args:
            sid: 服务器ID

        Returns:
            媒体服务器配置列表
        """
        with self.session() as db:
            if sid:
                return db.query(MEDIASERVER).filter(int(sid) == MEDIASERVER.ID).all()
            return db.query(MEDIASERVER).all()

    def get_media_server_by_name(self, name: str) -> MEDIASERVER | None:
        """
        根据名称查询媒体服务器配置

        Args:
            name: 服务器名称

        Returns:
            媒体服务器配置
        """
        if not name:
            return None
        with self.session() as db:
            return db.query(MEDIASERVER).filter(name == MEDIASERVER.NAME).first()

    def update_media_server(
        self, sid: int | None, name: str, enabled: int, config: str, is_default: int = 0, note: str | None = None
    ) -> None:
        """
        更新或插入媒体服务器配置

        Args:
            sid: 服务器ID
            name: 名称
            enabled: 是否启用
            config: 配置(JSON字符串)
            is_default: 是否默认
            note: 备注
        """
        with self.session() as db:
            if sid:
                item = self.get_media_servers(sid)
                if item:
                    db.query(MEDIASERVER).filter(int(sid) == MEDIASERVER.ID).update(
                        {
                            "NAME": name,
                            "ENABLED": int(enabled),
                            "CONFIG": config,
                            "IS_DEFAULT": int(is_default),
                            "NOTE": note or "",
                        }
                    )
                    return
            db.add(
                MEDIASERVER(
                    NAME=name,
                    ENABLED=int(enabled),
                    CONFIG=config,
                    IS_DEFAULT=int(is_default),
                    NOTE=note or "",
                )
            )

    def delete_media_server(self, sid: int | None) -> None:
        """
        删除媒体服务器配置

        Args:
            sid: 服务器ID
        """
        if not sid:
            return
        with self.session() as db:
            db.query(MEDIASERVER).filter(int(sid) == MEDIASERVER.ID).delete()

    def set_default_media_server(self, name: str) -> None:
        """
        设置默认媒体服务器，仅更新 IS_DEFAULT 标记

        Args:
            name: 服务器名称
        """
        with self.session() as db:
            db.query(MEDIASERVER).update({"IS_DEFAULT": 0})
            if name:
                db.query(MEDIASERVER).filter(name == MEDIASERVER.NAME).update({"IS_DEFAULT": 1})

    def get_default_media_server(self) -> MEDIASERVER | None:
        """
        获取默认媒体服务器

        Returns:
            默认媒体服务器配置
        """
        with self.session() as db:
            return db.query(MEDIASERVER).filter(MEDIASERVER.IS_DEFAULT == 1).first()

    # ==================== SQL Operations ====================

    def _execute_raw(self, sql: str) -> object:
        """执行原始SQL语句（仅供初始化场景使用，禁止传入外部输入）。

        使用 exec_driver_sql 原样下发，避免 text() 将正则中的 :xxx
        （如非捕获分组 (?:简体|…)）误解析为绑定参数。
        """
        with self.session() as db:
            return db.connection().exec_driver_sql(sql)

    def drop_table(self, table_name: str) -> object:
        """
        删除表

        Args:
            table_name: 表名

        Returns:
            执行结果
        """
        # 验证表名只含字母数字下划线，防注入
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table_name}")
        with self.session() as db:
            return db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

    # ==================== Media Config ====================

    def get_media_config(self) -> CONFIGMEDIA | None:
        """获取媒体库路径配置"""
        with self.session() as db:
            return db.query(CONFIGMEDIA).first()

    def _update_media_config_col(self, col_name: str, value: str) -> None:
        """更新 CONFIG_MEDIA 表的单个列（由 MediaConfigRepositoryAdapter 调用）"""
        with self.session() as db:
            existing = db.query(CONFIGMEDIA).first()
            if existing:
                setattr(existing, col_name, value)
                db.commit()
            else:
                config = CONFIGMEDIA(**{col_name: value})
                db.add(config)
                db.commit()

    def set_media_config(
        self,
        movie_path: str,
        tv_path: str,
        anime_path: str,
        unknown_path: str,
        movie_backend: str = "",
        tv_backend: str = "",
        anime_backend: str = "",
        unknown_backend: str = "",
    ) -> None:
        """设置媒体库路径配置（单条记录）"""
        with self.session() as db:
            existing = db.query(CONFIGMEDIA).first()
            if existing:
                existing.MOVIE_PATH = movie_path or ""
                existing.TV_PATH = tv_path or ""
                existing.ANIME_PATH = anime_path or ""
                existing.UNKNOWN_PATH = unknown_path or ""
                existing.MOVIE_BACKEND = movie_backend or existing.MOVIE_BACKEND or ""
                existing.TV_BACKEND = tv_backend or existing.TV_BACKEND or ""
                existing.ANIME_BACKEND = anime_backend or existing.ANIME_BACKEND or ""
                existing.UNKNOWN_BACKEND = unknown_backend or existing.UNKNOWN_BACKEND or ""
            else:
                config = CONFIGMEDIA(
                    MOVIE_PATH=movie_path or "",
                    TV_PATH=tv_path or "",
                    ANIME_PATH=anime_path or "",
                    UNKNOWN_PATH=unknown_path or "",
                    MOVIE_BACKEND=movie_backend or "",
                    TV_BACKEND=tv_backend or "",
                    ANIME_BACKEND=anime_backend or "",
                    UNKNOWN_BACKEND=unknown_backend or "",
                )
                db.add(config)

    # ==================== Category Config ====================

    def get_category_configs(self) -> list[CONFIGCATEGORY]:
        with self.session() as db:
            return db.query(CONFIGCATEGORY).order_by(CONFIGCATEGORY.SORT_ORDER).all()

    def get_category_rules(self) -> list[CONFIGCATEGORYRULE]:
        with self.session() as db:
            return db.query(CONFIGCATEGORYRULE).all()

    def save_category_config(
        self, media_type: str, name: str, sort_order: int, is_default: int, rules: dict[str, str]
    ) -> int:
        with self.session() as db:
            existing = (
                db.query(CONFIGCATEGORY)
                .filter(
                    CONFIGCATEGORY.MEDIA_TYPE == media_type,
                    CONFIGCATEGORY.NAME == name,
                )
                .first()
            )
            if existing:
                existing.SORT_ORDER = sort_order
                existing.IS_DEFAULT = is_default
                cid = existing.ID
            else:
                cat = CONFIGCATEGORY(MEDIA_TYPE=media_type, NAME=name, SORT_ORDER=sort_order, IS_DEFAULT=is_default)
                db.add(cat)
                db.flush()
                cid = cat.ID

            db.query(CONFIGCATEGORYRULE).filter(CONFIGCATEGORYRULE.CATEGORY_ID == cid).delete()
            for field, value in rules.items():
                db.add(CONFIGCATEGORYRULE(CATEGORY_ID=cid, FIELD=field, VALUE=value))
            return int(cid)

    def delete_category_config(self, cid: int) -> None:
        with self.session() as db:
            db.query(CONFIGCATEGORYRULE).filter(CONFIGCATEGORYRULE.CATEGORY_ID == cid).delete()
            db.query(CONFIGCATEGORY).filter(CONFIGCATEGORY.ID == cid).delete()

    def clear_category_configs(self) -> None:
        with self.session() as db:
            db.query(CONFIGCATEGORYRULE).delete()
            db.query(CONFIGCATEGORY).delete()
