"""TemplateEngine - Jinja2 模板渲染与客户端配置解析."""

import json
import re
import time

from jinja2 import BaseLoader, Environment

import log
from app.message.templates import DEFAULT_MESSAGE_TEMPLATES
from app.utils import ExceptionUtils, StringUtils
from app.utils.json_utils import JsonUtils


def _filesize_filter(value):
    """Jinja2 filter: 格式化文件大小."""
    if value is None:
        return ""
    return StringUtils.str_filesize(value) if value else ""


def _datetime_filter(value, format_str="%Y-%m-%d %H:%M:%S"):
    """Jinja2 filter: 格式化日期时间."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        return time.strftime(format_str, time.localtime(value))
    if isinstance(value, str):
        try:
            timestamp = float(value)
            return time.strftime(format_str, time.localtime(timestamp))
        except (ValueError, TypeError):
            return value
    return str(value)


def _default_filter(value, default_value="", boolean=False):
    """Jinja2 filter: 默认值处理."""
    if value is None or value == "" or (boolean and not value):
        return default_value
    return value


def _yesno_filter(value, yes="是", no="否"):
    """Jinja2 filter: 布尔值转换为是/否."""
    if value is True:
        return yes
    elif value is False:
        return no
    return no


def _truncatestr_filter(value, length=100, suffix="..."):
    """Jinja2 filter: 截断字符串."""
    if not value:
        return ""
    value = str(value)
    if len(value) <= length:
        return value
    return value[: length - len(suffix)] + suffix


def _striptags_filter(value):
    """Jinja2 filter: 去除 HTML 标签."""
    if not value:
        return ""
    return re.sub(r"<[^>]+", "", str(value))


class TemplateEngine:
    """负责 Jinja2 模板渲染和客户端模板配置应用."""

    def render_template(self, template_str, variables):
        """使用 Jinja2 渲染模板."""
        if not template_str:
            return None
        try:
            env = Environment(loader=BaseLoader(), autoescape=True)
            env.filters["filesize"] = _filesize_filter
            env.filters["datetime"] = _datetime_filter
            env.filters["default"] = _default_filter
            env.filters["yesno"] = _yesno_filter
            env.filters["truncatestr"] = _truncatestr_filter
            env.filters["striptags"] = _striptags_filter
            template = env.from_string(template_str)
            result = template.render(**variables)
            result = result.replace("\\n", "\n")
            return result
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"[Message]模板渲染失败：{str(e)}")
            return None

    def apply_client_template(self, client, msg_type, variables):
        """应用客户端模板，返回 (rendered_title, rendered_text)."""
        client_name = client.get("name", "未知")
        templates = client.get("templates")

        if isinstance(templates, str):
            try:
                templates = JsonUtils.loads(templates)
            except json.JSONDecodeError as e:
                log.error(f"[Message]客户端 {client_name} 模板配置 JSON 解析失败: {e}")
                return None, None

        # 客户端无模板配置或对应类型模板：回退默认模板（非纯文本）
        template_config = None
        if isinstance(templates, dict):
            template_config = templates.get(msg_type)
            if not isinstance(template_config, dict):
                template_config = None
        if template_config is None:
            template_config = DEFAULT_MESSAGE_TEMPLATES.get(msg_type)
        if not template_config:
            log.debug(f"[Message]客户端 {client_name} 消息类型 {msg_type} 无可用模板")
            return None, None

        title_template = template_config.get("title")
        text_template = template_config.get("text")

        rendered_title = self.render_template(title_template, variables) if title_template else None
        rendered_text = self.render_template(text_template, variables) if text_template else None

        return rendered_title, rendered_text
