"""
消息通知默认模板
"""

DEFAULT_MESSAGE_TEMPLATES = {
    "download_start": {
        "title": "🎬 {{ title_ep_string|default(item.get_title_ep_string()) }} 开始下载 ⬇️",
        "text": (
            "🌐 站点：{{ site|default(item.site)|default('未知') }} ｜ "
            "💾 大小：{{ size_str|default(item.size|filesize) }}\n"
            "📦 质量：{{ resource_type|default(item.get_resource_type_string())|default('未知') }}\n\n"
            "🧲 种子：{{ org_string|default(item.org_string)|truncatestr(50) }}\n"
            "🌱 做种：{{ seeders|default(item.seeders)|default(0) }} ｜ "
            "⚡️ 促销：{{ volume_factor|default(item.get_volume_factor_string())|default('未知') }} ｜ "
            "🚨 H&R：{{ hit_and_run|default(item.hit_and_run)|yesno('是','否') }}"
        ),
    },
    "transfer_finished": {
        "title": (
            "✅ {% if total_episodes and total_episodes > 1 %}"
            "{{ media_info.get_title_string() }} {{ media_info.get_season_string() }} "
            "共{{ total_episodes }}集"
            "{% else %}{{ media_info.get_title_string() }} "
            "{{ media_info.get_season_episode_string() }}{% endif %} 已入库"
        ),
        "text": (
            "{% if media_info.vote_average %}⭐ {{ media_info.get_vote_string() }}\n"
            "{% endif %}📺 类型：{{ media_info.type.value }}\n"
            "{% if media_info.category and category_flag %}📁 类别：{{ media_info.category }}\n"
            "{% endif %}{% if media_info.get_resource_type_string() %}"
            "📦 质量：{{ media_info.get_resource_type_string() }}\n"
            "{% endif %}💾 大小：{{ media_info.size|filesize }}\n"
            "📥 来自：{{ in_from }}\n"
            "{% if exist_filenum != 0 %}⚠️ {{ exist_filenum }}个文件已存在{% endif %}"
        ),
    },
    "download_fail": {
        "title": "❌ 下载失败：{{ item.get_title_string() }}",
        "text": "🌐 站点：{{ item.site }}\n🧲 种子：{{ item.org_string|truncatestr(50) }}\n❗ 错误：{{ error_msg }}",
    },
    "rss_added": {
        "title": (
            "📌 {% if media_info.type.value == '电影' %}{{ media_info.get_title_string() }}"
            "{% else %}{{ media_info.get_title_string() }} {{ media_info.get_season_string() }}"
            "{% endif %} 已添加订阅"
        ),
        "text": (
            "{% if media_info.vote_average %}⭐ {{ media_info.get_vote_string() }}\n"
            "{% endif %}📺 类型：{{ media_info.type.value }}\n"
            "📥 来自：{{ in_from }}\n"
            "{% if media_info.user_name %}👤 用户：{{ media_info.user_name }}{% endif %}"
        ),
    },
    "rss_finished": {
        "title": (
            "🎉 {{ media_info.get_title_string() }} {{ media_info.get_season_string() }} "
            "{% if media_info.over_edition %}已完成洗版{% else %}已完成订阅{% endif %}"
        ),
        "text": (
            "{% if media_info.vote_average %}⭐ {{ media_info.get_vote_string() }}\n"
            "{% endif %}📺 类型：{{ media_info.type.value }}"
        ),
    },
    "site_signin": {"title": "📊 站点签到", "text": "{{ msgs|join('\\n') }}"},
    "site_message": {"title": "📬 {{ title }}", "text": "{{ text }}"},
    "transfer_fail": {"title": "❌ 入库失败：{{ count }} 个文件", "text": "📁 源路径：{{ path }}\n❗ 原因：{{ text }}"},
    "auto_remove_torrents": {"title": "🗑️ 自动删种：{{ title }}", "text": "{{ text }}"},
    "brushtask_added": {"title": "🌊 刷流下种：{{ title }}", "text": "{{ text }}"},
    "brushtask_remove": {"title": "🗑️ 刷流删种：{{ title }}", "text": "{{ text }}"},
    "brushtask_pause": {"title": "⏸️ 刷流暂停：{{ title }}", "text": "{{ text }}"},
    "mediaserver_message": {"title": "🎬 {{ message_title }}", "text": "{{ message_content }}"},
    "custom_message": {"title": "🔌 {{ title }}", "text": "{{ text }}"},
    "ptrefresh_date_message": {"title": "📊 站点数据统计", "text": "{{ msgs|join('\\n') }}"},
}
