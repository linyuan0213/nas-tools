"""Test TMDB identify for problem files"""
import sys; sys.path.insert(0, '/nexus-media/src')
from app.media.parser._metainfo import meta_info

titles = [
    "[ANi] Dr.STONE 新石紀 第四季 - 14 [1080P][Baha][WEB-DL][AAC AVC][CHT]",
    "[ANi] Dr.STONE 新石紀 第四季 - 31 [1080P][Baha][WEB-DL][AAC AVC][CHT]",
    "Golden.Kamuy.S05E11.The.Battle.of.Goryoukaku.1080p.CR.WEB-DL.DDP2.0.H.264-Kitsune",
    "[Haruhana] Kaoru Hana wa Rin to Saku - 05 [WebRip][HEVC-10bit 1080p][CHS_JPN]",
]
for t in titles:
    mi = meta_info(t)
    print(f"parser: en={mi.en_name!r} cn={mi.cn_name!r} season={mi.begin_season} ep={mi.begin_episode} year={mi.year} type={mi.type}")
