"""
刷流任务规则引擎（领域层）
集中处理 RSS选种规则、删种规则、停种规则 的解析与检查

设计原则：
- 纯规则逻辑，不依赖数据库、Service 或应用层对象
- 需要的外部数据通过参数传入
- 调用方（BrushTaskService）负责获取数据并传入
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import dateutil
import dateutil.parser
import pytz

import log
from app.domain.enums import BrushDeleteType, BrushStopType, SwitchState
from app.domain.mediatypes import MediaType
from app.utils import ExceptionUtils, JsonUtils, StringUtils


def _calc_alive_hours(add_time: str | None) -> float | None:
    if not add_time:
        return None
    try:
        dt = dateutil.parser.parse(str(add_time))
        if dt.tzinfo is None:
            # naive 视为服务器本地时间，统一转 aware 后与 UTC now 相减
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return (datetime.now(pytz.utc) - dt.astimezone(pytz.utc)).total_seconds() / 3600
    except Exception:
        return None


class BrushRuleEngine:
    """刷流规则引擎 — 纯领域逻辑，不持有任何外部依赖"""

    # 操作符映射，用于前端展示
    OP_DISPLAY = {"gt": ">", "lt": "<", "bw": ""}

    # --------------------------------------------------
    # 通用范围检查
    # --------------------------------------------------
    @staticmethod
    def check_range_rule(value: float | int | None, rule_value: str, multiplier: float = 1.0) -> bool:
        """
        通用范围规则检查函数
        :param value: 实际值
        :param rule_value: 规则值，格式为 'operator#min,max'
        :param multiplier: 可选，值的单位倍数，比如 1024 ** 3 表示 GB，3600 表示小时
        """
        if value is None:
            return True
        if not rule_value or not isinstance(rule_value, str):
            return True

        rule_parts = rule_value.split("#")
        if len(rule_parts) < 2 or not rule_parts[1]:
            return True

        operator = rule_parts[0]
        range_values = rule_parts[1].split(",")

        try:
            min_value = float(range_values[0]) * multiplier if range_values[0] else 0.0
            max_value = float(range_values[1]) * multiplier if len(range_values) > 1 and range_values[1] else None
        except (ValueError, TypeError):
            return True

        if operator == "gt" and value < min_value:
            return False
        if operator == "lt" and value > min_value:
            return False
        return not (operator == "bw" and (value < min_value or max_value is not None and value >= max_value))

    # --------------------------------------------------
    # RSS 选种规则
    # --------------------------------------------------
    @classmethod
    def check_rss_rule(
        cls,
        rss_rule: dict | None,
        title: str,
        torrent_size: float,
        pubdate: datetime | None,
        torrent_attr: dict,
        category: str = "",
        labels: str = "",
        media_info: Any = None,
        rss_movies: dict | None = None,
        rss_tvs: dict | None = None,
    ) -> bool:
        """
        检查种子是否符合刷流过滤条件

        :param rss_rule: RSS 选种规则
        :param title: 种子标题
        :param torrent_size: 种子体积（字节）
        :param pubdate: 发布时间
        :param torrent_attr: 种子属性（free/hr/peer_count 等）
        :param media_info: 已识别的媒体信息（用于排除已订阅，由调用方提供）
        :param rss_movies: 电影订阅列表（用于排除已订阅，由调用方提供）
        :param rss_tvs: 电视剧订阅列表（用于排除已订阅，由调用方提供）
        """
        if not rss_rule:
            return True

        try:
            rule_checks: dict[str, Callable[[Any], bool]] = {
                "size": lambda rv: cls.check_range_rule(torrent_size, rv, 1024**3),
                "include": lambda rv: bool(re.search(rv, title, re.IGNORECASE)),
                "exclude": lambda rv: not bool(re.search(rv, title, re.IGNORECASE)),
                "category_include": lambda rv: bool(re.search(rv, category or "", re.IGNORECASE)),
                "category_exclude": lambda rv: not bool(re.search(rv, category or "", re.IGNORECASE)),
                "label_include": lambda rv: bool(re.search(rv, labels or "", re.IGNORECASE)),
                "label_exclude": lambda rv: not bool(re.search(rv, labels or "", re.IGNORECASE)),
                "free": lambda rv: cls._check_free_status(torrent_attr, rv),
                "hr": lambda _rv: not torrent_attr.get("hr"),
                "peercount": lambda rv: cls.check_range_rule(torrent_attr.get("peer_count"), rv),
                "pubdate": lambda rv: cls._check_pubdate(pubdate, torrent_attr, rv),
                "exclude_subscribe": lambda rv: not cls._check_subscribe_status(media_info, rss_movies, rss_tvs, rv),
            }

            for rule, check_func in rule_checks.items():
                rule_value = rss_rule.get(rule)
                log.debug(f"检查字段: {rule}, 规则值: {rule_value}")
                if rule_value in ("#", SwitchState.OFF.value, None, ""):
                    log.debug(f"规则 {rule} 被设置为忽略，跳过检查")
                    continue
                if not check_func(rule_value):
                    log.debug(f"字段: {rule} 不符合规则")
                    return False
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

        return True

    @staticmethod
    def _check_free_status(torrent_attr: dict, rule_value: str) -> bool:
        if rule_value == "FREE" and not torrent_attr.get("free"):
            return False
        if rule_value == "2XFREE" and not torrent_attr.get("2xfree"):
            return False
        return not (rule_value == "NORMAL" and (torrent_attr.get("free") or torrent_attr.get("2xfree")))

    @classmethod
    def _check_pubdate(cls, pubdate: datetime | None, torrent_attr: dict, rule_value: str) -> bool:
        if torrent_attr.get("pubdate"):
            local_time_str = torrent_attr.get("pubdate")
            try:
                if local_time_str:
                    pubdate = dateutil.parser.parse(str(local_time_str)).replace(tzinfo=timezone(timedelta(hours=8)))
            except Exception:
                pubdate = None

        if pubdate:
            pubdate_hours = (datetime.now(pytz.utc) - pubdate).total_seconds() / 3600
            return cls.check_range_rule(pubdate_hours, rule_value, multiplier=1)
        return True

    @staticmethod
    def _check_subscribe_status(
        media_info: Any,
        rss_movies: dict | None,
        rss_tvs: dict | None,
        rule_value: str,
    ) -> bool:
        """排除已订阅的媒体 — 纯逻辑，数据由调用方提供"""
        if rule_value == SwitchState.OFF.value:
            return False
        if not media_info:
            return False

        match_flag = False
        # 匹配电影
        if media_info.type == MediaType.MOVIE and rss_movies:
            for rss_info in rss_movies.values():
                if BrushRuleEngine._match_media(media_info, rss_info):
                    match_flag = True
                    break
        # 匹配电视剧
        elif rss_tvs:
            for rss_info in rss_tvs.values():
                rss_sites = BrushRuleEngine._parse_rss_sites(rss_info.get("rss_sites"))
                # media_info.site 为空时无法按站点过滤（站点未知不误排除，交由名称匹配决定）
                if media_info.site and rss_sites and media_info.site not in rss_sites:
                    continue
                if BrushRuleEngine._match_media(media_info, rss_info, is_tv=True):
                    match_flag = True
                    break

        return match_flag

    @staticmethod
    def _parse_rss_sites(rss_sites: Any) -> list:
        """兼容订阅 rss_sites 的多种存储格式：JSON 数组字符串 / 逗号分隔字符串 / 列表"""
        if not rss_sites:
            return []
        if isinstance(rss_sites, list):
            return [str(s) for s in rss_sites]
        if isinstance(rss_sites, str):
            try:
                parsed = JsonUtils.loads(rss_sites)
                if isinstance(parsed, list):
                    return [str(s) for s in parsed]
            except (ValueError, TypeError):
                pass
            return [s.strip() for s in rss_sites.split(",") if s.strip()]
        return [str(rss_sites)]

    @staticmethod
    def _match_media(media_info, rss_info: dict, is_tv: bool = False) -> bool:
        """单个订阅与媒体信息匹配"""
        name = rss_info.get("name")
        year = rss_info.get("year")
        tmdbid = rss_info.get("tmdbid")
        fuzzy_match = rss_info.get("fuzzy_match")
        season = rss_info.get("season") if is_tv else None

        if not fuzzy_match:
            if tmdbid and not str(tmdbid).startswith("DB:"):
                if str(media_info.tmdb_id) != str(tmdbid):
                    return False
            else:
                if year and str(media_info.year) not in [str(year), str(int(year) + 1), str(int(year) - 1)]:
                    return False
                if name != media_info.title:
                    return False
            if is_tv and season and season != media_info.get_season_string():
                return False
        else:
            if is_tv and season and season != "S00" and season != media_info.get_season_string():
                return False
            if year and str(year) != str(media_info.year):
                return False
            search_title = f"{media_info.rev_string} {media_info.title} {media_info.year}"
            if name and (not re.search(name, search_title, re.I) and name not in search_title):
                return False
        return True

    # --------------------------------------------------
    # 删种规则
    # --------------------------------------------------
    @classmethod
    def check_remove_rule(
        cls, remove_rule: dict | None, params: dict
    ) -> tuple[bool, BrushDeleteType | list[BrushDeleteType]]:
        """
        检查是否符合删种规则
        :param remove_rule: 删种规则，包含 mode 字段来决定使用 and 或 or 模式
        :param params: 一个字典，包含所有要检查的参数
        """
        if not remove_rule:
            return False, BrushDeleteType.NOTDELETE

        values = {
            "time": params.get("seeding_time"),
            "hr_time": params.get("seeding_time"),
            "ratio": params.get("ratio"),
            "uploadsize": params.get("uploaded"),
            "dltime": params.get("dltime"),
            "avg_upspeed": params.get("avg_upspeed"),
            "upspeed": params.get("upspeed"),
            "iatime": params.get("iatime"),
            "pending_time": params.get("pending_time"),
            "freespace": params.get("freespace"),
            "alive_time": _calc_alive_hours(params.get("add_time")),
            "freestatus": params.get("torrent_attr", {}).get("free", False),
            "hr": params.get("torrent_attr", {}).get("hr", False),
            "tracker_error": params.get("tracker_error"),
        }

        rule_checks = {
            "time": (BrushDeleteType.SEEDTIME, lambda value, rv: cls.check_range_rule(value, rv, 3600)),
            "hr_time": (BrushDeleteType.HRSEEDTIME, lambda value, rv: cls.check_range_rule(value, rv, 3600)),
            "ratio": (BrushDeleteType.RATIO, lambda value, rv: cls.check_range_rule(value, rv)),
            "uploadsize": (BrushDeleteType.UPLOADSIZE, lambda value, rv: cls.check_range_rule(value, rv, 1024**3)),
            "dltime": (BrushDeleteType.DLTIME, lambda value, rv: cls.check_range_rule(value, rv, 3600)),
            "avg_upspeed": (BrushDeleteType.AVGUPSPEED, lambda value, rv: cls.check_range_rule(value, rv, 1024)),
            "iatime": (BrushDeleteType.IATIME, lambda value, rv: cls.check_range_rule(value, rv, 3600)),
            "pending_time": (BrushDeleteType.PENDINGTIME, lambda value, rv: cls.check_range_rule(value, rv, 3600)),
            "freespace": (BrushDeleteType.FREESPACE, lambda value, rv: cls.check_range_rule(value, rv, 1024**3)),
            # freestatus = “Free到期删”：仍免费时不删，Free 到期（非免费）才删；
            # 该键开关（前端以 'Y' 存储，历史模板也可能为 FREE/NORMAL），
            # 关闭态已在循环外跳过，这里统一按到期语义判断，杜绝“免费即删”误删。
            "freestatus": (
                BrushDeleteType.FREESTATUS,
                lambda value, rv: not value,
            ),
            "hr": (BrushDeleteType.HR, lambda value, rv: value if rv == "HR" else not value if rv == "NOHR" else True),
            "alive_time": (BrushDeleteType.ALIVETIME, lambda value, rv: cls.check_range_rule(value, rv, 1)),
            "upspeed": (BrushDeleteType.UPSPEED, lambda value, rv: cls.check_range_rule(value, rv, 1024)),
            "tracker_error": (
                BrushDeleteType.TRACKERERROR,
                lambda value, rv: bool(value) if rv in (SwitchState.ON.value, "Y") else True,
            ),
        }

        triggered_types = []
        mode = remove_rule.get("mode", "and")
        log.info(
            f"[删种规则] 当前值 ratio={values['ratio']}, 做种={values['time']}s, "
            f"上传={values['uploadsize']}B, 活了{values['alive_time']}h, "
            f"free={values['freestatus']}, tracker_err={bool(values['tracker_error'])}"
        )

        for rule, (delete_type, check_func) in rule_checks.items():
            rule_value = remove_rule.get(rule)
            if rule_value in ("#", SwitchState.OFF.value, None, ""):
                continue

            # hr_time 规则仅对 HR 种子生效，非 HR 种子在两种模式下都跳过
            if rule == "hr_time" and not params.get("torrent_attr", {}).get("hr"):
                log.info("[删种规则] hr_time 仅对 HR 种子生效，跳过非 HR 种子")
                continue

            value = values.get(rule)
            if value is None:
                log.info(
                    f"[删种规则] {rule}={rule_value}, 但种子无此数据 (None)，"
                    f"模式={mode}，" + ("阻止删种" if mode == "and" else "跳过该规则")
                )
                if mode == "and":
                    return False, BrushDeleteType.NOTDELETE
                continue

            matched = check_func(value, rule_value)
            if matched:
                triggered_types.append(delete_type)
                log.info(f"[删种规则] {rule} 触发: 当前={value}, 规则={rule_value}")
                if mode == "or":
                    _t = triggered_types
                    return True, _t[0] if len(_t) == 1 else _t  # type: ignore[return-value]
            else:
                log.info(f"[删种规则] {rule} 未触发: 当前={value}, 规则={rule_value}")
                if mode == "and":
                    return False, BrushDeleteType.NOTDELETE

        if mode == "and" and triggered_types:
            return True, triggered_types
        return False, BrushDeleteType.NOTDELETE

    # --------------------------------------------------
    # 停种规则
    # --------------------------------------------------
    @classmethod
    def check_stop_rule(cls, stop_rule: dict | None, params: dict):
        if not stop_rule:
            return False, BrushStopType.NOTSTOP

        values = {
            "ratio": params.get("ratio"),
            "uploadsize": params.get("uploaded"),
            "seedtime": params.get("seeding_time"),
            "avg_upspeed": params.get("avg_upspeed"),
            "stopfree": params.get("free"),
        }

        rule_checks = {
            "ratio": (BrushStopType.RATIO, lambda rv: cls.check_range_rule(values["ratio"], rv)),
            "uploadsize": (
                BrushStopType.UPLOADSIZE,
                lambda rv: cls.check_range_rule(values["uploadsize"], rv, 1024**3),
            ),
            "seedtime": (
                BrushStopType.SEEDTIME,
                lambda rv: cls.check_range_rule(values["seedtime"], rv, 3600),
            ),
            "avg_upspeed": (
                BrushStopType.AVGUPSPEED,
                lambda rv: cls.check_range_rule(values["avg_upspeed"], rv, 1024),
            ),
            # stopfree = “Free到期停”：仍免费不停，Free 到期（非免费）才停；
            # 前端以 'Y' 存储，历史模板可能为 'ON'，关闭态已在循环外跳过，统一按到期语义判断。
            "stopfree": (
                BrushStopType.FREEEND,
                lambda rv: not values["stopfree"],
            ),
        }

        log.info(
            f"[停种规则] ratio={values['ratio']}, 做种={values['seedtime']}s, "
            f"上传={values['uploadsize']}B, avg={values['avg_upspeed']}, "
            f"free={values['stopfree']}"
        )

        for rule, (stop_type, check_func) in rule_checks.items():
            rule_value = stop_rule.get(rule)
            if rule_value in ("#", SwitchState.OFF.value, None, ""):
                continue
            if check_func(rule_value):
                log.info(f"[停种规则] {rule} 触发: 规则={rule_value}")
                return True, stop_type
            log.info(f"[停种规则] {rule} 未触发: 规则={rule_value}")
        return False, BrushStopType.NOTSTOP

    # --------------------------------------------------
    # RSS 拒绝原因
    # --------------------------------------------------
    _RULE_FAIL_REASONS = {
        "size": "体积不符合",
        "include": "标题不匹配",
        "exclude": "排除关键词命中",
        "category_include": "分类不匹配",
        "category_exclude": "分类排除命中",
        "label_include": "标签不匹配",
        "label_exclude": "标签排除命中",
        "free": "优惠状态不符合",
        "hr": "命中 HR",
        "peercount": "做种人数不符合",
        "pubdate": "发布时间不符合",
        "exclude_subscribe": "已订阅",
    }

    @classmethod
    def get_rss_reject_reason(
        cls,
        rss_rule: dict | None,
        title: str,
        torrent_size: float,
        pubdate: datetime | None,
        torrent_attr: dict,
        category: str = "",
        labels: str = "",
        media_info: Any = None,
        rss_movies: dict | None = None,
        rss_tvs: dict | None = None,
    ) -> str:
        if not rss_rule:
            return ""

        try:
            rule_checks: dict[str, Callable[[Any], bool]] = {
                "size": lambda rv: cls.check_range_rule(torrent_size, rv, 1024**3),
                "include": lambda rv: bool(re.search(rv, title, re.IGNORECASE)),
                "exclude": lambda rv: not bool(re.search(rv, title, re.IGNORECASE)),
                "category_include": lambda rv: bool(re.search(rv, category or "", re.IGNORECASE)),
                "category_exclude": lambda rv: not bool(re.search(rv, category or "", re.IGNORECASE)),
                "label_include": lambda rv: bool(re.search(rv, labels or "", re.IGNORECASE)),
                "label_exclude": lambda rv: not bool(re.search(rv, labels or "", re.IGNORECASE)),
                "free": lambda rv: cls._check_free_status(torrent_attr, rv),
                "hr": lambda _rv: not torrent_attr.get("hr"),
                "peercount": lambda rv: cls.check_range_rule(torrent_attr.get("peer_count"), rv),
                "pubdate": lambda rv: cls._check_pubdate(pubdate, torrent_attr, rv),
                "exclude_subscribe": lambda rv: not cls._check_subscribe_status(media_info, rss_movies, rss_tvs, rv),
            }

            for rule, check_func in rule_checks.items():
                rule_value = rss_rule.get(rule)
                if rule_value in ("#", SwitchState.OFF.value, None, ""):
                    continue
                if not check_func(rule_value):
                    return cls._RULE_FAIL_REASONS.get(rule, rule)
        except Exception:
            return "规则检查异常"

        return ""

    # --------------------------------------------------
    # RSS 匹配原因格式化
    # --------------------------------------------------
    @staticmethod
    def format_rss_match_reason(rss_rule: dict | None) -> str:
        if not rss_rule:
            return "RSS 进种"

        parts: list[str] = []

        free_val = rss_rule.get("free")
        if free_val == "FREE":
            parts.append("免费")
        elif free_val == "2XFREE":
            parts.append("2X免费")
        elif free_val == "NORMAL":
            parts.append("普通种")

        hr_val = rss_rule.get("hr")
        if hr_val and hr_val not in ("#", "", None):
            parts.append("排除HR")

        size_val = rss_rule.get("size")
        if size_val and size_val not in ("#", "", None):
            parts.append("体积符合")

        pubdate_val = rss_rule.get("pubdate")
        if pubdate_val and pubdate_val not in ("#", "", None):
            parts.append("发布时间符合")

        include_val = rss_rule.get("include")
        if include_val and include_val not in ("#", "", None):
            parts.append("标题匹配")

        exclude_val = rss_rule.get("exclude")
        if exclude_val and exclude_val not in ("#", "", None):
            parts.append("排除过滤")

        category_include_val = rss_rule.get("category_include")
        if category_include_val and category_include_val not in ("#", "", None):
            parts.append("分类匹配")

        category_exclude_val = rss_rule.get("category_exclude")
        if category_exclude_val and category_exclude_val not in ("#", "", None):
            parts.append("分类排除")

        label_include_val = rss_rule.get("label_include")
        if label_include_val and label_include_val not in ("#", "", None):
            parts.append("标签匹配")

        label_exclude_val = rss_rule.get("label_exclude")
        if label_exclude_val and label_exclude_val not in ("#", "", None):
            parts.append("标签排除")

        peercount_val = rss_rule.get("peercount")
        if peercount_val and peercount_val not in ("#", "", None):
            parts.append("做种人数符合")

        exclude_sub_val = rss_rule.get("exclude_subscribe")
        if exclude_sub_val and exclude_sub_val not in ("#", "", None):
            parts.append("排除已订阅")

        if not parts:
            return "RSS 进种"
        return ", ".join(parts)

    # --------------------------------------------------
    # 辅助方法
    # --------------------------------------------------
    @staticmethod
    def parse_rule_string(rule_str: str) -> dict:
        """解析规则字符串为字典"""
        rules = {}
        if not rule_str:
            return rules

        for item in rule_str.split("&&"):
            item = item.strip()
            if "#" in item:
                key, value = item.split("#", 1)
                rules[key.strip()] = value.strip()
        return rules

    @staticmethod
    def format_rule_string(rules: dict) -> str:
        """将规则字典格式化为字符串"""
        if not rules:
            return ""
        return " && ".join(f"{k}#{v}" for k, v in rules.items() if v not in (None, "", "#"))

    @classmethod
    def format_rule_html(cls, rules: dict | None) -> str:
        """将规则字典渲染为 HTML badge 字符串"""
        if not rules:
            return ""

        rule_htmls: list[str] = []

        if rules.get("exclude_subscribe") == SwitchState.ON.value:
            rule_htmls.append(cls._badge("排除订阅: 开", "text-green", "排除订阅"))
        elif rules.get("exclude_subscribe"):
            rule_htmls.append(cls._badge("排除订阅: 关", "text-green", "排除订阅"))

        for key, title, color, unit in [
            ("size", "种子大小", "text-blue", "GB"),
            ("pubdate", "发布时间", "text-blue", "小时"),
        ]:
            cls._append_range_badge(rule_htmls, rules, key, title, color, unit)

        if rules.get("upspeed"):
            rule_htmls.append(
                cls._badge(f"上传限速: {cls._filesize(int(rules['upspeed']) * 1024)}B/s", "text-blue", "上传限速")
            )
        if rules.get("downspeed"):
            rule_htmls.append(
                cls._badge(f"下载限速: {cls._filesize(int(rules['downspeed']) * 1024)}B/s", "text-blue", "下载限速")
            )

        if rules.get("include"):
            rule_htmls.append(cls._badge_wrap(f"包含: {rules['include']}", "text-green", "包含规则"))
        if rules.get("hr"):
            rule_htmls.append(cls._badge("排除: HR", "text-red", "排除HR"))
        if rules.get("exclude"):
            rule_htmls.append(cls._badge_wrap(f"排除: {rules['exclude']}", "text-red", "排除规则"))
        if rules.get("dlcount"):
            rule_htmls.append(cls._badge(f"同时下载: {rules['dlcount']}", "text-blue", "同时下载数量限制"))

        peercount = rules.get("peercount")
        if peercount:
            parsed = cls._parse_peercount(peercount)
            if parsed:
                op, val = parsed
                rule_htmls.append(
                    cls._badge(f"做种人数: {cls.OP_DISPLAY.get(op, op)} {val}", "text-blue", "当前做种人数限制")
                )

        if rules.get("mode"):
            mode_str = "与" if rules["mode"] == "and" else "或"
            rule_htmls.append(cls._badge_wrap(f"删种模式: {mode_str}", "text-red", "删种模式"))

        for key, title, color, unit in [
            ("time", "做种时间", "text-orange", "小时"),
            ("ratio", "分享率", "text-orange", ""),
            ("uploadsize", "上传量", "text-orange", "GB"),
            ("dltime", "下载耗时", "text-orange", "小时"),
            ("avg_upspeed", "平均上传速度", "text-orange", "KB/S"),
            ("iatime", "未活动时间", "text-orange", "小时"),
            ("pending_time", "等待时间", "text-orange", "小时"),
            ("freespace", "磁盘剩余空间", "text-blue", "GB"),
        ]:
            cls._append_range_badge(rule_htmls, rules, key, title, color, unit)

        for key, title in [("freestatus", "Free 到期"), ("stopfree", "Free 到期")]:
            val = rules.get(key)
            if val == SwitchState.ON.value:
                rule_htmls.append(cls._badge(f"{title}: 开", "text-green", title))
            elif val:
                rule_htmls.append(cls._badge(f"{title}: 关", "text-green", title))

        return "<br>".join(rule_htmls)

    @staticmethod
    def _badge(text: str, color: str, title: str = "") -> str:
        return f'<span class="badge badge-outline {color} me-1 mb-1" title="{title}">{text}</span>'

    @staticmethod
    def _badge_wrap(text: str, color: str, title: str = "") -> str:
        return f'<span class="badge badge-outline {color} me-1 mb-1 text-wrap text-start" title="{title}">{text}</span>'

    @classmethod
    def _append_range_badge(cls, htmls: list, rules: dict, key: str, title: str, color: str, unit: str):
        val = rules.get(key)
        if not val:
            return
        parts = val.split("#")
        if len(parts) < 2 or not parts[0]:
            return
        op = cls.OP_DISPLAY.get(parts[0], parts[0])
        range_str = parts[1].replace(",", "-") if parts[1] else ""
        htmls.append(cls._badge(f"{title}: {op} {range_str}{unit}", color, title))

    @staticmethod
    def _parse_peercount(peercount: str):
        """兼容处理 peercount 字段，返回 (op, val) 或 None"""
        if peercount == "#":
            return None
        if "#" in peercount:
            parts = peercount.split("#")
            return (parts[0], parts[1].replace(",", "-")) if len(parts) >= 2 else None
        try:
            return "lt", str(int(peercount))
        except Exception:
            return None

    @staticmethod
    def _filesize(size_bytes: int) -> str:
        return StringUtils.str_filesize(size_bytes)
