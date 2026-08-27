"""
媒体身份元数据模型（ADR-014）

Work / Alias / Franchise / EditionGraph 的数据结构与序列化。
Redis schema: identity:v1:*（版本前缀，演进期双读）
"""

from dataclasses import asdict, dataclass, field

from app.utils import StringUtils

SCHEMA_VERSION = "v1"

# 别名类别
ALIAS_OFFICIAL = "official"
ALIAS_TRANSLATION = "translation"
ALIAS_ROMANIZATION = "romanization"
ALIAS_FAN = "fan"  # 学成别名：仅作评分证据，不可单独确定身份

# fan → translation 升格所需的一致命中次数
FAN_PROMOTE_HITS = 2

# 版本/子系列标记词（单一来源）：IdentityResolver 版本下钻 + ResultFilter 衍生词判断共用。
# 拉丁词组（2nd gig / stand alone complex 等）与「第X季」模式由 resolver 正则单独补充。
EDITION_MARKERS: frozenset[str] = frozenset(
    {"剧场版", "特别篇", "总集篇", "特别版", "OVA", "OAD", "oad", "OVA版", "OAD版", "SAC_2045", "ARISE"}
)


def normalize_text(text: str) -> str:
    """别名归一化 — 与全链路比较语义一致"""
    return StringUtils.handler_special_chars(str(text)).upper().strip()


def alias_key(text: str) -> str:
    """别名索引键（md5，避免超长与多语言字符）"""
    return f"identity:{SCHEMA_VERSION}:alias:{StringUtils.md5_hash(normalize_text(text))}"


def work_key(source: str, work_id: int) -> str:
    return f"identity:{SCHEMA_VERSION}:work:{source}:{work_id}"


def franchise_key(key: str) -> str:
    return f"identity:{SCHEMA_VERSION}:franchise:{key}"


def edition_key(source: str, work_id: int) -> str:
    return f"identity:{SCHEMA_VERSION}:edition:{source}:{work_id}"


@dataclass
class Alias:
    text: str
    lang: str = "unknown"  # zh-Hans / zh-Hant / en / ja / romaji / unknown
    kind: str = ALIAS_TRANSLATION  # official / translation / romanization / fan
    source: str = ""  # tmdb:alternative_titles / tmdb:translations / bgm / learned

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Alias":
        return cls(
            text=data.get("text", ""),
            lang=data.get("lang", "unknown"),
            kind=data.get("kind", ALIAS_TRANSLATION),
            source=data.get("source", ""),
        )


@dataclass
class AliasEntry:
    """AliasIndex 单条：别名 → 作品引用"""

    source: str  # tmdb / bgm
    work_id: int
    kind: str = ALIAS_TRANSLATION
    lang: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AliasEntry":
        return cls(
            source=data.get("source", ""),
            work_id=int(data.get("work_id", 0)),
            kind=data.get("kind", ALIAS_TRANSLATION),
            lang=data.get("lang", "unknown"),
        )


@dataclass
class Work:
    source: str  # tmdb / bgm
    work_id: int
    media_type: str = "tv"  # tv / movie / anime（遵循 ADR-009）
    year: int | None = None
    official_titles: list[str] = field(default_factory=list)
    aliases: list[Alias] = field(default_factory=list)
    franchise: str | None = None  # 所属虚拟 franchise 节点 key

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "work_id": self.work_id,
            "media_type": self.media_type,
            "year": self.year,
            "official_titles": self.official_titles,
            "aliases": [a.to_dict() for a in self.aliases],
            "franchise": self.franchise,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Work":
        return cls(
            source=data.get("source", ""),
            work_id=int(data.get("work_id", 0)),
            media_type=data.get("media_type", "tv"),
            year=data.get("year"),
            official_titles=data.get("official_titles") or [],
            aliases=[Alias.from_dict(a) for a in data.get("aliases") or []],
            franchise=data.get("franchise"),
        )

    def all_name_strings(self) -> list[str]:
        """全部名称（正名 + 别名），去重保序 — 兼容 get_all_names 语义"""
        ret: list[str] = []
        for n in [*self.official_titles, *(a.text for a in self.aliases)]:
            if n and n not in ret:
                ret.append(n)
        return ret


@dataclass
class Franchise:
    """虚拟系列节点 — franchise 概念在 TMDB/BGM 均非条目，需虚拟根承载跨作品关系"""

    key: str
    name: str
    members: list[tuple[str, int]] = field(default_factory=list)  # [(source, work_id)]

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "members": [list(m) for m in self.members]}

    @classmethod
    def from_dict(cls, data: dict) -> "Franchise":
        return cls(
            key=data.get("key", ""),
            name=data.get("name", ""),
            members=[(m[0], int(m[1])) for m in data.get("members") or []],
        )


@dataclass
class EditionEdge:
    """EditionGraph 边：跨作品关系"""

    target_source: str
    target_id: int
    relation: str  # sequel / spinoff / special / remake / compilation
    target_title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EditionEdge":
        return cls(
            target_source=data.get("target_source", ""),
            target_id=int(data.get("target_id", 0)),
            relation=data.get("relation", ""),
            target_title=data.get("target_title", ""),
        )
