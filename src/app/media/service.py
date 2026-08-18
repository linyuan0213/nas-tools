import copy
import difflib
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import log
from app.core.settings import settings
from app.domain.enums import IdentifyStatus, MatchMode
from app.domain.mediatypes import MediaType
from app.domain.validators.media_title import is_valid_media_title
from app.domain.word_processor import get_words_info, process_title
from app.infrastructure.cache_system import cacheman
from app.infrastructure.http.exceptions import HttpRateLimitError
from app.infrastructure.image_proxy import ImageProxy
from app.media.identity import get_identity_builder
from app.media.identity.remapper import EpisodeRemapper
from app.media.lookup.base import LookupResult
from app.media.lookup.tmdb_lookup import TmdbLookup
from app.media.models import MediaInfo
from app.media.parser.base import BaseParser, ParserResult
from app.media.parser.episode_mapper import EpisodeMapper
from app.media.parser.regex import RegexParser
from app.storage.backends.base import StorageBackend
from app.utils import EpisodeFormat, PathUtils, StringUtils


class MediaService:
    """媒体识别服务门面 —  Parser + Lookup 解耦架构"""

    def __init__(
        self,
        tmdb_lookup: TmdbLookup,
        llm_parser: BaseParser,
    ):
        self._llm_parser = llm_parser
        self._parser = self._build_parser()
        self._lookup = tmdb_lookup
        self._episode_mapper = EpisodeMapper(self._lookup)
        self._episode_remapper = EpisodeRemapper(episode_mapper=self._episode_mapper)
        self._init_config()

    def _init_config(self):
        app = settings.get("app")
        media = settings.get("media")
        laboratory = settings.get("laboratory")
        self._search_keyword = laboratory.get("search_keyword")
        self._search_tmdbweb = laboratory.get("search_tmdbweb")
        self._default_language = media.get("tmdb_language", "zh") or "zh"
        self._episode_mapping_enabled = media.get("episode_mapping_enabled", False)
        if self._episode_mapping_enabled:
            log.info("[MediaService]集数映射已启用")
        rmt_match_mode = app.get("rmt_match_mode", "normal")
        if isinstance(rmt_match_mode, str):
            rmt_match_mode = rmt_match_mode.upper()
        else:
            rmt_match_mode = "NORMAL"
        self._rmt_match_mode = MatchMode.STRICT if rmt_match_mode == "STRICT" else MatchMode.NORMAL

    def _build_parser(self) -> BaseParser:
        cfg = settings.get("agent") or {}
        if cfg.get("enabled") and cfg.get("media_recognizer_enabled"):
            if self._llm_parser and self._llm_parser.ready:
                return self._llm_parser
        return RegexParser()

    def _post_process(self, parsed, title: str, subtitle: str = "") -> ParserResult | None:
        """解析后处理（所有识别入口共用）：集名粘连修复 / 中文名补充 / 末尾年份提取。

        统一 identify / identify_batch / identify_files 的行为，避免同一解析器在不同
        路径上后处理不一致（如"识别测试正常但转移识别错"）。
        """
        if not parsed:
            return None

        # 1. 集名粘连修复：S05E10 后的短语剥离，从搜索名中分离
        if parsed.title_en and not parsed.title_cn and parsed.season:
            se_text = f"S{parsed.season:02d}E{parsed.episode:02d}" if parsed.episode else f"S{parsed.season:02d}"
            idx = title.upper().find(se_text.upper())
            if idx < 0 and parsed.episode:
                se_text = f"S{parsed.season}E{parsed.episode}"
                idx = title.upper().find(se_text.upper())
            if idx >= 0:
                prefix = title[:idx].replace(".", " ").strip()
                # 剥离前缀中的发布组方括号与末尾年份，避免污染搜索名
                prefix = re.sub(r"\[[^\]]*\]", " ", prefix)
                if parsed.year:
                    prefix = re.sub(rf"\s*{re.escape(str(parsed.year))}\s*$", "", prefix)
                prefix = re.sub(r"\s+", " ", prefix).strip()
                if prefix and len(prefix) >= 3:
                    parsed.title_en = prefix

        # 2. 中文名补充：标题无中文名且副标题含中文 → 从副标题补提中文名；
        #    副标题解析出的英文名仅在主标题缺失时才采用，避免无意义目录名（如 /tmp）覆盖真实标题
        if not parsed.title_cn and subtitle:
            sub_parsed = self._parser.parse(subtitle, "")
            if sub_parsed and sub_parsed.title_cn:
                parsed.title_cn = sub_parsed.title_cn
            elif sub_parsed and sub_parsed.title_en and not parsed.title_en:
                parsed.title_en = sub_parsed.title_en

        # 3. 名称末尾年份提取
        if not parsed.year:
            name = parsed.title_cn or parsed.title_en or ""
            year_match = re.search(r"\s+(\d{4})$", name)
            if year_match:
                extracted_year = year_match.group(1)
                if 1900 < int(extracted_year) < 2050:
                    parsed.year = extracted_year
                    cleaned = re.sub(r"\s+\d{4}$", "", name)
                    if parsed.title_cn == name:
                        parsed.title_cn = cleaned
                    elif parsed.title_en == name:
                        parsed.title_en = cleaned
        return parsed

    @staticmethod
    def _backfill_total_episodes(info: MediaInfo) -> None:
        """从实际解析出的集信息补全 total_episodes（单集=1、多集范围=差+1），避免"共0集"."""
        if info.total_episodes == 0 and info.begin_episode is not None:
            if info.end_episode is not None and info.end_episode >= info.begin_episode:
                info.total_episodes = (info.end_episode - info.begin_episode) + 1
            else:
                info.total_episodes = 1

    @staticmethod
    def _fill_episode_from_parent_paths(file_path: str, parsed: ParserResult | None) -> None:
        """文件名解析不出集号时，从父目录名提取季/集（动漫单集目录常携带 S01E07）.

        订阅下载时下载历史只记到季（S01），单集集号通常只在转移路径的目录名中。
        裸数字文件名（1.mkv）解析出的数字是种子内索引而非集号，优先用父目录的集号覆盖。
        """
        if parsed is None:
            return
        file_stem = os.path.splitext(os.path.basename(file_path))[0]
        bare_index = bool(re.fullmatch(r"\d+", file_stem))
        if parsed.episode is not None and not bare_index:
            return
        parent = os.path.basename(os.path.dirname(file_path))
        parent_parent = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
        for ctx in (parent, parent_parent):
            if not ctx or ctx in (".", "/", "\\", ""):
                continue
            try:
                ctx_parsed = RegexParser().parse(ctx)
            except Exception:  # noqa: BLE001
                ctx_parsed = None
            if ctx_parsed and ctx_parsed.episode:
                if parsed.season is None or bare_index:
                    parsed.season = ctx_parsed.season
                parsed.episode = ctx_parsed.episode
                if parsed.end_episode is None:
                    parsed.end_episode = ctx_parsed.end_episode
                log.info(
                    f"[MediaService]文件名无集号，从父目录提取: {os.path.basename(file_path)} "
                    f"-> S{parsed.season or '-'}E{parsed.episode}"
                )
                return

    @staticmethod
    def _apply_words(title: str, subtitle: str | None = None) -> tuple[str, str]:
        """套用识别词（屏蔽 / 替换 / 集偏移），与 meta_info() 的前置清洗保持一致."""
        words = get_words_info()
        if not words:
            return title, subtitle or ""
        rev_title, msg, used_info = process_title(words, title)
        for msg_item in msg:
            log.warn(f"[MediaService]{msg_item}")
        if used_info and any(used_info.values()):
            log.info(
                f"[MediaService]识别词生效: 屏蔽={used_info.get('ignored')} "
                f"替换={used_info.get('replaced')} 集偏移={used_info.get('offset')}"
            )
        if subtitle:
            subtitle, _, _ = process_title(words, subtitle)
        return rev_title, subtitle or ""

    # ---------- 单条识别 ----------

    def identify(
        self,
        title: str,
        subtitle: str = "",
        mtype: MediaType | None = None,
        strict=None,
        cache=True,
        language: str | None = None,
        chinese=True,
        append_to_response=None,
    ) -> MediaInfo | None:
        if not title:
            return None

        # 设置语言
        if language:
            self._lookup.client.set_language(language)

        # 1. Parser: 文件名解析（Regex 失败时 fallback 到 LLM）
        # 全路径 → 提取文件名，父目录作为兜底上下文
        if isinstance(title, str) and ("/" in title or "\\" in title):
            parent = os.path.basename(os.path.dirname(title)).strip()
            title = os.path.basename(title)
            if parent and parent not in (".", "/", "") and not subtitle:
                subtitle = parent
        title, subtitle = self._apply_words(title, subtitle)
        parsed = self._parser.parse(title, subtitle)
        if not parsed and not self._parser.is_llm:
            # Fallback: 默认是 RegexParser 时，用 LLM Parser 兜底
            llm_parser = self._llm_parser
            if llm_parser.ready:
                parsed = llm_parser.parse(title, subtitle)
                if parsed:
                    log.info(f"[MediaService]LLM Parser fallback 成功: {parsed.title_cn or parsed.title_en}")
        if not parsed:
            if language:
                self._lookup.client.set_language()
            return None

        # 公共后处理（与 identify_batch / identify_files 一致）
        parsed = self._post_process(parsed, title, subtitle)
        if not parsed:
            if language:
                self._lookup.client.set_language()
            return None

        # 领域规则：标题质量过滤，排除纯网站名/垃圾词
        search_name = parsed.title_en or parsed.title_cn or ""
        if not is_valid_media_title(search_name):
            log.debug(f"[MediaService]标题质量不合格，跳过识别: {title} -> {search_name}")
            if language:
                self._lookup.client.set_language()
            return None

        if mtype:
            parsed.type = mtype

        search_name = parsed.title_en or parsed.title_cn or title

        # 尝试从缓存获取
        if cache:
            cached = self._lookup.client.redis_cache.get_media_info(
                title=search_name, year=parsed.year or "", mtype=parsed.type
            )
            if cached and isinstance(cached, MediaInfo):
                # 验证缓存的季集是否与当前解析结果匹配（避免不同集数标题的缓存碰撞）
                if (
                    cached.begin_season == parsed.season
                    and cached.begin_episode == parsed.episode
                    and cached.end_episode == parsed.end_episode
                ):
                    log.info(f"[MediaService]从缓存获取媒体信息: {search_name}")
                    if language:
                        self._lookup.client.set_language()
                    # 缓存只提供 TMDB 身份；资源字段（org_string/发布组/分辨率/音视频等）
                    # 是种子专属的，必须来自当前解析，避免返回首次缓存种子的过期资源字段
                    info = MediaInfo.from_parser(parsed)
                    info.org_string = title
                    for _field in (
                        "tmdb_id",
                        "title",
                        "original_title",
                        "year",
                        "overview",
                        "vote_average",
                        "poster_path",
                        "backdrop_path",
                        "fanart_poster",
                        "fanart_backdrop",
                        "tmdb_info",
                        "cn_name",
                        "en_name",
                        "type",
                    ):
                        setattr(info, _field, getattr(cached, _field))
                    self.enrich_en_name(info)
                    return info
                log.debug(
                    f"[MediaService]缓存季集不匹配，跳过缓存: "
                    f"cached=S{cached.begin_season}E{cached.begin_episode}-"
                    f"{cached.end_episode or ''}, "
                    f"parsed=S{parsed.season}E{parsed.episode}-"
                    f"{parsed.end_episode or ''}"
                )

        # 计算 strict 模式
        use_strict = strict if strict is not None else (self._rmt_match_mode == MatchMode.STRICT)

        # 2. Lookup: TMDB 查询 (含内部 fallback)
        if mtype is not None:
            result = self._lookup.lookup(parsed, hint_type=mtype, strict=use_strict, language=language or "")
        else:
            result = self._lookup.lookup(parsed, strict=use_strict, language=language or "")

        # 3. Fallback: WEB 抓取
        if not result and self._search_tmdbweb:
            web_info = self._lookup.search.search_web(search_name, parsed.type or MediaType.UNKNOWN)
            if web_info:
                result = self._lookup._to_lookup_result(web_info)

        # 4. Fallback: 搜索引擎
        if not result and self._search_keyword:
            keyword, is_movie = self._search_engine(search_name)
            if keyword:
                cacheman["tmdb_supply"].set(search_name, keyword)
                if is_movie:
                    search_result = self._lookup.search.search_movie(keyword)
                else:
                    search_result = self._lookup.search.search_multi(keyword)
                if search_result:
                    result = self._lookup._to_lookup_result(search_result)

        # 5. 组装
        info = MediaInfo.from_parser(parsed)
        info.org_string = title
        original_year = info.year  # 保存解析器原始年份
        if result:
            # TMDB 识别年份与种子原始年份偏差>1 → 尝试下一个结果
            if (
                original_year
                and result.year
                and str(original_year).isdigit()
                and str(result.year).isdigit()
                # 文件年份早于 TMDB 首播 5 年以上 → 可能错配，拒绝
                and int(original_year) < int(result.year) - 5
            ):
                log.info(f"[service]年份冲突 种子={original_year} TMDB={result.year} → 尝试补充搜索")
                if parsed.title_en:
                    combined = f"{parsed.title_cn or ''} {parsed.title_en}".strip()
                    if combined != (parsed.title_cn or ""):
                        if language:
                            self._lookup.client.set_language(language or "")
                        try:
                            retry_parsed = copy.copy(parsed)
                            retry_parsed.title_cn = combined
                            retry_result = self._lookup.lookup(
                                retry_parsed, hint_type=mtype, strict=use_strict, language=language or ""
                            )
                            if retry_result:
                                # 重试结果也要年份校验
                                r_year = retry_result.year or ""
                                if (
                                    original_year
                                    and r_year
                                    and str(original_year).isdigit()
                                    and str(r_year).isdigit()
                                    and abs(int(original_year) - int(r_year)) <= 1
                                ):
                                    result = retry_result
                                else:
                                    result = None
                            else:
                                result = None
                        except Exception:
                            result = None
                    else:
                        result = None
                else:
                    result = None
        # 全名搜索失败 → 中文名去掉 "剧场版/劇場版/映画" 前缀重试
        if not result and parsed.title_cn:
            short_cn = re.sub(r"^(剧场版|劇場版|映画|电影版)\s*", "", parsed.title_cn)
            if short_cn and short_cn != parsed.title_cn:
                retry = copy.copy(parsed)
                retry.title_cn = short_cn
                result = self._lookup.lookup(retry, hint_type=mtype, strict=use_strict, language=language or "")
        if result:
            info.tmdb_id = result.tmdb_id
            info.title = result.title
            info.original_title = result.original_title
            info.year = result.year
            info.overview = result.overview
            info.vote_average = result.vote_average
            info.poster_path = result.poster_path
            info.backdrop_path = result.backdrop_path
            info.tmdb_info = {
                "id": result.tmdb_id,
                "title": result.title,
                "original_title": result.original_title,
                "media_type": result.media_type.value if result.media_type else None,
                "year": result.year,
                "overview": result.overview,
                "vote_average": result.vote_average,
                "poster_path": result.poster_path,
                "backdrop_path": result.backdrop_path,
                "genres": result.genres,
                "external_ids": result.external_ids,
            }
            # 补充全量信息（获取 genre_ids 等）
            full_info = self._lookup.get_tmdb_info(
                mtype=result.media_type,
                tmdbid=result.tmdb_id,
                language=language,
                append_to_response=append_to_response,
                chinese=chinese,
            )
            if full_info:
                info.tmdb_info = full_info
                info.title = full_info.get("title") or full_info.get("name") or info.title
                info.original_title = (
                    full_info.get("original_title") or full_info.get("original_name") or info.original_title
                )
                info.year = (
                    full_info.get("release_date", "")[:4]
                    if full_info.get("release_date")
                    else full_info.get("first_air_date", "")[:4]
                ) or info.year
                info.overview = full_info.get("overview") or info.overview
                info.vote_average = round(float(full_info.get("vote_average", 0)), 1) or info.vote_average
                info.poster_path = ImageProxy.get_tmdbimage_url(full_info.get("poster_path")) or info.poster_path
                info.backdrop_path = ImageProxy.get_tmdbimage_url(full_info.get("backdrop_path")) or info.backdrop_path
                # 根据 genre_ids 更新类型（动漫 vs 电视剧）
                info.set_tmdb_info(full_info)

        # 6.1 获取英文 / 中文标题用于匹配
        if info.tmdb_id:
            try:
                # en_name 为空或非拉丁（日/韩/中文原名）时补取 TMDB 英文标题用于搜索
                self.enrich_en_name(info)
                if not info.cn_name:
                    cn_title = self._lookup.get_tmdb_zh_title(info)
                    if cn_title and StringUtils.is_chinese(cn_title):
                        info.cn_name = cn_title
            except Exception as e:  # noqa: BLE001
                log.debug(f"[service]忽略异常: {e}")

        # 7. 集数映射（动漫合并季 / 绝对集号）
        if info.begin_episode:
            self._remap_season_episode(info)

        # 保存到缓存
        if cache:
            self._lookup.client.redis_cache.set_media_info(
                title=search_name, info=info, year=parsed.year or "", mtype=parsed.type
            )

        # 重置语言
        if language:
            self._lookup.client.set_language()

        return info

    def get_media_info(
        self,
        title,
        subtitle=None,
        mtype=None,
        strict=None,
        cache=True,
        language=None,
        chinese=True,
        append_to_response=None,
    ):
        """兼容旧接口 — 内部调用 identify"""
        return self.identify(title, subtitle or "", mtype, strict, cache, language, chinese, append_to_response)

    def identify_batch(self, items: list[dict], language: str | None = None) -> list:
        """批量识别 — Parser batch + 去重后并发 Lookup"""

        def _norm_name(name: str) -> str:
            return re.sub(r"[^\w\u4e00-\u9fff]", "", name.lower()).strip()

        if not items:
            return []

        titles = [i.get("title", "") for i in items]
        subtitles = [i.get("subtitle", "") for i in items]

        # 0. 套用识别词（屏蔽 / 替换 / 集偏移）
        for idx, t in enumerate(titles):
            titles[idx], subtitles[idx] = self._apply_words(t, subtitles[idx])

        # 1. Parser: 批量解析所有文件名
        parsed_list = self._parser.parse_batch(titles)

        # Fallback: 默认是 RegexParser 时，对解析失败的条目用 LLM Parser 重新解析
        if not self._parser.is_llm:
            failed_indices = [i for i, p in enumerate(parsed_list) if not p]
            if failed_indices:
                llm_parser = self._llm_parser
                if llm_parser.ready:
                    failed_titles = [titles[i] for i in failed_indices]
                    log.info(
                        f"[MediaService]批量识别: {len(failed_indices)} 条 Regex 解析失败，尝试 LLM Parser fallback"
                    )
                    llm_results = llm_parser.parse_batch(failed_titles)
                    for j, idx in enumerate(failed_indices):
                        if llm_results[j]:
                            parsed_list[idx] = llm_results[j]
                            log.info(f"[MediaService]LLM Parser fallback [{idx}]: {failed_titles[j][:60]}...")

        # 2. 去重: 按 (title, year, type) 分组，相同内容只查一次 TMDB
        unique_keys = {}
        key_to_indices = {}
        for idx, parsed in enumerate(parsed_list):
            if not parsed and subtitles[idx]:
                parsed = self._parser.parse(titles[idx], subtitles[idx])
                parsed_list[idx] = parsed
            if not parsed:
                continue
            # 公共后处理（与 identify / identify_files 一致）
            parsed = self._post_process(parsed, titles[idx], subtitles[idx])
            if not parsed:
                continue
            parsed_list[idx] = parsed
            # 领域规则：标题质量过滤
            search_name = parsed.title_en or parsed.title_cn or ""
            if not is_valid_media_title(search_name):
                log.debug(f"[MediaService]批量识别标题质量不合格，跳过: {titles[idx]} -> {search_name}")
                parsed_list[idx] = None
                continue
            key = (
                f"{_norm_name(parsed.title_en or parsed.title_cn or '')}:"
                f"{parsed.year or ''}:"
                f"{parsed.type.value if parsed.type else ''}"
            )
            if key not in unique_keys:
                unique_keys[key] = parsed
                key_to_indices[key] = []
            key_to_indices[key].append(idx)

        # 3. Lookup: 并发查询去重后的唯一组合
        lookup_results = {}
        if unique_keys:
            log.info(f"[MediaService]批量识别 {len(items)} 条，去重后 {len(unique_keys)} 条需查 TMDB")
            max_workers = min(len(unique_keys), 2)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_key = {
                    executor.submit(self._lookup.lookup, parsed, language=language or ""): key
                    for key, parsed in unique_keys.items()
                }
                for future in as_completed(future_to_key):
                    key = future_to_key[future]
                    try:
                        lookup_results[key] = future.result()
                    except Exception as e:
                        log.error(f"[MediaService]TMDB 查询出错: {key}, {e}")
                        lookup_results[key] = None

                # 失败重试：用另一语言名再搜一次
                _retry_items = []
                _retry_keys = {}
                for key, parsed in unique_keys.items():
                    if lookup_results.get(key) and lookup_results[key].tmdb_id != 0:
                        continue
                    alt_name = parsed.title_cn if parsed.title_en else parsed.title_en
                    if not alt_name or alt_name == (parsed.title_en or parsed.title_cn):
                        continue
                    alt_parsed = copy.copy(parsed)
                    alt_parsed.title_en, alt_parsed.title_cn = alt_name, parsed.title_en or parsed.title_cn
                    alt_key = (
                        f"{alt_parsed.title_en or alt_parsed.title_cn or ''}:"
                        f"{alt_parsed.year or ''}:"
                        f"{alt_parsed.type.value if alt_parsed.type else ''}"
                    )
                    if alt_key in unique_keys or alt_key in _retry_keys:
                        continue
                    _retry_keys[alt_key] = key
                    _retry_items.append((alt_key, alt_parsed))

                if _retry_items:
                    with ThreadPoolExecutor(max_workers=min(len(_retry_items), 2)) as executor:
                        _retry_futures = {
                            executor.submit(self._lookup.lookup, parsed, language=language or ""): alt_key
                            for alt_key, parsed in _retry_items
                        }
                        for future in as_completed(_retry_futures):
                            alt_key = _retry_futures[future]
                            try:
                                result = future.result()
                                if result and result.tmdb_id and result.tmdb_id != 0:
                                    orig_key = _retry_keys[alt_key]
                                    lookup_results[orig_key] = result
                                    lookup_results[alt_key] = result
                            except Exception as e:
                                log.debug(f"[MediaService]TMDB 重试查询出错: {alt_key}, {e}")

        # 4. 组装: 将结果映射回原始列表
        results = [MediaInfo() for _ in items]
        for idx, item in enumerate(items):
            parsed = parsed_list[idx]
            info = MediaInfo.from_parser(parsed) if parsed else MediaInfo()
            if parsed:
                key = (
                    f"{parsed.title_en or parsed.title_cn or ''}:"
                    f"{parsed.year or ''}:"
                    f"{parsed.type.value if parsed.type else ''}"
                )
                looked_up = lookup_results.get(key)
                if looked_up:
                    info.tmdb_id = looked_up.tmdb_id
                    info.title = looked_up.title
                    info.original_title = looked_up.original_title
                    info.year = looked_up.year
                    info.overview = looked_up.overview
                    info.vote_average = looked_up.vote_average
                    info.poster_path = looked_up.poster_path
                    info.backdrop_path = looked_up.backdrop_path
                    info.tmdb_info = {
                        "id": looked_up.tmdb_id,
                        "title": looked_up.title,
                        "original_title": looked_up.original_title,
                        "media_type": looked_up.media_type.value if looked_up.media_type else None,
                        "year": looked_up.year,
                        "overview": looked_up.overview,
                        "vote_average": looked_up.vote_average,
                        "poster_path": looked_up.poster_path,
                        "backdrop_path": looked_up.backdrop_path,
                        "genres": looked_up.genres,
                        "external_ids": looked_up.external_ids,
                    }
            info.site = item.get("site")
            info.enclosure = item.get("enclosure")
            info.size = item.get("size", 0)
            info.seeders = item.get("seeders", 0)
            info.page_url = item.get("page_url")
            info.org_string = item.get("title", "")
            results[idx] = info

        # 5. 集数映射（动漫合并季 / 绝对集号）
        if self._episode_mapping_enabled:
            map_items = []
            map_indices = []
            for idx, info in enumerate(results):
                if info.type != MediaType.MOVIE and info.tmdb_id and info.begin_episode:
                    map_items.append(
                        {
                            "tmdb_id": info.tmdb_id,
                            "season": info.begin_season,
                            "episode": info.begin_episode,
                            "end_episode": info.end_episode,
                        }
                    )
                    map_indices.append(idx)
            if map_items:
                log.info(f"[EpisodeMapper]批量映射 {len(map_items)} 条记录")
                mapped = self._episode_mapper.map_batch(map_items)
                mapped_count = 0
                for i, mapped_result in enumerate(mapped):
                    if isinstance(mapped_result, tuple):
                        idx = map_indices[i]
                        old_season = results[idx].begin_season
                        old_episode = results[idx].begin_episode
                        if old_season != mapped_result[0] or old_episode != mapped_result[1]:
                            results[idx].seeds_season = old_season
                            results[idx].seeds_episode = old_episode
                            results[idx].seeds_end_episode = results[idx].end_episode
                        if len(mapped_result) == 4:
                            (
                                results[idx].begin_season,
                                results[idx].begin_episode,
                                results[idx].end_season,
                                results[idx].end_episode,
                            ) = mapped_result
                        else:
                            results[idx].begin_season, results[idx].begin_episode = mapped_result
                        mapped_count += 1
                if mapped_count > 0:
                    log.info(f"[EpisodeMapper]批量映射完成: {mapped_count}/{len(map_items)} 条已映射")

        return results

    # ---------- 分组识别（名称候选驱动） ----------

    def identify_groups(self, groups: list[dict], language: str | None = None) -> dict:
        """
        按组识别 — 组内聚合名称候选，中文优先，逐名尝试直到命中。

        :param groups: [{_cache_key, names, cn_name, en_name, year, type,
                         seasons, episodes, title, site, enclosure, size, seeders}]
        :return: {cache_key: (IdentifyStatus, MediaInfo)}
        """
        results: dict = {}
        if not groups:
            return results

        max_workers = min(len(groups), 2)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_key = {
                executor.submit(self._identify_group, group, language): group["_cache_key"] for group in groups
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    log.error(f"[MediaService]组识别执行出错: {key}, {e}")
                    results[key] = (IdentifyStatus.ERROR, MediaInfo(org_string=key))

        # 集数映射（动漫合并季 / 绝对集号），仅处理命中项
        if self._episode_mapping_enabled:
            hit_infos = [
                info
                for status, info in results.values()
                if status == IdentifyStatus.HIT and info.type != MediaType.MOVIE and info.tmdb_id and info.begin_episode
            ]
            if hit_infos:
                map_items = [
                    {
                        "tmdb_id": info.tmdb_id,
                        "season": info.begin_season,
                        "episode": info.begin_episode,
                        "end_episode": info.end_episode,
                    }
                    for info in hit_infos
                ]
                log.info(f"[EpisodeMapper]批量映射 {len(map_items)} 条记录")
                mapped = self._episode_mapper.map_batch(map_items)
                mapped_count = 0
                for info, mapped_result in zip(hit_infos, mapped, strict=False):
                    if isinstance(mapped_result, tuple):
                        # 保存种子原始值
                        info.seeds_season = info.begin_season
                        info.seeds_episode = info.begin_episode
                        info.seeds_end_episode = info.end_episode
                        if len(mapped_result) == 4:
                            info.begin_season, info.begin_episode, info.end_season, info.end_episode = mapped_result
                        else:
                            info.begin_season, info.begin_episode = mapped_result
                        mapped_count += 1
                if mapped_count > 0:
                    log.info(f"[EpisodeMapper]批量映射完成: {mapped_count}/{len(map_items)} 条已映射")

        return results

    def _identify_group(self, group: dict, language: str | None) -> tuple:
        """单组识别：按序尝试名称候选，返回 (IdentifyStatus, MediaInfo)"""
        seasons = group.get("seasons") or []
        episodes = group.get("episodes") or []
        info = MediaInfo(
            cn_name=group.get("cn_name"),
            en_name=group.get("en_name"),
            year=group.get("year"),
            begin_season=seasons[0] if seasons else None,
            end_season=seasons[-1] if len(seasons) > 1 else None,
            begin_episode=episodes[0] if episodes else None,
            end_episode=episodes[-1] if len(episodes) > 1 else None,
            type=group.get("type"),
        )
        info.site = group.get("site")
        info.enclosure = group.get("enclosure")
        info.size = group.get("size", 0)
        info.seeders = group.get("seeders", 0)
        info.org_string = group.get("title", "")

        hits: list[tuple[str, LookupResult]] = []
        for name in group.get("names") or []:
            is_cn = bool(StringUtils.is_chinese(name))
            query = SimpleNamespace(
                title_cn=name if is_cn else None,
                title_en=None if is_cn else name,
                year=group.get("year"),
                season=seasons[0] if seasons else None,
                episode=episodes[0] if episodes else None,
                type=group.get("type"),
                org_string=group.get("title") or "",
            )
            try:
                looked_up = self._lookup.lookup(query, language=language or "")
            except HttpRateLimitError as err:
                log.warn(f"[MediaService]组识别被限流: {group.get('cn_name') or name}, {err}")
                return IdentifyStatus.ERROR, info
            except Exception as err:
                log.error(f"[MediaService]组识别出错: {name}, {err}")
                return IdentifyStatus.ERROR, info
            if looked_up and looked_up.tmdb_id:
                hits.append((name, looked_up))

        if not hits:
            return IdentifyStatus.NOT_FOUND, info
        # 多名共识：全部名称指向同一 TMDB 条目才可信；
        # 冲突时采信最具体（最长）名称 —— 短名往往是系列通称（如 攻壳机动队 vs ...Stand Alone Complex）
        chosen_name, looked_up = hits[0]
        distinct = {r.tmdb_id for _, r in hits}
        if len(distinct) > 1:
            chosen_name, looked_up = max(hits, key=lambda h: len(h[0]))
            log.warn(
                f"[MediaService]组内名称识别冲突: {[(n, r.tmdb_id) for n, r in hits]}，"
                f"采信最具体名称 '{chosen_name}' -> TMDBID={looked_up.tmdb_id}"
            )
        if looked_up and looked_up.tmdb_id:
            info.tmdb_id = looked_up.tmdb_id
            info.title = looked_up.title
            info.original_title = looked_up.original_title
            info.year = looked_up.year or info.year
            info.overview = looked_up.overview
            info.vote_average = looked_up.vote_average
            info.poster_path = looked_up.poster_path
            info.backdrop_path = looked_up.backdrop_path
            info.tmdb_info = {
                "id": looked_up.tmdb_id,
                "title": looked_up.title,
                "original_title": looked_up.original_title,
                "media_type": looked_up.media_type.value if looked_up.media_type else None,
                "year": looked_up.year,
                "overview": looked_up.overview,
                "vote_average": looked_up.vote_average,
                "poster_path": looked_up.poster_path,
                "backdrop_path": looked_up.backdrop_path,
                "genres": looked_up.genres,
                "external_ids": looked_up.external_ids,
            }
            return IdentifyStatus.HIT, info
        return IdentifyStatus.NOT_FOUND, info

    # ---------- 文件列表识别 ----------

    def identify_files(
        self,
        file_list,
        tmdb_info=None,
        media_type=None,
        season=None,
        episode_format: EpisodeFormat | None = None,
        language=None,
        chinese=True,
        append_to_response=None,
        backend: StorageBackend | None = None,
    ):
        if not isinstance(file_list, list):
            file_list = [file_list]
        return_media_infos = {}

        def _path_exists(p: str) -> bool:
            return backend.exists(p) if backend else os.path.exists(p)

        def _path_isdir(p: str) -> bool:
            if backend:
                info = backend.stat(p)
                return info is not None and info.is_dir
            return os.path.isdir(p)

        # 1. 有过 tmdb_info 时：本地计算，逐个处理（无需网络）
        if tmdb_info:
            for file_path in file_list:
                try:
                    if not _path_exists(file_path):
                        continue
                    file_name = os.path.basename(file_path)
                    if not _path_isdir(file_path) and PathUtils.get_bluray_dir(file_path):
                        continue
                    file_name, _ = self._apply_words(file_name)
                    parsed = self._parser.parse(file_name)
                    parsed = self._post_process(parsed, file_name)
                    self._fill_episode_from_parent_paths(file_path, parsed)
                    info = MediaInfo.from_parser(parsed) if parsed else MediaInfo()
                    info.set_tmdb_info(tmdb_info)
                    self._backfill_total_episodes(info)
                    if season and info.type != MediaType.MOVIE:
                        info.begin_season = int(season)
                    if episode_format:
                        begin_ep, end_ep, part = episode_format.split_episode(file_name)
                        if begin_ep is not None:
                            info.begin_episode = begin_ep
                            info.part = part
                        if end_ep is not None:
                            info.end_episode = end_ep
                    return_media_infos[file_path] = info
                except Exception as err:
                    log.error(f"[Rmt]发生错误：{str(err)}")

            # 1.1 集数映射（动漫合并季 / 绝对集号）
            if self._episode_mapping_enabled:
                map_items = []
                map_paths = []
                for file_path, info in return_media_infos.items():
                    if info.type != MediaType.MOVIE and info.tmdb_id and info.begin_episode:
                        map_items.append(
                            {
                                "tmdb_id": info.tmdb_id,
                                "season": info.begin_season,
                                "episode": info.begin_episode,
                                "end_episode": info.end_episode,
                            }
                        )
                        map_paths.append(file_path)
                if map_items:
                    log.info(f"[EpisodeMapper]文件批量映射 {len(map_items)} 条记录")
                    mapped = self._episode_mapper.map_batch(map_items)
                    mapped_count = 0
                    for i, mapped_result in enumerate(mapped):
                        if isinstance(mapped_result, tuple):
                            file_path = map_paths[i]
                            info = return_media_infos[file_path]
                            info.seeds_season = info.begin_season
                            info.seeds_episode = info.begin_episode
                            info.seeds_end_episode = info.end_episode
                            if len(mapped_result) == 4:
                                info.begin_season, info.begin_episode, info.end_season, info.end_episode = mapped_result
                            else:
                                info.begin_season, info.begin_episode = mapped_result
                            mapped_count += 1
                    if mapped_count > 0:
                        log.info(f"[EpisodeMapper]文件批量映射完成: {mapped_count}/{len(map_items)} 条已映射")

            return return_media_infos

        # 2. 无 tmdb_info 时：批量识别
        items = []
        path_map = {}
        for file_path in file_list:
            try:
                if not _path_exists(file_path):
                    continue
                file_name = os.path.basename(file_path)
                if not _path_isdir(file_path) and PathUtils.get_bluray_dir(file_path):
                    continue
                file_name, _ = self._apply_words(file_name)
                parent_name = os.path.basename(os.path.dirname(file_path))
                parent_parent_name = os.path.basename(PathUtils.get_parent_paths(file_path, 2))
                items.append(
                    {
                        "title": file_name,
                        "parent_name": parent_name,
                        "parent_parent_name": parent_parent_name,
                    }
                )
                path_map[len(items) - 1] = file_path
            except Exception as err:
                log.error(f"[Rmt]发生错误：{str(err)}")

        if not items:
            return return_media_infos

        # 2.1 批量解析文件名
        titles = [i["title"] for i in items]
        parsed_list = self._parser.parse_batch(titles)

        # 2.2 fallback：从父目录提取信息
        for idx, item in enumerate(items):
            if not parsed_list[idx]:
                parsed_list[idx] = self._parser.parse(
                    item["title"], f"{item['parent_name']} {item['parent_parent_name']}"
                )
            # 公共后处理（与 identify / identify_batch 一致）
            parsed_list[idx] = self._post_process(
                parsed_list[idx],
                item["title"],
                f"{item['parent_name']} {item['parent_parent_name']}",
            )
            # 文件名解析不出集号时，从父目录名提取（动漫单集目录常携带 S01E07）
            if parsed_list[idx]:
                self._fill_episode_from_parent_paths(path_map[idx], parsed_list[idx])

        # 2.3 去重后并发查 TMDB

        unique_keys = {}
        for _, parsed in enumerate(parsed_list):
            if not parsed:
                continue
            key = (
                f"{parsed.title_en or parsed.title_cn or ''}:"
                f"{parsed.year or ''}:"
                f"{parsed.type.value if parsed.type else ''}"
            )
            if key not in unique_keys:
                unique_keys[key] = parsed

        lookup_results = {}
        if unique_keys:
            max_workers = min(len(unique_keys), 2)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_key = {
                    executor.submit(self._lookup.lookup, parsed, language=language or ""): key
                    for key, parsed in unique_keys.items()
                }
                for future in as_completed(future_to_key):
                    key = future_to_key[future]
                    try:
                        lookup_results[key] = future.result()
                    except Exception as e:
                        log.error(f"[MediaService]文件批量识别 TMDB 出错: {key}, {e}")
                        lookup_results[key] = None

        # 2.4 组装结果
        for idx, item in enumerate(items):
            file_path = path_map[idx]
            parsed = parsed_list[idx]
            info = MediaInfo.from_parser(parsed) if parsed else MediaInfo()
            self._backfill_total_episodes(info)
            if parsed:
                key = (
                    f"{parsed.title_en or parsed.title_cn or ''}:"
                    f"{parsed.year or ''}:"
                    f"{parsed.type.value if parsed.type else ''}"
                )
                looked_up = lookup_results.get(key)
                if looked_up:
                    info.tmdb_id = looked_up.tmdb_id
                    info.title = looked_up.title
                    info.year = looked_up.year
                    info.poster_path = looked_up.poster_path
                    info.backdrop_path = looked_up.backdrop_path
                    # 取完整 TMDB detail（含 origin_country/genre_ids 等），
                    # 确保 set_tmdb_info 的类型与分类判定正确，避免落到"未分类"
                    detail = self.get_tmdb_info(
                        mtype=looked_up.media_type or parsed.type,
                        tmdbid=looked_up.tmdb_id,
                    )
                    if detail:
                        info.tmdb_info = detail
                        info.set_tmdb_info(detail)
                    else:
                        info.tmdb_info = {
                            "id": looked_up.tmdb_id,
                            "title": looked_up.title,
                            "name": looked_up.title,
                            "media_type": (
                                MediaType.from_string(looked_up.media_type.value) if looked_up.media_type else None
                            ),
                            "year": looked_up.year,
                            "overview": looked_up.overview,
                            "vote_average": looked_up.vote_average,
                            "poster_path": looked_up.poster_path,
                            "backdrop_path": looked_up.backdrop_path,
                            "genres": looked_up.genres,
                            "external_ids": looked_up.external_ids,
                        }
                        info.set_tmdb_info(info.tmdb_info)
                if episode_format:
                    begin_ep, end_ep, part = episode_format.split_episode(item["title"])
                    if begin_ep is not None:
                        info.begin_episode = begin_ep
                        info.part = part
                    if end_ep is not None:
                        info.end_episode = end_ep
                # 根据识别出的季集数设置 total_episodes（单集=1，范围=差+1），
                # 供转移完成消息聚合"共N集"使用
                if info.begin_episode is not None:
                    if info.end_episode is not None and info.end_episode != info.begin_episode:
                        info.total_episodes = (info.end_episode - info.begin_episode) + 1
                    else:
                        info.total_episodes = 1
            return_media_infos[file_path] = info

        # 3. 集数映射（动漫合并季 / 绝对集号）
        if self._episode_mapping_enabled:
            map_items = []
            map_paths = []
            for file_path, info in return_media_infos.items():
                if info.type != MediaType.MOVIE and info.tmdb_id and info.begin_episode:
                    map_items.append(
                        {
                            "tmdb_id": info.tmdb_id,
                            "season": info.begin_season,
                            "episode": info.begin_episode,
                            "end_episode": info.end_episode,
                        }
                    )
                    map_paths.append(file_path)
            if map_items:
                log.info(f"[EpisodeMapper]文件识别后映射 {len(map_items)} 条记录")
                mapped = self._episode_mapper.map_batch(map_items)
                mapped_count = 0
                for i, mapped_result in enumerate(mapped):
                    if isinstance(mapped_result, tuple):
                        file_path = map_paths[i]
                        info = return_media_infos[file_path]
                        info.seeds_season = info.begin_season
                        info.seeds_episode = info.begin_episode
                        info.seeds_end_episode = info.end_episode
                        if len(mapped_result) == 4:
                            info.begin_season, info.begin_episode, info.end_season, info.end_episode = mapped_result
                        else:
                            info.begin_season, info.begin_episode = mapped_result
                        mapped_count += 1
                if mapped_count > 0:
                    log.info(f"[EpisodeMapper]文件识别后映射完成: {mapped_count}/{len(map_items)} 条已映射")

        return return_media_infos

    def get_media_info_on_files(
        self,
        file_list,
        tmdb_info=None,
        media_type=None,
        season=None,
        episode_format=None,
        language=None,
        chinese=True,
        append_to_response=None,
        backend: StorageBackend | None = None,
    ):
        return self.identify_files(
            file_list, tmdb_info, media_type, season, episode_format, language, chinese, append_to_response, backend
        )

    # ---------- AI Fallback ----------

    # ---------- 搜索引擎 Fallback ----------

    def _search_engine(self, feature_name):
        if not feature_name:
            return None, False
        log.info(f"[Meta]开始通过搜索引擎辅助查询：{feature_name} ...")

        clean_name = self._clean_search_keyword(feature_name)
        if not clean_name:
            return None, False

        candidates = self._lookup.search.search_multi_infos(clean_name)
        if not candidates:
            candidates = self._lookup.search.search_movie_infos(clean_name, None)
            if not candidates:
                return None, False
            matched = self._best_match(clean_name, candidates)
            return (matched.get("title"), True) if matched else (None, False)

        matched = self._best_match(clean_name, candidates)
        if matched:
            is_movie = matched.get("media_type") == MediaType.MOVIE
            return matched.get("title"), is_movie

        return None, False

    @staticmethod
    def _clean_search_keyword(name: str) -> str:
        cleaned = re.sub(r"[\[\]【】\(\)（）{}]", " ", name)
        cleaned = re.sub(r"\d{4}[-\s]*\d{2}[-\s]*\d{2}", " ", cleaned)
        cleaned = re.sub(r"\b\d{3,}p?\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b(?:hdtv|bluray|web-dl|webrip|brrip|dvdrip|x264|x265|hevc|avc|av1|aac|ac3|dts|"
            r"ddp?\d*\.?\d*|flac|atmos|truehd|hdr\d*|dv|sdr|hlg|remux|imax|repack|proper|"
            r"internal|extended|uncut|directors\s*cut|theatrical|unrated|rerelease|remastered|"
            r"upscaled)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _best_match(name: str, candidates: list) -> dict | None:
        if not candidates:
            return None
        name_lower = name.lower()
        best = None
        best_score = 0.0
        for c in candidates:
            title = (c.get("title") or c.get("name") or "").lower()
            if not title:
                continue
            score = difflib.SequenceMatcher(None, name_lower, title).ratio()
            if score > best_score:
                best_score = score
                best = c
        return best if best_score >= 0.6 else None

    # ---------- TMDB 代理方法 ----------

    def get_tmdb_info(self, mtype, tmdbid, language=None, append_to_response=None, chinese=True):
        return self._lookup.get_tmdb_info(mtype, tmdbid, language, append_to_response, chinese)

    def get_tmdb_infos(self, title, year=None, mtype=None, language=None, page=1):
        return self._lookup.get_tmdb_infos(title, year, mtype, language, page)

    def search_tmdb_person(self, name):
        return self._lookup.search_tmdb_person(name)

    def get_tmdbperson_chinese_name(self, person_id=None, person_info=None):
        return self._lookup.get_tmdbperson_chinese_name(person_id, person_info)

    def get_tmdbperson_aka_names(self, person_id):
        return self._lookup.get_tmdbperson_aka_names(person_id)

    def get_tmdb_tv_seasons(self, tv_info):
        return self._lookup.get_tmdb_tv_seasons(tv_info)

    def get_tmdb_tv_seasons_byid(self, tmdbid):
        return self._lookup.get_tmdb_tv_seasons_byid(tmdbid)

    def get_tmdb_season_episodes(self, tmdbid, season):
        return self._lookup.get_tmdb_season_episodes(tmdbid, season)

    def get_tmdb_tv_season_detail(self, tmdbid, season):
        return self._lookup.get_tmdb_tv_season_detail(tmdbid, season)

    def get_tmdb_backdrop(self, mtype, tmdbid):
        return self._lookup.get_tmdb_backdrop(mtype, tmdbid)

    def get_tmdb_backdrops(self, tmdbinfo, original=True):
        return self._lookup.get_tmdb_backdrops(tmdbinfo, original)

    def get_movie_similar(self, tmdbid, page=1):
        return self._lookup.get_movie_similar(tmdbid, page)

    def get_movie_recommendations(self, tmdbid, page=1):
        return self._lookup.get_movie_recommendations(tmdbid, page)

    def get_tv_similar(self, tmdbid, page=1):
        return self._lookup.get_tv_similar(tmdbid, page)

    def get_tv_recommendations(self, tmdbid, page=1):
        return self._lookup.get_tv_recommendations(tmdbid, page)

    def get_tmdb_discover(self, mtype, params=None, page=1):
        return self._lookup.get_tmdb_discover(mtype, params, page)

    def get_tmdb_en_title(self, media_info):
        return self._lookup.get_tmdb_en_title(media_info)

    def enrich_en_name(self, media_info) -> None:
        """补全英文名：en_name 为空或非拉丁（日/韩/中文原名）时取 TMDB 英文标题用于搜索与匹配."""
        if not media_info or not getattr(media_info, "tmdb_id", None):
            return
        if not media_info.en_name or not re.search(r"[A-Za-z]", str(media_info.en_name or "")):
            try:
                en_title = self.get_tmdb_en_title(media_info)
                if en_title and en_title != media_info.title and en_title != media_info.original_title:
                    media_info.en_name = en_title
            except Exception as e:  # noqa: BLE001
                log.debug(f"[service]补全英文名失败: {e}")

    def get_tmdb_zhtw_title(self, media_info):
        return self._lookup.get_tmdb_zhtw_title(media_info)

    def get_tmdbid_by_imdbid(self, imdbid):
        return self._lookup.get_tmdbid_by_imdbid(imdbid)

    def get_random_discover_backdrop(self):
        return self._lookup.get_random_discover_backdrop()

    def get_tmdb_hot_movies(self, page):
        return self._lookup.discover.get_tmdb_hot_movies(page)

    def get_tmdb_hot_tvs(self, page):
        return self._lookup.discover.get_tmdb_hot_tvs(page)

    def get_tmdb_new_movies(self, page):
        return self._lookup.discover.get_tmdb_new_movies(page)

    def get_tmdb_new_tvs(self, page):
        return self._lookup.discover.get_tmdb_new_tvs(page)

    def get_tmdb_upcoming_movies(self, page):
        return self._lookup.discover.get_tmdb_upcoming_movies(page)

    def get_tmdb_trending_all_week(self, page=1):
        return self._lookup.discover.get_tmdb_trending_all_week(page)

    def get_tmdb_cats(self, mtype, tmdbid):
        return self._lookup.get_tmdb_cats(mtype, tmdbid)

    def get_tmdb_genres(self, mtype):
        return self._lookup.get_tmdb_genres(mtype)

    def get_tmdb_genres_names(self, tmdbinfo):
        return self._lookup.get_tmdb_genres_names(tmdbinfo)

    def get_tmdb_directors_actors(self, tmdbinfo):
        return self._lookup.get_tmdb_directors_actors(tmdbinfo)

    def get_tmdb_crews(self, tmdbinfo, nums=None):
        return self._lookup.get_tmdb_crews(tmdbinfo, nums)

    def get_tmdb_production_company_names(self, tmdbinfo):
        return self._lookup.get_tmdb_production_company_names(tmdbinfo)

    def get_tmdb_season_episodes_num(self, tv_info, season):
        return self._lookup.get_tmdb_season_episodes_num(tv_info, season)

    def get_episode_title(self, media_info, language=None):
        return self._lookup.get_episode_title(media_info, language)

    def get_episode_images(self, tv_id, season_id, episode_id, orginal=False):
        return self._lookup.get_episode_images(tv_id, season_id, episode_id, orginal)

    def get_tmdb_factinfo(self, media_info):
        return self._lookup.get_tmdb_factinfo(media_info)

    def get_tmdb_discover_movies_pages(self, params=None):
        return self._lookup.get_tmdb_discover_movies_pages(params)

    def get_person_medias(self, personid, mtype=None, page=1):
        return self._lookup.get_person_medias(personid, mtype, page)

    def get_all_names(self, tmdb_id, mtype) -> list[str]:
        """获取 TMDB 条目全部名称（正名/原名/别名/译名）

        开启 laboratory.identity_index 后走别名索引（热路径零网络），失败回退旧路径。
        """
        if settings.get("laboratory").get("identity_index"):
            try:
                names = get_identity_builder().get_work_names("tmdb", int(tmdb_id), mtype)
                if names:
                    return names
            except Exception as e:
                log.warn(f"[MediaService]身份索引获取别名失败，回退旧路径: {e}")
        return self._lookup.all_names(tmdb_id, mtype)

    def _remap_season_episode(self, info):
        """发布组季/集重映射（种子编号 → TMDB 规范编号）"""
        if not self._episode_mapping_enabled:
            return
        if not info or not info.tmdb_id or info.type == MediaType.MOVIE or info.begin_season is None:
            return
        # 已映射成功则跳过（begin_season != seeds_season 说明 remap 已生效）
        if info.seeds_season and info.begin_season != info.seeds_season:
            return
        mapped = self._episode_remapper.remap(
            int(info.tmdb_id), info.begin_season, info.begin_episode, info.end_episode
        )
        if isinstance(mapped, tuple):
            new_season = mapped[0]
            new_episode = mapped[1]
            if len(mapped) == 4:
                if (
                    new_season != info.begin_season
                    or new_episode != info.begin_episode
                    or mapped[2] != info.end_season
                    or mapped[3] != info.end_episode
                ):
                    info.seeds_season = info.begin_season
                    info.seeds_episode = info.begin_episode
                    info.seeds_end_episode = info.end_episode
                info.begin_season, info.begin_episode, info.end_season, info.end_episode = mapped
            else:
                if new_season != info.begin_season or new_episode != info.begin_episode:
                    info.seeds_season = info.begin_season
                    info.seeds_episode = info.begin_episode
                    info.seeds_end_episode = info.end_episode
                info.begin_season, info.begin_episode = mapped
                # episode=0 表示仅映射季号，保留原 begin_episode 状态
                if info.begin_episode == 0:
                    info.begin_episode = None

    def merge_media_info(self, target, source):
        result = self._lookup.merge_media_info(target, source)
        self._remap_season_episode(result)
        return result

    def get_detail_url(self, mtype, tmdbid):
        return self._lookup.get_detail_url(mtype, tmdbid)
