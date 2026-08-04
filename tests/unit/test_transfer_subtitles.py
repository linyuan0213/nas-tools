"""TransferEngine.transfer_subtitles 单元测试"""

import os

import pytest

from app.services.transfer_engine import TransferEngine


@pytest.fixture
def engine():
    return TransferEngine()


def _make_files(tmp_path, names: dict[str, bytes]):
    for name, content in names.items():
        (tmp_path / name).write_bytes(content)


class TestTransferSubtitles:
    """字幕转移：已存在/大小不一致/单条失败场景"""

    def test_skip_when_same_size_exists(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"subtitle-content"})
        new_name = str(tmp_path / "out" / "Show.S01E01.mkv")
        os.makedirs(tmp_path / "out")
        # 目标已存在同名同大小字幕
        (tmp_path / "out" / "Show.S01E01.chi.zh-cn.srt").write_bytes(b"subtitle-content")

        engine.transfer_subtitles(str(tmp_path / video), new_name, "link")
        # 原字幕未被转移（仍在源目录），无异常
        assert (tmp_path / sub).exists()
        assert not (tmp_path / "out" / "Show.S01E01.chi.zh-cn.1.srt").exists()

    def test_next_tag_when_size_differs(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"subtitle-content"})
        new_name = str(tmp_path / "out" / "Show.S01E01.mkv")
        os.makedirs(tmp_path / "out")
        # 目标已存在同名但大小不同的字幕 → 应使用 .1 序号而不是报错
        (tmp_path / "out" / "Show.S01E01.chi.zh-cn.srt").write_bytes(b"different")

        engine.transfer_subtitles(str(tmp_path / video), new_name, "link")
        assert (tmp_path / "out" / "Show.S01E01.chi.zh-cn.srt").read_bytes() == b"different"
        assert (tmp_path / "out" / "Show.S01E01.chi.zh-cn.1.srt").read_bytes() == b"subtitle-content"

    def test_link_to_existing_path_does_not_raise(self, engine, tmp_path):
        """所有序号都被占用/冲突时，单条字幕失败不应抛出异常中断转移"""
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"new-subtitle"})
        new_name = str(tmp_path / "out" / "Show.S01E01.mkv")
        os.makedirs(tmp_path / "out")
        # 占满默认标签 + 5 个序号（内容均不同）
        for tag in [".chi.zh-cn"] + [f".chi.zh-cn.{i}" for i in range(1, 6)]:
            (tmp_path / "out" / f"Show.S01E01{tag}.srt").write_bytes(f"old-{tag}".encode())

        engine.transfer_subtitles(str(tmp_path / video), new_name, "link")
        # 无异常，已有文件未被覆盖
        assert (tmp_path / "out" / "Show.S01E01.chi.zh-cn.srt").read_bytes() == b"old-.chi.zh-cn"

    def test_copy_operation(self, engine, tmp_path):
        video = "Show.S01E02.1080p.mkv"
        sub = "Show.S01E02.1080p.srt"
        _make_files(tmp_path, {video: b"v", sub: b"plain-sub"})
        new_name = str(tmp_path / "out" / "Show.S01E02.mkv")

        engine.transfer_subtitles(str(tmp_path / video), new_name, "copy")
        assert (tmp_path / "out" / "Show.S01E02.und.srt").read_bytes() == b"plain-sub"

    def test_no_subtitles_noop(self, engine, tmp_path):
        _make_files(tmp_path, {"Show.S01E01.1080p.mkv": b"v"})
        engine.transfer_subtitles(
            str(tmp_path / "Show.S01E01.1080p.mkv"), str(tmp_path / "out" / "Show.S01E01.mkv"), "link"
        )


class _FakeRemoteBackend:
    """模拟远程存储后端：内存文件系统"""

    def __init__(self):
        from app.storage.backends.base import FileInfo

        self._files: dict[str, bytes] = {}
        self._fileinfo = FileInfo

    def stat(self, path):
        if path not in self._files:
            return None
        return self._fileinfo(path=path, size=len(self._files[path]), mtime=0.0, is_dir=False)

    def exists(self, path):
        return path in self._files

    def remove(self, path, recursive=False):
        self._files.pop(path, None)

    def read_stream(self, path):
        raise NotImplementedError

    def write_stream(self, path, stream, size=0, chunk_size=0):
        self._files[path] = stream.read()


class TestTransferSubtitlesRemote:
    """字幕/音轨转移走存储后端（远程目标）"""

    def test_subtitle_to_remote_backend(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"remote-sub"})
        backend = _FakeRemoteBackend()
        new_name = "/remote/lib/Show.S01E01.mkv"

        engine.transfer_subtitles(str(tmp_path / video), new_name, "link", dst_backend=backend)
        # 远程后端不支持 link → 降级 copy，字幕写入后端
        assert backend._files["/remote/lib/Show.S01E01.chi.zh-cn.srt"] == b"remote-sub"

    def test_subtitle_remote_existing_same_size_skipped(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"remote-sub"})
        backend = _FakeRemoteBackend()
        backend._files["/remote/lib/Show.S01E01.chi.zh-cn.srt"] = b"remote-sub"

        engine.transfer_subtitles(str(tmp_path / video), "/remote/lib/Show.S01E01.mkv", "copy", dst_backend=backend)
        assert "/remote/lib/Show.S01E01.chi.zh-cn.1.srt" not in backend._files

    def test_subtitle_remote_size_differs_uses_next_tag(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        sub = "Show.S01E01.1080p.chi.srt"
        _make_files(tmp_path, {video: b"v", sub: b"remote-sub"})
        backend = _FakeRemoteBackend()
        backend._files["/remote/lib/Show.S01E01.chi.zh-cn.srt"] = b"old"

        engine.transfer_subtitles(str(tmp_path / video), "/remote/lib/Show.S01E01.mkv", "copy", dst_backend=backend)
        assert backend._files["/remote/lib/Show.S01E01.chi.zh-cn.srt"] == b"old"
        assert backend._files["/remote/lib/Show.S01E01.chi.zh-cn.1.srt"] == b"remote-sub"

    def test_audio_track_to_remote_backend(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        track = "Show.S01E01.1080p.mka"
        _make_files(tmp_path, {video: b"v", track: b"audio-track"})
        backend = _FakeRemoteBackend()

        engine.transfer_audio_tracks(
            str(tmp_path / video), "/remote/lib/Show.S01E01.mkv", "copy", False, dst_backend=backend
        )
        assert backend._files["/remote/lib/Show.S01E01.mka"] == b"audio-track"

    def test_audio_track_remote_existing_no_overwrite(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        track = "Show.S01E01.1080p.mka"
        _make_files(tmp_path, {video: b"v", track: b"audio-track"})
        backend = _FakeRemoteBackend()
        backend._files["/remote/lib/Show.S01E01.mka"] = b"old-track"

        engine.transfer_audio_tracks(
            str(tmp_path / video), "/remote/lib/Show.S01E01.mkv", "copy", False, dst_backend=backend
        )
        assert backend._files["/remote/lib/Show.S01E01.mka"] == b"old-track"

    def test_audio_track_remote_overwrite_with_flag(self, engine, tmp_path):
        video = "Show.S01E01.1080p.mkv"
        track = "Show.S01E01.1080p.mka"
        _make_files(tmp_path, {video: b"v", track: b"audio-track"})
        backend = _FakeRemoteBackend()
        backend._files["/remote/lib/Show.S01E01.mka"] = b"old-track"

        engine.transfer_audio_tracks(
            str(tmp_path / video), "/remote/lib/Show.S01E01.mkv", "copy", True, dst_backend=backend
        )
        assert backend._files["/remote/lib/Show.S01E01.mka"] == b"audio-track"
