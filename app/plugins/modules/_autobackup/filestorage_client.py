from webdav4.client import Client, ResourceAlreadyExists, ResourceNotFound
from smb.SMBConnection import SMBConnection
from abc import ABC, abstractmethod
import shutil
import os

# 抽象基类定义
class FileStorageClient(ABC):
    @abstractmethod
    def list_files(self, path):
        pass

    @abstractmethod
    def download_file(self, remote_path, local_path):
        pass

    @abstractmethod
    def upload_file(self, local_path, remote_path):
        pass
    
    @abstractmethod
    def delete_file(self, path):
        pass

# WebDAV 客户端实现
class WebDAVClient(FileStorageClient):
    def __init__(self, base_url, username, password, share_name):
        base_url = f'{base_url.rstrip("/")}/{share_name.rstrip("/")}' # 去掉末尾的斜杠
        auth = (username, password)
        self.client = Client(base_url, auth)

    def list_files(self, path="/"):
        files = self.client.ls(path)
        return [file.get("name") for file in files if file.get("type") != "directory"]

    def download_file(self, remote_path, local_path):
        try:
            self.client.download_file(remote_path, local_path)
        except ResourceNotFound:
            os.remove(local_path)

    def upload_file(self, local_path, remote_path):
        try:
            self.client.upload_file(local_path, remote_path)
        except ResourceAlreadyExists:
            pass
        
    def delete_file(self, path):
        try:
            self.client.remove(path)
        except ResourceNotFound:
            pass

# Samba 客户端实现
class SambaClient(FileStorageClient):
    def __init__(self, base_url, username, password, client_name, server_name, share_name):
        # base_url 格式：smb://<server_ip>:<port>
        if not base_url.startswith("smb://"):
            raise ValueError("Samba base_url must start with 'smb://'")
        
        url_parts = base_url.replace("smb://", "").split(":")
        self.server_ip = url_parts[0]
        self.port = int(url_parts[1]) if len(url_parts) > 1 else 139  # 默认端口为 139

        self.conn = SMBConnection(
            username, password, client_name, server_name, use_ntlm_v2=True
        )
        self.conn.connect(self.server_ip, self.port)
        self.share_name = share_name

    def list_files(self, path="/"):
        files = self.conn.listPath(self.share_name, path)
        return [file.filename for file in files if not file.isDirectory]

    def download_file(self, remote_path, local_path):
        try:
            with open(local_path, "wb") as f:
                self.conn.retrieveFile(self.share_name, remote_path, f)
        except Exception:
            os.remove(local_path)

    def upload_file(self, local_path, remote_path):
        with open(local_path, "rb") as f:
            self.conn.storeFile(self.share_name, remote_path, f)
            
    def delete_file(self, path):
        self.conn.deleteFiles(self.share_name, path)


# 本地客户端实现
class LocalClient(FileStorageClient):
    def __init__(self, share_name="."):
        self.root_directory = share_name

    def list_files(self, path=""):
        path = "" if path == "/" else path
        full_path = os.path.join(self.root_directory, path)
        return [file for file in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, file))]

    def download_file(self, remote_path, local_path):
        full_remote_path = os.path.join(self.root_directory, remote_path)
        shutil.copy(full_remote_path, local_path)

    def upload_file(self, local_path, remote_path):
        full_remote_path = os.path.join(self.root_directory, remote_path)
        shutil.copy(local_path, full_remote_path)

    def delete_file(self, path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

# 工厂类
class FileClientFactory:
    @staticmethod
    def create_client(client_type, **kwargs):
        client_type = client_type.lower()
        if client_type == "webdav":
            return WebDAVClient(
                base_url=kwargs.get("base_url"),
                username=kwargs.get("username"),
                password=kwargs.get("password"),
                share_name=kwargs.get("share_name")
            )
        elif client_type == "samba":
            return SambaClient(
                base_url=kwargs.get("base_url"),
                username=kwargs.get("username"),
                password=kwargs.get("password"),
                client_name="NT",
                server_name="",
                share_name=kwargs.get("share_name")
            )