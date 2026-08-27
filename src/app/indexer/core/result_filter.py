"""
结果过滤器

提供搜索结果的两阶段过滤：
1. local_filter：基于 meta_info 的本地轻量级过滤（无 TMDB 依赖）
2. match_filter：基于 TMDB 识别结果的匹配过滤

不依赖服务层，规则数据通过仓库层直接查询。
"""

import difflib
import re

import log
from app.core.settings import settings
from app.db.repositories.config_repo_adapter import FilterGroupRepositoryAdapter, FilterRuleRepositoryAdapter
from app.domain.enums import ProgressKey
from app.domain.mediatypes import MediaType
from app.indexer.core.batch_identifier import BatchIdentifier
from app.indexer.core.filter_engine import IndexerFilterEngine
from app.indexer.core.miss_collector import get_miss_collector
from app.indexer.core.models import FilterStats, SearchCandidate
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.progress import ProgressTracker
from app.media.identity.matcher import get_target_matcher
from app.media.identity.models import EDITION_MARKERS as _EDITION_MARKERS
from app.media.parser.parse_cache import cached_meta_info
from app.utils import StringUtils

# 字幕/配音标签前缀（如 "中字攻壳机动队"），会污染名称比较需剥除
_CN_TAG_PREFIX_RE = re.compile(r"^(?:官方中字|中文字幕|中文字|中字|国配|粤配|日配|简中|繁中|简繁|繁简)")

# 命中置信度低于该值告警（canary：与 IdentityResolver._LOW_CONFIDENCE_WARN 一致）
_LOW_CONFIDENCE_WARN = 0.65


def _strip_cn_tag_prefix(name: str) -> str:
    """剥除中文名前的字幕/配音标签，剥空时返回原名"""
    stripped = _CN_TAG_PREFIX_RE.sub("", name).strip()
    return stripped or name


class ResultFilter:
    """
    结果过滤器

    内部通过 IndexerFilterEngine 进行纯逻辑计算，
    规则数据通过 FilterGroupRepositoryAdapter / FilterRuleRepositoryAdapter 从仓库层获取。
    """

    def __init__(
        self,
        media,
        indexer_filter_engine: IndexerFilterEngine | None = None,
        filter_group_repo: FilterGroupRepositoryAdapter | None = None,
        filter_rule_repo: FilterRuleRepositoryAdapter | None = None,
    ):
        self._engine = indexer_filter_engine or IndexerFilterEngine()
        self._media = media
        self._group_repo = filter_group_repo or FilterGroupRepositoryAdapter()
        self._rule_repo = filter_rule_repo or FilterRuleRepositoryAdapter()
        self._rule_cache = {}

    def _get_rules(self, rulegroup_id=None):
        """
        从仓库层获取规则组和规则列表，带本地缓存

        :return: (rulegroup_info: dict, filters: list)
        """
        cache_key = rulegroup_id if rulegroup_id is not None else "__default__"
        if cache_key in self._rule_cache:
            return self._rule_cache[cache_key]

        if rulegroup_id:
            group = self._group_repo.get_by_id(int(rulegroup_id))
        else:
            groups = self._group_repo.get_all()
            group = None
            for g in groups:
                if g.default:
                    group = g
                    break

        if not group:
            rulegroup_info = {"name": "未配置"}
            filters = []
        else:
            rulegroup_info = group.to_dict()
            entities = self._rule_repo.get_by_group(group.id)
            filters = []
            for e in entities:
                include_str = e.include or ""
                exclude_str = e.exclude or ""
                filters.append(
                    {
                        "include": [x.strip() for x in include_str.splitlines() if x.strip()] if include_str else None,
                        "exclude": [x.strip() for x in exclude_str.splitlines() if x.strip()] if exclude_str else None,
                        "size": None,
                        "free": e.note,
                        "pri": e.priority,
                    }
                )

        self._rule_cache[cache_key] = (rulegroup_info, filters)
        log.info(
            f"[ResultFilter]加载规则组: {rulegroup_info.get('name')} "
            f"(ID={rulegroup_info.get('id')}), 规则数: {len(filters)}"
        )
        return rulegroup_info, filters

    def _check_full_filter(self, meta_info, filter_args, uploadvolumefactor, downloadvolumefactor):
        """
        完整过滤：基础条件 + 规则

        :return: (是否通过, 优先级, 信息)
        """
        match_flag, res_order, match_msg = self._engine.check_torrent_filter(
            meta_info=meta_info,
            filter_args=filter_args,
            uploadvolumefactor=uploadvolumefactor,
            downloadvolumefactor=downloadvolumefactor,
        )
        if not match_flag:
            return match_flag, res_order, match_msg

        rulegroup_id = filter_args.get("rule")
        rulegroup_info, filters = self._get_rules(rulegroup_id)
        match_flag, res_order, rule_name = self._engine.check_rules(meta_info, rulegroup_info, filters)
        if not match_flag:
            msg = (
                f"{meta_info.org_string} 大小：{StringUtils.str_filesize(meta_info.size)} "
                f"促销：{meta_info.get_volume_factor_string()} "
                f"不符合过滤规则 {rule_name} 要求"
            )
            return match_flag, res_order, msg

        return True, res_order, ""

    @staticmethod
    def quick_name_match(meta_info, match_media):
        """
        快速名称匹配：不调用 TMDB，仅通过名称判断是否可能匹配
        """
        if not meta_info or not match_media:
            return False

        # 年份冲突拒绝：种子有年份且与订阅年份偏差超过1年 → 不匹配
        meta_year = str(meta_info.year or "").strip()
        match_year = str(match_media.year or "").strip()
        if meta_year and match_year and meta_year.isdigit() and match_year.isdigit():
            if abs(int(meta_year) - int(match_year)) > 1:
                return False

        # 类型冲突拒绝：电影 ≠ 剧集/动漫（互斥），动漫和剧集双向兼容
        _anime_tv = {MediaType.TV, MediaType.ANIME}
        _torrent_type = meta_info.type
        if not _torrent_type or _torrent_type == MediaType.TV:
            _source = str(meta_info.rev_string or meta_info.org_string or "")
            if re.search(r"(?i)\[movie[^\[\]]*\]", _source):
                _torrent_type = MediaType.MOVIE
        if (
            _torrent_type
            and _torrent_type != MediaType.UNKNOWN
            and match_media.type
            and match_media.type != MediaType.UNKNOWN
        ):
            if not ({_torrent_type, match_media.type} <= _anime_tv):
                if _torrent_type != match_media.type:
                    return False

        def _norm(name):
            if not name:
                return ""
            return _strip_cn_tag_prefix(
                StringUtils.handler_special_chars(str(name)).upper().strip()  # type: ignore[union-attr]
            )

        # 中文虚词归一化：去掉 "的"/"之"/"与"/"和" 等，解决 "黄泉使者" vs "黄泉的使者"
        def _cn_simplify(name):
            if not name:
                return ""
            if not any("\u4e00" <= c <= "\u9fff" for c in name):
                return name
            return re.sub(r"[\u7684\u4e4b\u4e0e\u548c\u4e4e\u4e4b]", "", name)

        def _has_cjk(s):
            return bool(re.search(r"[\u3000-\u9fff]", s))

        def _extract_conflicting_year(mi, expected_year):
            source = mi.org_string or mi.rev_string or ""
            found = re.findall(r"(?<!\d)(19\d{2}|20[0-4]\d)(?!\d)", str(source))
            for y in found:
                if y.isdigit() and expected_year.isdigit():
                    if abs(int(y) - int(expected_year)) > 1:
                        return y
            return None

        _EDITION_SET = _EDITION_MARKERS  # 局部引用，略快

        match_names = {
            _norm(match_media.title),
            _norm(match_media.cn_name),
            _norm(match_media.en_name),
            _norm(match_media.original_title),
        }
        match_names.discard("")

        meta_names = {
            _norm(meta_info.title),
            _norm(meta_info.cn_name),
            _norm(meta_info.en_name),
        }
        meta_names.discard("")

        if not match_names or not meta_names:
            return False

        if meta_names & match_names:
            # 所有 meta 名都在 match 中才算可靠；否则另一半名包含区分信息
            if meta_names.issubset(match_names):
                return True
            # 有多个名称但未全部匹配 → 存在区分信息，不走快速匹配
            if len(meta_names) > 1:
                return False

        for mn in meta_names:
            if len(mn) < 3:
                continue
            for mmn in match_names:
                if len(mmn) < 3:
                    continue
                if mn == mmn:
                    return True
                # 子串匹配：两个方向用不同阈值
                # 订阅名 in 种子名（如 "GHOSTINTHESHELL" in "GHOSTINTHESHELLSAC2045S02"）→ 高阈值防误匹配
                # 种子名 in 订阅名 → 低阈值（订阅更具体）
                if _has_cjk(mn) == _has_cjk(mmn):
                    if mmn in mn:
                        if len(mmn) / len(mn) >= 0.85:
                            # 非 CJK 精确匹配时，检查 CJK 名称是否含衍生词（特别篇/OVA 等）
                            if not _has_cjk(mn):
                                _mcn = _cn_simplify(meta_info.cn_name or meta_info.title or "")
                                _scn = _cn_simplify(match_media.cn_name or match_media.title or "")
                                if _mcn and _scn and _has_cjk(_mcn) and _has_cjk(_scn):
                                    if _scn in _mcn:
                                        _extra = _mcn[len(_scn) :].strip()
                                        if _extra and all("\u4e00" <= c <= "\u9fff" for c in _extra):
                                            if any(m in _extra for m in _EDITION_SET):
                                                continue
                            return True
                    elif mn in mmn:
                        if len(mn) / len(mmn) >= 0.6:
                            if not _has_cjk(mn) and meta_info.cn_name and re.search(r"[A-Za-z]", meta_info.cn_name):
                                continue
                            # 非 CJK 匹配时，检查 CJK 名称是否含衍生词（特别篇/OVA 等）
                            if not _has_cjk(mn):
                                _mcn = _cn_simplify(meta_info.cn_name or meta_info.title or "")
                                _scn = _cn_simplify(match_media.cn_name or match_media.title or "")
                                if _mcn and _scn and _has_cjk(_mcn) and _has_cjk(_scn):
                                    if _scn in _mcn:
                                        _extra = _mcn[len(_scn) :].strip()
                                        if _extra and all("\u4e00" <= c <= "\u9fff" for c in _extra):
                                            if any(m in _extra for m in _EDITION_SET):
                                                continue
                            return True
                # 中文虚词归一化后二次匹配（全中文后缀=元数据标签，宽松；含英文/数字=衍生，严格）
                mn_simp = _cn_simplify(mn)
                mmn_simp = _cn_simplify(mmn)
                if mn_simp and mmn_simp:
                    if mn_simp == mmn_simp:
                        return True
                    if _has_cjk(mn_simp) and _has_cjk(mmn_simp):
                        if mmn_simp in mn_simp:
                            extra = mn_simp[len(mmn_simp) :]
                            if extra and all("\u4e00" <= c <= "\u9fff" for c in extra):
                                threshold = 0.65 if any(m in extra for m in _EDITION_SET) else 0.4
                            else:
                                threshold = 0.85
                            if len(mmn_simp) / len(mn_simp) >= threshold:
                                if threshold < 0.5:
                                    _conflict = _extract_conflicting_year(meta_info, match_year)
                                    if _conflict:
                                        continue
                                    if meta_info.en_name:
                                        _en = _norm(meta_info.en_name)
                                        _found = False
                                        for mn in match_names:
                                            if _has_cjk(mn):
                                                continue
                                            if _en == mn or mn in _en:
                                                if len(mn) / len(_en) >= 0.7:
                                                    _found = True
                                                    break
                                        if not _found:
                                            continue
                                return True
                        if mn_simp in mmn_simp:
                            extra = mmn_simp[len(mn_simp) :]
                            if extra and all("\u4e00" <= c <= "\u9fff" for c in extra):
                                threshold = 0.65 if any(m in extra for m in _EDITION_SET) else 0.4
                            else:
                                threshold = 0.85
                            if len(mn_simp) / len(mmn_simp) >= threshold:
                                if threshold < 0.5:
                                    _conflict = _extract_conflicting_year(meta_info, match_year)
                                    if _conflict:
                                        continue
                                    if meta_info.en_name:
                                        _en = _norm(meta_info.en_name)
                                        _found = False
                                        for mn in match_names:
                                            if _has_cjk(mn):
                                                continue
                                            if _en == mn or mn in _en:
                                                if len(mn) / len(_en) >= 0.7:
                                                    _found = True
                                                    break
                                        if not _found:
                                            continue
                                return True
                    elif mmn_simp in mn_simp or mn_simp in mmn_simp:
                        if not _has_cjk(mn_simp) and meta_info.cn_name:
                            cn_norm = _norm(meta_info.cn_name)
                            _cn_match = False
                            for _mmn in match_names:
                                if _has_cjk(_mmn) and (cn_norm == _mmn or _mmn in cn_norm):
                                    if cn_norm == _mmn or len(_mmn) / len(cn_norm) >= 0.75:
                                        _cn_match = True
                                        break
                            if not _cn_match:
                                continue
                        shorter = min(len(mn_simp), len(mmn_simp))
                        longer = max(len(mn_simp), len(mmn_simp))
                        if shorter / longer >= 0.5:
                            return True
                # SequenceMatcher 兜底：CJK↔CJK 高阈值（防 "攻壳机动队2"→攻壳机动队），
                # 其他语言保持 0.86
                shorter_len = min(len(mn), len(mmn))
                longer_len = max(len(mn), len(mmn))
                if shorter_len / longer_len >= 0.75:
                    _both_cjk = _has_cjk(mn) and _has_cjk(mmn)
                    _seq_threshold = 0.92 if _both_cjk else 0.86
                    if difflib.SequenceMatcher(None, mn, mmn).ratio() >= _seq_threshold:
                        if _has_cjk(mn) == _has_cjk(mmn):
                            return True

        return False

    @staticmethod
    def _type_compatible(a, b):
        if a == b:
            return True
        return bool(a in (MediaType.TV, MediaType.ANIME) and b in (MediaType.TV, MediaType.ANIME))

    def local_filter(self, result_array, filter_args, match_media=None, search_name=""):
        """
        第一阶段：本地轻量级过滤

        :param result_array: 原始结果列表，每个元素为 dict，需包含站点元信息字段
        :return: (candidates, direct_results, stats)
        """
        candidates = []
        direct_results = []
        stats = FilterStats()

        def _norm(name):
            if not name:
                return ""
            if isinstance(name, str):
                return StringUtils.handler_special_chars(name).upper().strip()  # type: ignore[union-attr]
            return ""

        for item in result_array:
            torrent_name = item.get("title")
            description = item.get("description")
            if torrent_name:
                torrent_name = re.sub(r"\|\d+(\|\d+)?$", "", torrent_name)
            if not torrent_name:
                stats.index_error += 1
                continue

            enclosure = item.get("enclosure")
            size = item.get("size")
            seeders = item.get("seeders")
            peers = item.get("peers")
            page_url = item.get("page_url")
            uv = item.get("uploadvolumefactor")
            dv = item.get("downloadvolumefactor")
            uploadvolumefactor = round(float(uv), 1) if uv not in (None, "") else 1.0
            downloadvolumefactor = round(float(dv), 1) if dv not in (None, "") else 1.0
            imdbid = item.get("imdbid")
            labels = item.get("labels")
            indexer_name = item.get("_indexer_name", "")
            indexer_order = item.get("_indexer_order", 0)
            indexer_public = item.get("_indexer_public", False)
            # 公开站(BT站)无魔力/分享率系统，种子均为免费
            if indexer_public:
                downloadvolumefactor = 0.0

            if filter_args.get("seeders") and not indexer_public and str(seeders) == "0":
                log.info(f"[ResultFilter]{torrent_name} 做种数为0")
                stats.index_rule_fail += 1
                continue

            mi = cached_meta_info(title=torrent_name, subtitle=f"{labels} {description}")
            # 若标题未解析出中文名，尝试从 description 中提取与目标媒体匹配的中文短语
            if not mi.cn_name and description and match_media:
                desc = str(description)
                i = 0
                while i < len(desc):
                    while i < len(desc) and not ("\u4e00" <= desc[i] <= "\u9fff"):
                        i += 1
                    start = i
                    while i < len(desc) and "\u4e00" <= desc[i] <= "\u9fff":
                        i += 1
                    if i - start >= 2:
                        phrase: str = desc[start:i]
                        p_norm = str(StringUtils.handler_special_chars(phrase)).upper().strip()
                        m_norm = str(StringUtils.handler_special_chars(match_media.cn_name or "")).upper().strip()
                        t_norm = str(StringUtils.handler_special_chars(match_media.title or "")).upper().strip()
                        if p_norm and (p_norm == m_norm or p_norm == t_norm or p_norm in m_norm or m_norm in p_norm):
                            _, cleaned, _, _, _, _ = StringUtils.get_keyword_from_string(phrase)
                            # 剥除字幕/配音标签前缀（如 "中字攻壳机动队" → "攻壳机动队"）
                            mi.cn_name = _strip_cn_tag_prefix(cleaned or phrase)
                            log.info(f"[ResultFilter]{torrent_name} 从 description 提取中文名: {mi.cn_name}")
                            break
            if not mi.get_name():
                log.info(f"[ResultFilter]{torrent_name} 无法识别到名称")
                stats.index_match_fail += 1
                continue

            mi.set_torrent_info(
                size=size,
                imdbid=imdbid,
                upload_volume_factor=uploadvolumefactor,
                download_volume_factor=downloadvolumefactor,
                labels=labels,
            )

            if mi.type == MediaType.TV and filter_args.get("type") == MediaType.MOVIE:
                log.info(
                    f"[ResultFilter]{torrent_name} 是 {mi.type.value}，不匹配类型：{filter_args.get('type').value}"
                )
                stats.index_rule_fail += 1
                continue

            match_flag, res_order, match_msg = self._check_full_filter(
                meta_info=mi,
                filter_args=filter_args,
                uploadvolumefactor=uploadvolumefactor,
                downloadvolumefactor=downloadvolumefactor,
            )
            if not match_flag:
                log.info(f"[ResultFilter]{match_msg}")
                stats.index_rule_fail += 1
                continue

            if not match_media:
                # 无 TMDB 匹配时用 filter_args 年份 + search_name 做基础过滤
                filter_year = str(filter_args.get("year", "") or "").strip()
                if filter_year and mi.year:
                    mi_year = str(mi.year).strip()
                    if mi_year.isdigit() and filter_year.isdigit():
                        if abs(int(mi_year) - int(filter_year)) > 1:
                            log.info(
                                f"[ResultFilter]{torrent_name} 年份冲突 (种子={mi_year}, 搜索={filter_year})，跳过"
                            )
                            stats.index_match_fail += 1
                            continue
                # search_name 伪匹配：种子名与搜索词差异大时跳过
                if search_name and mi.get_name():
                    _sn_norm = _norm(search_name)
                    _mi_norm = _norm(mi.get_name())
                    if _sn_norm and _mi_norm and len(_sn_norm) >= 3 and len(_mi_norm) >= 3:
                        if _sn_norm not in _mi_norm and _mi_norm not in _sn_norm:
                            sn_ratio = difflib.SequenceMatcher(None, _sn_norm, _mi_norm).ratio()
                            if sn_ratio < 0.4:
                                log.info(
                                    f"[ResultFilter]{torrent_name} 名称不匹配搜索词"
                                    f" (种子={_mi_norm}, 搜索={_sn_norm}, ratio={sn_ratio:.2f})，跳过"
                                )
                                stats.index_match_fail += 1
                                continue
                media_info = mi
                media_info.set_torrent_info(
                    site=indexer_name,
                    site_order=indexer_order,
                    enclosure=enclosure,
                    res_order=res_order,
                    filter_rule=filter_args.get("rule"),
                    size=size,
                    seeders=seeders,
                    peers=peers,
                    description=description,
                    page_url=page_url,
                    upload_volume_factor=uploadvolumefactor,
                    download_volume_factor=downloadvolumefactor,
                )
                if media_info not in direct_results:
                    stats.index_sucess += 1
                    direct_results.append(media_info)
                else:
                    stats.index_rule_fail += 1
                continue

            if mi.imdb_id and match_media.imdb_id and str(mi.imdb_id) == str(match_media.imdb_id):
                log.debug(f"[ResultFilter]{torrent_name} IMDB匹配成功，跳过TMDB查询")
                candidates.append(
                    SearchCandidate(
                        item=item,
                        meta_info=mi,
                        res_order=res_order,
                        skip_tmdb=True,
                        media_info=self._media.merge_media_info(mi, match_media),
                        indexer_name=indexer_name,
                        indexer_order=indexer_order,
                        indexer_public=indexer_public,
                    )
                )
                continue

            qnm_result = self.quick_name_match(mi, match_media)
            log.info(
                f"[ResultFilter]{torrent_name} quick_name_match: {qnm_result}, "
                f"meta_name={mi.get_name()}, match_name={match_media.get_name()}"
            )
            if qnm_result:
                # ADR-014：qnm 降级为召回门，命中不再直通，交 BatchIdentifier 身份层识别
                log.info(f"[ResultFilter]{torrent_name} 快速名称匹配，走身份层识别")
                candidates.append(
                    SearchCandidate(
                        item=item,
                        meta_info=mi,
                        res_order=res_order,
                        skip_tmdb=False,
                        media_info=mi,
                        indexer_name=indexer_name,
                        indexer_order=indexer_order,
                        indexer_public=indexer_public,
                    )
                )
                continue

            # cn_name 部分匹配但 en_name 别名不同 → 低置信走 TMDB 识别
            _mi_names = set()
            for n in (mi.title, mi.cn_name, mi.en_name):
                if n and isinstance(n, str):
                    _mi_names.add(StringUtils.handler_special_chars(n).upper().strip())
            _mm_names = set()
            for n in (match_media.title, match_media.cn_name, match_media.en_name, match_media.original_title):  # type: ignore[union-attr]
                if n and isinstance(n, str):
                    _mm_names.add(StringUtils.handler_special_chars(n).upper().strip())
            _mi_names.discard("")
            _mm_names.discard("")
            if _mi_names & _mm_names:
                log.info(f"[ResultFilter]{torrent_name} 中文名匹配但英文名不同，低置信走 TMDB")
                candidates.append(
                    SearchCandidate(
                        item=item,
                        meta_info=mi,
                        res_order=res_order,
                        skip_tmdb=False,
                        media_info=mi,
                        indexer_name=indexer_name,
                        indexer_order=indexer_order,
                        indexer_public=indexer_public,
                    )
                )
                continue

            log.info(f"[ResultFilter]{torrent_name} 快速名称不匹配，跳过")
            get_miss_collector().record(indexer_name, torrent_name, "quick_name_miss")
            stats.index_match_fail += 1
            continue

        return candidates, direct_results, stats

    @staticmethod
    def _use_target_matcher() -> bool:
        """ADR-014 P3 灰度开关：TargetMatcher 统一判等"""
        return bool(settings.get("laboratory").get("target_matcher"))

    def match_filter(
        self,
        candidates,
        match_media,
        filter_args,
        progress: ProgressTracker | None = None,
        progress_key=ProgressKey.Search,
    ):
        """
        第三阶段：TMDB 匹配及后续过滤

        :param progress: 进度追踪器，传入时按处理进度在 85~95 区间细分上报
        :return: (matched_results, stats)
        """
        ret_array = []
        stats = FilterStats()
        media_ident_cache = get_cache_manager().get_or_create("media_ident", "memory", maxsize=2000, ttl=3600)

        total = len(candidates)
        report_step = max(1, total // 10)
        for idx, cand in enumerate(candidates):
            if progress and idx and idx % report_step == 0:
                progress.update_max(
                    value=85 + int(idx / total * 10),
                    text=f"TMDB 匹配过滤 {idx}/{total} ...",
                    ptype=progress_key,
                )
            item = cand.item
            meta_info = cand.meta_info
            res_order = cand.res_order
            torrent_name = item.get("title")
            description = item.get("description")
            size = item.get("size")
            seeders = item.get("seeders")
            peers = item.get("peers")
            page_url = item.get("page_url")
            uv = item.get("uploadvolumefactor")
            dv = item.get("downloadvolumefactor")
            uploadvolumefactor = round(float(uv), 1) if uv not in (None, "") else 1.0
            downloadvolumefactor = round(float(dv), 1) if dv not in (None, "") else 1.0
            # 公开站(BT站)无魔力/分享率系统，种子均为免费
            if item.get("_indexer_public", False):
                downloadvolumefactor = 0.0
            enclosure = item.get("enclosure")
            cache_key = BatchIdentifier.build_cache_key(meta_info, torrent_name)
            indexer_name = cand.indexer_name
            indexer_order = cand.indexer_order

            if cand.skip_tmdb:
                media_info = cand.media_info
                log.info(
                    f"[ResultFilter]{torrent_name} skip_tmdb=True, merged_media_info: "
                    f"tmdb_id={media_info.tmdb_id}, type={media_info.type}, "
                    f"season={media_info.begin_season}, episode={media_info.begin_episode}"
                )
            elif not cache_key:
                log.warn(f"[ResultFilter]{torrent_name} 无法构建缓存键")
                stats.index_error += 1
                continue
            else:
                cached_info = media_ident_cache.get(cache_key)
                # 深拷贝：同组候选共享缓存对象，直接引用会导致
                # 判重塌缩（每组只剩一条）及 torrent_info 互相覆盖
                media_info = cached_info.model_copy(deep=True) if cached_info is not None else None
                if media_info is not None:
                    log.info(
                        f"[ResultFilter]{torrent_name} 从缓存获取: {cache_key}, "
                        f"tmdb_id={media_info.tmdb_id}, tmdb_info={media_info.tmdb_info is not None}"
                    )

                if not media_info:
                    log.warn(f"[ResultFilter]{torrent_name} ({cache_key}) 识别媒体信息出错！")
                    stats.index_error += 1
                    continue

                if not media_info.tmdb_info:
                    # 低置信（仅有中文名）且 TMDB 未识别 → 拒绝，不用回退
                    if not meta_info.en_name and meta_info.cn_name:
                        log.info(f"[ResultFilter]{torrent_name} ({cache_key}) 仅中文名低置信匹配 + TMDB 未识别，拒绝")
                        stats.index_match_fail += 1
                        continue
                    if (
                        match_media
                        and self._type_compatible(meta_info.type, match_media.type)
                        and self.quick_name_match(meta_info, match_media)
                    ):
                        log.info(
                            f"[ResultFilter]{torrent_name} ({cache_key}) 未匹配到TMDB，"
                            f"回退使用搜索媒体信息: {match_media.get_name()}"
                        )
                        media_info = self._media.merge_media_info(media_info, match_media)
                    else:
                        qnm = self.quick_name_match(meta_info, match_media) if match_media else False
                        log.info(
                            f"[ResultFilter]{torrent_name} ({cache_key}) 识别为 {media_info.get_name()} "
                            f"未匹配到媒体信息, quick_name_match={qnm}"
                        )
                        get_miss_collector().record(indexer_name, torrent_name, "tmdb_no_match")
                        stats.index_match_fail += 1
                        continue
                elif self._use_target_matcher():
                    # ADR-014 P3：TargetMatcher 统一判等（ID 判等 + edition 距离，可解释）
                    result = get_target_matcher().match(media_info, match_media)
                    if not result.matched:
                        log.info(f"[ResultFilter]{torrent_name} ({cache_key}) {result.reason}")
                        stats.index_match_fail += 1
                        continue
                    media_info = self._media.merge_media_info(media_info, match_media)
                elif str(media_info.tmdb_id) != str(match_media.tmdb_id):
                    media_type_str = media_info.type.value if media_info.type else "Unknown"
                    match_type_str = match_media.type.value if match_media.type else "Unknown"
                    log.info(
                        f"[ResultFilter]{torrent_name} ({cache_key}) 识别为 "
                        f"{media_type_str}/{media_info.get_title_string()}/{media_info.tmdb_id} "
                        f"与 {match_type_str}/{match_media.get_title_string()}/{match_media.tmdb_id} 不匹配"
                    )
                    stats.index_match_fail += 1
                    continue
                else:
                    media_info = self._media.merge_media_info(media_info, match_media)

            # 每条结果保留自己的种子标题（缓存对象的 org_string 是组代表的标题）
            if meta_info.org_string:
                media_info.org_string = meta_info.org_string

            if filter_args.get("type"):
                if (filter_args.get("type") == MediaType.TV and media_info.type == MediaType.MOVIE) or (
                    filter_args.get("type") == MediaType.MOVIE and media_info.type == MediaType.TV
                ):
                    display_name = cache_key if not cand.skip_tmdb else torrent_name
                    log.info(
                        f"[ResultFilter]{display_name} 是 {media_info.type.value}/"
                        f"{media_info.tmdb_id}，不是 {filter_args.get('type').value}"
                    )
                    stats.index_rule_fail += 1
                    continue

            display_name = cache_key if not cand.skip_tmdb else torrent_name
            if match_media.over_edition:
                if media_info.type != MediaType.MOVIE and media_info.get_episode_list():
                    log.info(
                        f"[ResultFilter]"
                        f"{media_info.get_title_string()}{media_info.get_season_string()} "
                        f"正在洗版，过滤掉季集不完整的资源：{display_name} {description}"
                    )
                    continue
                if match_media.res_order and int(res_order) <= int(match_media.res_order):
                    log.info(
                        f"[ResultFilter]"
                        f"{media_info.get_title_string()}{media_info.get_season_string()} "
                        f"正在洗版，已洗版优先级：{100 - int(match_media.res_order)}，"
                        f"当前资源优先级：{100 - int(res_order)}，"
                        f"跳过低优先级或同优先级资源：{display_name}"
                    )
                    continue

            sey_match = self._engine.is_torrent_match_sey(
                media_info, filter_args.get("season"), filter_args.get("episode"), filter_args.get("year")
            )
            if not sey_match:
                media_type_str = media_info.type.value if media_info.type else "Unknown"
                log.info(
                    f"[ResultFilter]{display_name} 识别为 {media_type_str}/"
                    f"{media_info.get_title_string()}/{media_info.get_season_episode_string()} "
                    f"不匹配季/集/年份 ("
                    f"filter_season={filter_args.get('season')}, "
                    f"filter_episode={filter_args.get('episode')}, "
                    f"filter_year={filter_args.get('year')}, "
                    f"media_season={media_info.get_season_list()}, "
                    f"media_episode={media_info.get_episode_list()}, "
                    f"media_year={media_info.year})"
                )
                stats.index_match_fail += 1
                continue

            log.info(
                f"[ResultFilter]{display_name} {description} 识别为 {media_info.get_title_string()} "
                f"{media_info.get_season_episode_string()} 匹配成功"
            )
            if 0.0 < getattr(media_info, "confidence", 0.0) < _LOW_CONFIDENCE_WARN:
                log.warn(
                    f"[ResultFilter]{display_name} 低置信命中 confidence={media_info.confidence:.2f} "
                    f"（canary：观察学成别名/边缘评分的可靠性）"
                )
            # 只订阅免费：download_volume_factor==0 视为免费(free/2xfree)
            if filter_args.get("free") and downloadvolumefactor != 0.0:
                log.info(f"[ResultFilter]{display_name} 非免费种子(dl_factor={downloadvolumefactor})，仅订阅免费，跳过")
                stats.index_rule_fail += 1
                continue
            media_info.set_torrent_info(
                site=indexer_name,
                site_order=indexer_order,
                enclosure=enclosure,
                res_order=res_order,
                filter_rule=filter_args.get("rule"),
                size=size,
                seeders=seeders,
                peers=peers,
                description=description,
                page_url=page_url,
                upload_volume_factor=uploadvolumefactor,
                download_volume_factor=downloadvolumefactor,
            )
            if media_info not in ret_array:
                stats.index_sucess += 1
                ret_array.append(media_info)
            else:
                stats.index_rule_fail += 1
        return ret_array, stats
