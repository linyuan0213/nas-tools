import hashlib
import json
import time

from app.utils import RequestUtils
from app.utils.commons import SingletonMeta


class IyuuHelper(metaclass=SingletonMeta):
    _version = "2.0.0"
    _api_base = "http://dev.iyuu.cn%s"
    _sites = {}
    _token = None

    def __init__(self, token):
        self._token = token
        if self._token:
            self.init_config()

    def init_config(self):
        pass

    def __request_iyuu(self, url, method="get", params=None):
        """
        向IYUUApi发送请求
        """
        headers = {'token': self._token}
        # 开始请求
        if method == "get":
            ret = RequestUtils(
                accept_type="application/json",
                headers=headers
            ).get_res(f"{url}", params=params)
        else:
            ret = RequestUtils(
                accept_type="application/json",
                headers=headers
            ).post_res(f"{url}", data=params)
        if ret:
            result = ret.json()
            if result.get('code') == 0:
                return result.get('data'), ""
            else:
                return None, f"请求IYUU失败，状态码：{result.get('code')}，返回信息：{result.get('msg')}"
        elif ret is not None:
            return None, f"请求IYUU失败，状态码：{ret.status_code}，错误原因：{ret.reason}"
        else:
            return None, f"请求IYUU失败，未获取到返回信息"

    def get_torrent_url(self, sid):
        if not sid:
            return None, None
        if not self._sites:
            self._sites = self.__get_sites()
        if not self._sites.get(sid):
            return None, None
        site = self._sites.get(sid)
        return site.get('base_url'), site.get('download_page')

    def __get_sites(self):
        """
        返回支持辅种的全部站点
        :return: 站点列表、错误信息
        {
            "ret": 200,
            "data": {
                "sites": [
                    {
                        "id": 1,
                        "site": "keepfrds",
                        "nickname": "朋友",
                        "base_url": "pt.keepfrds.com",
                        "download_page": "download.php?id={}&passkey={passkey}",
                        "reseed_check": "passkey",
                        "is_https": 2
                    },
                ]
            }
        }
        """
        result, msg = self.__request_iyuu(url=self._api_base % '/reseed/sites/index')
        if result:
            ret_sites = {}
            sites = result.get('sites') or []
            for site in sites:
                ret_sites[site.get('id')] = site
            return ret_sites
        else:
            print(msg)
            return {}

    def get_seed_info(self, info_hashs: list):
        """
        返回info_hash对应的站点id、种子id
        {
            "code": 0,
            "data": {
                "7866fdafbcc5ad504c7750f2d4626dc03954c50a": {
                    "torrent": [
                        {
                            "sid": 32,
                            "torrent_id": 19537,
                            "info_hash": "93665ee3f41f1845c6628b105b2d236cc08b9826"
                        },
                        {
                            "sid": 14,
                            "torrent_id": 413945,
                            "info_hash": "9e2e41fba99d135db84585419703906ec710e241"
                        }
                    ]
                }
            },
            "msg": "ok"
        }
        """
        sites = self.__get_sites()
        site_ids = list(sites.keys())
        result, msg = self.__request_iyuu(url=self._api_base % '/reseed/sites/reportExisting',
                                    method="post",
                                    params=json.dumps({"sid_list": site_ids}))
        if not result:
            return result, msg
        sid_sha1 = result.get('sid_sha1')
        
        info_hashs.sort()
        json_data = json.dumps(info_hashs, separators=(',', ':'), ensure_ascii=False)
        sha1 = self.get_sha1(json_data)
        result, msg = self.__request_iyuu(url=self._api_base % '/reseed/index/index',
                                          method="post",
                                          params={
                                              "timestamp": int(time.time()),
                                              "hash": json_data,
                                              "sid_sha1": sid_sha1,
                                              "sha1": sha1,
                                              "version": "8.2.0"
                                          })
        return result, msg

    @staticmethod
    def get_sha1(json_str) -> str:
        return hashlib.sha1(json_str.encode('utf-8')).hexdigest()

    def get_auth_sites(self):
        """
        返回支持鉴权的站点列表
        [
            {
                "id": 2,
                "site": "pthome",
                "bind_check": "passkey,uid"
            }
        ]
        """
        result, msg = self.__request_iyuu(url=self._api_base % '/reseed/sites/recommend')
        if result:
            return result.get('list') or []
        else:
            print(msg)
            return []

    def bind_site(self, site, passkey, uid):
        """
        绑定站点
        :param site: 站点名称
        :param passkey: passkey
        :param uid: 用户id
        :return: 状态码、错误信息
        """
        sites = self.get_auth_sites()
        sid = ''
        for site_info in sites:
            if site_info.get('site') == site:
                sid = site_info.get('id')
                break
        if not sid:
            return None, "获取站点id失败"
        result, msg = self.__request_iyuu(url=self._api_base % '/reseed/users/bind',
                                          method="post",
                                          params={
                                              "token": self._token,
                                              "site": site,
                                              "passkey": self.get_sha1(passkey),
                                              "id": uid,
                                              "sid": sid
                                          })
        return result, msg
