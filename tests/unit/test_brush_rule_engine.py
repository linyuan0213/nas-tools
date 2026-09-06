"""BrushRuleEngine 单元测试 — check_range_rule / check_remove_rule / check_stop_rule / check_rss_rule."""

import pytest

from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.domain.enums import BrushDeleteType, BrushStopType, SwitchState

# =========================================================================
# check_range_rule
# =========================================================================


class TestCheckRangeRule:
    def test_none_value_returns_true(self):
        assert BrushRuleEngine.check_range_rule(None, "gt#100") is True

    def test_empty_rule_value_returns_true(self):
        assert BrushRuleEngine.check_range_rule(42, "") is True
        assert BrushRuleEngine.check_range_rule(42, None) is True  # type: ignore[arg-type]

    def test_no_hash_delimiter_returns_true(self):
        assert BrushRuleEngine.check_range_rule(42, "justastring") is True

    def test_empty_range_after_hash_returns_true(self):
        assert BrushRuleEngine.check_range_rule(42, "gt#") is True

    def test_gt_operator_value_below_min_returns_false(self):
        assert BrushRuleEngine.check_range_rule(5, "gt#10") is False

    def test_gt_operator_value_above_min_returns_true(self):
        assert BrushRuleEngine.check_range_rule(15, "gt#10") is True

    def test_gt_operator_value_equal_to_min_returns_true(self):
        assert BrushRuleEngine.check_range_rule(10, "gt#10") is True

    def test_lt_operator_value_below_max_returns_true(self):
        assert BrushRuleEngine.check_range_rule(5, "lt#10") is True

    def test_lt_operator_value_above_max_returns_false(self):
        assert BrushRuleEngine.check_range_rule(15, "lt#10") is False

    def test_lt_operator_value_equal_to_max_returns_true(self):
        assert BrushRuleEngine.check_range_rule(10, "lt#10") is True

    def test_bw_operator_value_inside_range_returns_true(self):
        assert BrushRuleEngine.check_range_rule(5, "bw#1,10") is True

    def test_bw_operator_value_equal_to_min_returns_true(self):
        assert BrushRuleEngine.check_range_rule(1, "bw#1,10") is True

    def test_bw_operator_value_equal_to_max_returns_false(self):
        assert BrushRuleEngine.check_range_rule(10, "bw#1,10") is False

    def test_bw_operator_value_below_range_returns_false(self):
        assert BrushRuleEngine.check_range_rule(0, "bw#1,10") is False

    def test_bw_operator_value_above_range_returns_false(self):
        assert BrushRuleEngine.check_range_rule(15, "bw#1,10") is False

    def test_bw_operator_without_max_returns_true(self):
        assert BrushRuleEngine.check_range_rule(100, "bw#5") is True

    def test_multiplier_applied_correctly(self):
        assert BrushRuleEngine.check_range_rule(3600, "gt#1", multiplier=3600) is True
        assert BrushRuleEngine.check_range_rule(1800, "gt#1", multiplier=3600) is False

    def test_non_numeric_rule_value_does_not_raise(self):
        assert BrushRuleEngine.check_range_rule(10, "gt#abc") is True

    def test_non_numeric_rule_value_with_multiple_parts(self):
        assert BrushRuleEngine.check_range_rule(10, "bw#abc,def") is True

    def test_type_error_in_float_conversion_returns_true(self):
        assert BrushRuleEngine.check_range_rule(10, "bw#foo,bar") is True

    def test_zero_value_zero_rule_with_gt(self):
        assert BrushRuleEngine.check_range_rule(0, "gt#0") is True

    def test_zero_value_with_gt_positive(self):
        assert BrushRuleEngine.check_range_rule(0, "gt#1") is False

    def test_float_values(self):
        assert BrushRuleEngine.check_range_rule(3.5, "gt#3.0") is True
        assert BrushRuleEngine.check_range_rule(2.5, "gt#3.0") is False


# =========================================================================
# check_remove_rule
# =========================================================================


class TestCheckRemoveRule:
    def test_empty_rule_returns_notdelete(self):
        need, dtype = BrushRuleEngine.check_remove_rule(None, {})
        assert need is False
        assert dtype == BrushDeleteType.NOTDELETE

    def test_empty_rule_dict_returns_notdelete(self):
        need, dtype = BrushRuleEngine.check_remove_rule({}, {})
        assert need is False
        assert dtype == BrushDeleteType.NOTDELETE

    def test_rule_off_or_hash_skipped(self):
        rule = {
            "time": "#",
            "ratio": SwitchState.OFF.value,
            "uploadsize": None,
            "mode": "or",
        }
        need, dtype = BrushRuleEngine.check_remove_rule(rule, {})
        assert need is False

    @pytest.mark.parametrize(
        "rule_key,rule_value,params,expected_delete_type",
        [
            ("time", "gt#1", {"seeding_time": 4000}, BrushDeleteType.SEEDTIME),
            ("ratio", "gt#1", {"ratio": 2.0}, BrushDeleteType.RATIO),
            ("uploadsize", "gt#1", {"uploaded": 5 * 1024**3}, BrushDeleteType.UPLOADSIZE),
            ("avg_upspeed", "gt#50", {"avg_upspeed": 100 * 1024}, BrushDeleteType.AVGUPSPEED),
            ("iatime", "gt#1", {"iatime": 4000}, BrushDeleteType.IATIME),
            ("upspeed", "gt#100", {"upspeed": 200 * 1024}, BrushDeleteType.UPSPEED),
        ],
    )
    def test_range_rule_triggers_in_or_mode(self, rule_key, rule_value, params, expected_delete_type):
        rule = {rule_key: rule_value, "mode": "or"}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == expected_delete_type

    @pytest.mark.parametrize(
        "rule_key,rule_value,params",
        [
            ("time", "gt#100", {"seeding_time": 100}),
            ("ratio", "gt#10", {"ratio": 1.0}),
            ("uploadsize", "gt#10", {"uploaded": 0}),
            ("avg_upspeed", "gt#1000", {"avg_upspeed": 0}),
        ],
    )
    def test_range_rule_not_triggered(self, rule_key, rule_value, params):
        rule = {rule_key: rule_value, "mode": "or"}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_freestatus_free_rule_triggers_when_free_expired(self):
        rule = {"freestatus": "FREE", "mode": "or"}
        params = {"torrent_attr": {"free": False}}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.FREESTATUS

    def test_freestatus_free_rule_not_triggers_when_still_free(self):
        rule = {"freestatus": "FREE", "mode": "or"}
        params = {"torrent_attr": {"free": True}}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_freestatus_switch_triggers_when_free_expired(self):
        # 前端开关存值 'Y'：免费到期（非免费）才删
        rule = {"freestatus": "Y", "mode": "or"}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, {"torrent_attr": {"free": False}})
        assert need is True
        assert dtype == BrushDeleteType.FREESTATUS

    def test_freestatus_switch_not_triggers_when_still_free(self):
        rule = {"freestatus": "Y", "mode": "or"}
        need, _ = BrushRuleEngine.check_remove_rule(rule, {"torrent_attr": {"free": True}})
        assert need is False

    def test_freestatus_normal_rule_not_triggers_when_currently_free(self):
        # 与“到期删”一致：仍免费不删，避免把免费种子刚进就删
        rule = {"freestatus": "NORMAL", "mode": "or"}
        params = {"torrent_attr": {"free": True}}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_freestatus_normal_rule_triggers_when_not_free(self):
        rule = {"freestatus": "NORMAL", "mode": "or"}
        params = {"torrent_attr": {"free": False}}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.FREESTATUS

    def test_hr_rule_triggers_when_is_hr(self):
        rule = {"hr": "HR", "mode": "or"}
        params = {"torrent_attr": {"hr": True}}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.HR

    def test_hr_rule_not_triggers_when_not_hr(self):
        rule = {"hr": "HR", "mode": "or"}
        params = {"torrent_attr": {"hr": False}}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_hr_nohr_rule_triggers_when_not_hr(self):
        rule = {"hr": "NOHR", "mode": "or"}
        params = {"torrent_attr": {"hr": False}}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.HR

    def test_hr_nohr_rule_not_triggers_when_is_hr(self):
        rule = {"hr": "NOHR", "mode": "or"}
        params = {"torrent_attr": {"hr": True}}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_tracker_error_triggers_when_on_and_has_error(self):
        rule = {"tracker_error": SwitchState.ON.value, "mode": "or"}
        params = {"tracker_error": True}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.TRACKERERROR

    def test_tracker_error_not_triggers_when_on_and_no_error(self):
        rule = {"tracker_error": SwitchState.ON.value, "mode": "or"}
        params = {"tracker_error": False}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_tracker_error_y_triggers_when_has_error(self):
        rule = {"tracker_error": "Y", "mode": "or"}
        params = {"tracker_error": True}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True

    def test_and_mode_all_rules_must_trigger(self):
        rule = {"time": "gt#1", "ratio": "gt#1", "mode": "and"}
        params = {"seeding_time": 4000, "ratio": 2.5}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert isinstance(dtype, list) and len(dtype) == 2

    def test_and_mode_one_rule_fails_returns_notdelete(self):
        rule = {"time": "gt#1", "ratio": "gt#100", "mode": "and"}
        params = {"seeding_time": 4000, "ratio": 0.5}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False
        assert dtype == BrushDeleteType.NOTDELETE

    def test_or_mode_first_match_returns_immediately(self):
        rule = {"time": "gt#1", "ratio": "gt#1", "mode": "or"}
        params = {"seeding_time": 4000, "ratio": 0.0}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.SEEDTIME

    def test_and_mode_none_value_blocks_deletion(self):
        rule = {"time": "gt#1", "freespace": "lt#100", "mode": "and"}
        params = {"seeding_time": 4000}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False
        assert dtype == BrushDeleteType.NOTDELETE

    def test_or_mode_none_value_skips_rule(self):
        rule = {"time": "gt#1", "freespace": "lt#100", "mode": "or"}
        params = {"seeding_time": 4000}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.SEEDTIME

    def test_mode_default_is_and(self):
        rule = {"time": "gt#1", "ratio": "gt#100"}
        params = {"seeding_time": 4000, "ratio": 0.5}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False

    def test_multiple_rules_or_mode_single_trigger_returned(self):
        rule = {"time": "gt#1", "avg_upspeed": "gt#1", "mode": "or"}
        params = {"seeding_time": 4000, "avg_upspeed": 0}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.SEEDTIME

    def test_dltime_rule(self):
        rule = {"dltime": "gt#1", "mode": "or"}
        params = {"dltime": 4000}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.DLTIME

    def test_pending_time_rule(self):
        rule = {"pending_time": "gt#1", "mode": "or"}
        params = {"pending_time": 4000}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.PENDINGTIME

    def test_alive_time_rule(self):
        rule = {"alive_time": "lt#1", "mode": "or"}
        params = {"add_time": "2099-01-01T00:00:00Z"}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.ALIVETIME

    def test_hr_time_rule(self):
        # 非 HR 种子跳过 hr_time 规则（不触发删种）
        rule = {"hr_time": "gt#1", "mode": "or"}
        params = {"seeding_time": 4000, "torrent_attr": {"hr": False}}
        need, _ = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is False
        # HR 种子按做种时间评估
        params_hr = {"seeding_time": 4000, "torrent_attr": {"hr": True}}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params_hr)
        assert need is True
        assert dtype == BrushDeleteType.HRSEEDTIME

    def test_freespace_rule(self):
        rule = {"freespace": "lt#100", "mode": "or"}
        params = {"freespace": 10 * 1024**3}
        need, dtype = BrushRuleEngine.check_remove_rule(rule, params)
        assert need is True
        assert dtype == BrushDeleteType.FREESPACE


# =========================================================================
# check_stop_rule
# =========================================================================


class TestCheckStopRule:
    def test_empty_rule_returns_notstop(self):
        need, stype = BrushRuleEngine.check_stop_rule(None, {})
        assert need is False
        assert stype == BrushStopType.NOTSTOP

    def test_empty_dict_returns_notstop(self):
        need, stype = BrushRuleEngine.check_stop_rule({}, {})
        assert need is False
        assert stype == BrushStopType.NOTSTOP

    def test_rule_off_or_hash_skipped(self):
        stop_rule = {"ratio": "#", "uploadsize": SwitchState.OFF.value, "seedtime": None}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, {})
        assert need is False

    def test_ratio_rule_triggers(self):
        stop_rule = {"ratio": "lt#5.0"}
        params = {"ratio": 2.5}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.RATIO

    def test_ratio_rule_not_triggers(self):
        stop_rule = {"ratio": "lt#1.0"}
        params = {"ratio": 5.0}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is False

    def test_uploadsize_rule_triggers(self):
        stop_rule = {"uploadsize": "gt#1"}
        params = {"uploaded": 5 * 1024**3}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.UPLOADSIZE

    def test_seedtime_rule_triggers(self):
        stop_rule = {"seedtime": "gt#1"}
        params = {"seeding_time": 4000}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.SEEDTIME

    def test_avg_upspeed_rule_triggers(self):
        stop_rule = {"avg_upspeed": "gt#50"}
        params = {"avg_upspeed": 100 * 1024}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.AVGUPSPEED

    def test_avg_upspeed_rule_not_triggers(self):
        stop_rule = {"avg_upspeed": "gt#1000"}
        params = {"avg_upspeed": 50 * 1024}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is False

    def test_stopfree_on_when_free_expired_triggers(self):
        stop_rule = {"stopfree": SwitchState.ON.value}
        params = {"free": False}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.FREEEND

    def test_stopfree_on_when_still_free_does_not_trigger(self):
        stop_rule = {"stopfree": SwitchState.ON.value}
        params = {"free": True}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is False

    def test_stopfree_off_always_passes(self):
        stop_rule = {"stopfree": SwitchState.OFF.value}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, {"free": True})
        assert need is False

    def test_stopfree_switch_triggers_when_free_expired(self):
        # 前端开关存值 'Y'：非 Free（到期）才停
        stop_rule = {"stopfree": "Y"}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, {"free": False})
        assert need is True
        assert stype == BrushStopType.FREEEND

    def test_stopfree_switch_not_triggers_when_still_free(self):
        stop_rule = {"stopfree": "Y"}
        need, _ = BrushRuleEngine.check_stop_rule(stop_rule, {"free": True})
        assert need is False

    def test_first_triggering_rule_wins(self):
        stop_rule = {"ratio": "lt#5.0", "seedtime": "gt#1"}
        params = {"ratio": 2.5, "seeding_time": 4000}
        need, stype = BrushRuleEngine.check_stop_rule(stop_rule, params)
        assert need is True
        assert stype == BrushStopType.RATIO


# =========================================================================
# check_rss_rule
# =========================================================================


class TestCheckRssRule:
    def test_empty_rule_returns_true(self):
        assert BrushRuleEngine.check_rss_rule(None, "title", 1024, None, {}) is True

    def test_rule_value_off_or_hash_skipped(self):
        rss_rule = {"size": "#", "include": SwitchState.OFF.value, "exclude": None}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}) is True

    def test_size_rule_gb_conversion_passes(self):
        rss_rule = {"size": "bw#1,10"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 5 * 1024**3, None, {}) is True

    def test_size_rule_gb_conversion_fails(self):
        rss_rule = {"size": "bw#1,10"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 50 * 1024**3, None, {}) is False

    def test_include_rule_matches_title(self):
        rss_rule = {"include": "BluRay"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.BluRay.1080p", 1024, None, {}) is True

    def test_include_rule_not_matches_title(self):
        rss_rule = {"include": "BluRay"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.WEB-DL.1080p", 1024, None, {}) is False

    def test_exclude_rule_excludes_title(self):
        rss_rule = {"exclude": "CAM"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.CAM.1080p", 1024, None, {}) is False

    def test_exclude_rule_passes_clean_title(self):
        rss_rule = {"exclude": "CAM"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.BluRay.1080p", 1024, None, {}) is True

    def test_include_regex_anchors_and_dots(self):
        rss_rule = {"include": "1080p|2160p"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.2160p.x265", 1024, None, {}) is True

    def test_free_rule_free_seed_passes(self):
        rss_rule = {"free": "FREE"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"free": True}) is True

    def test_free_rule_non_free_seed_fails(self):
        rss_rule = {"free": "FREE"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"free": False}) is False

    def test_free_rule_normal_passes_non_free(self):
        rss_rule = {"free": "NORMAL"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"free": False, "2xfree": False}) is True

    def test_free_rule_2xfree_fails_on_regular_free(self):
        rss_rule = {"free": "2XFREE"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"free": True, "2xfree": False}) is False

    def test_hr_rule_excludes_hr_seed(self):
        rss_rule = {"hr": "Y"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"hr": True}) is False

    def test_hr_rule_passes_non_hr_seed(self):
        rss_rule = {"hr": "Y"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"hr": False}) is True

    def test_peercount_rule_passes(self):
        rss_rule = {"peercount": "gt#5"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"peer_count": 10}) is True

    def test_peercount_rule_fails(self):
        rss_rule = {"peercount": "gt#5"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {"peer_count": 2}) is False

    def test_category_include_matches(self):
        rss_rule = {"category_include": "Movie"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}, category="Movie") is True

    def test_category_exclude_blocks(self):
        rss_rule = {"category_exclude": "TV"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}, category="TV") is False

    def test_label_include_matches(self):
        rss_rule = {"label_include": "HDTV"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}, labels="HDTV,WebDL") is True

    def test_label_exclude_blocks(self):
        rss_rule = {"label_exclude": "CAM"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}, labels="CAM,BadSrc") is False

    def test_multiple_rules_all_must_pass(self):
        rss_rule = {"include": "1080p", "size": "bw#1,50", "free": "FREE"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.1080p", 5 * 1024**3, None, {"free": True}) is True

    def test_multiple_rules_one_fails_returns_false(self):
        rss_rule = {"include": "1080p", "size": "bw#1,50", "free": "FREE"}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "Movie.1080p", 0.1 * 1024**3, None, {"free": True}) is False

    def test_exclude_subscribe_off_passes(self):
        rss_rule = {"exclude_subscribe": SwitchState.OFF.value}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}) is True

    def test_exclude_subscribe_without_media_info_passes(self):
        rss_rule = {"exclude_subscribe": SwitchState.ON.value}
        assert BrushRuleEngine.check_rss_rule(rss_rule, "test", 1024, None, {}) is True

    def test_exclude_subscribe_json_sites_no_crash(self):
        """订阅 rss_sites 存 JSON 字符串 + media_info.site 为 None 时不应崩溃（原为 TypeError）"""
        from app.domain.mediatypes import MediaType

        class _MI:
            type = MediaType.TV
            site = None
            tmdb_id = "123"
            year = "2026"
            title = "测试剧"
            rev_string = ""

            def get_season_string(self):
                return "S01"

        rss_tvs = {
            1: {
                "name": "测试剧",
                "year": "2026",
                "tmdbid": "123",
                "fuzzy_match": None,
                "season": "S01",
                "rss_sites": '["M-Team"]',
            }
        }
        result = BrushRuleEngine.check_rss_rule(
            {"exclude_subscribe": SwitchState.ON.value},
            "测试剧 S01E01",
            1024,
            None,
            {},
            media_info=_MI(),
            rss_tvs=rss_tvs,
        )
        assert result is False  # 站点未知不崩溃，按名称/ID 匹配到订阅 → 排除

    def test_exclude_subscribe_other_site_not_excluded(self):
        """订阅仅限 M-Team，但当前种子来自其他站点时不应排除"""
        from app.domain.mediatypes import MediaType

        class _MI:
            type = MediaType.TV
            site = "OtherSite"
            tmdb_id = "123"
            year = "2026"
            title = "测试剧"
            rev_string = ""

            def get_season_string(self):
                return "S01"

        rss_tvs = {
            1: {
                "name": "测试剧",
                "year": "2026",
                "tmdbid": "123",
                "fuzzy_match": None,
                "season": "S01",
                "rss_sites": '["M-Team"]',
            }
        }
        result = BrushRuleEngine.check_rss_rule(
            {"exclude_subscribe": SwitchState.ON.value},
            "测试剧 S01E01",
            1024,
            None,
            {},
            media_info=_MI(),
            rss_tvs=rss_tvs,
        )
        assert result is True


# =========================================================================
# get_rss_reject_reason
# =========================================================================


class TestGetRssRejectReason:
    def test_empty_rule_returns_empty_string(self):
        assert BrushRuleEngine.get_rss_reject_reason(None, "test", 1024, None, {}) == ""

    def test_rule_passes_returns_empty_string(self):
        rss_rule = {"size": "gt#1"}
        assert BrushRuleEngine.get_rss_reject_reason(rss_rule, "test", 5 * 1024**3, None, {}) == ""

    def test_rule_fails_returns_reason(self):
        rss_rule = {"size": "gt#100"}
        reason = BrushRuleEngine.get_rss_reject_reason(rss_rule, "test", 1, None, {})
        assert reason == "体积不符合"

    def test_include_fails_returns_reason(self):
        rss_rule = {"include": "BluRay"}
        reason = BrushRuleEngine.get_rss_reject_reason(rss_rule, "Movie.WEB-DL", 1024, None, {})
        assert reason == "标题不匹配"


# =========================================================================
# Helper: parse_rule_string / format_rule_string
# =========================================================================


class TestParseRuleString:
    def test_empty_string_returns_empty_dict(self):
        assert BrushRuleEngine.parse_rule_string("") == {}

    def test_none_returns_empty_dict(self):
        assert BrushRuleEngine.parse_rule_string(None) == {}  # type: ignore[arg-type]

    def test_single_rule(self):
        assert BrushRuleEngine.parse_rule_string("size#gt#5") == {"size": "gt#5"}

    def test_multiple_rules(self):
        result = BrushRuleEngine.parse_rule_string("size#gt#5 && ratio#lt#10")
        assert result == {"size": "gt#5", "ratio": "lt#10"}

    def test_no_hash_skipped(self):
        assert BrushRuleEngine.parse_rule_string("just text") == {}


class TestFormatRuleString:
    def test_empty_dict_returns_empty_string(self):
        assert BrushRuleEngine.format_rule_string({}) == ""

    def test_single_rule(self):
        assert BrushRuleEngine.format_rule_string({"size": "gt#5"}) == "size#gt#5"

    def test_multiple_rules(self):
        result = BrushRuleEngine.format_rule_string({"size": "gt#5", "ratio": "lt#10"})
        assert "size#gt#5" in result
        assert "ratio#lt#10" in result
        assert " && " in result

    def test_none_and_empty_values_skipped(self):
        result = BrushRuleEngine.format_rule_string({"size": "gt#5", "ratio": None, "include": ""})
        assert result == "size#gt#5"


# =========================================================================
# format_rss_match_reason
# =========================================================================


class TestFormatRssMatchReason:
    def test_empty_rule_returns_default(self):
        assert BrushRuleEngine.format_rss_match_reason(None) == "RSS 进种"

    def test_free_false_returns_rss_default(self):
        assert BrushRuleEngine.format_rss_match_reason({"free": "NORMAL"}) == "普通种"

    def test_free_true(self):
        assert BrushRuleEngine.format_rss_match_reason({"free": "FREE"}) == "免费"

    def test_custom_rss_body_flags(self):
        reason = BrushRuleEngine.format_rss_match_reason({"free": "FREE", "hr": "Y", "size": "gt#1"})
        assert "免费" in reason
        assert "排除HR" in reason
        assert "体积符合" in reason
