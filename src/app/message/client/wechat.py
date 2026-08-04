import base64
import hashlib
import struct
from datetime import datetime
from threading import Lock

import defusedxml.ElementTree as ET
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import log
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.message.client._base import _IMessageClient
from app.message.commands import WECHAT_MENU, WECHAT_PLUGIN_GROUP
from app.message.schema import ConfigField, MessageConfigSchema
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils

_menu_lock = Lock()


class WeChat(_IMessageClient):
    schema = "wechat"
    config_schema = MessageConfigSchema(
        name="微信",
        icon_url="/static/img/message/wechat.png",
        search_type="WX",
        max_length=2048,
        fields=[
            ConfigField(
                id="corpid",
                required=True,
                title="企业ID",
                tooltip='每个企业都拥有唯一的corpid，获取此信息可在管理后台"我的企业"－"企业信息"下查看"企业ID"（需要有管理员权限）',
                type="text",
            ),
            ConfigField(
                id="corpsecret",
                required=True,
                title="应用Secret",
                tooltip='每个应用都拥有唯一的secret，获取此信息可在管理后台"应用与小程序"－"自建"下查看"Secret"（需要有管理员权限）',
                type="text",
                placeholder="Secret",
            ),
            ConfigField(
                id="agentid",
                required=True,
                title="应用ID",
                tooltip='每个应用都拥有唯一的agentid，获取此信息可在管理后台"应用与小程序"－"自建"下查看"AgentId"（需要有管理员权限）',
                type="text",
                placeholder="AgentId",
            ),
            ConfigField(
                id="default_proxy",
                required=False,
                title="消息推送代理",
                tooltip="由于微信官方限制，2022年6月20日后创建的企业微信应用需要有固定的公网IP地址并加入IP白名单后才能发送消息，使用有固定公网IP的代理服务器转发可解决该问题；代理服务器需自行搭建，搭建方法可参考项目主页说明",
                type="text",
                placeholder="https://wechat.nexus-media.cn",
            ),
            ConfigField(
                id="token",
                required=False,
                title="Token",
                tooltip="需要交互功能时才需要填写，在微信企业应用管理后台-接收消息设置页面生成，填入完成后重启本应用，然后再在微信页面输入地址确定",
                type="text",
                placeholder="API接收消息Token",
            ),
            ConfigField(
                id="encodingAESKey",
                required=False,
                title="EncodingAESKey",
                tooltip="需要交互功能时才需要填写，在微信企业应用管理后台-接收消息设置页面生成，填入完成后重启本应用，然后再在微信页面输入地址确定",
                type="text",
                placeholder="API接收消息EncodingAESKey",
            ),
            ConfigField(
                id="adminUser",
                required=False,
                title="AdminUser",
                tooltip=(
                    "需要交互功能时才需要填写，可执行交互菜单命令的用户名，"
                    "为空则不限制，多个;号分割。可在企业微信后台查看成员的Account ID"
                ),
                type="text",
                placeholder="可执行交互菜单的用户名",
            ),
        ],
    )

    _send_msg_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=%s"
    _token_url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=%s&corpsecret=%s"
    _menu_url = "https://qyapi.weixin.qq.com/cgi-bin/menu/create?access_token=%s&agentid=%s"
    _proxy_url = ""
    _menu_done = set()

    def __init__(self, config, apikey_service=None, message=None):
        self.corpid = None
        self.corpsecret = None
        self.agent_id = None
        self.token = None
        self.encoding_aes_key = None
        self.interactive = False
        self._use_proxy = False
        self._access_token = None
        self._expires_in = None
        self._token_time = None
        self._message = message
        super().__init__(config, apikey_service, message=message)

    def _normalize_proxy_url(self, base: str) -> str:
        """统一代理地址格式，缺少 scheme 时默认补 https://。"""
        base = base.strip()
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        return base.rstrip("/")

    def read_config(self):
        cfg = self._config or {}
        self.corpid = cfg.get("corpid")
        self.corpsecret = cfg.get("corpsecret")
        self.agent_id = cfg.get("agentid")
        self.token = cfg.get("token")
        self.encoding_aes_key = cfg.get("encodingAESKey")
        self.interactive = cfg.get("interactive", False)
        self._use_proxy = cfg.get("default_proxy", False)
        if self._use_proxy:
            base = self._use_proxy if isinstance(self._use_proxy, str) else self._proxy_url
            base = self._normalize_proxy_url(base)
            self._send_msg_url = f"{base}/cgi-bin/message/send?access_token=%s"
            self._token_url = f"{base}/cgi-bin/gettoken?corpid=%s&corpsecret=%s"
            self._menu_url = f"{base}/cgi-bin/menu/create?access_token=%s&agentid=%s"

    def _verify_signature(self, signature: str, timestamp: str, nonce: str, *extras: str) -> bool:
        """验证企业微信签名（sha1(token, timestamp, nonce, *extras)）。"""
        if not self.token:
            return False
        parts = [self.token, timestamp, nonce, *extras]
        parts.sort()
        expected = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
        return expected == signature

    def _decrypt_aes(self, encrypted: str) -> bytes:
        """使用 EncodingAESKey 解密企业微信 AES 消息。"""
        if not self.encoding_aes_key:
            return b""
        try:
            key = base64.b64decode(self.encoding_aes_key + "=")
            if len(key) != 32:
                return b""
            iv = key[:16]
            ciphertext = base64.b64decode(encrypted)
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            unpadder = padding.PKCS7(128).unpadder()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            try:
                plaintext = unpadder.update(padded) + unpadder.finalize()
            except ValueError:
                # 兼容第三方代理重加密的非 PKCS7 填充（如空格填充）：
                # 消息结构自带长度前缀（随机16字节 + 4字节长度 + 消息 + corpid），可直接按长度提取
                plaintext = padded
            msg_len = struct.unpack(">I", plaintext[16:20])[0]
            msg = plaintext[20 : 20 + msg_len]
            if not self.corpid:
                return b""
            # 按 corpid 固定长度精确截取，兼容任意非 PKCS7 填充字节（空格/ESC 等）
            appid = plaintext[20 + msg_len : 20 + msg_len + len(self.corpid)].decode("utf-8", errors="ignore")
            if appid != self.corpid:
                return b""
            return msg
        except Exception:
            return b""

    def verify_url(self, signature: str, timestamp: str, nonce: str, echostr: str) -> bytes | None:
        """验证企业微信回调 URL，成功返回解密后的 echostr 字节，失败返回 None。"""
        if not self._verify_signature(signature, timestamp, nonce, echostr):
            return None
        if self.encoding_aes_key:
            return self._decrypt_aes(echostr)
        return echostr.encode("utf-8")

    def _verify_message_signature(self, signature: str, timestamp: str, nonce: str, encrypt: str | None = None) -> bool:
        """验证企业微信消息签名（加密模式包含 Encrypt 字段）。"""
        if not self.token:
            return False
        parts = [self.token, timestamp, nonce]
        if encrypt:
            parts.append(encrypt)
        parts.sort()
        expected = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
        return expected == signature

    def parse_message(self, xml_text: str, signature: str = "", timestamp: str = "", nonce: str = "") -> dict | None:
        """解析并验证企业微信消息 XML，支持加密/明文模式。"""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        encrypt = root.findtext("Encrypt")
        if encrypt and self.encoding_aes_key:
            if signature and not self._verify_message_signature(signature, timestamp, nonce, encrypt):
                return None
            decrypted = self._decrypt_aes(encrypt)
            if not decrypted:
                return None
            try:
                root = ET.fromstring(decrypted)
            except ET.ParseError:
                return None
        elif signature and not self._verify_message_signature(signature, timestamp, nonce):
            return None

        return {
            "FromUserName": root.findtext("FromUserName", ""),
            "ToUserName": root.findtext("ToUserName", ""),
            "Content": root.findtext("Content", ""),
            "MsgType": root.findtext("MsgType", ""),
            "MsgId": root.findtext("MsgId", ""),
            "AgentID": root.findtext("AgentID", ""),
            "Event": root.findtext("Event", ""),
            "EventKey": root.findtext("EventKey", ""),
        }

    def setup(self):
        # 菜单不再在 setup() 中设置，避免后台线程延迟执行覆盖插件命令
        # 统一由 Message.refresh_menus() 在系统启动完成后刷新
        pass

    def stop(self):
        pass

    @classmethod
    def match(cls, ctype):
        return ctype == cls.schema

    def _get_access_token(self, force=False):
        need = False
        duration = (datetime.now() - self._token_time).seconds if self._token_time else 0

        if not self._access_token or duration >= (self._expires_in or 7200):
            need = True
        if not need and not force:
            return self._access_token
        if not self.corpid or not self.corpsecret:
            return None
        try:
            token_url = self._token_url % (self.corpid, self.corpsecret)
            res = HttpClient().get(token_url)
            data = res.json()
            if data.get("errcode") == 0:
                self._access_token = data.get("access_token")
                self._expires_in = data.get("expires_in")
                self._token_time = datetime.now()
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
        return self._access_token

    def send_msg(self, title, text="", image="", url="", user_id=None):
        if not title and not text:
            return False, "标题和内容不能同时为空"
        token = self._get_access_token()
        if not token:
            return False, "参数未配置或配置不正确"
        log.info(f"[WeChat]send_msg image={image}, url={url}")
        if image:
            return self._send_image(token, title, text, image, url, user_id)
        return self._send_text(token, title, text, url, user_id)

    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        token = self._get_access_token()
        if not token:
            return False, "参数未配置或配置不正确"
        if not isinstance(medias, list):
            return False, "数据错误"
        message_url = self._send_msg_url % token
        if not user_id:
            user_id = "@all"
        articles = []
        for i, media in enumerate(medias):
            vote = media.get_vote_string()
            item_title = f"{i + 1}. {media.get_title_string()}"
            if vote:
                item_title = f"{item_title}\n{media.get_type_string()}，{vote}"
            else:
                item_title = f"{item_title}\n{media.get_type_string()}"
            articles.append(
                {
                    "title": item_title,
                    "description": "",
                    "picurl": media.get_message_image() if i == 0 else media.get_poster_image(),
                    "url": media.get_detail_url(),
                }
            )
        req = {"touser": user_id, "msgtype": "news", "agentid": self.agent_id, "news": {"articles": articles}}
        return self._post_request(message_url, req)

    def _send_text(self, token, title, text, url, user_id):
        message_url = self._send_msg_url % token
        content = f"{title}\n{text.replace(chr(10) + chr(10), chr(10))}" if text else title
        if url:
            content = f"{content}\n\n<a href='{url}'>查看详情</a>"
        if not user_id:
            user_id = "@all"
        req = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 0,
        }
        return self._post_request(message_url, req)

    def _send_image(self, token, title, text, image_url, url, user_id):
        message_url = self._send_msg_url % token
        if not user_id:
            user_id = "@all"
        req = {
            "touser": user_id,
            "msgtype": "news",
            "agentid": self.agent_id,
            "news": {
                "articles": [
                    {
                        "title": title,
                        "description": text.replace("\n\n", "\n") if text else "",
                        "picurl": image_url,
                        "url": url,
                    }
                ]
            },
        }
        return self._post_request(message_url, req)

    def _create_menu(self):
        if not self.agent_id:
            return
        with _menu_lock:
            if str(self.agent_id) in WeChat._menu_done:
                return
            token = self._get_access_token()
            if not token:
                log.error("[WeChat]无法获取access_token，菜单创建跳过")
                return
            try:
                message = self._message
                commands = message.get_commands() if message else {}
                plugin_cmds = message.get_plugin_commands() if message else {}
                # 先填内置命令
                group_subs = {}
                for group in WECHAT_MENU:
                    subs = []
                    for cmd in group["commands"]:
                        name = commands.get(cmd, cmd)
                        if not name:
                            continue
                        subs.append({"type": "click", "name": name, "key": cmd.lstrip("/")})
                    group_subs[group["name"]] = subs
                # 插件命令按 管理 → 同步 → 下载 顺序填入各组空位（每组上限 5 个）
                group_priority = [WECHAT_PLUGIN_GROUP] + [
                    g["name"] for g in reversed(WECHAT_MENU) if g["name"] != WECHAT_PLUGIN_GROUP
                ]
                plugin_items = [
                    {"type": "click", "name": info.get("desc", cmd), "key": cmd.lstrip("/")}
                    for cmd, info in plugin_cmds.items()
                ]
                for group_name in group_priority:
                    subs = group_subs.get(group_name, [])
                    while plugin_items and len(subs) < 5:
                        subs.append(plugin_items.pop(0))
                buttons = []
                for group in WECHAT_MENU:
                    subs = group_subs.get(group["name"], [])
                    if subs:
                        buttons.append({"name": group["name"], "sub_button": subs})
                if not buttons:
                    return
                log.info(f"[WeChat]正在创建菜单：{JsonUtils.dumps(buttons, ensure_ascii=False)}")
                data = JsonUtils.dumps({"button": buttons}, ensure_ascii=False).encode("utf-8")
                headers = {"content-type": "application/json"}
                menu_url = self._menu_url % (token, self.agent_id)
                log.info(f"[WeChat]菜单请求URL: {menu_url}")
                res = HttpClient(config=HttpClientConfig(default_headers=headers)).post(menu_url, data=data)
                body = res.json()
                if body.get("errcode") == 0:
                    WeChat._menu_done.add(str(self.agent_id))
                    log.info("[WeChat]应用菜单创建成功")
                else:
                    log.error(
                        "[WeChat]菜单创建失败 errcode={} errmsg={}".format(body.get("errcode"), body.get("errmsg"))
                    )
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                log.error(f"[WeChat]菜单创建异常：{e}")

    def refresh_menu(self):
        """刷新命令菜单（插件命令变更时调用）"""
        WeChat._menu_done.discard(str(self.agent_id))
        self._create_menu()

    def _post_request(self, url, req_json):
        headers = {"content-type": "application/json"}
        try:
            data = JsonUtils.dumps(req_json, ensure_ascii=False).encode("utf-8")
            log.debug("[WeChat]POST {}".format(url.split("?")[0]) if "?" in url else url)
            res = HttpClient(config=HttpClientConfig(default_headers=headers)).post(url, data=data)
            body = res.json()
            if body.get("errcode") == 0:
                return True, body.get("errmsg")
            if body.get("errcode") == 42001:
                self._get_access_token(force=True)
            return False, body.get("errmsg")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False, str(err)
