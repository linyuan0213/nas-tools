"""存储后端配置数据类。"""

from dataclasses import dataclass

from app.storage.backends.base import StorageConfig, StorageType


@dataclass
class LocalStorageConfig(StorageConfig):
    type: StorageType = StorageType.LOCAL

    @classmethod
    def get_fields(cls) -> list[dict]:
        return []


@dataclass
class WebDAVStorageConfig(StorageConfig):
    type: StorageType = StorageType.WEBDAV
    url: str = ""
    username: str = ""
    password: str = ""
    ssl_verify: bool = True
    connect_timeout: int = 10
    read_timeout: int = 30
    chunk_size: int = 8 * 1024 * 1024

    @classmethod
    def get_fields(cls) -> list[dict]:
        return [
            {"key": "url", "label": "URL", "placeholder": "https://dav.example.com", "required": True},
            {"key": "username", "label": "用户名", "placeholder": "admin"},
            {"key": "password", "label": "密码", "placeholder": "******"},
            {"key": "ssl_verify", "label": "SSL 验证", "placeholder": "true"},
            {"key": "connect_timeout", "label": "连接超时", "placeholder": "10"},
            {"key": "read_timeout", "label": "读取超时", "placeholder": "30"},
        ]


@dataclass
class SMBStorageConfig(StorageConfig):
    type: StorageType = StorageType.SMB
    server: str = ""
    share: str = ""
    port: int = 445
    username: str = ""
    password: str = ""
    domain: str = ""
    mount_point: str = ""

    @classmethod
    def get_fields(cls) -> list[dict]:
        return [
            {"key": "server", "label": "服务器", "placeholder": "192.168.1.100", "required": True},
            {"key": "share", "label": "共享名", "placeholder": "nas-share", "required": True},
            {"key": "port", "label": "端口", "placeholder": "445"},
            {"key": "username", "label": "用户名", "placeholder": "admin"},
            {"key": "password", "label": "密码", "placeholder": "******"},
            {"key": "domain", "label": "域", "placeholder": "WORKGROUP"},
            {"key": "mount_point", "label": "挂载点", "placeholder": "/mnt/smb"},
        ]


@dataclass
class S3StorageConfig(StorageConfig):
    type: StorageType = StorageType.S3
    endpoint: str = ""
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    region: str = ""
    secure: bool = True

    @classmethod
    def get_fields(cls) -> list[dict]:
        return [
            {"key": "endpoint", "label": "Endpoint", "placeholder": "s3.amazonaws.com", "required": True},
            {"key": "bucket", "label": "Bucket", "placeholder": "my-bucket", "required": True},
            {"key": "region", "label": "Region", "placeholder": "us-east-1"},
            {"key": "access_key", "label": "Access Key", "placeholder": "AKIAXXXXXX", "required": True},
            {"key": "secret_key", "label": "Secret Key", "placeholder": "******", "required": True},
            {"key": "secure", "label": "HTTPS", "type": "bool", "placeholder": "是否使用 HTTPS"},
        ]


@dataclass
class RcloneStorageConfig(StorageConfig):
    type: StorageType = StorageType.RCLONE
    remote_name: str = ""
    rc_url: str = ""

    @classmethod
    def get_fields(cls) -> list[dict]:
        return [
            {"key": "remote_name", "label": "Remote 名称", "placeholder": "例如：gdrive", "required": True},
            {"key": "rc_url", "label": "RC URL", "placeholder": "http://127.0.0.1:5572", "required": True},
        ]


@dataclass
class OpenListStorageConfig(StorageConfig):
    type: StorageType = StorageType.OPENLIST
    base_url: str = ""
    username: str = ""
    password: str = ""
    api_token: str = ""
    write_enabled: bool = False

    @classmethod
    def get_fields(cls) -> list[dict]:
        return [
            {"key": "base_url", "label": "Base URL", "placeholder": "https://alist.example.com", "required": True},
            {"key": "username", "label": "用户名", "placeholder": "admin"},
            {"key": "password", "label": "密码", "placeholder": "******"},
            {"key": "api_token", "label": "API Token", "placeholder": "直接填 token 可跳过登录"},
            {"key": "write_enabled", "label": "允许写入", "type": "bool", "placeholder": "是否允许向该后端写入文件"},
        ]
