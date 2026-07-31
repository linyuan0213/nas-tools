"""编码提取规则 — 覆盖 PT/BT 常见编码格式"""

from __future__ import annotations

import re

from .base import ExtractionRule

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="hevc_h265",
        pattern=re.compile(r"\b(HEVC|H\.?265|X\.?265|H265|x265)\b", re.IGNORECASE),
        category="video_codec",
        priority=85,
        confidence=0.9,
        _extract_fn=lambda m, _: {"video_codec": "HEVC"},
    ),
    ExtractionRule(
        name="avc_h264",
        pattern=re.compile(r"\b(AVC|H\.?264|X\.?264|H264|x264)\b", re.IGNORECASE),
        category="video_codec",
        priority=83,
        confidence=0.9,
        _extract_fn=lambda m, _: {"video_codec": "H.264"},
    ),
    ExtractionRule(
        name="av1",
        pattern=re.compile(r"\b(AV1)\b", re.IGNORECASE),
        category="video_codec",
        priority=81,
        confidence=0.9,
    ),
    ExtractionRule(
        name="vp9",
        pattern=re.compile(r"\b(VP9)\b", re.IGNORECASE),
        category="video_codec",
        priority=79,
        confidence=0.9,
    ),
    ExtractionRule(
        name="vc1_mpeg2",
        pattern=re.compile(r"\b(VC-?1|MPEG-?2|MPEG2)\b", re.IGNORECASE),
        category="video_codec",
        priority=77,
        confidence=0.9,
        _extract_fn=lambda m, _: _vc1_mpeg2_normalize(m),
    ),
    ExtractionRule(
        name="xvid_divx",
        pattern=re.compile(r"\b(XviD|DivX)\b", re.IGNORECASE),
        category="video_codec",
        priority=70,
        confidence=0.85,
    ),
    ExtractionRule(
        name="flac",
        pattern=re.compile(r"\b(FLAC|ALAC|APE|WAV|WavPack|DSD)\b", re.IGNORECASE),
        category="audio_codec",
        priority=85,
        confidence=0.9,
    ),
    ExtractionRule(
        name="dts",
        pattern=re.compile(r"\b(DTS[-\s]?X|DTS[-\s]?HD[-\s]?MA|DTS[-\s]?HD|DTS)\b", re.IGNORECASE),
        category="audio_codec",
        priority=82,
        confidence=0.9,
        _extract_fn=lambda m, _: _dts_normalize(m),
    ),
    ExtractionRule(
        name="truehd_atmos",
        pattern=re.compile(r"\b(TrueHD|Atmos)\b", re.IGNORECASE),
        category="audio_codec",
        priority=80,
        confidence=0.9,
        _extract_fn=lambda m, _: _truehd_normalize(m),
    ),
    ExtractionRule(
        name="aac_ac3",
        pattern=re.compile(r"\b(AAC|AC-?3|E-?AC-?3|DD[P+]?\d*(?:\.\d+)?|DD\d*\.\d+)\b", re.IGNORECASE),
        category="audio_codec",
        priority=75,
        confidence=0.85,
        _extract_fn=lambda m, _: _aac_ac3_normalize(m),
    ),
    ExtractionRule(
        name="mp3_opus",
        pattern=re.compile(r"\b(MP3|MP2|Opus|OGG|Vorbis|WMA)\b", re.IGNORECASE),
        category="audio_codec",
        priority=72,
        confidence=0.85,
    ),
    ExtractionRule(
        name="lpcm_pcm",
        pattern=re.compile(r"\b(LPCM|PCM)\b", re.IGNORECASE),
        category="audio_codec",
        priority=70,
        confidence=0.85,
    ),
]


def _dts_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper().replace(" ", "").replace("-", "")
    if "HDMA" in val:
        return {"audio_codec": "DTS-HD MA"}
    if "HD" in val:
        return {"audio_codec": "DTS-HD"}
    if "X" in val:
        return {"audio_codec": "DTS-X"}
    return {"audio_codec": "DTS"}


def _truehd_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper()
    if "ATMOS" in val:
        return {"audio_codec": "Dolby Atmos"}
    return {"audio_codec": "TrueHD"}


def _aac_ac3_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper().replace(" ", "").replace("-", "")
    if val in ("DDP51", "DD+51", "DDP", "DD+") or val.startswith("DD") and "DDP" in val.replace(".", ""):
        return {"audio_codec": "E-AC-3"}
    if "EAC3" in val:
        return {"audio_codec": "E-AC-3"}
    if "AC3" in val or val.startswith("DD") or "AC" in val and "3" in val:
        return {"audio_codec": "AC-3"}
    return {"audio_codec": "AAC"}


def _vc1_mpeg2_normalize(m: re.Match[str]) -> dict[str, str]:
    val = m.group(0).upper().replace(" ", "").replace("-", "")
    if "MPEG" in val:
        return {"video_codec": "MPEG-2"}
    return {"video_codec": "VC-1"}
