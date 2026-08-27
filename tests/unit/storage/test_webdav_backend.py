"""WebDAV 存储后端单元测试（href 路径转换与目录列表解析）. """

from types import SimpleNamespace

from app.storage.backends.webdav import WebDAVStorageBackend
from app.storage.config_models import WebDAVStorageConfig

PROPFIND_XML = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/remote.php/dav/files/user/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/remote.php/dav/files/user/%E4%B8%AD%E6%96%87%E7%9B%AE%E5%BD%95/</D:href>
    <D:propstat><D:prop>
      <D:getcontentlength>0</D:getcontentlength>
      <D:getlastmodified>Wed, 26 Aug 2026 08:00:00 GMT</D:getlastmodified>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/remote.php/dav/files/user/hello.txt</D:href>
    <D:propstat><D:prop>
      <D:getcontentlength>1024</D:getcontentlength>
      <D:getlastmodified>Wed, 26 Aug 2026 08:00:00 GMT</D:getlastmodified>
      <D:resourcetype/>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/remote.php/dav/files/user/My%20File%20with%20spaces.txt</D:href>
    <D:propstat><D:prop>
      <D:getcontentlength>2</D:getcontentlength>
      <D:getlastmodified>Wed, 26 Aug 2026 08:00:00 GMT</D:getlastmodified>
      <D:resourcetype/>
    </D:prop></D:propstat>
  </D:response>
</D:multistatus>
"""


def _backend():
    return WebDAVStorageBackend(
        WebDAVStorageConfig(
            id="t1",
            name="test",
            url="https://dav.example.com/remote.php/dav/files/user",
            ssl_verify=True,
            username="u",
            password="p",
        )
    )


class TestWebDAVBackend:
    def test_href_to_path_strips_base_and_decodes(self):
        b = _backend()
        assert b._href_to_path("/remote.php/dav/files/user/hello.txt") == "hello.txt"
        assert b._href_to_path("/remote.php/dav/files/user/%E4%B8%AD%E6%96%87/") == "中文"
        assert b._href_to_path("https://dav.example.com/remote.php/dav/files/user/foo.txt") == "foo.txt"

    def test_url_for_encodes_path_segments(self):
        b = _backend()
        assert b._url_for("hello.txt") == "https://dav.example.com/remote.php/dav/files/user/hello.txt"
        assert b._url_for("Folder With Spaces") == (
            "https://dav.example.com/remote.php/dav/files/user/Folder%20With%20Spaces"
        )
        assert b._url_for("测试目录/中文文件.txt") == (
            "https://dav.example.com/remote.php/dav/files/user/"
            "%E6%B5%8B%E8%AF%95%E7%9B%AE%E5%BD%95/%E4%B8%AD%E6%96%87%E6%96%87%E4%BB%B6.txt"
        )

    def test_list_dir_decodes_names_and_paths(self):
        b = _backend()
        resp = SimpleNamespace(content=PROPFIND_XML.encode("utf-8"))
        b._req = lambda method, path, **kw: resp  # type: ignore[method-assign]
        items = list(b.list_dir(""))
        names = [i.path for i in items]
        # 根目录自身被排除，中文/空格目录 URL 解码为可读名
        assert names == ["中文目录", "hello.txt", "My File with spaces.txt"]
        assert items[0].is_dir is True
        assert items[1].is_dir is False
        assert items[1].size == 1024
        assert items[1].mtime > 0
        assert items[2].size == 2

    def test_list_dir_excludes_self(self):
        b = _backend()
        resp = SimpleNamespace(
            content=b"""<?xml version="1.0"?>
            <D:multistatus xmlns:D="DAV:">
              <D:response><D:href>/remote.php/dav/files/user/sub/</D:href></D:response>
              <D:response><D:href>/remote.php/dav/files/user/sub/a.txt</D:href>
                <D:propstat><D:prop><D:getcontentlength>5</D:getcontentlength>
                <D:resourcetype/></D:prop></D:propstat></D:response>
            </D:multistatus>"""
        )
        b._req = lambda method, path, **kw: resp  # type: ignore[method-assign]
        items = list(b.list_dir("sub"))
        assert [i.path for i in items] == ["sub/a.txt"]
