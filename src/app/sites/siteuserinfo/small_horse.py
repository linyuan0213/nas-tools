"""SmallHorse 架构用户信息解析"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lxml import etree

import log
from app.utils import StringUtils

if TYPE_CHECKING:
    from app.sites.siteuserinfo.config_html import ConfigHtmlUserInfo


def is_small_horse(ins: ConfigHtmlUserInfo) -> bool:
    return "Small Horse" in ins._index_html


def parse(ins: ConfigHtmlUserInfo) -> None:
    html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", ins._index_html))
    html: Any = etree.HTML(html_text)
    if html is None:
        return

    ret: Any = html.xpath('//a[contains(@href, "user.php")]//text()')
    if ret:
        ins.username = str(ret[0])
    user_detail = re.search(r"user.php\?id=(\d+)", html_text)
    if user_detail and user_detail.group(1):
        ins.userid = user_detail.group(1)

    tmps: Any = html.xpath('//ul[@class="stats nobullet"]')
    if tmps:
        try:
            li = tmps[1].xpath("li")
            if li and li[0].xpath("span//text()"):
                ins.join_at = StringUtils.unify_datetime_str(li[0].xpath("span//text()")[0])
            ins.upload = StringUtils.num_filesize(str(li[2].xpath("text()")[0]).split(":")[1].strip())
            ins.download = StringUtils.num_filesize(str(li[3].xpath("text()")[0]).split(":")[1].strip())
            if li[4].xpath("span//text()"):
                ins.ratio = StringUtils.str_float(str(li[4].xpath("span//text()")[0]).replace("∞", "0"))
            else:
                ins.ratio = StringUtils.str_float(re.split(r":", str(li[5].xpath("text()")[0]))[1])
            ins.bonus = StringUtils.str_float(str(li[5].xpath("text()")[0]).split(":")[1])
            ins.user_level = str(tmps[3].xpath("li")[0].xpath("text()")[0]).split(":")[1].strip()
            ins.leeching = StringUtils.str_int(
                (tmps[4].xpath("li")[6].xpath("text()")[0]).split(":")[1].replace("[", "")  # type: ignore[reportArgumentType]
            )
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Sites]忽略异常: {e}")
