"""浏览器工具 Schema — 基于基础设施 Chrome 能力（nexus-chrome 服务）"""

from app.agent.tools.base import BaseTool, ToolLevel


class BrowserFetchTool(BaseTool):
    name = "browser_fetch"
    description = (
        "使用无头浏览器访问网页并返回页面文本内容。"
        "当需要查看某个网页/站点的页面内容、或 API 拿不到的登录后页面信息时调用；"
        "可携带站点已登录 Cookie（传 site_key）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 URL"},
            "site_key": {"type": "string", "description": "可选：站点标识（使用该站点已登录 Cookie）；匿名访问留空"},
            "timeout": {"type": "integer", "description": "可选：页面加载超时秒数", "default": 30},
        },
        "required": ["url"],
    }
    level = ToolLevel.READ


class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = (
        "使用无头浏览器访问网页并截图（PNG），返回图片 URL 供展示。"
        "当用户要求查看某个页面/站点的外观、布局、界面时调用；可携带站点 Cookie。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 URL"},
            "site_key": {"type": "string", "description": "可选：站点标识（使用该站点已登录 Cookie）"},
            "full_page": {"type": "boolean", "description": "可选：整页截图（默认视口）", "default": False},
        },
        "required": ["url"],
    }
    level = ToolLevel.READ
