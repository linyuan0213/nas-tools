"""Debug One Piece EP range"""

from app.media.parser.unified import UnifiedParser


def test_debug():
    p = UnifiedParser()
    t = "One Piece EP0011-0012 1999 1080p AAC 2.0 x264@JJL"
    r = p.parse(t)
    print(f"en={r.title_en!r}  ep={r.episode} end_ep={r.end_episode}  year={r.year}  res={r.resource_pix}")
