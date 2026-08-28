from abc import ABCMeta, abstractmethod

from app.message.registry import register
from app.message.schema import MessageConfigSchema


class _IMessageClient(metaclass=ABCMeta):
    schema: str | None = None
    config_schema: MessageConfigSchema | None = None

    def __init_subclass__(cls, **kwargs):
        """子类定义时自动注册到消息客户端注册表（避免启动竞态窗口构建出空客户端）"""
        super().__init_subclass__(**kwargs)
        if cls.schema:
            register(cls)

    def __init__(self, config: dict, apikey_service=None, message=None):
        self._config = config
        self._message = message
        self.read_config()

    def read_config(self):
        """Override to read message client configuration."""
        return

    def setup(self):
        """Override to initialize message client resources."""
        return

    def stop(self):
        """Override to clean up message client resources."""
        return

    def get_webhook_allow_ip(self) -> dict:
        """从客户端 CONFIG 读取 webhook IP 白名单，默认全放行。"""
        return {
            "ipv4": str(self._config.get("webhook_ipv4") or "0.0.0.0/0"),
            "ipv6": str(self._config.get("webhook_ipv6") or "::/0"),
        }

    @classmethod
    def match(cls, ctype):
        return ctype == cls.schema if cls.schema else False

    @abstractmethod
    def send_msg(self, title, text="", image="", url="", user_id="") -> tuple[bool, str]:
        pass

    @abstractmethod
    def send_list_msg(self, medias: list, user_id="", title="", **kwargs) -> tuple[bool, str]:
        pass
