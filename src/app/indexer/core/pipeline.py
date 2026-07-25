"""
搜索流水线编排器

三阶段全局批量处理模型：
1. 本地过滤（Local Filter）：遍历所有站点结果，做 meta_info 解析和规则过滤
2. 批量识别（Batch Identify）：跨站点收集需要 TMDB 的候选，去重后并发查询
3. 匹配过滤（Match Filter）：用 TMDB 结果统一匹配和过滤

关键设计：所有站点的搜索结果收集完成后，统一进入流水线处理，
实现真正的"批量识别"（跨站点去重，一次并发查询所有不重复名称）。
"""

import datetime

import log
from app.domain.enums import ProgressKey, SearchType
from app.indexer.core.batch_identifier import BatchIdentifier
from app.indexer.core.models import FilterStats, PipelineResult
from app.indexer.core.result_filter import ResultFilter
from app.infrastructure.progress import ProgressTracker


class SearchPipeline:
    """
    搜索流水线编排器
    """

    def __init__(
        self,
        media_service,
        result_filter: ResultFilter | None = None,
        batch_identifier: BatchIdentifier | None = None,
        progress: ProgressTracker | None = None,
    ):
        self.result_filter = result_filter or ResultFilter(media=media_service)
        self.batch_identifier = batch_identifier or BatchIdentifier(media_service=media_service)
        self.progress = progress or ProgressTracker()

    def process(
        self,
        all_results,
        filter_args,
        match_media=None,
        in_from: SearchType | None = None,
        progress_key=ProgressKey.Search,
        search_name="",
    ):
        """
        执行三阶段全局批量搜索过滤流水线

        :param all_results: 所有站点的原始搜索结果合并列表（每个 dict 含 _indexer_name/_indexer_order/_indexer_public）
        :param filter_args: 过滤条件
        :param match_media: 需要匹配的媒体信息
        :param in_from: 搜索渠道
        :param progress_key: 进度键
        :param search_name: 搜索关键词（无 match_media 时做伪匹配）
        :return: PipelineResult
        """
        start_time = datetime.datetime.now()
        total_raw = len(all_results)

        # ---------- 阶段1：本地解析和过滤 ----------
        self.progress.update_max(
            ptype=progress_key,
            value=60,
            text=f"本地解析过滤 {total_raw} 条结果...",
        )
        candidates, direct_results, local_stats = self.result_filter.local_filter(
            result_array=all_results,
            filter_args=filter_args,
            match_media=match_media,
            search_name=search_name,
        )

        # ---------- 阶段2：批量识别（跨站点去重） ----------
        if candidates:
            ident_count = sum(1 for c in candidates if not c.skip_tmdb)
            self.progress.update_max(
                ptype=progress_key,
                value=70,
                text=f"批量识别 {ident_count} 条不重复结果...",
            )
            self.batch_identifier.identify(candidates, progress_key=progress_key, match_media=match_media)

        # ---------- 阶段3：TMDB匹配和最终过滤 ----------
        if match_media and candidates:
            self.progress.update_max(
                ptype=progress_key,
                value=85,
                text=f"TMDB 匹配过滤 {len(candidates)} 条候选...",
            )
            matched_results, match_stats = self.result_filter.match_filter(
                candidates=candidates,
                match_media=match_media,
                filter_args=filter_args,
            )
        else:
            matched_results = []
            match_stats = FilterStats()

        all_matched = direct_results + matched_results
        total_stats = local_stats.merge(match_stats)

        end_time = datetime.datetime.now()
        elapsed = (end_time - start_time).seconds

        log.info(
            f"[SearchPipeline]{len(all_results)} 条数据中，"
            f"过滤 {total_stats.index_rule_fail}，"
            f"不匹配 {total_stats.index_match_fail}，"
            f"错误 {total_stats.index_error}，"
            f"有效 {total_stats.index_sucess}，"
            f"耗时 {elapsed} 秒"
        )
        self.progress.update_max(
            ptype=progress_key,
            value=95,
            text=(
                f"共 {len(all_results)} 条，过滤 {total_stats.index_rule_fail}，"
                f"不匹配 {total_stats.index_match_fail}，有效 {total_stats.index_sucess}"
            ),
        )

        return PipelineResult(results=all_matched, stats=total_stats, elapsed_seconds=elapsed)
