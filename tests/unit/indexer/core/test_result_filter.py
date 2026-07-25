"""match_filter 缓存对象独立性回归测试"""

from app.media.models import MediaInfo


class TestCachedMediaInfoIsolation:
    """同组候选共享缓存对象：读取方必须深拷贝，否则
    1) `media_info not in ret_array` 判重塌缩（每组只剩一条）
    2) 后处理候选的 torrent_info 覆盖先前候选（张冠李戴）
    """

    def test_model_copy_isolates_torrent_info(self):
        cached = MediaInfo(cn_name="穹庐下的魔女", tmdb_id=288971, tmdb_info={"id": 288971})

        first = cached.model_copy(deep=True)
        first.set_torrent_info(site="SiteA", enclosure="magnet:a")
        second = cached.model_copy(deep=True)
        second.set_torrent_info(site="SiteB", enclosure="magnet:b")

        # 缓存对象不被污染
        assert cached.site is None or cached.site == ""
        # 两个候选互不影响
        assert first.enclosure == "magnet:a"
        assert second.enclosure == "magnet:b"
        # 判重按内容：org_string 不同的两条都应能入列
        first.org_string = "title A"
        second.org_string = "title B"
        ret_array = [first]
        assert second not in ret_array
