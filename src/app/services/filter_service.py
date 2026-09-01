import base64
import contextlib
import os
import re

from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, select

import log
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.module_config import ModuleConf
from app.db.repositories.config_repo_adapter import FilterGroupRepositoryAdapter, FilterRuleRepositoryAdapter
from app.db.sql_adapter import adapt_sql_for_engine
from app.domain.mediatypes import MediaType
from app.media import ReleaseGroupsMatcher, meta_info
from app.utils import StringUtils
from app.utils.json_utils import JsonUtils


class FilterRuleEngine:
    """
    过滤规则引擎（纯逻辑，无状态）
    负责种子与过滤规则的纯匹配计算
    """

    @staticmethod
    def check_rules(meta_info, rulegroup_info: dict, filters: list) -> tuple[bool, int, str]:
        """
        检查种子是否匹配站点过滤规则：排除规则、包含规则、优先规则
        :param meta_info: 识别的信息
        :param rulegroup_info: 已解析的规则组字典
        :param filters: 规则列表
        :return: 是否匹配，匹配的优先值，规则名称，值越大越优先
        """
        if not meta_info:
            return False, 0, ""

        title = meta_info.rev_string
        if meta_info.subtitle:
            title = f"{title} {meta_info.subtitle}"

        order_seq = 0
        group_match = True
        group_name = rulegroup_info.get("name", "")

        for filter_info in filters:
            try:
                rule_match = True
                order_seq = 100 - int(filter_info.get("pri", 0))

                # 必须包括的项
                includes = filter_info.get("include")
                if includes and rule_match:
                    include_flag = True
                    for include in includes:
                        if not include:
                            continue
                        if not re.search(rf"{include.strip()}", title, re.IGNORECASE):
                            include_flag = False
                            break
                    if not include_flag:
                        rule_match = False

                # 不能包含的项
                excludes = filter_info.get("exclude")
                if excludes and rule_match:
                    exclude_flag = False
                    exclude_count = 0
                    for exclude in excludes:
                        if not exclude:
                            continue
                        exclude_count += 1
                        if not re.search(rf"{exclude.strip()}", title, re.IGNORECASE):
                            exclude_flag = True
                    if exclude_count > 0 and not exclude_flag:
                        rule_match = False

                # 大小
                sizes = filter_info.get("size")
                if sizes and rule_match and meta_info.size:
                    meta_info.size = StringUtils.num_filesize(meta_info.size)
                    if sizes.find(",") != -1:
                        sizes = sizes.split(",")
                        begin_size = float(sizes[0].strip()) if StringUtils.is_numeric(sizes[0]) else 0
                        end_size = float(sizes[1].strip()) if StringUtils.is_numeric(sizes[1]) else 0
                    else:
                        begin_size = 0
                        end_size = float(sizes.strip()) if StringUtils.is_numeric(sizes) else 0

                    if meta_info.type == MediaType.MOVIE:
                        if not begin_size * (1024**3) <= int(meta_info.size) <= end_size * (1024**3):
                            rule_match = False
                    else:
                        if meta_info.total_episodes and not begin_size * (1024**3) <= int(meta_info.size) / int(
                            meta_info.total_episodes
                        ) <= end_size * (1024**3):
                            rule_match = False

                # 促销
                free = filter_info.get("free")
                if free and meta_info.upload_volume_factor is not None and meta_info.download_volume_factor is not None:
                    ul_factor, dl_factor = free.split()
                    if (
                        float(ul_factor) > meta_info.upload_volume_factor
                        or float(dl_factor) < meta_info.download_volume_factor
                    ):
                        rule_match = False

                if rule_match:
                    return True, order_seq, group_name
                else:
                    group_match = False
            except Exception as err:
                log.error(f"[Filter]过滤规则出现严重错误 {err}，请检查：{filter_info}")

        if not group_match:
            return False, 0, group_name
        return True, order_seq, group_name

    @staticmethod
    def check_torrent_filter(
        meta_info,
        filter_args: dict,
        rg_matcher: ReleaseGroupsMatcher,
        uploadvolumefactor=None,
        downloadvolumefactor=None,
    ) -> tuple[bool, int, str]:
        """
        对种子进行过滤
        :param meta_info: 名称识别后的MetaBase对象
        :param filter_args: 过滤条件的字典
        :param rg_matcher: 制作组匹配器
        :param uploadvolumefactor: 种子的上传因子，传空不过滤
        :param downloadvolumefactor: 种子的下载因子，传空不过滤
        :return: 是否匹配，匹配的优先值，匹配信息，值越大越优先
        """
        text = meta_info.rev_string
        if meta_info.subtitle:
            text = f"{text} {meta_info.subtitle}"

        # 过滤质量
        if filter_args.get("restype"):
            restype_values = [s.strip().upper() for s in str(filter_args.get("restype")).split(",") if s.strip()]
            restype_res = [ModuleConf.TORRENT_SEARCH_PARAMS["restype"].get(v) for v in restype_values]
            restype_res = [r for r in restype_res if r]
            if restype_res:
                if not meta_info.get_edtion_string():
                    return False, 0, f"{meta_info.org_string} 不符合质量 {filter_args.get('restype')} 要求"
                combined_re = "|".join(restype_res)
                if not re.search(rf"{combined_re}", meta_info.get_edtion_string(), re.I):
                    return False, 0, f"{meta_info.org_string} 不符合质量 {filter_args.get('restype')} 要求"

        # 过滤分辨率
        if filter_args.get("pix"):
            pix_values = [s.strip().lower() for s in str(filter_args.get("pix")).split(",") if s.strip()]
            pix_res = [ModuleConf.TORRENT_SEARCH_PARAMS["pix"].get(v) for v in pix_values]
            pix_res = [r for r in pix_res if r]
            if pix_res:
                if not meta_info.resource_pix:
                    return False, 0, f"{meta_info.org_string} 不符合分辨率 {filter_args.get('pix')} 要求"
                combined_re = "|".join(pix_res)
                if not re.search(rf"{combined_re}", meta_info.resource_pix, re.I):
                    return False, 0, f"{meta_info.org_string} 不符合分辨率 {filter_args.get('pix')} 要求"

        # 过滤制作组/字幕组
        if filter_args.get("team"):
            team = filter_args.get("team")
            if not meta_info.resource_team:
                resource_team = rg_matcher.match(title=meta_info.rev_string, groups=team)
                if not resource_team:
                    return False, 0, f"{meta_info.org_string} 不符合制作组/字幕组 {team} 要求"
                else:
                    meta_info.resource_team = resource_team
            elif not re.search(rf"{team}", meta_info.resource_team, re.I):
                return False, 0, f"{meta_info.org_string} 不符合制作组/字幕组 {team} 要求"

        # 过滤促销
        if filter_args.get("sp_state"):
            sp_state = filter_args.get("sp_state") or ""
            ul_factor, dl_factor = sp_state.split()
            if uploadvolumefactor and ul_factor not in ("*", str(uploadvolumefactor)):
                return False, 0, f"{meta_info.org_string} 不符合促销要求"
            if downloadvolumefactor and dl_factor not in ("*", str(downloadvolumefactor)):
                return False, 0, f"{meta_info.org_string} 不符合促销要求"

        # 过滤包含
        if filter_args.get("include"):
            include = filter_args.get("include")
            if not re.search(rf"{include}", text, re.I):
                return False, 0, f"{meta_info.org_string} 不符合包含 {include} 要求"

        # 过滤排除
        if filter_args.get("exclude"):
            exclude = filter_args.get("exclude")
            if re.search(rf"{exclude}", text, re.I):
                return False, 0, f"{meta_info.org_string} 不符合排除 {exclude} 要求"

        # 过滤关键字
        if filter_args.get("key"):
            key = filter_args.get("key")
            if not re.search(rf"{key}", text, re.I):
                return False, 0, f"{meta_info.org_string} 不符合 {key} 要求"

        return True, 0, ""

    @staticmethod
    def is_torrent_match_sey(media_info, s_num, e_num, year_str):
        """
        种子名称关键字匹配
        :param media_info: 已识别的种子信息
        :param s_num: 要匹配的季号，为空则不匹配
        :param e_num: 要匹配的集号，为空则不匹配
        :param year_str: 要匹配的年份，为空则不匹配
        :return: 是否命中
        """
        if s_num:
            if not media_info.get_season_list():
                return False
            if not isinstance(s_num, list):
                s_num = [s_num]
            if not set(s_num).issuperset(set(media_info.get_season_list())):
                return False
        if e_num:
            if not isinstance(e_num, list):
                e_num = [e_num]
            if not set(e_num).issuperset(set(media_info.get_episode_list())):
                return False
        if year_str:
            if str(media_info.year) != str(year_str):
                return False
        return True


class FilterService:
    """
    过滤业务服务
    负责规则数据加载与规则匹配调度
    """

    def __init__(
        self,
        filter_group_repo: FilterGroupRepositoryAdapter,
        filter_rule_repo: FilterRuleRepositoryAdapter,
        rg_matcher: ReleaseGroupsMatcher,
    ):
        self._filter_group_repo = filter_group_repo
        self._filter_rule_repo = filter_rule_repo
        self._rg_matcher = rg_matcher
        self._groups = []
        self._rules = []
        self.reload()

    def reload(self):
        """重新加载过滤规则数据"""
        self._groups = self._filter_group_repo.get_config_filter_group() or []
        self._rules = self._filter_rule_repo.get_config_filter_rule() or []

    # ------------------- 规则组查询 -------------------

    def get_rule_groups(self, groupid=None, default=False) -> dict | list:
        """获取所有规则组"""
        ret_groups = []
        for group in self._groups:
            group_info = {"id": group.ID, "name": group.GROUP_NAME, "default": group.IS_DEFAULT, "note": group.NOTE}
            if (groupid and str(groupid) == str(group.ID)) or (default and str(group.IS_DEFAULT or "") == "Y"):
                return group_info
            ret_groups.append(group_info)
        if groupid or default:
            return {}
        return ret_groups

    def get_rule_infos(self):
        """获取所有的规则组及组内的规则"""
        groups = self.get_rule_groups()
        for group in groups:
            group["rules"] = self.get_rules(group.get("id"))
        return groups

    def get_rules(self, groupid, ruleid=None):
        """获取过滤规则"""
        if not groupid:
            return []
        ret_rules = []
        for rule in self._rules:
            rule_info = {
                "id": rule.ID,
                "group": rule.GROUP_ID,
                "name": rule.ROLE_NAME,
                "pri": rule.PRIORITY or 0,
                "include": str(rule.INCLUDE or "").split("\n") if rule.INCLUDE is not None else [],
                "exclude": str(rule.EXCLUDE or "").split("\n") if rule.EXCLUDE is not None else [],
                "size": rule.SIZE_LIMIT,
                "free": rule.NOTE,
                "free_text": {"1.0 1.0": "普通", "1.0 0.0": "免费", "2.0 0.0": "2X免费"}.get(
                    str(rule.NOTE or ""), "全部"
                )
                if rule.NOTE is not None
                else "",
            }
            if str(rule.GROUP_ID) == str(groupid) and (not ruleid or int(ruleid) == rule.ID):
                ret_rules.append(rule_info)
        if ruleid:
            return ret_rules[0] if ret_rules else {}
        return ret_rules

    def get_rule_first_order(self, rulegroup):
        """获取规则的最高优先级"""
        if not rulegroup:
            rulegroup = self.get_rule_groups(default=True)
        first_order = min(
            [
                int(rule_info.get("pri"))
                for rule_info in self.get_rules(
                    groupid=rulegroup.get("id") if isinstance(rulegroup, dict) else rulegroup
                )
            ]
            or [0]
        )
        return 100 - first_order

    # ------------------- 规则匹配 -------------------

    def check_rules(self, meta_info, rulegroup=None):
        """检查种子是否匹配站点过滤规则"""
        if not meta_info:
            return False, 0, ""
        if rulegroup and int(rulegroup) == -1:
            return True, 0, "不过滤"

        if not rulegroup:
            rulegroup = self.get_rule_groups(default=True)
            if not rulegroup:
                return True, 0, "未配置过滤规则"
        else:
            rulegroup = self.get_rule_groups(groupid=rulegroup)

        filters = self.get_rules(groupid=rulegroup.get("id") if isinstance(rulegroup, dict) else rulegroup)
        return FilterRuleEngine.check_rules(
            meta_info, rulegroup if isinstance(rulegroup, dict) else {}, filters if isinstance(filters, list) else []
        )

    def is_torrent_match_sey(self, media_info, s_num, e_num, year_str):
        """兼容方法：委托给 FilterRuleEngine"""
        return FilterRuleEngine.is_torrent_match_sey(media_info, s_num, e_num, year_str)

    def is_rule_free(self, rulegroup=None):
        """判断规则中是否需要Free检测"""
        if not rulegroup:
            rulegroup = self.get_rule_groups(default=True)
            if not rulegroup:
                return False
        else:
            rulegroup = self.get_rule_groups(groupid=rulegroup)
        filters = self.get_rules(groupid=rulegroup.get("id") if isinstance(rulegroup, dict) else rulegroup)
        return any(filter_info.get("free") for filter_info in filters)

    def check_torrent_filter(self, meta_info, filter_args, uploadvolumefactor=None, downloadvolumefactor=None):
        """对种子进行过滤"""
        match_flag, order_seq, match_msg = FilterRuleEngine.check_torrent_filter(
            meta_info, filter_args, self._rg_matcher, uploadvolumefactor, downloadvolumefactor
        )
        if not match_flag:
            return match_flag, order_seq, match_msg

        # 过滤过滤规则，-1表示不使用过滤规则，空则使用默认过滤规则
        size_str = StringUtils.str_filesize(meta_info.size)
        factor_str = meta_info.get_volume_factor_string()
        org = meta_info.org_string
        if filter_args.get("rule"):
            match_flag, order_seq, rule_name = self.check_rules(meta_info, filter_args.get("rule"))
            match_msg = f"{org} 大小：{size_str} 促销：{factor_str} 不符合订阅/站点过滤规则 {rule_name} 要求"
            return match_flag, order_seq, match_msg
        else:
            match_flag, order_seq, rule_name = self.check_rules(meta_info)
            match_msg = f"{org} 大小：{size_str} 促销：{factor_str} 不符合默认过滤规则 {rule_name} 要求"
            return match_flag, order_seq, match_msg

    # ------------------- 规则管理 -------------------

    def add_group(self, name, default="N"):
        """添加过滤规则组"""
        ret = self._filter_group_repo.add_filter_group(name, default)
        self.reload()
        return ret

    def delete_filtergroup(self, groupid):
        """删除过滤规则组"""
        ret = self._filter_group_repo.delete_filtergroup(groupid)
        self.reload()
        return ret

    def set_default_filtergroup(self, groupid):
        """设置默认过滤规则组"""
        ret = self._filter_group_repo.set_default_filtergroup(groupid)
        self.reload()
        return ret

    def add_filter_rule(self, item, ruleid=None):
        """添加过滤规则"""
        ret = self._filter_rule_repo.insert_filter_rule(item, ruleid)
        self.reload()
        return ret

    def delete_filterrule(self, ruleid):
        """删除过滤规则"""
        ret = self._filter_rule_repo.delete_filterrule(ruleid)
        self.reload()
        return ret

    def get_filter_group(self, gid=None):
        """获取过滤规则组"""
        return self._filter_group_repo.get_config_filter_group(gid)

    def get_filter_rule(self, groupid=None):
        """获取过滤规则"""
        return self._filter_rule_repo.get_config_filter_rule(groupid)

    def get_filter_groupid_by_name(self, name):
        """根据名称获取过滤规则组ID"""
        return self._filter_group_repo.get_filter_groupid_by_name(name)

    def import_filter_group(self, content: str) -> None:
        """导入规则组（Base64编码的JSON字符串），失败时抛出异常"""
        try:
            json_str = base64.b64decode(str(content).encode("utf-8")).decode("utf-8")
            json_obj = JsonUtils.loads(json_str)
        except Exception as err:
            raise ValidationError(f"数据格式不正确，{err}") from err

        if not json_obj or not json_obj.get("name"):
            raise ValidationError("数据格式不正确")
        self.add_group(name=json_obj.get("name"))
        group_id = self.get_filter_groupid_by_name(json_obj.get("name"))
        if not group_id:
            raise ValidationError("数据内容不正确")
        if json_obj.get("rules"):
            for rule in json_obj.get("rules"):
                self.add_filter_rule(
                    item={
                        "group": group_id,
                        "name": rule.get("name"),
                        "pri": rule.get("pri"),
                        "include": rule.get("include"),
                        "exclude": rule.get("exclude"),
                        "size": rule.get("size"),
                        "free": rule.get("free"),
                    }
                )

    def restore_filter_group(self, groupids: list, init_rulegroups: list) -> None:
        """恢复初始规则组"""
        for groupid in groupids:
            with contextlib.suppress(Exception):
                self.delete_filtergroup(groupid)
            for init_rulegroup in init_rulegroups:
                if str(init_rulegroup.get("id")) == groupid:
                    for sql in init_rulegroup.get("sql", []):
                        self._filter_group_repo._repo._execute_raw(adapt_sql_for_engine(sql))

    def get_filterrules(self, script_path: str):
        """获取所有过滤规则及初始规则"""
        rule_groups = self.get_rule_infos()
        sql_file = os.path.join(script_path, "init_filter.sql")
        init_rule_groups = self._load_init_rule_groups(sql_file) if os.path.exists(sql_file) else []
        return rule_groups, init_rule_groups

    @staticmethod
    def _load_init_rule_groups(sql_file: str) -> list[dict]:
        """解析内置过滤规则 SQL 文件.

        数据在内存 SQLite 中实际执行后读回，避免文本解析受正则/换行/转义影响；
        同时保留原始 SQL 语句块供「恢复规则组」直接执行。
        """
        with open(sql_file, encoding="utf-8") as f:
            content = f.read()

        entries: list[dict] = []
        for stmt in content.split(";\n"):
            stmt = stmt.strip()
            if not stmt or "INSERT" not in stmt.upper():
                continue
            upper = stmt.upper()
            if "CONFIG_FILTER_GROUP" in upper:
                match = re.search(r"VALUES\s*\(\s*(\d+)", stmt, re.I)
                if match:
                    entries.append({"id": int(match.group(1)), "sql": [stmt]})
            elif "CONFIG_FILTER_RULES" in upper and entries:
                entries[-1]["sql"].append(stmt)

        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        group_table = Table(
            "CONFIG_FILTER_GROUP",
            metadata,
            Column("ID", Integer, primary_key=True),
            Column("GROUP_NAME", Text),
            Column("IS_DEFAULT", Text),
            Column("NOTE", Text),
        )
        rule_table = Table(
            "CONFIG_FILTER_RULES",
            metadata,
            Column("ID", Integer, primary_key=True),
            Column("GROUP_ID", Integer),
            Column("ROLE_NAME", Text),
            Column("PRIORITY", Text),
            Column("INCLUDE", Text),
            Column("EXCLUDE", Text),
            Column("SIZE_LIMIT", Text),
            Column("NOTE", Text),
        )
        try:
            with engine.begin() as conn:
                metadata.create_all(conn)
                for entry in entries:
                    for stmt in entry["sql"]:
                        conn.exec_driver_sql(stmt)
                names = {row[0]: row[1] for row in conn.execute(select(group_table.c.ID, group_table.c.GROUP_NAME))}
                rule_rows: dict[int, list] = {}
                rows = conn.execute(
                    select(
                        rule_table.c.GROUP_ID,
                        rule_table.c.ROLE_NAME,
                        rule_table.c.INCLUDE,
                        rule_table.c.EXCLUDE,
                    ).order_by(rule_table.c.ID)
                ).all()
                for gid, name, include, exclude in rows:
                    rule_rows.setdefault(gid, []).append({"name": name, "include": include, "exclude": exclude})
        finally:
            engine.dispose()

        return [
            {
                "id": entry["id"],
                "name": names.get(entry["id"], ""),
                "rules": rule_rows.get(entry["id"], []),
                "sql": entry["sql"],
            }
            for entry in entries
        ]

    def share_filter_group(self, gid) -> str:
        """分享规则组（返回Base64编码的JSON字符串），失败时抛出异常"""
        group_info = self.get_filter_group(gid=gid)
        if not group_info:
            raise ResourceNotFoundError("规则组不存在")
        group_rules = self.get_filter_rule(groupid=gid)
        if not group_rules:
            raise ResourceNotFoundError("规则组没有对应规则")
        rules = []
        for rule in group_rules:
            rules.append(
                {
                    "name": rule.ROLE_NAME,
                    "pri": rule.PRIORITY,
                    "include": rule.INCLUDE,
                    "exclude": rule.EXCLUDE,
                    "size": rule.SIZE_LIMIT,
                    "free": rule.NOTE,
                }
            )
        rule_json = {"name": group_info[0].GROUP_NAME, "rules": rules}
        return base64.b64encode(JsonUtils.dumps(rule_json).encode("utf-8")).decode("utf-8")

    def test_rule(
        self, title: str, subtitle: str | None, size: str | None, rulegroup: str | None
    ) -> tuple[bool, str, int]:
        """测试规则是否匹配给定标题"""
        mi = meta_info(title=title, subtitle=subtitle)
        mi.size = int(float(size) * 1024**3) if size else 0
        match_flag, res_order, match_msg = self.check_torrent_filter(meta_info=mi, filter_args={"rule": rulegroup})
        text = "匹配" if match_flag else "未匹配"
        order = 100 - res_order if res_order else 0
        return match_flag, text, order

    def get_rule_detail(self, groupid, ruleid) -> dict:
        """获取规则详情（include/exclude 转为换行字符串）"""
        ruleinfo = self.get_rules(groupid=groupid, ruleid=ruleid)
        if ruleinfo and isinstance(ruleinfo, dict):
            ruleinfo["include"] = "\n".join(ruleinfo.get("include", []))
            ruleinfo["exclude"] = "\n".join(ruleinfo.get("exclude", []))
        return ruleinfo if isinstance(ruleinfo, dict) else {}
