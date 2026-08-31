import json
from threading import Lock

from jinja2 import BaseLoader, Environment

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils

lock = Lock()


class JsonTemplateEnvironment(Environment):
    """自定义 Jinja2 环境，自动应用 tojson 过滤器到所有变量"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 注册默认的 tojson 过滤器（如果 jinja2 内置版本支持）
        if "tojson" not in self.filters:
            self.filters["tojson"] = self._tojson

    @staticmethod
    def _tojson(value):
        """将值转为 JSON 字符串，确保中文正常显示"""
        return JsonUtils.dumps(value, ensure_ascii=False)


class Webhook(_IMessageClient):
    schema = "webhook"
    config_schema = MessageConfigSchema(
        name="Webhook",
        icon_url="/api/plugin-framework/plugins/msg_webhook/assets/webhook_icon.png",
        fields=[
            ConfigField(
                id="url",
                required=True,
                title="URL",
                type="text",
                placeholder="https://xxx.com/your_api/",
            ),
            ConfigField(
                id="method",
                required=True,
                title="HTTP方法",
                tooltip="GET方法中请求体将被忽略，由于查询参数不支持复杂格式，发送列表类消息请使用POST",
                type="select",
                options={"GET": "GET", "POST": "POST", "PUT": "PUT", "PATCH": "PATCH", "DELETE": "DELETE"},
                default="POST",
            ),
            ConfigField(
                id="token",
                required=False,
                title="Token",
                tooltip="会放在Header的Authorization中",
                type="text",
                placeholder="Authorization-Token",
            ),
            ConfigField(
                id="query_params",
                required=False,
                title="额外查询参数",
                tooltip="JSON字符串",
                type="text",
                placeholder='{"search": "keyword"}',
            ),
            ConfigField(
                id="json_tpl",
                required=False,
                title="单条消息模板",
                tooltip=(
                    "Jinja2 JSON模板，用于单条消息。可用变量：title, text, image, url, user_id。"
                    "字符串变量默认会进行 tojson 过滤以保证生成的JSON格式正确，"
                    "如需使用原始字符串请使用 |safe 过滤器"
                ),
                type="textarea",
                placeholder='{\n  "title": "{{ title }}",\n  "text": "{{ text }}"\n}',
            ),
            ConfigField(
                id="json_list_tpl",
                required=False,
                title="列表消息模板",
                tooltip=(
                    "Jinja2 JSON模板，用于列表消息。可用变量：title, user_id, medias。字符串变量默认会进行 tojson 过滤"
                ),
                type="textarea",
                placeholder=(
                    "{\n"
                    '  "title": "{{ title }}",\n'
                    '  "items": [\n'
                    "    {% for media in medias %}\n"
                    "    {\n"
                    '      "title": "{{ media.title }}"\n'
                    "    }{% if not loop.last %},{% endif %}\n"
                    "    {% endfor %}\n"
                    "  ]\n"
                    "}"
                ),
            ),
        ],
    )

    def __init__(self, config, apikey_service=None, message=None):
        self._domain = None
        self._url = None
        self._method = None
        self._query_params = None
        self._json_tpl = None
        self._json_list_tpl = None
        self._token = None
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        if self._config:
            self._url = self._config.get("url")
            self._method = self._config.get("method")
            self._query_params = self.__parse_json(self._config.get("query_params"), "query_params")
            self._json_tpl = self._config.get("json_tpl", "")
            self._json_list_tpl = self._config.get("json_list_tpl", "")
            self._token = self._config.get("token")

    @classmethod
    def __parse_json(cls, json_str, attr_name):
        json_str = json_str.strip()
        if not json_str:
            return None
        try:
            return JsonUtils.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"{attr_name} Json解析失败：{json_str}") from e

    @classmethod
    def __render_template(cls, template_str, variables):
        """
        使用 jinja2 模板引擎渲染模板字符串
        支持的变量:
          - 单条消息: title, text, image, url, user_id
          - 列表消息: title, user_id, medias (数组，每项包含: title, url, type, vote)
        使用自定义 Jinja2 环境，自动应用 tojson 过滤器
        """
        if not template_str:
            return None
        try:
            # 使用自定义环境，自动应用 tojson 过滤器
            env = JsonTemplateEnvironment(loader=BaseLoader())
            template = env.from_string(template_str)
            return template.render(**variables)
        except Exception as e:
            raise ValueError(f"模板渲染失败：{str(e)}\n原始模板：{template_str}\n变量：{variables}") from e

    def send_msg(self, title, text="", image="", url="", user_id=""):
        """
        发送web请求
        :param title: 消息标题
        :param text: 消息内容
        :param image: 消息图片地址
        :param url: 点击消息转转的URL
        :param user_id: 用户ID，如有则只发消息给该用户
        :user_id: 发送消息的目标用户ID，为空则发给管理员
        """
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._url:
            return False, "url参数未配置"
        if not self._method:
            return False, "method参数未配置"
        try:
            # 模板变量
            variables = {"title": title, "text": text, "image": image, "url": url, "user_id": user_id}

            query_params = self._query_params.copy() if self._query_params else {}

            # 渲染JSON模板
            if self._json_tpl:
                # 使用模板：直接发送渲染后的 JSON 字符串
                rendered_tpl = self.__render_template(self._json_tpl, variables)
                if not rendered_tpl:
                    return False, "模板渲染失败"
                return self.__send_request(query_params, rendered_tpl)
            else:
                # 不使用模板：直接序列化 variables
                return self.__send_request(query_params, JsonUtils.dumps(variables, ensure_ascii=False))

        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        """
        发送列表类消息
        """
        if not title:
            return False, "title为空"
        if not medias or not isinstance(medias, list):
            return False, "medias错误"
        if not self._url:
            return False, "url参数未配置"
        if not self._method:
            return False, "method参数未配置"
        if self._method == "GET":
            return False, "GET不支持发送发送列表类消息"
        try:
            medias_data = [
                {
                    "title": media.get_title_string(),
                    "url": media.get_detail_url(),
                    "type": media.get_type_string(),
                    "vote": media.get_vote_string(),
                }
                for media in medias
            ]

            query_params = self._query_params.copy() if self._query_params else {}

            # 模板变量
            variables = {"title": title, "user_id": user_id, "medias": medias_data}

            # 渲染JSON模板（使用列表消息模板）
            if self._json_list_tpl:
                # 使用模板：直接发送渲染后的 JSON 字符串
                rendered_tpl = self.__render_template(self._json_list_tpl, variables)
                if not rendered_tpl:
                    return False, "模板渲染失败"
                return self.__send_request(query_params, rendered_tpl)
            else:
                # 不使用模板：直接序列化 variables
                return self.__send_request(query_params, JsonUtils.dumps(variables, ensure_ascii=False))
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def __send_request(self, query_params, json_data=None):
        """
        发送消息请求
        :param query_params: 查询参数
        :param json_data: JSON 字符串（POST/PUT 等请求），None 表示 GET 请求
        """
        client = HttpClient(config=HttpClientConfig(timeout=30))
        method = self._method or "GET" if json_data is None else self._method or "POST"
        try:
            if json_data is None:
                response = client.request(method, self._url or "", params=query_params, headers=self.header)
            else:
                response = client.request(
                    method, self._url or "", params=query_params, data=json_data, headers=self.header
                )
            if 200 <= response.status_code <= 299:
                return True, ""
            return False, f"请求失败：{response.status_code}"
        except Exception as e:
            return False, f"请求异常：{str(e)}"

    @property
    def header(self):
        r = {"Content-Type": "application/json"}
        if self._token:
            r["Authorization"] = self._token
        return r
