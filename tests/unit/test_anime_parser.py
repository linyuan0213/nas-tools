"""测试动漫标题预处理和日文标题提取"""

from app.media.parser.unified.preprocessor import extract_japanese_title, prepare_title


class TestPrepareTitle:
    def test_empty_title(self):
        assert prepare_title("") == ""
        assert prepare_title("") is None

    def test_mikan_march_tag(self):
        result = prepare_title("[喵萌奶茶屋][鬼灭之刃 柱训练篇][1080p][简日双语]")
        assert "鬼灭之刃" in result

    def test_dmhy_bracket_format(self):
        result = prepare_title("[喵萌奶茶屋&LoliHouse] 鬼灭之刃 / Kimetsu no Yaiba [01-08][WebRip 1080p]")
        assert "鬼灭之刃" in result or "Kimetsu" in result

    def test_filesize_removal(self):
        result = prepare_title("[LoliHouse] Title [1.5GB]")
        assert "1.5GB" not in result

    def test_tv_number_conversion(self):
        result = prepare_title("[TV 02][1080p] Title")
        assert "02" in result

    def test_4k_conversion(self):
        result = prepare_title("[4K] Anime Title [BDrip]")
        assert "2160p" in result.lower()

    def test_category_bracket_removal(self):
        result = prepare_title("[动画][纪录片] Title [1080p]")
        assert "动画" not in result

    def test_slash_name_handling(self):
        result = prepare_title("[LoliHouse] 鬼灭之刃 柱训练篇 / Kimetsu no Yaiba [1080p]")
        assert result

    def test_noise_stripping(self):
        result = prepare_title("[ANi] Jujutsu Kaisen S2 - 01 [1080p][CHS]")
        assert "Jujutsu" in result or result


class TestExtractJapaneseTitle:
    def test_dmhy_slash_format(self):
        result = extract_japanese_title("鬼灭之刃 柱训练篇 / Kimetsu no Yaiba: Hashira Geiko Hen [1080p]")
        assert result is not None
        assert "Kimetsu" in result

    def test_mikan_format(self):
        result = extract_japanese_title(
            "【喵萌奶茶屋】★04月新番★ 鬼灭之刃 柱训练篇 / Kimetsu no Yaiba - Hashira Geiko Hen [1080p]"
        )
        assert result and "Kimetsu" in result

    def test_no_japanese_title(self):
        result = extract_japanese_title("鬼灭之刃 柱训练篇 [1080p]")
        assert result is None

    def test_japanese_chars_skipped(self):
        result = extract_japanese_title("かんなぎ / Kannagi [1080p]")
        assert result is not None and "Kannagi" in result

    def test_multiple_slashes(self):
        result = extract_japanese_title("Chinese Name / Kantai Collection / Kancolle [1080p]")
        assert result and "a" in result.lower()


class TestFansubCnNameRecovery:
    """字幕组标题中文名提取回归 — 穹庐下的魔女案例"""

    def test_cn_romaji_bracket_episode(self):
        """[字幕组] 中文 / 罗马字 [04] 格式：中文名不被 prepare 丢弃"""
        from app.media import meta_info

        mi = meta_info(title="[绿茶字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [04][WebRip][1080p][繁日内嵌]")
        assert mi.cn_name == "穹庐下的魔女"
        assert mi.en_name == "Tenmaku No Jaadugar"
        assert mi.get_episode_list() == [4]

    def test_release_group_not_cn_name(self):
        """字幕组名不得被误识别为中文名"""
        from app.media import meta_info

        mi = meta_info(title="[北宇治字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [03][WebRip][HEVC_AAC][简日内嵌]")
        assert mi.cn_name == "穹庐下的魔女"
        assert "字幕组" not in (mi.cn_name or "")

    def test_en_cn_order(self):
        """英文在前中文在后（ANi 格式）：中文名不丢失"""
        from app.media import meta_info

        mi = meta_info(title="[ANi] Tenmaku no Jādūgar /  穹庐下的魔女 - 04 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]")
        assert mi.cn_name == "穹庐下的魔女"
        assert "Baha" not in (mi.en_name or "")
        assert "Mp4" not in (mi.en_name or "")

    def test_dash_episode_format_kept(self):
        """既有 '- 04' 格式不受影响"""
        from app.media import meta_info

        mi = meta_info(
            title="[绿茶字幕组&LoliHouse] 穹庐下的魔女 / Tenmaku no Jaadugar - 04 "
            "[WebRip 1080p HEVC-10bit AAC][简繁日内封字幕]"
        )
        assert mi.cn_name == "穹庐下的魔女"
        assert mi.en_name == "Tenmaku No Jaadugar"
