"""S3 存储后端（替换 MinIO 命令）。"""

from collections.abc import Iterator
from typing import BinaryIO

import boto3

from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class S3StorageBackend(StorageBackend):
    """
    S3 存储后端。

    使用 boto3 操作 S3/MinIO 兼容服务。
    """

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)
        self._bucket = getattr(config, "bucket", "data")
        self._client = boto3.client(
            "s3",
            endpoint_url=getattr(config, "endpoint", None) or None,
            aws_access_key_id=getattr(config, "access_key", "") or None,
            aws_secret_access_key=getattr(config, "secret_key", "") or None,
            region_name=getattr(config, "region", "us-east-1") or None,
            use_ssl=getattr(config, "secure", True),
        )

    def _key(self, path: str) -> str:
        return path.lstrip("/")

    def exists(self, path: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(path))
            return True
        except Exception:
            return False

    def stat(self, path: str) -> FileInfo | None:
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=self._key(path))
            return FileInfo(
                path=path,
                size=resp.get("ContentLength", 0),
                mtime=resp.get("LastModified", 0).timestamp() if resp.get("LastModified") else 0,
                is_dir=False,
            )
        except Exception:
            return None

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        prefix = self._key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix, Delimiter="/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix:
                    continue
                yield FileInfo(
                    path="/" + key,
                    size=obj.get("Size", 0),
                    mtime=obj.get("LastModified", 0).timestamp() if obj.get("LastModified") else 0,
                    is_dir=False,
                )
            for cp in page.get("CommonPrefixes", []):
                key = cp["Prefix"]
                if key == prefix:
                    continue
                yield FileInfo(
                    path="/" + key.rstrip("/"),
                    size=0,
                    mtime=0,
                    is_dir=True,
                )

    def read_stream(self, path: str) -> BinaryIO:
        resp = self._client.get_object(Bucket=self._bucket, Key=self._key(path))
        return resp["Body"]

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        # boto3 upload_fileobj 内部自动分块；chunk_size 未设置时交给 boto3 默认处理
        self._client.upload_fileobj(stream, self._bucket, self._key(path))

    def mkdir(self, path: str, parents: bool = True) -> None:
        pass

    def remove(self, path: str, recursive: bool = False) -> None:
        key = self._key(path)
        if recursive:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=key):
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if objects:
                    self._client.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": objects},
                    )
        else:
            self._client.delete_object(Bucket=self._bucket, Key=key)

    def copy(self, src: str, dst: str) -> None:
        src_key = self._key(src)
        dst_key = self._key(dst)
        self._client.copy_object(
            Bucket=self._bucket,
            Key=dst_key,
            CopySource={"Bucket": self._bucket, "Key": src_key},
        )

    def move(self, src: str, dst: str) -> None:
        self.copy(src, dst)
        self.remove(src)

    def health_check(self) -> tuple[bool, str]:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True, "连接成功"
        except Exception as e:
            # 凭据有效但 bucket 不存在（404）时自动创建，其余按连接失败处理
            resp = getattr(e, "response", None)
            status_code = resp.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(resp, dict) else None
            if status_code == 404:
                try:
                    self._client.create_bucket(Bucket=self._bucket)
                    return True, "连接成功（bucket 不存在，已自动创建）"
                except Exception as ce:  # noqa: BLE001
                    return False, f"bucket 不存在且创建失败: {ce}"
            return False, str(e)
