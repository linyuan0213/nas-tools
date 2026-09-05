"""
索引器过滤引擎

职责：提供搜索结果过滤的纯逻辑计算，不依赖服务层。
所有方法均为无状态静态方法，仅基于输入参数进行判断。
"""

import re

import log
from app.core.module_config import ModuleConf
from app.core.settings import settings
from app.domain.mediatypes import MediaType
from app.media import ReleaseGroupsMatcher
from app.utils import StringUtils


class IndexerFilterEngine:
    """
    索引器过滤引擎（纯逻辑，无状态）

    与 services.filter_service.FilterRuleEngine 的区别：
    - 本类位于索引器层，不依赖服务层
    - 所有规则数据通过参数传入，不自行查询数据库
    """

    _rg_matcher = ReleaseGroupsMatcher()

    @staticmethod
    def check_torrent_filter(
        meta_info, filter_args: dict, uploadvolumefactor=None, downloadvolumefactor=None
    ) -> tuple[bool, int, str]:
        """
        对种子进行过滤（基于 filter_args 中的基础条件）

        :return: (是否匹配, 优先值, 信息)
        """
        text = meta_info.rev_string or ""
        if meta_info.subtitle:
            text = f"{text} {meta_info.subtitle}"

        # 过滤纯音频文件（FLAC/MP3/OST/OP/ED等）
        _audio_patterns = [
            r"\[FLAC\]",
            r"\[MP3\]",
            r"\[AAC\]",
            r"\[WAV\]",
            r"\[OGG\]",
            r"\[ALAC\]",
            r"\[OST\]",
            r"\[Soundtrack\]",
            r"\[Music\]",
            r"\[Audio\]",
            r"OPテーマ",
            r"EDテーマ",
            r"主題歌",
            r"キャラソン",
            r"\.flac",
            r"\.mp3",
            r"\.m4a",
            r"\.wav",
            r"\.ogg",
        ]
        for pat in _audio_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return False, 0, f"{meta_info.org_string} 为音频文件，不匹配视频订阅"

        # 过滤漫画/书籍类资源（仅检查标题，不检查 description 避免误杀）
        target_type = filter_args.get("type")
        if isinstance(target_type, str):
            target_type = MediaType.from_string(target_type)
        if target_type in (MediaType.TV, MediaType.MOVIE, MediaType.ANIME):
            _book_patterns = [
                r"(?:漫画|コミック|单行本|Manga|Comic|巻相当|Graphic Novel)",
                r"(?:raw|RAW)\b.*第\s*\d+\s*巻",
                r"第\s*\d+\s*巻.*(?:raw|RAW)\b",
            ]
            _title_text = meta_info.org_string or meta_info.rev_string or ""
            for pat in _book_patterns:
                if re.search(pat, _title_text, re.IGNORECASE):
                    return False, 0, f"{meta_info.org_string} 为漫画/书籍类资源，不匹配视频订阅"

        # 过滤过小文件（字幕/样本等非视频资源）
        if target_type in (MediaType.TV, MediaType.MOVIE, MediaType.ANIME):
            min_filesize_mb = (settings.get("media") or {}).get("min_filesize", 150)
            if min_filesize_mb and meta_info.size:
                size_bytes = StringUtils.num_filesize(meta_info.size)
                if size_bytes and size_bytes < min_filesize_mb * 1024 * 1024:
                    return (
                        False,
                        0,
                        f"{meta_info.org_string} 大小 {StringUtils.str_filesize(size_bytes)}"
                        f" < {min_filesize_mb}M 最小限制",
                    )

        # 过滤质量
        if filter_args.get("restype"):
            restype_values = [s.strip().upper() for s in str(filter_args.get("restype")).split(",") if s.strip()]
            restype_res = [ModuleConf.TORRENT_SEARCH_PARAMS["restype"].get(v) for v in restype_values]
            restype_res = [r for r in restype_res if r]
            if restype_res:
                if not meta_info.get_edtion_string():
                    return False, 0, f"{meta_info.org_string} 不符合质量 {filter_args.get('restype')} 要求"
                combined_re = "|".join(restype_res)
                if not re.search(rf"{combined_re}", meta_info.get_edtion_string(), re.IGNORECASE):
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
                if not re.search(rf"{combined_re}", meta_info.resource_pix, re.IGNORECASE):
                    return False, 0, f"{meta_info.org_string} 不符合分辨率 {filter_args.get('pix')} 要求"

        # 过滤制作组/字幕组
        if filter_args.get("team"):
            team = filter_args.get("team")
            if not meta_info.resource_team:
                resource_team = IndexerFilterEngine._rg_matcher.match(title=meta_info.rev_string, groups=team)
                if not resource_team:
                    return False, 0, f"{meta_info.org_string} 不符合制作组/字幕组 {team} 要求"
                else:
                    meta_info.resource_team = resource_team
            elif not re.search(rf"{team}", meta_info.resource_team, re.IGNORECASE):
                return False, 0, f"{meta_info.org_string} 不符合制作组/字幕组 {team} 要求"

        # 过滤促销
        if filter_args.get("sp_state"):
            sp_state = filter_args.get("sp_state") or ""
            ul_factor, dl_factor = sp_state.split()
            if uploadvolumefactor and ul_factor not in ("*", str(uploadvolumefactor)):
                return False, 0, f"{meta_info.org_string} 不符合促销要求"
            if downloadvolumefactor and dl_factor not in ("*", str(downloadvolumefactor)):
                return False, 0, f"{meta_info.org_string} 不符合促销要求"

        # 只订阅免费：download_volume_factor==0 视为免费(free/2xfree)
        # downloadvolumefactor 为 None 表示无法判断(站点未开启解析)，保守跳过(搜索会补充)
        if filter_args.get("free"):
            if downloadvolumefactor is None or float(downloadvolumefactor) != 0.0:
                return False, 0, f"{meta_info.org_string} 非免费种子，仅订阅免费"

        # 过滤包含
        if filter_args.get("include"):
            include = filter_args.get("include")
            if not re.search(rf"{include}", text, re.IGNORECASE):
                return False, 0, f"{meta_info.org_string} 不符合包含 {include} 要求"

        # 过滤排除
        if filter_args.get("exclude"):
            exclude = filter_args.get("exclude")
            if re.search(rf"{exclude}", text, re.IGNORECASE):
                return False, 0, f"{meta_info.org_string} 不符合排除 {exclude} 要求"

        # 过滤关键字
        if filter_args.get("key"):
            key = filter_args.get("key")
            if not re.search(rf"{key}", text, re.IGNORECASE):
                return False, 0, f"{meta_info.org_string} 不符合 {key} 要求"

        return True, 0, ""

    @staticmethod
    def check_rules(meta_info, rulegroup_info: dict, filters: list) -> tuple[bool, int, str]:
        """
        检查种子是否匹配站点过滤规则：排除规则、包含规则、优先规则

        :param rulegroup_info: 已解析的规则组字典
        :param filters: 规则列表
        :return: (是否匹配, 优先值, 规则名称)
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
            log.info(
                f"[FilterEngine]规则组 {group_name} 无匹配: "
                f"title={title}, pix={meta_info.resource_pix}, encode={meta_info.video_encode}"
            )
            return False, 0, group_name
        return True, order_seq, group_name

    @staticmethod
    def is_torrent_match_sey(media_info, s_num, e_num, year_str):
        """
        种子名称关键字匹配（季/集/年）

        :param s_num: 季号，为空则不匹配
        :param e_num: 集号，为空则不匹配
        :param year_str: 年份，为空则不匹配
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
        # 年份允许 ±1 年偏差（如订阅 S1 2025，匹配 S2 2026 的种子）
        if year_str and str(media_info.year).isdigit() and str(year_str).isdigit():
            if abs(int(media_info.year) - int(year_str)) > 1:
                return False
        return True
