"""回归测试：meta_info() 入口（媒体搜索）同样剥离站点标记"""

from app.media.parser._metainfo import meta_info


def test_metainfo_bracket_domain():
    mi = meta_info("The.Boys.S04E08.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv")
    assert mi.en_name == "The Boys"
    assert mi.begin_season == 4
    assert mi.begin_episode == 8


def test_metainfo_www_domain():
    mi = meta_info("www.UIndex.org    -    FBI.S08E16.1080p.WEB.h264-ETHEL")
    assert mi.en_name == "Fbi"
    assert mi.begin_season == 8
    assert mi.begin_episode == 16
