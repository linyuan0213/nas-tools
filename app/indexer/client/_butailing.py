import time

from app.indexer.client._butailing_spider import ButailingSpider


class Butailing(object):
    indexer = None

    def __init__(self, indexer):
        if indexer:
            self.indexer = indexer

    def search(self, keyword=None, mtype=None, timeout=30):
        """
        根据关键字搜索单个站点
        :param: indexer: 站点配置
        :param: keyword: 关键字
        :param: mtype: 媒体类型
        :param: timeout: 超时时间
        :return: 是否发生错误, 种子列表
        """
        spider = ButailingSpider(thread_count=10)
        spider.setparam(indexer=self.indexer,
                        keyword=keyword,
                        mtype=mtype)
        spider.start()
        # 循环判断是否获取到数据
        sleep_count = 0
        while not spider.is_complete:
            sleep_count += 1
            time.sleep(1)
            if sleep_count > timeout:
                break
        # 是否发生错误
        result_flag = spider.is_error
        # 种子列表
        result_array = spider.torrents_info_array.copy()
        # 重置状态
        spider.torrents_info_array.clear()

        return result_flag, result_array
