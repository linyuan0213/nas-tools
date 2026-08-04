"""MediaFileService 文件操作单元测试."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ResourceNotFoundError, ServiceError, ValidationError
from app.services.media_file_service import MediaFileService


@pytest.fixture
def service():
    return MediaFileService(
        event_bus=MagicMock(),
        storage_backend_repo=MagicMock(),
        media_service=MagicMock(),
        thread_executor=MagicMock(),
        scraper=MagicMock(),
    )


class TestMakeDir:
    def test_create_ok(self, service, tmp_path):
        target = service.make_dir(str(tmp_path), "新目录")
        assert (tmp_path / "新目录").is_dir()
        assert target.endswith("新目录")

    def test_create_parents(self, service, tmp_path):
        service.make_dir(str(tmp_path / "a" / "b"), "c")
        assert (tmp_path / "a" / "b" / "c").is_dir()

    def test_already_exists(self, service, tmp_path):
        (tmp_path / "dup").mkdir()
        with pytest.raises(ValidationError):
            service.make_dir(str(tmp_path), "dup")

    @pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b"])
    def test_invalid_name(self, service, tmp_path, name):
        with pytest.raises(ValidationError):
            service.make_dir(str(tmp_path), name)


class TestMoveOrCopyFiles:
    def _setup(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.mkv").write_bytes(b"aaa")
        (src / "b.mkv").write_bytes(b"bbb")
        return src, dst

    def test_move_ok(self, service, tmp_path):
        src, dst = self._setup(tmp_path)
        files = [str(src / "a.mkv"), str(src / "b.mkv")]
        msg = service.move_or_copy_files(files, str(dst), move=True)
        assert msg == "移动成功"
        assert (dst / "a.mkv").exists() and (dst / "b.mkv").exists()
        assert not (src / "a.mkv").exists()

    def test_copy_ok(self, service, tmp_path):
        src, dst = self._setup(tmp_path)
        msg = service.move_or_copy_files([str(src / "a.mkv")], str(dst), move=False)
        assert msg == "复制成功"
        assert (dst / "a.mkv").exists() and (src / "a.mkv").exists()

    def test_empty_files(self, service, tmp_path):
        with pytest.raises(ValidationError):
            service.move_or_copy_files([], str(tmp_path))

    def test_empty_dest(self, service):
        with pytest.raises(ValidationError):
            service.move_or_copy_files(["/a"], "")

    def test_dest_not_exists(self, service, tmp_path):
        with pytest.raises(ResourceNotFoundError):
            service.move_or_copy_files(["/a"], str(tmp_path / "nope"))

    def test_dest_is_file(self, service, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        with pytest.raises(ResourceNotFoundError):
            service.move_or_copy_files(["/a"], str(f))

    def test_partial_failure(self, service, tmp_path):
        src, dst = self._setup(tmp_path)
        files = [str(src / "a.mkv"), str(src / "ghost.mkv")]
        with pytest.raises(ServiceError):
            service.move_or_copy_files(files, str(dst), move=False)
        assert (dst / "a.mkv").exists()


class TestOpenDownload:
    def test_ok(self, service, tmp_path):
        f = tmp_path / "a.mkv"
        f.write_bytes(b"data")
        stream, info = service.open_download(str(f))
        try:
            assert stream.read() == b"data"
            assert not info.is_dir
        finally:
            stream.close()

    def test_not_exists(self, service, tmp_path):
        with pytest.raises(ResourceNotFoundError):
            service.open_download(str(tmp_path / "nope.mkv"))

    def test_is_dir(self, service, tmp_path):
        with pytest.raises(ResourceNotFoundError):
            service.open_download(str(tmp_path))

    def test_empty_path(self, service):
        with pytest.raises(ValidationError):
            service.open_download("")


class TestSaveUpload:
    def test_ok(self, service, tmp_path):
        target = service.save_upload(str(tmp_path), "up.txt", BytesIO(b"hello"))
        assert (tmp_path / "up.txt").read_bytes() == b"hello"
        assert target.endswith("up.txt")

    def test_invalid_name(self, service, tmp_path):
        with pytest.raises(ValidationError):
            service.save_upload(str(tmp_path), "../evil.txt", BytesIO(b"x"))

    def test_dest_not_exists(self, service, tmp_path):
        with pytest.raises(ResourceNotFoundError):
            service.save_upload(str(tmp_path / "nope"), "up.txt", BytesIO(b"x"))


class TestResolveBackend:
    def test_local(self, service):
        backend = service._resolve_backend("local")
        assert backend.config.type.name == "LOCAL"

    def test_empty_is_local(self, service):
        backend = service._resolve_backend("")
        assert backend.config.type.name == "LOCAL"

    def test_remote_not_found(self, service):
        service._storage_backend_repo.get_by_id.return_value = None
        with pytest.raises(ResourceNotFoundError):
            service._resolve_backend("99")
