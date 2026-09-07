"""
核心常量定义
从 config.py 拆分出来，避免循环导入
"""

# 种子名/文件名要素分隔字符
SPLIT_CHARS = r"\.|\s+|\(|\)|\[|]|-|\+|★|[|]|/|～|;|&|\||#|_|「|」|~|{|}"

# 默认User-Agent
DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"

# 收藏了的媒体的目录名
RMT_FAVTYPE = "精选"

# 支持的媒体文件后缀格式
RMT_MEDIAEXT = [
    ".mp4",
    ".mkv",
    ".ts",
    ".iso",
    ".rmvb",
    ".avi",
    ".mov",
    ".mpeg",
    ".mpg",
    ".wmv",
    ".3gp",
    ".asf",
    ".m4v",
    ".flv",
    ".m2ts",
    ".strm",
    ".tp",
]

# 支持的字幕文件后缀格式
RMT_SUBEXT = [".srt", ".ass", ".ssa"]

# 支持的音轨文件后缀格式
RMT_AUDIO_TRACK_EXT = [".mka"]

# 电视剧动漫的分类genre_ids
ANIME_GENREIDS = ["16"]

# 默认过滤的文件大小，150M
RMT_MIN_FILESIZE = 150 * 1024 * 1024

# 删种检查时间间隔
AUTO_REMOVE_TORRENTS_INTERVAL = 1800

# 下载文件转移高频轮询间隔（DownloadMonitor 实时检测）
PT_TRANSFER_INTERVAL = 30

# 下载文件转移低频兜底时间间隔（pttransfer，处理事件丢失）
PT_TRANSFER_INTERVAL_FALLBACK = 1800

# TMDB信息缓存定时保存时间
METAINFO_SAVE_INTERVAL = 600

# SYNC目录同步聚合转移时间
SYNC_TRANSFER_INTERVAL = 60

# RSS队列中处理时间间隔
RSS_CHECK_INTERVAL = 300

# 刷新订阅TMDB数据的时间间隔（小时）
RSS_REFRESH_TMDB_INTERVAL = 6

# 刷流删除的检查时间间隔
BRUSH_REMOVE_TORRENTS_INTERVAL = 300

# 刷流免费过期的检查时间间隔
BRUSH_STOP_TORRENTS_INTERVAL = 300

# 定时清除未识别的缓存时间间隔（小时）
META_DELETE_UNKNOWN_INTERVAL = 12

# fanart的api
FANART_MOVIE_API_URL = "https://webservice.fanart.tv/v3/movies/%s?api_key=d2d31f9ecabea050fc7d68aa3146015f"
FANART_TV_API_URL = "https://webservice.fanart.tv/v3/tv/%s?api_key=d2d31f9ecabea050fc7d68aa3146015f"

# 默认背景图地址
DEFAULT_TMDB_IMAGE = "https://s3.bmp.ovh/imgs/2022/07/10/77ef9500c851935b.webp"

# TMDB域名地址
TMDB_API_DOMAINS = ["api.themoviedb.org", "api.tmdb.org"]
TMDB_IMAGE_DOMAIN = "image.tmdb.org"

# TMDB图片尺寸配置
TMDB_IMAGE_SIZE = {
    "thumb": "w92",
    "small": "w185",
    "medium": "w342",
    "large": "w500",
    "xlarge": "w780",
    "original": "original",
}

# 添加下载时增加的标签
PT_TAG = "NEXUS_MEDIA"

# 电影默认命名格式
DEFAULT_MOVIE_FORMAT = "{title} ({year})/{title} ({year})-{part} - {videoFormat}"

# 电视剧默认命名格式
DEFAULT_TV_FORMAT = "{title} ({year})/Season {season}/{title} - {season_episode}-{part} - 第 {episode} 集"

# 辅助识别参数
KEYWORD_SEARCH_WEIGHT_1 = [10, 3, 2, 0.5, 0.5]
KEYWORD_SEARCH_WEIGHT_2 = [10, 2, 1]
KEYWORD_SEARCH_WEIGHT_3 = [10, 2]
KEYWORD_STR_SIMILARITY_THRESHOLD = 0.2
KEYWORD_DIFF_SCORE_THRESHOLD = 30
KEYWORD_BLACKLIST = [
    "中字",
    "韩语",
    "双字",
    "中英",
    "日语",
    "双语",
    "国粤",
    "HD",
    "BD",
    "中日",
    "粤语",
    "完全版",
    "法语",
    "西班牙语",
    "HRHDTVAC3264",
    "未删减版",
    "未删减",
    "国语",
    "字幕组",
    "人人影视",
    "www66ystv",
    "人人影视制作",
    "英语",
    "www6vhaotv",
    "无删减版",
    "完成版",
    "德意",
]

# M-Team base url

# sites.dat github
SITES_DATA_URL = "https://api.github.com/repos/linyuan0213/nexus-media-sites/releases/latest"

# EpisodeMapper 阈值配置
EPISODE_MAPPER_SEASON_GAP_DAYS = 90
EPISODE_MAPPER_SEASON_GAP_FORCE_DAYS = 180
EPISODE_MAPPER_MIN_BLOCK_LENGTH = 20
EPISODE_MAPPER_MIN_TOTAL_EPISODES = 30
