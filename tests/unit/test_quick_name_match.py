"""验证 quick_name_match 对攻壳机动队系列种子的过滤能力."""

import pytest

from app.domain.mediatypes import MediaType
from app.indexer.core.result_filter import ResultFilter
from app.media import meta_info


def _make_expected():
    """构造预期媒体 — 攻壳机动队 (2026)"""
    mi = meta_info(title="攻壳机动队 2026", mtype=MediaType.ANIME)
    mi.cn_name = "攻壳机动队"
    mi.en_name = "THE GHOST IN THE SHELL"
    mi.title = "攻壳机动队"
    mi.year = "2026"
    mi.type = MediaType.ANIME
    mi.tmdb_id = 255358
    return mi


@pytest.fixture(scope="module")
def expected():
    return _make_expected()


def _check(expected, title, should_match):
    """解析种子并验证 quick_name_match 结果."""
    mi = meta_info(title=title)
    result = ResultFilter.quick_name_match(mi, expected)
    cn = mi.cn_name or "-"
    en = mi.en_name or "-"
    yr = mi.year or "-"
    tp = mi.type.value if mi.type else "-"
    label = "MATCH" if should_match else "REJECT"
    assert result == should_match, (
        f"[{title[:60]}]\n"
        f"  期望={label} 实际={'MATCH' if result else 'REJECT'}\n"
        f"  解析: cn={cn}, en={en}, year={yr}, type={tp}"
    )


# ---- 应被拒绝的种子 ----

REJECT_CASES = [
    (
        "Ghost in the Shell SAC2045 S02 JAPANESE 1080p NF WEB-DL x265.10bit HDR DDP5.1 Atmos-SMURF[rartv]",
        "SAC_2045 S02",
    ),
    (
        "[攻殼機動隊2 INNOCENCE][Ghost in the Shell 2: Innocence][イノセンス][加流重灌][1080P][MOVIE][SweetDreamDay]",
        "INNOCENCE 电影",
    ),
    (
        "[攻壳机动队][Ghost in the Shell][攻殻機動隊][BDMV][1080p][MOVIE][ITA]",
        "攻壳机动队 1995 电影",
    ),
    (
        "[攻壳机动队2.0][Ghost in the Shell 2.0][攻殻機動隊2.0][BDMV][1080p][MOVIE][AVC][GER]",
        "攻壳机动队 2.0 电影",
    ),
    (
        "[攻壳机动队SAC + 2nd GIG][Ghost in the Shell: SAC + 2nd GIG][FRA][BDMV][1080p][TV 01-52 Fin + 2 OVA]",
        "SAC + 2nd GIG 老 TV",
    ),
    (
        "[攻壳机动队: 个别的11人][Ghost in the Shell S.A.C. 2nd GIG - Individual Eleven][HK][1080P][MOVIE][BDISO]",
        "个别的11人 OVA",
    ),
    (
        "[philosophy-raws&VCB-Studio]攻壳机动队 STAND ALONE COMPLEX 10bit 1080p HEVC BDRip[Fin]",
        "SAC 老 TV",
    ),
    (
        "[VCB-Studio] Ghost in the Shell Arise / 攻壳机动队 Arise 10bit 1080p BDRip (Fin)",
        "ARISE OVA",
    ),
    (
        "[攻壳机动队 S.A.C. 笑面男][Ghost in the Shell: Stand Alone Complex - The Laughing Man][BDMV][1080p][OVA]",
        "笑面男 OVA",
    ),
    (
        "[攻壳机动队][Ghost in the Shell][攻殻機動隊][BDMV][2160p][MOVIE UHDBDx1+BDx2][ITA]",
        "攻壳机动队 4K 电影",
    ),
    (
        "[攻壳机动队ARISE Alternative Architecture 09-10话][Ghost in the Shell Arise - 05 - Pyrophoric Cult][BDRip]",
        "ARISE Alternative Architecture",
    ),
    # 英文名匹配 + 中文名含英文后缀 → 拒绝
    (
        "Ghost in the shell 攻殼機動隊GIG 1080P BDRIP 第1~26話 全 外挂字幕 收藏版！",
        "攻殼機動隊GIG (SAC 2nd GIG, 含英文后缀)",
    ),
    # 全中文衍生标识词 → 应拒绝
    (
        "[攻壳机动队 新剧场版][攻殻機動隊 新劇場版]",
        "攻壳机动队 新剧场版（含衍生词 剧场版）",
    ),
    (
        "[攻壳机动队 特别篇][Ghost in the Shell Special]",
        "攻壳机动队 特别篇（含衍生词 特别篇）",
    ),
    (
        "[攻壳机动队 总集篇]",
        "攻壳机动队 总集篇（含衍生词 总集篇）",
    ),
    (
        "[VCB-Studio] 攻壳机动队 OVA [BDRip]",
        "攻壳机动队 OVA（含衍生词 OVA）",
    ),
    # 非CJK _cn_simplify 子串匹配 + cn_name 含英文 → 拒绝
    (
        "[攻殼機動隊2 INNOCENCE][Ghost in the Shell 2: Innocence][MOVIE]",
        "INNOCENCE 2004 电影（非CJK子串 + cn含英文）",
    ),
]


@pytest.mark.parametrize("title,label", REJECT_CASES)
def test_reject_noise(expected, title, label):
    _check(expected, title, should_match=False)


# ---- 应通过的种子 ----

MATCH_CASES = [
    (
        "THE.GHOST.IN.THE.SHELL.S01E03.2026.1080p.AMZN.WEB-DL.H264.DDP-CMCTV",
        "2026 S01E03 AMZN",
    ),
    (
        "[LoliHouse] 攻壳机动队 / The Ghost in the Shell - 03 [WebRip 1080p HEVC-10bit AAC][简繁内封字幕]",
        "2026 S01E03 LoliHouse",
    ),
    (
        "THE.GHOST.IN.THE.SHELL.S01E02.2026.1080p.AMZN.WEB-DL.H264.DDP-CMCTV",
        "2026 S01E02 AMZN",
    ),
    (
        "THE.GHOST.IN.THE.SHELL.S01E01.2026.1080p.AMZN.WEB-DL.H264.DDP-CMCTV",
        "2026 S01E01 AMZN",
    ),
    (
        "THE GHOST IN THE SHELL S01E03 EPISODE 03 1080p AMZN WEB-DL DUAL DDP2.0 H 264-VARYG",
        "2026 S01E03 VARYG",
    ),
    (
        "[ToonsHub] THE GHOST IN THE SHELL S01E01 1080p AMZN WEB-DL DUAL DDP2.0 H.265",
        "2026 S01E01 ToonsHub",
    ),
    (
        "[ToonsHub] THE GHOST IN THE SHELL S01E03 1080p AMZN WEB-DL DUAL DDP2.0 H.264",
        "2026 S01E03 ToonsHub H264",
    ),
    (
        "[sam] The Ghost in the Shell (2026) - S01E03 (WEB 1080p HEVC x265 10-bit EAC-3) [Dual-Audio]",
        "2026 S01E03 sam",
    ),
    (
        "[sam] The Ghost in the Shell (2026) - S01E02 (WEB 1080p HEVC x265 10-bit EAC-3) [Dual-Audio]",
        "2026 S01E02 sam",
    ),
    (
        "[sam] The Ghost in the Shell (2026) - S01E01 (WEB 1080p HEVC x265 10-bit EAC-3) [Dual-Audio]",
        "2026 S01E01 sam",
    ),
    (
        "[DKB] The Ghost in the Shell - S01E01 [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]",
        "2026 S01E01 DKB",
    ),
    (
        "[DKB] The Ghost in the Shell - S01E02 [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]",
        "2026 S01E02 DKB",
    ),
    (
        "[DKB] The Ghost in the Shell - S01E03 [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]",
        "2026 S01E03 DKB",
    ),
    (
        "[Ironclad] THE GHOST IN THE SHELL - S01E01 [WEB.1080p.AV1] | THE GHOST in the SHELL",
        "2026 S01E01 Ironclad",
    ),
    (
        "[Ironclad] THE GHOST IN THE SHELL - S01E02 [WEB.1080p.AV1] | THE GHOST in the SHELL",
        "2026 S01E02 Ironclad",
    ),
    (
        "[Ironclad] THE GHOST IN THE SHELL - S01E03 [WEB.1080p.AV1] | THE GHOST in the SHELL",
        "2026 S01E03 Ironclad",
    ),
    (
        "[Reza] THE GHOST IN THE SHELL (2026) - S01E01 [WEBRip HEVC 1080p EAC3] (Dual Audio)",
        "2026 S01E01 Reza",
    ),
    (
        "[Reza] THE GHOST IN THE SHELL (2026) - S01E02 [WEBRip HEVC 1080p EAC3] (Dual Audio)",
        "2026 S01E02 Reza",
    ),
    (
        "[Reza] THE GHOST IN THE SHELL (2026) - S01E03 [WEBRip HEVC 1080p EAC3] (Dual Audio)",
        "2026 S01E03 Reza",
    ),
    (
        "The Ghost in the Shell 2026 S01E01-S01E03 1080p AMZN WEB-DL H264 DDP2.0-UBWEB",
        "2026 S01E01-E03 合集",
    ),
    (
        "[NanakoRaws] Koukaku Kidoutai The Ghost in the Shell S01E01 (THK 1080p HEVC AAC)",
        "2026 S01E01 NanakoRaws",
    ),
    (
        "[NanakoRaws] Koukaku Kidoutai The Ghost in the Shell S01E02 (THK 1080p HEVC AAC)",
        "2026 S01E02 NanakoRaws",
    ),
    (
        "[NanakoRaws] Koukaku Kidoutai The Ghost in the Shell S01E03 (THK 1080p HEVC AAC)",
        "2026 S01E03 NanakoRaws",
    ),
]


@pytest.mark.parametrize("title,label", MATCH_CASES)
def test_accept_valid(expected, title, label):
    _check(expected, title, should_match=True)


# ---- 描述提取 cn_name 清洗（cn_name 经 get_keyword_from_string 去季数后缀后匹配） ----

DESC_CLEAN_REJECT_CASES = [
    (
        "Ghost in the Shell: Stand Alone Complex S03 BluRay REMUX AVC 1080p TrueHD Atmos 7.1-FraMeSToR",
        "攻壳机动队第三季",
        "SAC S03 cn_name 清洗后 en_name 含 SAC 不匹配",
    ),
    (
        "Ghost in the Shell Stand Alone Complex S01 1080p BluRay Remux AVC DTS-HD MA 5.1-TRiToN",
        "攻壳机动队第一季",
        "SAC S01 cn_name 清洗后 en_name 含 SAC 不匹配",
    ),
]

DESC_CLEAN_MATCH_CASES = [
    (
        "THE GHOST IN THE SHELL S01E03 1080p AMZN WEB-DL DUAL DDP2.0 H.264-VARYG",
        "攻壳机动队第一季",
        "2026 S01E03 cn_name 清洗为 攻壳机动队 后正常匹配",
    ),
    (
        "[LoliHouse] 攻壳机动队 / The Ghost in the Shell - 03 [WebRip 1080p]",
        "攻壳机动队第一季",
        "cn_name 清洗后 en_name 和 cn_name 都在 match 中",
    ),
]


def _check_with_cn(expected, title, cn_name, should_match):
    """解析种子，手动设置 cn_name（模拟描述提取+清洗），再验证 quick_name_match"""
    from app.utils import StringUtils

    mi = meta_info(title=title)
    if cn_name:
        _, cleaned, _, _, _, _ = StringUtils.get_keyword_from_string(cn_name)
        mi.cn_name = cleaned or cn_name
    result = ResultFilter.quick_name_match(mi, expected)
    cn = mi.cn_name or "-"
    en = mi.en_name or "-"
    yr = mi.year or "-"
    label = "MATCH" if should_match else "REJECT"
    assert result == should_match, (
        f"[{title[:60]}] cn_desc={cn_name}\n"
        f"  期望={label} 实际={'MATCH' if result else 'REJECT'}\n"
        f"  解析: cn={cn}, en={en}, year={yr}"
    )


@pytest.mark.parametrize("title,cn_name,label", DESC_CLEAN_REJECT_CASES)
def test_desc_clean_reject(expected, title, cn_name, label):
    _check_with_cn(expected, title, cn_name, should_match=False)


@pytest.mark.parametrize("title,cn_name,label", DESC_CLEAN_MATCH_CASES)
def test_desc_clean_match(expected, title, cn_name, label):
    _check_with_cn(expected, title, cn_name, should_match=True)


# ---- 字幕标签前缀污染（"中字攻壳机动队" 来自 description 提取） ----

TAG_PREFIX_CASES = [
    ("中字攻壳机动队", False, "中字前缀 → 剥除后等同 攻壳机动队，en 含 SAC 应拒绝"),
    ("官方中字攻壳机动队", False, "官方中字前缀"),
    ("中文字幕攻壳机动队", False, "中文字幕前缀"),
    ("中文字攻壳机动队", False, "中文字前缀"),
]


@pytest.mark.parametrize("cn_name,should_match,label", TAG_PREFIX_CASES)
def test_tag_prefix_contamination(expected, cn_name, should_match, label):
    """description 提取的中文名带字幕标签前缀时不得直通"""
    from types import SimpleNamespace

    meta = SimpleNamespace(
        title=None,
        cn_name=cn_name,
        en_name="Ghost in the Shell Stand Alone Complex",
        year=None,
        type=MediaType.TV,
        org_string="Ghost in the Shell Stand Alone Complex S04 1080p NF WEB-DL",
        rev_string=None,
    )
    result = ResultFilter.quick_name_match(meta, expected)
    assert result == should_match, f"{label}: cn={cn_name}, 期望={'MATCH' if should_match else 'REJECT'}"


def test_strip_cn_tag_prefix():
    from app.indexer.core.result_filter import _strip_cn_tag_prefix

    assert _strip_cn_tag_prefix("中字攻壳机动队") == "攻壳机动队"
    assert _strip_cn_tag_prefix("官方中字攻壳机动队") == "攻壳机动队"
    assert _strip_cn_tag_prefix("中文字幕攻壳机动队") == "攻壳机动队"
    assert _strip_cn_tag_prefix("攻壳机动队") == "攻壳机动队"
    # 合法剧名不被误剥
    assert _strip_cn_tag_prefix("中华小当家") == "中华小当家"
