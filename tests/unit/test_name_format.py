"""重命名格式 name_format 模块测试"""

from app.services.transfer import name_format as nf


def test_parse_fields():
    assert nf.parse_fields("{title} ({year})/{title} - {season_episode}") == ["season_episode", "title", "year"]
    assert nf.parse_fields("{en_title: {en_title} ({year})}") == ["en_title", "year"]
    assert nf.parse_fields("") == []


def test_validate_ok():
    res = nf.validate("{title} ({year})/{title} - {season_episode}")
    assert res["ok"] is True
    assert res["problems"] == []


def test_validate_unclosed_brace():
    res = nf.validate("{title} ({year")
    assert res["ok"] is False
    assert any("未闭合" in p for p in res["problems"])


def test_validate_unknown_field():
    res = nf.validate("{foo} {title}")
    assert res["ok"] is False
    assert any("foo" in p for p in res["problems"])


def test_render_default():
    d = {"title": "FBI", "year": "2018", "season_episode": "S08E07"}
    out = nf.render("{title} ({year})/{title} - {season_episode}", d)
    assert out == "FBI (2018)/FBI - S08E07"


def test_render_optional_segment_filled():
    d = {"en_title": "FBI", "year": "2018"}
    out = nf.render("{en_title: {en_title} ({year})}", d)
    assert out == " FBI (2018)"


def test_render_optional_segment_empty():
    # 空值在 get_format_dict 中会被替换为 \t 哨兵
    d = {"en_title": "\t", "year": "2018"}
    out = nf.render("{en_title: {en_title} ({year})}", d)
    assert out == ""


def test_render_optional_segment_empty_no_residual_separator():
    # 电影无季集：条件段整体消失，不留分隔符
    d = {"title": "Inception", "year": "2010", "season_episode": "\t"}
    out = nf.render("{title} ({year}){season_episode: - {season_episode}}", d)
    assert out == "Inception (2010)"


def test_split_format_movie():
    assert nf.split_format("{title} ({year})/{title} - {videoFormat}", "movie") == {
        "dir": "{title} ({year})",
        "file": "{title} - {videoFormat}",
    }


def test_split_format_tv():
    assert nf.split_format(
        "{title} ({year})/Season {season}/{title} - {season_episode}", "tv"
    ) == {
        "dir": "{title} ({year})",
        "season": "Season {season}",
        "file": "{title} - {season_episode}",
    }


def test_render_path_movie():
    out = nf.render_path(
        "{title} ({year})/{title} - {videoFormat}",
        "movie",
        {"title": "Inception", "year": "2010", "videoFormat": "1080p"},
    )
    assert out["dir"] == "Inception (2010)"
    assert out["file"] == "Inception - 1080p"


def test_render_path_tv_optional_episode():
    # 电影/无季集时条件段整段消失
    out = nf.render_path(
        "{title} ({year})/Season {season}/{title}{episode_title: - {episode_title}}",
        "tv",
        {"title": "FBI", "year": "2018", "season": "8"},
    )
    assert out["dir"] == "FBI (2018)"
    assert out["season"] == "Season 8"
    assert out["file"] == "FBI"


def test_field_groups_cover_catalog():
    keys = {f["key"] for g in nf.field_groups() for f in g["fields"]}
    assert keys == nf.NAME_FORMAT_FIELDS
