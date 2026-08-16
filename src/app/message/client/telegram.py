import contextlib
import html
import time
from threading import Lock
from urllib.parse import urlencode

import log
from app.core.settings import settings
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.thread import ThreadExecutor
from app.message.client._base import _IMessageClient
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils
from app.utils.config_tools import get_domain, get_proxies

_webhook_lock = Lock()
_webhook_set = False


class Telegram(_IMessageClient):
    schema = "telegram"
    config_schema = MessageConfigSchema(
        name="Telegram",
        icon_url="/static/img/message/telegram.png",
        search_type="TG",
        fields=[
            ConfigField(
                id="token",
                required=True,
                title="Bot Token",
                tooltip="telegram机器人的Token，关注BotFather创建机器人",
                type="text",
            ),
            ConfigField(
                id="chat_id",
                required=True,
                title="Chat ID",
                tooltip="接受消息通知的用户、群组或频道Chat ID，关注@getidsbot获取",
                type="text",
            ),
            ConfigField(
                id="user_ids",
                required=False,
                title="User IDs",
                tooltip="允许使用交互的用户Chat ID，留空则只允许管理用户使用，关注@getidsbot获取",
                type="text",
                placeholder="使用,分隔多个Id",
            ),
            ConfigField(
                id="admin_ids",
                required=False,
                title="Admin IDs",
                tooltip="允许使用管理命令的用户Chat ID，关注@getidsbot获取",
                type="text",
                placeholder="使用,分隔多个Id",
            ),
            ConfigField(
                id="webhook",
                required=False,
                title="Webhook",
                tooltip=(
                    "Telegram机器人消息有两种模式：Webhook或消息轮循；开启后将使用Webhook方式，"
                    "需要在基础设置中正确配置好外网访问地址，同时受Telegram官方限制，"
                    "外网访问地址需要设置为以下端口之一：443, 80, 88, 8443，"
                    "且需要有公网认证的可信SSL证书；关闭后将使用消息轮循方式，"
                    "使用该方式需要在基础设置->安全处将Telegram ipv4源地址设置为127.0.0.1，"
                    "如同时使用了内置的SSL证书功能，消息轮循方式可能无法正常使用"
                ),
                type="switch",
            ),
            ConfigField(
                id="webhook_ipv4",
                required=False,
                title="Webhook IPv4 白名单",
                tooltip="允许的 IPv4 地址段（CIDR），逗号分隔，默认 0.0.0.0/0 放行所有",
                type="text",
                placeholder="0.0.0.0/0",
                advanced=True,
            ),
            ConfigField(
                id="webhook_ipv6",
                required=False,
                title="Webhook IPv6 白名单",
                tooltip="允许的 IPv6 地址段（CIDR），逗号分隔，默认 ::/0 放行所有",
                type="text",
                placeholder="::/0",
                advanced=True,
            ),
            ConfigField(
                id="secret_token",
                required=False,
                title="Webhook Secret Token",
                tooltip="Telegram 官方 Webhook 安全令牌，留空使用 API Key 校验",
                type="text",
                placeholder="随机字符串",
                advanced=True,
            ),
        ],
    )
    _setup_done = set()

    def __init__(self, config, apikey_service, message=None):
        self.token = None
        self.chat_id = None
        self.webhook = False
        self.interactive = False
        self.secret_token = None
        self._webhook_url = None
        self._admin_ids = []
        self._user_ids = []
        self._domain = None
        self._api_key = None
        self._enabled = True
        self._proxy_event = None
        self._apikey_service = apikey_service
        self._message = message
        super().__init__(config, apikey_service, message=message)

    def read_config(self):
        cfg = self._config or {}
        self.token = cfg.get("token")
        self.chat_id = cfg.get("chat_id")
        self.webhook = cfg.get("webhook", False)
        self.interactive = cfg.get("interactive", False)
        self.secret_token = cfg.get("secret_token")
        self._admin_ids = cfg.get("admin_ids") or []
        self._user_ids = cfg.get("user_ids") or []
        self._domain = get_domain()
        self._api_key = self._apikey_service.get_or_create_system_key("MessageWebhook")
        self._webhook_url = f"{self._domain}/telegram?apikey={self._api_key}"
        admin_ids = cfg.get("admin_ids")
        if admin_ids and not isinstance(admin_ids, list):
            self._admin_ids = [admin_ids]
        user_ids = cfg.get("user_ids")
        if user_ids and not isinstance(user_ids, list):
            self._user_ids = [user_ids]

    def _get_proxies(self):
        if self._proxy_event is not None:
            return self._proxy_event.wait(3)
        return get_proxies()

    def setup(self):
        if self.schema in Telegram._setup_done:
            return
        Telegram._setup_done.add(self.schema)
        if self.webhook:
            self._set_webhook()
        else:
            self._start_polling()
        # 菜单不再在 setup() 中设置，避免后台线程延迟执行覆盖插件命令
        # 统一由 Message.refresh_menus() 在系统启动完成后刷新

    def send_msg(self, title, text="", image="", url="", user_id=""):
        if not self.token or not self.chat_id or not self._enabled:
            return False, "参数未配置"
        if not title and not text:
            return False, "标题和内容不能同时为空"
        # 用 HTML parse_mode 而非 Markdown：内容可能含文件名/番号中的 `_ [ ] ( ) ~ #` 等
        # 未转义字符，Markdown 模式会触发 Telegram 400 "can't parse entities"
        caption_parts = []
        if title:
            caption_parts.append(f"<b>{html.escape(title)}</b>")
        if text:
            caption_parts.append(html.escape(text))
        caption = "\n".join(caption_parts)
        if not caption:
            return False, "消息内容为空"
        proxies = self._get_proxies()
        chat_ids = []
        if user_id and self.interactive:
            chat_ids = [user_id]
        else:
            chat_ids = self._user_ids + [self.chat_id]
        # 去重：避免同一 chat_id 在 user_ids 和 chat_id 中重复配置导致重复发送
        seen = set()
        unique_chat_ids = []
        for cid in chat_ids:
            if cid and cid not in seen:
                seen.add(cid)
                unique_chat_ids.append(cid)
        proxy_url = proxies.get("http") if proxies else None
        for chat_id in unique_chat_ids:
            try:
                req = HttpClient(config=HttpClientConfig(proxy_url=proxy_url))
                if image:
                    url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
                    res = req.post(
                        url,
                        data={"chat_id": chat_id, "photo": image, "caption": caption, "parse_mode": "HTML"},
                    )
                else:
                    url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                    res = req.post(
                        url,
                        data={"chat_id": chat_id, "text": caption, "parse_mode": "HTML"},
                    )
                ok, msg = self._parse_response(res)
                if not ok:
                    return ok, msg
            except Exception as e:
                return False, str(e)
        return True, ""

    def _parse_response(self, res):
        try:
            data = res.json()
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "未知错误")
        except Exception:
            return False, "响应解析失败"

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        if not self.token or not self.chat_id:
            return False, "参数未配置"
        if not title or not isinstance(medias, list):
            return False, "数据错误"
        image = ""
        caption = f"*{title}*"
        for i, m in enumerate(medias):
            if not image:
                image = m.get_message_image()
            vote = m.get_vote_string()
            if vote:
                caption += f"\n{i + 1}. [{m.get_title_string()}]({m.get_detail_url()})\n{m.get_type_string()}，{vote}"
            else:
                caption += f"\n{i + 1}. [{m.get_title_string()}]({m.get_detail_url()})\n{m.get_type_string()}"
        chat_id = user_id or self.chat_id
        return self.send_msg(title="", text=caption, image=image, user_id=chat_id)

    def _start_polling(self):
        if not self.token or not self._enabled:
            return
        ThreadExecutor(name="telegram_poll").submit(self._polling_loop)

    def _polling_loop(self):
        offset = 0
        while self._enabled:
            try:
                proxies = self._get_proxies()
                proxy_url = proxies.get("http") if proxies else None
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={offset}&limit=10"
                try:
                    res = HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=30)).get(url)
                    data = res.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update.get("update_id", offset) + 1
                            self._process_update(update)
                except Exception as e:
                    err_msg = str(e)
                    if "409" in err_msg:
                        log.debug(f"[Telegram]轮询跳过（多实例冲突）: {err_msg}")
                    else:
                        log.error(f"[Telegram]轮询异常: {err_msg}")
                time.sleep(2)
            except Exception as e:
                log.error(f"[Telegram]轮询异常: {e}")
                time.sleep(5)

    def _process_update(self, update):
        msg = update.get("message") or update.get("edited_message", {})
        text = msg.get("text", "")
        if not text:
            return
        user = msg.get("from", {})
        user_id = str(user.get("id", ""))
        if self._admin_ids and user_id not in self._admin_ids:
            return
        ds_url = f"http://127.0.0.1:{settings.get('app').get('web_port')}/telegram?apikey={self._api_key}"
        with contextlib.suppress(Exception):
            HttpClient(config=HttpClientConfig(timeout=5)).post(ds_url, data=update)

    def _set_commands(self):
        if not self.token:
            log.warn("[Telegram]跳过设置菜单：token 为空")
            return
        try:
            commands = self._message.get_commands() if self._message else {}
            cmds = [{"command": k[1:], "description": v} for k, v in commands.items()]
            log.info(f"[Telegram]正在设置菜单，共 {len(cmds)} 个命令: {list(commands.keys())}")
            data = {"commands": cmds, "scope": {"type": "default"}}
            headers = {"content-type": "application/json"}
            proxies = get_proxies()
            proxy_url = proxies.get("http") if proxies else None
            res = HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=10)).post(
                f"https://api.telegram.org/bot{self.token}/setMyCommands",
                data=data,
                headers=headers,
            )
            if res and res.json().get("ok"):
                log.info(f"[Telegram]命令菜单已设置，共 {len(cmds)} 个")
            else:
                log.error("[Telegram]命令菜单设置失败：%s" % (res.json().get("description") if res else "网络错误"))
        except Exception as e:
            ExceptionUtils.exception_traceback(e)

    def refresh_menu(self):
        """刷新命令菜单（插件命令变更时调用）"""
        log.info("[Telegram]收到菜单刷新请求")
        self._set_commands()

    def _set_webhook(self):
        if not self._webhook_url:
            return
        with _webhook_lock:
            global _webhook_set
            if _webhook_set:
                return
            status = self._get_webhook_status()
            if not status or status == 1:
                _webhook_set = True
                return
            if status == 2:
                self._del_webhook()
            values = {"url": self._webhook_url, "allowed_updates": ["message"]}
            if self.secret_token:
                values["secret_token"] = self.secret_token
            url = f"https://api.telegram.org/bot{self.token}/setWebhook?" + urlencode(values)
            try:
                proxies = get_proxies()
                proxy_url = proxies.get("http") if proxies else None
                res = HttpClient(config=HttpClientConfig(proxy_url=proxy_url)).get(url)
                if res.json().get("ok"):
                    _webhook_set = True
                    log.info(f"[Telegram]Webhook 设置成功：{self._webhook_url}")
            except Exception as e:  # noqa: BLE001
                log.debug(f"[telegram]忽略异常: {e}")

    def _get_webhook_status(self):
        url = f"https://api.telegram.org/bot{self.token}/getWebhookInfo"
        try:
            proxies = get_proxies()
            proxy_url = proxies.get("http") if proxies else None
            res = HttpClient(config=HttpClientConfig(proxy_url=proxy_url)).get(url)
            data = res.json()
            if data.get("ok"):
                info = data.get("result", {})
                if info.get("url") == self._webhook_url:
                    return 1
                elif info.get("url"):
                    return 2
                return 0
        except Exception as e:  # noqa: BLE001
            log.debug(f"[telegram]忽略异常: {e}")
        return 0

    def _del_webhook(self):
        url = f"https://api.telegram.org/bot{self.token}/deleteWebhook"
        try:
            proxies = get_proxies()
            proxy_url = proxies.get("http") if proxies else None
            HttpClient(config=HttpClientConfig(proxy_url=proxy_url)).get(url)
            log.info("[Telegram]Webhook 已删除")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[telegram]忽略异常: {e}")
