import re
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from datetime import time as dtime
from urllib.parse import urlsplit

import dateutil
import pytz
from apscheduler.triggers.cron import CronTrigger

from app.entities.torrent import Torrent
from app.entities.torrentstatus import TorrentStatus
from app.media.media import Media
from app.subscribe import Subscribe
from app.utils.commons import SingletonMeta
from config import Config
import log
from app.downloader import Downloader
from app.filter import Filter
from app.helper import DbHelper, RssHelper
from app.media.meta import MetaInfo
from app.message import Message
from app.sites import Sites, SiteConf
from app.utils import StringUtils, ExceptionUtils, JsonUtils
from app.utils.types import BrushDeleteType, BrushStopType, MediaType

from app.scheduler_service import SchedulerService
from app.queue import scheduler_queue
from app.utils import RedisStore


class BrushTask(metaclass=SingletonMeta):
    message = None
    sites = None
    siteconf = None
    filter = None
    dbhelper = None
    rsshelper = None
    downloader = None
    redis_store = None
    _scheduler = None
    _jobstore = "brushtask"
    _brush_tasks = {}
    _torrents_cache = []
    _qb_client = "qbittorrent"
    _tr_client = "transmission"

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()
        self.rsshelper = RssHelper()
        self.message = Message()
        self.sites = Sites()
        self.siteconf = SiteConf()
        self.filter = Filter()
        self.downloader = Downloader()
        self.redis_store = RedisStore()
        # 移除现有任务
        self.stop_service()
        # 读取刷流任务列表
        self.load_brushtasks()
        # 清理缓存
        self._torrents_cache = []
        # 启动RSS任务
        if self._brush_tasks:
            self._scheduler = SchedulerService()
            # running_task 计数
            running_task = 0
            for _, task in self._brush_tasks.items():
                # 任务状态：Y-正常，S-停止下载新种，N-完全停止
                if task.get("state") in ['Y', 'S'] \
                        and task.get("interval"):
                    cron = str(task.get("interval")).strip()
                    if cron.isdigit():
                        if task.get("state") == 'Y':
                            scheduler_queue.put({
                                                "func_str": "BrushTask.check_task_rss",
                                                "args": [task.get("id")],
                                                "job_id": f"BrushTask.check_task_rss_{task.get('id')}",
                                                "trigger": "interval",
                                                "seconds": int(cron) * 60,
                                                "jobstore": self._jobstore
                                                })
                            running_task = running_task + 1
                        # 启动停种任务
                        scheduler_queue.put({
                                "func_str": "BrushTask.stop_task_torrents",
                                "args": [task.get("id")],
                                "job_id": f"BrushTask.stop_task_torrents_{task.get('id')}",
                                "trigger": "interval",
                                "seconds": int(cron) * 60,
                                "jobstore": self._jobstore
                                })
                        # 启动删种任务
                        scheduler_queue.put({
                                "func_str": "BrushTask.remove_task_torrents",
                                "args": [task.get("id")],
                                "job_id": f"BrushTask.remove_task_torrents_{task.get('id')}",
                                "trigger": "interval",
                                "seconds": int(cron) * 60,
                                "jobstore": self._jobstore
                                })
                    elif cron.count(" ") == 4:
                        if task.get("state") == 'Y':
                            try:
                                scheduler_queue.put({
                                    "func_str": "BrushTask.check_task_rss",
                                                "args": [task.get("id")],
                                                "job_id": f"BrushTask.check_task_rss_{task.get('id')}",
                                                "trigger": CronTrigger.from_crontab(cron),
                                                "jobstore": self._jobstore
                                })
                                running_task = running_task + 1
                            except Exception as err:
                                log.error(
                                    f"任务 {task.get('name')} 运行周期格式不正确：{str(err)}")
                        try:
                            # 启动停种任务
                            scheduler_queue.put({
                                    "func_str": "BrushTask.stop_task_torrents",
                                    "args": [task.get("id")],
                                    "job_id": f"BrushTask.stop_task_torrents_{task.get('id')}",
                                    "trigger": CronTrigger.from_crontab(cron),
                                    "jobstore": self._jobstore
                                    })
                            # 启动删种任务
                            scheduler_queue.put({
                                    "func_str": "BrushTask.remove_task_torrents",
                                    "args": [task.get("id")],
                                    "job_id": f"BrushTask.remove_task_torrents_{task.get('id')}",
                                    "trigger": CronTrigger.from_crontab(cron),
                                    "jobstore": self._jobstore
                                    })
                        except Exception as err:
                            log.error(
                                f"任务 {task.get('name')} 运行周期格式不正确：{str(err)}")
                    else:
                        log.error(f"任务 {task.get('name')} 运行周期格式不正确")
            if running_task > 0:
                log.info(f"{running_task} 个刷流服务正常启动")

    def load_brushtasks(self):
        """
        从数据库加载刷流任务
        """
        self._brush_tasks = {}
        brushtasks = self.dbhelper.get_brushtasks()
        if not brushtasks:
            return
        # 加载任务到内存
        for task in brushtasks:
            site_info = self.sites.get_sites(siteid=task.SITE)
            if site_info:
                site_url = StringUtils.get_base_url(
                    site_info.get("signurl") or site_info.get("rssurl"))
            else:
                site_url = ""
            downloader_info = self.downloader.get_downloader_conf(
                task.DOWNLOADER)
            total_size = round(
                int(self.dbhelper.get_brushtask_totalsize(task.ID)) / (1024 ** 3), 1)
            self._brush_tasks[str(task.ID)] = {
                "id": task.ID,
                "name": task.NAME,
                "site": site_info.get("name"),
                "site_id": task.SITE,
                "interval": task.INTEVAL,
                "label": task.LABEL,
                "savepath": task.SAVEPATH,
                "state": task.STATE,
                "downloader": task.DOWNLOADER,
                "downloader_name": downloader_info.get("name") if downloader_info else None,
                "transfer": True if task.TRANSFER == "Y" else False,
                "sendmessage": True if task.SENDMESSAGE == "Y" else False,
                "free": task.FREELEECH,
                "rss_rule": eval(task.RSS_RULE),
                "remove_rule": eval(task.REMOVE_RULE),
                "stop_rule": eval(task.STOP_RULE if task.STOP_RULE else "{'stopfree': 'Y'}"),
                "seed_size": task.SEED_SIZE,
                "time_range": task.TIME_RANGE,
                "total_size": total_size,
                "rss_url": task.RSSURL if task.RSSURL else site_info.get("rssurl"),
                "rss_url_show": task.RSSURL,
                "cookie": site_info.get("cookie"),
                "ua": site_info.get("ua"),
                "headers": site_info.get("headers"),
                "download_count": task.DOWNLOAD_COUNT,
                "remove_count": task.REMOVE_COUNT,
                "download_size": StringUtils.str_filesize(task.DOWNLOAD_SIZE),
                "upload_size": StringUtils.str_filesize(task.UPLOAD_SIZE),
                "lst_mod_date": task.LST_MOD_DATE,
                "site_url": site_url
            }

    def get_brushtask_info(self, taskid=None):
        """
        读取刷流任务列表
        """
        self.load_brushtasks()
        if taskid:
            return self._brush_tasks.get(str(taskid)) or {}
        else:
            return self._brush_tasks.values()

    def check_task_rss(self, taskid):
        """
        检查RSS并添加下载，由定时服务调用
        :param taskid: 刷流任务的ID
        """
        if not taskid:
            return
        # 任务信息
        taskinfo = self.get_brushtask_info(taskid)
        if not taskinfo:
            return
        # 任务属性
        task_name = taskinfo.get("name")
        site_id = taskinfo.get("site_id")
        rss_url = taskinfo.get("rss_url")
        rss_rule = taskinfo.get("rss_rule")
        cookie = taskinfo.get("cookie")
        rss_free = taskinfo.get("free")
        downloader_id = taskinfo.get("downloader")
        ua = taskinfo.get("ua")
        headers = taskinfo.get("headers")
        if JsonUtils.is_valid_json(headers):
            headers = json.loads(taskinfo.get("headers"))
        else:
            headers = {}
        headers.update({'User-Agent': ua})
        state = taskinfo.get("state")
        if state != 'Y':
            log.info("【Brush】刷流任务 %s 已停止下载新种！" % task_name)
            return
        # 查询站点信息
        site_info = self.sites.get_sites(siteid=site_id)
        if not site_info:
            log.error("【Brush】刷流任务 %s 的站点已不存在，无法刷流！" % task_name)
            return
        # 站点属性
        site_id = site_info.get("id")
        site_name = site_info.get("name")
        site_proxy = site_info.get("proxy")
        site_brush_enable = site_info.get("brush_enable")
        if not site_brush_enable:
            log.error("【Brush】站点 %s 未开启刷流功能，无法刷流！" % site_name)
            return
        if not rss_url:
            log.error("【Brush】站点 %s 未配置RSS订阅地址，无法刷流！" % site_name)
            return
        if rss_free and (not cookie and not taskinfo.get("headers")):
            log.warn("【Brush】站点 %s 未配置Cookie或请求头，无法开启促销刷流" % site_name)
            return
        # 下载器参数
        downloader_cfg = self.downloader.get_downloader_conf(downloader_id)
        if not downloader_cfg:
            log.error("【Brush】任务 %s 下载器不存在，无法刷流！" % task_name)
            return

        log.info("【Brush】开始站点 %s 的刷流任务：%s..." % (site_name, task_name))
        # 检查是否达到保种体积
        if not self.__is_allow_new_torrent(taskinfo=taskinfo,
                                           dlcount=rss_rule.get("dlcount")):
            return

        rss_result = self.rsshelper.parse_rssxml(url=rss_url, proxy=site_proxy)
        if rss_result is None:
            # RSS链接过期
            log.error(f"【Brush】{task_name} RSS链接已过期，请重新获取！")
            return
        if len(rss_result) == 0:
            log.warn("【Brush】%s RSS未下载到数据" % site_name)
            return
        else:
            log.info("【Brush】%s RSS获取数据：%s" % (site_name, len(rss_result)))

        # 同时下载数
        max_dlcount = rss_rule.get("dlcount")
        success_count = 0
        new_torrent_count = 0
        if max_dlcount:
            downloading_count = self.__get_downloading_count(
                downloader_id) or 0
            new_torrent_count = int(max_dlcount) - int(downloading_count)

        for res in rss_result:
            try:
                # 种子名
                torrent_name = res.get('title')
                # 种子链接
                enclosure = res.get('enclosure')
                # 种子页面
                page_url = res.get('link')
                # 种子大小
                size = res.get('size')
                # 发布时间
                pubdate = res.get('pubdate')

                if enclosure not in self._torrents_cache:
                    self._torrents_cache.append(enclosure)
                else:
                    log.debug("【Brush】%s 已处理过" % torrent_name)
                    continue
                torrent_attr = self.siteconf.check_torrent_attr(torrent_url=page_url,
                                                cookie=cookie,
                                                ua=ua,
                                                headers=headers,
                                                proxy=site_proxy)
                log.debug("【Brush】%s 解析详情, %s" % (torrent_name, torrent_attr))
                # 检查种子是否符合选种规则
                if not self.__check_rss_rule(rss_rule=rss_rule,
                                             title=torrent_name,
                                             torrent_size=size,
                                             pubdate=pubdate,
                                             torrent_attr=torrent_attr):
                    continue
                # 检查能否添加当前种子，判断是否超过保种体积大小
                if not self.__is_allow_new_torrent(taskinfo=taskinfo,
                                                   dlcount=max_dlcount,
                                                   torrent_size=size):
                    continue
                # 检查是否已处理过
                if self.is_torrent_handled(enclosure=enclosure):
                    log.info("【Brush】%s 已在刷流任务中" % torrent_name)
                    continue
                # 开始下载
                log.debug("【Brush】%s 符合条件，开始下载..." % torrent_name)
                if self.__download_torrent(taskinfo=taskinfo,
                                           rss_rule=rss_rule,
                                           site_info=site_info,
                                           title=torrent_name,
                                           enclosure=enclosure,
                                           size=size,
                                           page_url=page_url):
                    # 计数
                    success_count += 1
                    # 添加种子后不能超过最大下载数量
                    if max_dlcount and success_count >= new_torrent_count:
                        break

                    # 再判断一次
                    if not self.__is_allow_new_torrent(taskinfo=taskinfo,
                                                       dlcount=max_dlcount):
                        break
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                continue
        log.info("【Brush】任务 %s 本次添加了 %s 个下载" % (task_name, success_count))

    def remove_task_torrents(self, taskid):
        """
        根据条件检查所有任务下载完成的种子，按条件进行删除，并更新任务数据
        由定时服务调用
        """

        def __send_message(_task_name, _delete_type, _torrent_name, _download_name, _torrent_size,
                        _download_size, _upload_size, _ratio, _add_time):
            """
            发送删种消息
            """
            _msg_title = f"【刷流任务 {_task_name} 删除做种】"
            _msg_text = (
                f"下载器名：{_download_name}\n"
                f"种子名称：{_torrent_name}\n"
                f"种子大小：{_torrent_size}\n"
                f"已下载量：{_download_size}\n"
                f"已上传量：{_upload_size}\n"
                f"分享比率：{_ratio}\n"
                f"添加时间：{_add_time}\n"
                f"删除时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n"
                f"删除规则：{_delete_type}"
            )
            self.message.send_brushtask_remove_message(title=_msg_title, text=_msg_text)

        def process_torrents(torrents: list[Torrent], downloader_cfg: dict, site_info: dict, is_downloading: bool = False):
            """
            处理种子的删除或更新逻辑
            """
            nonlocal total_uploaded, total_downloaded, delete_ids, update_torrents, remove_torrent_ids, torrent_id_maps
            
            for torrent in torrents:
                torrent_id = torrent.id
                total_uploaded += torrent.uploaded
                total_downloaded += torrent.downloaded
                
                
                if torrent_id_maps.get(torrent_id):
                    enclosure = torrent_id_maps.get(torrent_id)
                    torrent_url, torrent_attr = self.get_torrent_attr(site_info, enclosure)
                log.debug("【Brush】%s 解析详情 %s" %
                            (torrent_url, torrent_attr))
                torrent_params = {
                    "seeding_time": torrent.seeding_time,
                    "ratio": round(torrent.ratio or 0, 2),
                    "uploaded": torrent.uploaded,
                    "iatime": torrent.iatime,
                    "avg_upspeed": torrent.avg_upload_speed,
                    "freespace": self.downloader.get_free_space(downloader_id, download_dir),
                    "torrent_attr": torrent_attr,
                }

                if is_downloading:
                    torrent_params.update({"dltime": torrent.download_time, "pending_time": torrent.iatime if torrent.status == TorrentStatus.Pending else None})

                need_delete, delete_type = self.__check_remove_rule(remove_rule, torrent_params)
                if need_delete:
                    if isinstance(delete_type, list):
                        delete_type = ",".join([d.value for d in delete_type])
                    else:
                        delete_type = delete_type.value
                    log.info(f"【Brush】{torrent.name} 达到删种条件：{delete_type}，删除任务...")
                    if sendmessage:
                        __send_message(task_name, delete_type, torrent.name, downloader_cfg.get("name"),
                                    StringUtils.str_filesize(torrent.size), StringUtils.str_filesize(torrent.downloaded),
                                    StringUtils.str_filesize(torrent.uploaded), torrent_params["ratio"], torrent.add_time)

                    if torrent_id not in delete_ids:
                        delete_ids.append(torrent_id)
                        update_torrents.append((f"{torrent.uploaded},{torrent.downloaded}", taskid, torrent_id))

        taskinfo = self.get_brushtask_info(taskid)
        try:
            # 初始化一些任务信息
            total_uploaded = 0
            total_downloaded = 0
            delete_ids = []
            update_torrents = []
            remove_torrent_ids = []
            site_id = taskinfo.get("site_id")
            task_name = taskinfo.get("name")
            downloader_id = taskinfo.get("downloader")
            remove_rule = taskinfo.get("remove_rule")
            sendmessage = taskinfo.get("sendmessage")
            download_dir = taskinfo.get("savepath")
            downloader_cfg = self.downloader.get_downloader_conf(downloader_id)

            site_info = self.sites.get_sites(siteid=site_id)
            if not downloader_cfg:
                log.warn(f"【Brush】任务 {task_name} 下载器不存在")
                return
            task_torrents = self.get_brushtask_torrents(taskid)

            torrent_id_maps = {
                item.DOWNLOAD_ID: item.ENCLOSURE for item in task_torrents if item.DOWNLOAD_ID}

            torrent_ids = list(torrent_id_maps.keys())
            if not torrent_ids:
                return

            # 查询下载器完成的种子并处理
            completed_torrents = self.downloader.get_completed_torrents(downloader_id, torrent_ids)
            if completed_torrents is None:
                log.warn(f"【Brush】任务 {task_name} 获取下载完成种子失败")
                return
            remove_torrent_ids = set(torrent_ids) - set([torrent.id for torrent in completed_torrents])
            process_torrents(completed_torrents, downloader_cfg, site_info)

            # 查询下载中种子并处理
            downloading_torrents = self.downloader.get_downloading_torrents(downloader_id, torrent_ids)
            if downloading_torrents is None:
                log.warn(f"【Brush】任务 {task_name} 获取下载中种子失败")
                return
            remove_torrent_ids -= set([torrent.id for torrent in downloading_torrents])
            process_torrents(downloading_torrents, downloader_cfg, site_info, is_downloading=True)

            # 删除下载器中已不存在的种子
            if remove_torrent_ids:
                log.info(f"【Brush】任务 {task_name} 删除不存在的下载任务：{remove_torrent_ids}")
                for remove_torrent_id in remove_torrent_ids:
                    self.dbhelper.delete_brushtask_torrent(taskid, remove_torrent_id)

            # 删除符合条件的种子
            if delete_ids:
                self.downloader.delete_torrents(downloader_id, delete_ids, delete_file=True)
                time.sleep(5)
                torrents = self.downloader.get_torrents(downloader_id, delete_ids)
                if torrents is None:
                    delete_ids = []
                    update_torrents = []
                else:
                    for torrent in torrents:
                        if torrent.id in delete_ids:
                            delete_ids.remove(torrent.id)

                if delete_ids:
                    self.dbhelper.update_brushtask_torrent_state(update_torrents)
                    log.info(f"【Brush】任务 {task_name} 共删除 {len(delete_ids)} 个刷流下载任务")
                else:
                    log.info(f"【Brush】任务 {task_name} 本次检查未删除下载任务")

            # 更新任务统计数据
            self.dbhelper.add_brushtask_upload_count(taskid, total_uploaded, total_downloaded, len(delete_ids) + len(remove_torrent_ids))
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
    def __is_allow_new_torrent(self, taskinfo, dlcount, torrent_size=None):
        """
        检查是否还能添加新的下载
        """
        if not taskinfo:
            return False
        # 判断大小
        seed_size = taskinfo.get("seed_size") or None
        time_range = taskinfo.get("time_range") or ""
        task_name = taskinfo.get("name")
        downloader_id = taskinfo.get("downloader")
        downloader_name = taskinfo.get("downloader_name")
        total_size = self.dbhelper.get_brushtask_totalsize(taskinfo.get("id"))
        if torrent_size and seed_size:
            if float(torrent_size) + int(total_size) >= (float(seed_size) + 5) * 1024 ** 3:
                log.warn("【Brush】刷流任务 %s 当前保种体积 %sGB，种子大小 %sGB，不添加刷流任务"
                         % (task_name, round(int(total_size) / (1024 ** 3), 1),
                            round(int(torrent_size) / (1024 ** 3), 1)))
                return False
        if seed_size:
            if float(seed_size) * 1024 ** 3 <= int(total_size):
                log.warn("【Brush】刷流任务 %s 当前保种体积 %sGB，不再新增下载"
                         % (task_name, round(int(total_size) / 1024 / 1024 / 1024, 1)))
                return False
        # 检查正在下载的任务数
        if dlcount:
            downloading_count = self.__get_downloading_count(downloader_id)
            if downloading_count is None:
                log.error("【Brush】任务 %s 下载器 %s 无法连接" %
                          (task_name, downloader_name))
                return False
            if int(downloading_count) >= int(dlcount):
                log.warn("【Brush】下载器 %s 正在下载任务数：%s，超过设定上限，暂不添加下载" % (
                    downloader_name, downloading_count))
                return False
            
        # 检查下载时间段
        if not BrushTask.is_in_time_range(time_range=time_range):
            log.warn("【Brush】任务 %s 不在所选时间段 %s 内，暂不添加下载" %
                          (task_name, time_range))
            return False
                
        return True

    def __get_downloading_count(self, downloader_id):
        """
        查询当前正在下载的任务数
        """
        torrents = self.downloader.get_downloading_torrents(
            downloader_id=downloader_id) or []
        return len(torrents)

    def __download_torrent(self,
                           taskinfo,
                           rss_rule,
                           site_info,
                           title,
                           enclosure,
                           size,
                           page_url
                           ):
        """
        添加下载任务，更新任务数据
        :param taskinfo: 任务信息
        :param rss_rule: rss规则
        :param site_info: 站点信息
        :param title: 种子名称
        :param enclosure: 种子地址
        :param size: 种子大小
        """
        if not enclosure:
            return False
        # 站点流控
        if self.sites.check_ratelimit(site_info.get("id")):
            return False
        taskid = taskinfo.get("id")
        taskname = taskinfo.get("name")
        transfer = taskinfo.get("transfer")
        sendmessage = taskinfo.get("sendmessage")
        downloader_id = taskinfo.get("downloader")
        download_limit = rss_rule.get("downspeed")
        upload_limit = rss_rule.get("upspeed")
        download_dir = taskinfo.get("savepath")

        
        _, torrent_attr = self.get_torrent_attr(site_info, enclosure)
        hr_tag = []
        if torrent_attr.get("hr"):
            hr_tag = ['HR']
        tag = taskinfo.get("label").split(
            ',') if taskinfo.get("label") else None
        # 标签
        if not transfer:
            if tag:
                tag += ["已整理"]
                tag += hr_tag
            else:
                tag = ["已整理"]
                tag += hr_tag
        # 开始下载
        meta_info = MetaInfo(title=title)
        meta_info.set_torrent_info(site=site_info.get("name"),
                                   enclosure=enclosure,
                                   size=size)
        _, download_id, retmsg = self.downloader.download(
            media_info=meta_info,
            tag=tag,
            downloader_id=downloader_id,
            download_dir=download_dir,
            download_setting="-2",
            download_limit=download_limit,
            upload_limit=upload_limit
        )
        if not download_id:
            # 下载失败
            log.warn(f"【Brush】{taskname} 添加下载任务出错：{title}，"
                     f"错误原因：{retmsg or '下载器添加任务失败'}，"
                     f"种子链接：{enclosure}")
            return False
        else:
            # 下载成功
            log.info("【Brush】成功添加下载：%s" % title)
            if sendmessage:
                # 下载器参数
                downloader_cfg = self.downloader.get_downloader_conf(
                    downloader_id)
                # 下载器名称
                downlaod_name = downloader_cfg.get("name")
                msg_title = f"【刷流任务 {taskname} 新增下载】"
                msg_text = f"下载器名：{downlaod_name}\n" \
                           f"种子名称：{title}\n" \
                           f"种子大小：{StringUtils.str_filesize(size)}\n" \
                           f"添加时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
                self.message.send_brushtask_added_message(
                    title=msg_title, text=msg_text)

        # 插入种子数据
        if self.dbhelper.insert_brushtask_torrent(brush_id=taskid,
                                                  title=title,
                                                  enclosure=enclosure,
                                                  downloader=downloader_id,
                                                  download_id=download_id,
                                                  size=size):
            # 更新下载次数
            self.dbhelper.add_brushtask_download_count(brush_id=taskid)
        else:
            log.info("【Brush】%s 已下载过" % title)

        return True

    @staticmethod
    def __check_rss_rule(rss_rule,
                         title,
                         torrent_size,
                         pubdate,
                         torrent_attr):
        """
        检查种子是否符合刷流过滤条件
        :param rss_rule: 过滤条件字典
        :param title: 种子名称
        :param torrent_size: 种子大小
        :param pubdate: 发布时间
        :return: 是否命中
        """
        if not rss_rule:
            return True

        try:
            # 规则检查字典
            rule_checks = {
                "size": lambda rule_value: BrushTask.check_range_rule(torrent_size, rule_value, 1024 ** 3),
                "include": lambda rule_value: re.search(rule_value, title, re.IGNORECASE),
                "exclude": lambda rule_value: not re.search(rule_value, title, re.IGNORECASE),
                "free": lambda rule_value: BrushTask._check_free_status(torrent_attr, rule_value),
                "hr": lambda rule_value: not torrent_attr.get("hr"),
                "peercount": lambda rule_value: BrushTask._check_peer_count(torrent_attr.get("peer_count"), rule_value),
                "pubdate": lambda rule_value: BrushTask._check_pubdate(pubdate, torrent_attr, rule_value),
                "exclude_subscribe": lambda rule_value: not BrushTask._check_subscribe_status(title, rule_value)
            }

            # 遍历规则并进行检查
            for rule, check_func in rule_checks.items():
                rule_value = rss_rule.get(rule)
                log.debug(f"检查字段: {rule}, 规则值: {rule_value}")
                # 忽略规则为 "#"
                if rule_value == "#" or rule_value == "N":
                    log.debug(f"规则 {rule} 被设置为忽略 (#)，跳过检查")
                    continue
                if rule_value and not check_func(rule_value):
                    log.debug(f"字段: {rule} 不符合规则")
                    return False

        except Exception as err:
            ExceptionUtils.exception_traceback(err)

        return True


    @staticmethod
    def _check_subscribe_status(title, rule_value):
        """
        排除已订阅的媒体
        """
        if rule_value == "N":
            return False
        media = Media()
        subscribe = Subscribe()
        log.info("【Brush】开始排除已订阅媒体...")
        # 读取电影订阅
        rss_movies = subscribe.get_subscribe_movies(state='R')
        if not rss_movies:
            log.warn("【Brush】没有正在订阅的电影")
        else:
            log.info("【Brush】电影订阅清单：%s"
                        % " ".join('%s' % info.get("name") for _, info in rss_movies.items()))
        # 读取电视剧订阅
        rss_tvs = subscribe.get_subscribe_tvs(state='R')
        if not rss_tvs:
            log.warn("【Brush】没有正在订阅的电视剧")
        else:
            log.info("【Brush】电视剧订阅清单：%s"
                        % " ".join('%s' % info.get("name") for _, info in rss_tvs.items()))
        # 没有订阅退出
        if not rss_movies and not rss_tvs:
            return False
        
        # 识别种子名称，开始搜索TMDB
        media_info = MetaInfo(title=title)
        cache_info = media.get_cache_info(media_info)
        if cache_info.get("id"):
            # 使用缓存信息
            media_info.tmdb_id = cache_info.get("id")
            media_info.type = cache_info.get("type")
            media_info.title = cache_info.get("title")
            media_info.year = cache_info.get("year")
        else:
            # 重新查询TMDB
            media_info = media.get_media_info(title=title)
            if not media_info:
                log.warn(f"【Brush】{title} 无法识别出媒体信息！")
                return
            elif not media_info.tmdb_info:
                log.info(f"【Brush】{title} 识别为 {media_info.get_name()} 未匹配到TMDB媒体信息")
        
        match_flag = False
        match_rss_info = {}
        # 匹配电影
        if media_info.type == MediaType.MOVIE and rss_movies:
            for rid, rss_info in rss_movies.items():
                # tmdbid或名称年份匹配
                name = rss_info.get('name')
                year = rss_info.get('year')
                tmdbid = rss_info.get('tmdbid')
                fuzzy_match = rss_info.get('fuzzy_match')
                # 非模糊匹配
                if not fuzzy_match:
                    # 有tmdbid时使用tmdbid匹配
                    if tmdbid and not tmdbid.startswith("DB:"):
                        if str(media_info.tmdb_id) != str(tmdbid):
                            continue
                    else:
                        # 豆瓣年份与tmdb取向不同
                        if year and str(media_info.year) not in [str(year),
                                                                 str(int(year) + 1),
                                                                 str(int(year) - 1)]:
                            continue
                        if name != media_info.title:
                            continue
                # 模糊匹配
                else:
                    # 匹配年份
                    if year and str(year) != str(media_info.year):
                        continue
                    # 匹配关键字或正则表达式
                    search_title = f"{media_info.rev_string} {media_info.title} {media_info.year}"
                    if not re.search(name, search_title, re.I) and name not in search_title:
                        continue
                # 媒体匹配成功
                match_flag = True
                match_rss_info = rss_info

                break
        # 匹配电视剧
        elif rss_tvs:
            # 匹配种子标题
            for rid, rss_info in rss_tvs.items():
                rss_sites = rss_info.get('rss_sites')
                # 过滤订阅站点
                if rss_sites and media_info.site not in rss_sites:
                    continue
                # 有tmdbid时精确匹配
                name = rss_info.get('name')
                year = rss_info.get('year')
                season = rss_info.get('season')
                tmdbid = rss_info.get('tmdbid')
                fuzzy_match = rss_info.get('fuzzy_match')
                # 非模糊匹配
                if not fuzzy_match:
                    if tmdbid and not tmdbid.startswith("DB:"):
                        if str(media_info.tmdb_id) != str(tmdbid):
                            continue
                    else:
                        # 匹配年份，年份可以为空
                        if year and str(year) != str(media_info.year):
                            continue
                        # 匹配名称
                        if name != media_info.title:
                            continue
                    # 匹配季，季可以为空
                    if season and season != media_info.get_season_string():
                        continue
                # 模糊匹配
                else:
                    # 匹配季，季可以为空
                    if season and season != "S00" and season != media_info.get_season_string():
                        continue
                    # 匹配年份
                    if year and str(year) != str(media_info.year):
                        continue
                    # 匹配关键字或正则表达式
                    search_title = f"{media_info.rev_string} {media_info.title} {media_info.year}"
                    if not re.search(name, search_title, re.I) and name not in search_title:
                        continue
                # 媒体匹配成功
                match_flag = True
                match_rss_info = rss_info
                break
        log.info(f"【Brush】匹配到媒体: {match_rss_info}")
        return match_flag   
    
    @staticmethod
    def _check_free_status(torrent_attr, rule_value):
        """
        检查免费状态
        :param rule_value: 规则中的 free 值
        :param torrent_attr: 种子属性字典
        :return: 是否符合条件
        """
        if rule_value == "FREE" and not torrent_attr.get("free"):
            return False
        if rule_value == "2XFREE" and not torrent_attr.get("2xfree"):
            return False
        return True

    @staticmethod
    def _check_peer_count(torrent_peer_count, rule_value):
        """
        检查做种人数
        :param torrent_peer_count: 种子的做种人数
        :param rule_value: 规则中的 peercount 值
        :return: 是否符合条件
        """
        return BrushTask.check_range_rule(torrent_peer_count, rule_value)

    @staticmethod
    def _check_pubdate(pubdate, torrent_attr, rule_value):
        """
        检查发布时间
        :param pubdate: 种子发布时间
        :param torrent_attr: 种子属性字典
        :param rule_value: 规则中的 pubdate 值
        :return: 是否符合条件
        """
        if torrent_attr.get("pubdate"):
            local_time_str = torrent_attr.get("pubdate")
            pubdate = dateutil.parser.parse(local_time_str).replace(tzinfo=timezone(timedelta(hours=8)))

        if pubdate:
            pubdate_hours = (datetime.now(pytz.utc) - pubdate).total_seconds() / 3600
            return BrushTask.check_range_rule(pubdate_hours, rule_value, multiplier=1)
        return True

    @staticmethod
    def __check_remove_rule(remove_rule, params):
        """
        检查是否符合删种规则
        :param remove_rule: 删种规则，包含 mode 字段来决定使用 and 或 or 模式
        :param params: 一个字典，包含所有要检查的参数，如 seeding_time, ratio, uploaded, dltime, avg_upspeed, iatime 等
        """
        if not remove_rule:
            return False, BrushDeleteType.NOTDELETE

        hr = params.get('torrent_attr', {}).get('hr', False)
        log.debug(f"HR 状态 {hr}")

        # 提取各参数
        values = {
            "time": params.get("seeding_time"),
            "hr_time": params.get("seeding_time"),
            "ratio": params.get("ratio"),
            "uploadsize": params.get("uploaded"),
            "dltime": params.get("dltime"),
            "avg_upspeed": params.get("avg_upspeed"),
            "iatime": params.get("iatime"),
            "pending_time": params.get("pending_time"),
            "freespace": params.get("freespace"),
            "freestatus": params.get('torrent_attr', {}).get("free", False)
        }

        # 配置规则字段和检查函数
        rule_checks = {
            "time": (BrushDeleteType.SEEDTIME, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 3600)),
            "hr_time": (BrushDeleteType.HRSEEDTIME, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 3600)),
            "ratio": (BrushDeleteType.RATIO, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value)),
            "uploadsize": (BrushDeleteType.UPLOADSIZE, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 1024 ** 3)),
            "dltime": (BrushDeleteType.DLTIME, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 3600)),
            "avg_upspeed": (BrushDeleteType.AVGUPSPEED, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 1024)),
            "iatime": (BrushDeleteType.IATIME, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 3600)),
            "pending_time": (BrushDeleteType.PENDINGTIME, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 3600)),
            "freespace": (BrushDeleteType.FREESPACE, lambda value, rule_value: BrushTask.check_range_rule(value, rule_value, 1024 ** 3)),
            "freestatus": (BrushDeleteType.FREEEND, lambda value, rule_value: not value),
        }

        mode = remove_rule.get('mode', 'or')  # 默认为 OR 模式
        delete_type_result = []
        all_conditions_met = True if mode == 'and' else False

        try:
            for field, (delete_type, check_func) in rule_checks.items():
                rule_value = remove_rule.get(field)
                value = values.get(field)

                log.debug(f"检查字段: {field}, 规则值: {rule_value}, 实际值: {value}")
                if rule_value and value is not None:
                    
                    # 忽略规则为 "#"
                    if rule_value == "#" or rule_value == "N":
                        log.debug(f"规则 {field} 被设置为忽略 (#)，跳过检查")
                        continue

                    # hr 为 True 时只检查 hr_time，反之检查 time
                    if field == "time" and hr:
                        log.debug("跳过检查 'time'，因为 hr 为 True")
                        continue
                    if field == "hr_time" and not hr:
                        log.debug("跳过检查 'hr_time'，因为 hr 为 False")
                        continue
                    # 调用通用检查函数
                    if check_func(value, rule_value):
                        log.debug(f"字段: {field} 符合规则, 删除类型: {delete_type}")
                        if mode == 'or':
                            return True, delete_type  # 在 OR 模式下，只要一个满足条件即可
                        delete_type_result.append(delete_type)  # 在 AND 模式下，收集满足条件的删除类型
                    else:
                        if mode == 'and':
                            all_conditions_met = False  # 在 AND 模式下，任何一个不满足条件就不删除

            if mode == 'and' and all_conditions_met and delete_type_result:
                return True, delete_type_result

        except Exception as err:
            ExceptionUtils.exception_traceback(err)

        return False, BrushDeleteType.NOTDELETE
    @staticmethod
    def check_range_rule(value, rule_value, multiplier=1):
        """
        通用范围规则检查函数
        :param value: 实际值
        :param rule_value: 规则值，格式为 'operator#min,max'
        :param multiplier: 可选，值的单位倍数，比如 1024 ** 3 表示 GB，3600 表示小时
        :return: 满足条件返回 True，否则返回 False
        """
        rule_parts = rule_value.split("#")
        if len(rule_parts) < 2 or not rule_parts[1]:
            return True

        operator = rule_parts[0]
        range_values = rule_parts[1].split(",")

        min_value = float(range_values[0]) * multiplier
        max_value = float(range_values[1]) * multiplier if len(range_values) > 1 else None

        if operator == "gt" and value < min_value:
            return False
        if operator == "lt" and value > min_value:
            return False
        if operator == "bw" and (value < min_value or (max_value and value >= max_value)):
            return False
        return True

    @staticmethod
    def __check_stop_rule(stop_rule,
                          torrent_attr=None):
        """
        检查是否符合停种规则
        :param stop_rule: 停种规则
        :param torrent_status: 种子状态是否free
        """
        if not stop_rule:
            return False

        if stop_rule.get("stopfree") and torrent_attr:
            rule_stopfree = stop_rule.get("stopfree")
            if rule_stopfree:
                if rule_stopfree == "Y" and not (torrent_attr.get('2xfree') or torrent_attr.get('free')):
                    return True, BrushStopType.FREEEND

        return False, BrushStopType.NOTSTOP

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler and self._scheduler.SCHEDULER:
                self._scheduler.remove_all_jobs(jobstore=self._jobstore)
        except Exception as e:
            print(str(e))

    def update_brushtask(self, brushtask_id, item):
        """
        新增刷种任务
        """
        ret = self.dbhelper.update_brushtask(brushtask_id, item)
        self.init_config()
        return ret

    def delete_brushtask(self, brushtask_id):
        """
        删除刷种任务
        """
        ret = self.dbhelper.delete_brushtask(brushtask_id)
        self.init_config()
        return ret

    def update_brushtask_state(self, state, brushtask_id=None):
        """
        更新刷种任务状态
        """
        ret = self.dbhelper.update_brushtask_state(
            tid=brushtask_id, state=state)
        self.init_config()
        return ret

    def get_brushtask_torrents(self, brush_id, active=True):
        """
        获取刷种任务的种子列表
        """
        return self.dbhelper.get_brushtask_torrents(brush_id, active)

    def is_torrent_handled(self, enclosure):
        """
        判断种子是否已经处理过
        """
        return self.dbhelper.get_brushtask_torrent_by_enclosure(enclosure)

    def stop_task_torrents(self, taskid):
        """
        检查非free的所有任务正在下载的种子并进行暂停
        由定时服务调用
        """
        def __send_message(_task_name, _torrent_name, _download_name, _add_time):
            """
            发送删种消息
            """
            _msg_title = f"【刷流任务 {_task_name} 暂停做种】"
            _msg_text = f"下载器名：{_download_name}\n" \
                        f"种子名称：{_torrent_name}\n" \
                        f"添加时间：{_add_time}\n" \
                        f"暂停时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n" \
                        "暂停原因: free 时间到期"
            self.message.send_brushtask_pause_message(
                title=_msg_title, text=_msg_text)

        # 遍历所有任务
        taskinfo = self.get_brushtask_info(taskid)
        task_name = taskinfo.get("name")
        stop_rule = taskinfo.get("stop_rule")
        downloader_id = taskinfo.get("downloader")
        sendmessage = taskinfo.get("sendmessage")
        site_id = taskinfo.get("site_id")

        # 查询站点信息
        site_info = self.sites.get_sites(siteid=site_id)
        if not site_info:
            log.error("【Brush】刷流任务 %s 的站点已不存在，无法刷流！" % task_name)
            return

        log.info("【Brush】开始非免费种子暂停任务：%s..." % (task_name))
        # 当前任务种子详情
        task_torrents = self.get_brushtask_torrents(taskid)
        torrent_id_maps = {
            item.DOWNLOAD_ID: item.ENCLOSURE for item in task_torrents if item.DOWNLOAD_ID}
        torrent_ids = list(torrent_id_maps.keys())
        # 没有种子ID的不处理
        if not torrent_id_maps:
            return
        # 下载器参数
        downloader_cfg = self.downloader.get_downloader_conf(downloader_id)
        if not downloader_cfg:
            log.warn("【Brush】任务 %s 下载器不存在" % task_name)
            return
        # 下载器名称
        downlaod_name = downloader_cfg.get("name")
        # 查询下载器中正在下载的所有种子
        torrents = self.downloader.get_downloading_torrents(downloader_id=downloader_id,
                                                            ids=torrent_ids)
        # 有错误不处理了，避免误删种子
        if torrents is None:
            log.warn("【Brush】任务 %s 获取正在下载种子失败" % task_name)
            return
        for torrent in torrents:
            torrent_id = torrent.id
            # 种子名称
            torrent_name = torrent.name
            # 种子添加时间
            add_time = torrent.add_time
            if torrent_id_maps.get(torrent_id):
                enclosure = torrent_id_maps.get(torrent_id)
                torrent_url, torrent_attr = self.get_torrent_attr(site_info, enclosure)
                log.debug("【Brush】%s 解析详情 %s" %
                            (torrent_url, torrent_attr))

                need_stop, stop_type = self.__check_stop_rule(
                    stop_rule, torrent_attr=torrent_attr)
                if need_stop:
                    log.info("【Brush】%s 触发停种条件：%s，暂停任务..." %
                                (torrent_name, stop_type.value))
                    self.downloader.stop_torrents(
                        downloader_id, [torrent_id])
                    if sendmessage:
                        __send_message(_task_name=task_name,
                                        _torrent_name=torrent_name,
                                        _download_name=downlaod_name,
                                        _add_time=add_time)

    def get_torrent_attr(self, site_info: dict, enclosure: str):
        """
        通过下载链接获取种子属性
        """
        if not site_info:
            return None, {}
        ua = site_info.get("ua")
        headers = site_info.get("headers")
        if JsonUtils.is_valid_json(headers):
            headers = json.loads(site_info.get("headers"))
        else:
            headers = {}
        headers.update({'User-Agent': ua})
        site_proxy = site_info.get("proxy")
        site_cookie = site_info.get("cookie")
        split_url = urlsplit(site_info.get("rssurl"))
        site_base_url = f"{split_url.scheme}://{split_url.netloc}"

        tid = StringUtils.get_tid_by_url(enclosure)
        # 提取站点关键字并匹配相应的模板
        site_key = next((key for key in ['m-team', 'yemapt', 'star-space'] if key in enclosure), 'default')

        # 构建 torrent_url
        torrent_url = f"{site_base_url}{SiteConf().URL_DETAIL_TEMPLATES[site_key].format(tid=tid)}"

        torrent_attr = self.siteconf.check_torrent_attr(torrent_url=torrent_url,
                                                                cookie=site_cookie,
                                                                ua=ua,
                                                                headers=headers,
                                                                proxy=site_proxy)
                                                        
        return torrent_url,torrent_attr

    @staticmethod
    def is_in_time_range(time_range=None):
        if not time_range:
            return True  # 如果时间段字符串为空，返回 True，表示不限制
        try:
            # 解析时间段
            start_str, end_str = time_range.split('-')
            start_hour, start_minute = map(int, start_str.split(':'))
            end_hour, end_minute = map(int, end_str.split(':'))
            start_time = dtime(start_hour, start_minute)
            end_time = dtime(end_hour, end_minute)
            
            # 获取当前时间
            now = datetime.now().time()
            return start_time <= now <= end_time
        except ValueError:
            log.warn("【Brush】时间段格式错误，应为 'HH:MM-HH:MM'")
            return False  # 格式错误时返回 False，不执行任务