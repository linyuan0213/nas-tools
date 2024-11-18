from cachetools import cached, TTLCache

from app.utils import RequestUtils


class PluginHelper:

    @staticmethod
    def install(plugin_id):
        """
        插件安装统计计数
        """
        return None

    @staticmethod
    def report(plugins):
        """
        批量上报插件安装统计数据
        """
        return None

    @staticmethod
    @cached(cache=TTLCache(maxsize=1, ttl=3600))
    def statistic():
        """
        获取插件安装统计数据
        """
        return {}
