"""NexusPhp 架构用户信息解析 — 从 config_html.py 提取"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from lxml import etree

import log
from app.utils import StringUtils
from app.utils.json_utils import JsonUtils

if TYPE_CHECKING:
    from app.sites.siteuserinfo.config_html import ConfigHtmlUserInfo


def is_nexusphp(ins: ConfigHtmlUserInfo) -> bool:
    if "torrents.php" in ins._index_html or "browse.php" in ins._index_html:
        return True
    if "userdetails.php" in ins._index_html or "messages.php" in ins._index_html:
        return True
    search_cfg = ins._def.html.search if ins._def.html else {}
    paths = search_cfg.get("paths", [{}]) if isinstance(search_cfg, dict) else []
    path = paths[0].get("path", "") if paths else ""
    return "torrents.php" in path or "browse.php" in path


def parse(ins: ConfigHtmlUserInfo) -> None:
    _parse_userid(ins)
    _parse_base_info(ins)
    _parse_traffic(ins)
    _parse_seeding(ins)
    _parse_detail(ins)


def _parse_userid(ins: ConfigHtmlUserInfo) -> None:
    html = re.sub(r"#\d+", "", re.sub(r"\d+px", "", ins._index_html))
    m = re.search(r"userdetails.php\?id=(\d+)", html)
    if m and m.group(1):
        ins.userid = m.group(1)
    elif re.search(r"userdetails", html):
        ins.userid = None
    m = re.search(r"user_detail\.php\?uid=(\d+)", html)
    if m and m.group(1):
        ins.userid = m.group(1)


def _parse_base_info(ins: ConfigHtmlUserInfo) -> None:
    re.sub(r"#\d+", "", re.sub(r"\d+px", "", ins._index_html))
    doc: Any = etree.HTML(ins._index_html)
    if doc is None:
        return
    ret = doc.xpath('//a[contains(@href,"userdetails")]//b//text()')
    if ret:
        ins.username = str(ret[0])
    elif not ins.username:
        ret = doc.xpath('//a[contains(@href,"userdetails")]//text()')
        if ret:
            ins.username = str(ret[0])
    if not ins.username:
        ret = doc.xpath('//a[contains(@href,"userdetails")]//strong//text()')
        if ret:
            ins.username = str(ret[0])
    message_labels = doc.xpath('//a[@href="messages.php"]/..')
    extra_labels = doc.xpath('//a[contains(@href,"messages.php")]/..')
    if isinstance(extra_labels, list):
        message_labels.extend(extra_labels)
    if message_labels:
        text = str(message_labels[0].xpath("string(.)") or "")
        mm = re.findall(r"[^Date](信息箱\s*|\(|你有\xa0)(\d+)", text)
        if mm and len(mm[-1]) == 2:
            ins.message_unread = StringUtils.str_int(mm[-1][1])
        elif text.isdigit():
            ins.message_unread = StringUtils.str_int(text)


def _parse_traffic(ins: ConfigHtmlUserInfo) -> None:
    if not ins.userid:
        return
    page_url = urljoin(ins._base_url_str + "/", f"userdetails.php?id={ins.userid}")
    html_text = ins._fetch_html(page_url)
    if not html_text:
        return
    html = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_text))
    m = re.search(r"[^总]上[传傳]量?[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+[KMGTPI]*B)", html, re.I)
    ins.upload = StringUtils.num_filesize(m.group(1).strip()) if m else 0
    m = re.search(r"[^总子影力]下[载載]量?[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+[KMGTPI]*B)", html, re.I)
    ins.download = StringUtils.num_filesize(m.group(1).strip()) if m else 0
    m = re.search(r"分享率[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+)", html)
    calc = 0.0 if ins.download <= 0.0 else round(ins.upload / ins.download, 3)
    ins.ratio = StringUtils.str_float(m.group(1)) if (m and m.group(1).strip()) else calc
    m = re.search(r"(Torrents leeching|下载中)[\u4E00-\u9FA5\D\s]+(\d+)[\s\S]+<", html)
    ins.leeching = StringUtils.str_int(m.group(2)) if m and m.group(2).strip() else 0
    doc: Any = etree.HTML(html_text)
    if doc is not None:
        golds = doc.xpath('//span[@class="ucoin-symbol ucoin-gold"]//text()')
        silvers = doc.xpath('//span[@class="ucoin-symbol ucoin-silver"]//text()')
        coppers = doc.xpath('//span[@class="ucoin-symbol ucoin-copper"]//text()')
        if golds or silvers or coppers:
            g = StringUtils.str_float(str(golds[-1])) if golds else 0
            s = StringUtils.str_float(str(silvers[-1])) if silvers else 0
            c = StringUtils.str_float(str(coppers[-1])) if coppers else 0
            ins.bonus = g * 100 * 100 + s * 100 + c
            return
        tmps = doc.xpath('//a[contains(@href,"mybonus")]/@title')
        if not tmps:
            tmps = doc.xpath('//a[contains(@href,"mybonus")]/text()')
        if tmps:
            for t in tmps:
                bm = re.search(r"([\d,.]+)", str(t).strip())
                if bm and bm.group(1):
                    ins.bonus = StringUtils.str_float(bm.group(1))
                    return
    m = re.search(r"mybonus.[\[\]:：<>/a-zA-Z_\-=\"'\s#;.(使用魔力值豆]+\s*([\d,.]+)[<()&\s]", html)
    if m and m.group(1).strip():
        ins.bonus = StringUtils.str_float(m.group(1))


def _parse_seeding(ins: ConfigHtmlUserInfo) -> None:
    if not ins.userid:
        return
    ui = ins._def.user_info if isinstance(ins._def.user_info, dict) else {}
    sc = ui.get("seeding", {})
    page_paths = [f"getusertorrentlistajax.php?userid={ins.userid}&type=seeding"]
    if sc.get("page"):
        page_paths = [sc["page"].format(userid=ins.userid)]
    detail_page_text = ins._fetch_html(urljoin(ins._base_url_str + "/", f"userdetails.php?id={ins.userid}"))
    referer = f"{ins._base_url_str}/userdetails.php?id={ins.userid}"
    if detail_page_text:
        detail_text = re.sub(r"&nbsp;", " ", detail_page_text)
        m = re.search(r"\(\s*(\d+)\s*个种子[,，]\s*共计\s*([\d.]+\s*[KMGT]B)\s*\)", detail_text)
        if not m:
            m = re.search(r"(\d+)\s*个种子[,，]\s*共计\s*([\d.]+\s*[KMGT]B)", detail_text)
        if m:
            ins.seeding = StringUtils.str_int(m.group(1))
            ins.seeding_size = StringUtils.num_filesize(m.group(2))
            ins.seeding_info = "[]"
            return
        detail_doc: Any = etree.HTML(detail_page_text)
        if detail_doc is not None:
            for tag, base in [("a", "@href"), ("form", "@action")]:
                for pattern in ["getusertorrentlist.php", "getusertorrentlistajax.php"]:
                    links = detail_doc.xpath(f'//{tag}[contains({base},"{pattern}")]/{base}')
                    if links:
                        href = str(links[0]).strip()
                        if "userid" not in href:
                            href = f"{href}{'&' if '?' in href else '?'}userid={ins.userid}&type=seeding"
                        if href not in page_paths:
                            page_paths.append(href)
                        break
    for page_path in page_paths:
        page_url = urljoin(ins._base_url_str + "/", page_path)
        is_ajax = "ajax" in page_path.lower() or "torrentlist" in page_path.lower()
        html_text = ins._fetch_html(page_url, referer=referer, use_ajax_headers=is_ajax)
        if not html_text:
            continue
        doc: Any = etree.HTML(html_text.replace(r"\/", "/"))
        if doc is None:
            continue
        _parse_seeding_html(ins, doc, html_text)
        next_url = _next_page_url(ins, doc)
        while next_url:
            html_text = ins._fetch_html(next_url, referer=referer)
            if not html_text:
                break
            doc: Any = etree.HTML(html_text.replace(r"\/", "/"))
            if doc is None:
                break
            _parse_seeding_html(ins, doc, html_text)
            next_url = _next_page_url(ins, doc)


def _detect_col_index(doc: Any, table_prefix: str, class_names: list[str]) -> int:
    for cls_name in class_names:
        tds = doc.xpath(f'{table_prefix}//tr[1]//img[@class="{cls_name}"]/ancestor::td[1]')
        if not tds:
            continue
        header_row = doc.xpath(f"{table_prefix}//tr[1]")[0]
        for i, td in enumerate(header_row.xpath("td"), start=1):
            if td is tds[0]:
                return i
    return 4


def _is_filesize_text(text: str) -> bool:
    return bool(re.search(r"\d+(\.\d+)?\s*[KMGTP]?B?", text, re.I))


def _is_int_text(text: str) -> bool:
    return bool(re.search(r"^\d+$", text.strip()))


def _parse_seeding_html(ins: ConfigHtmlUserInfo, doc: Any, html_text: str) -> None:
    ui = ins._def.user_info if isinstance(ins._def.user_info, dict) else {}
    sc = ui.get("seeding", {})
    total_regex = sc.get("total_regex")
    if total_regex:
        m = re.search(total_regex, html_text, re.I)
        if m and m.group(1):
            ins.seeding = max(ins.seeding or 0, StringUtils.str_int(m.group(1)))
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                ins.seeding_size = max(ins.seeding_size or 0, StringUtils.num_filesize(m.group(2)))
            return
    total_match = re.search(r"<b>(\d+)</b>条记录 Total: ([\d.]+ TB)", html_text)
    if total_match:
        ins.seeding = max(ins.seeding or 0, StringUtils.str_int(total_match.group(1)))
        ins.seeding_size = max(ins.seeding_size or 0, StringUtils.num_filesize(total_match.group(2)))
        return
    total_match = re.search(r"合计<b>(\d+)</b>", html_text)
    if total_match:
        ins.seeding = max(ins.seeding or 0, StringUtils.str_int(total_match.group(1)))
    list_sel = sc.get("list_selector", "")
    if list_sel:
        rows = doc.cssselect(list_sel)
        if not rows:
            try:
                rows = doc.xpath(list_sel)
            except Exception:
                rows = []
            if not isinstance(rows, list):
                rows = []
        info = JsonUtils.loads(ins.seeding_info) if ins.seeding_info and ins.seeding_info != "[]" else []
        size_sel = sc.get("size_selector", "td:nth-child(4)")
        seeders_sel = sc.get("seeders_selector", "td:nth-child(5)")
        for row in rows:
            if row.xpath(".//td[contains(@class,'colhead')]") or row.xpath(".//th"):
                continue
            try:
                se = row.cssselect(size_sel)
                if not se:
                    continue
                sd_els = row.cssselect(seeders_sel)
                seeders = StringUtils.str_int(sd_els[0].xpath("string(.)").strip()) if sd_els else 0
                size = StringUtils.num_filesize(se[0].xpath("string(.)").strip())
                ins.seeding_size += size
                ins.seeding += 1
                info.append([seeders, size])
            except Exception as e:  # noqa: BLE001
                log.debug(f"[nexus_php]忽略异常: {e}")
        ins.seeding_info = JsonUtils.dumps(info)
        return
    table_prefix = (
        '//table[@class="torrents"]'
        if doc.xpath('//table[@class="torrents"]')
        else (
            '//table[.//td[contains(@class,"colhead")]]'
            if doc.xpath('//table[.//td[contains(@class,"colhead")]]')
            else ""
        )
    )
    if table_prefix and "torrents" not in table_prefix:
        size_col = _detect_col_index(doc, table_prefix, ["size"])
        seeders_col = _detect_col_index(doc, table_prefix, ["seeders"])
    else:
        size_col = 4
        seeders_col = 5
    size_texts = doc.xpath(f"{table_prefix}//tr[position()>1]/td[{size_col}]")
    if table_prefix:
        seeders_els = doc.xpath(f"{table_prefix}//tr[position()>1]/td[{seeders_col}]")
        seeders_texts = [el.xpath("string(.)").strip() for el in seeders_els]
    else:
        seeders_texts = doc.xpath(f"{table_prefix}//tr[position()>1]/td[{seeders_col}]//text()")
    if not isinstance(size_texts, list):
        return
    info = JsonUtils.loads(ins.seeding_info) if ins.seeding_info and ins.seeding_info != "[]" else []
    for i, sz in enumerate(size_texts):
        size_str = str(sz.xpath("string(.)")).strip()
        if not _is_filesize_text(size_str):
            continue
        size = StringUtils.num_filesize(size_str)
        sd = 0
        if isinstance(seeders_texts, list) and i < len(seeders_texts):
            sd_str = str(seeders_texts[i]).strip()
            sd = StringUtils.str_int(sd_str) if _is_int_text(sd_str) else 0
        ins.seeding_size += size
        ins.seeding += 1
        info.append([sd, size])
    ins.seeding_info = JsonUtils.dumps(info)


def _next_page_url(ins: ConfigHtmlUserInfo, doc: Any) -> str | None:
    links = doc.xpath('//a[contains(.,"下一页") or contains(.,"下一頁")]/@href')
    if links:
        next_url = str(links[-1]).strip()
        if "javascript:" in next_url:
            m = re.search(r"getusertorrentlistajax\(\d+,'\w+','[^']*',(\d+)\)", next_url)
            if m and m.group(1):
                next_url = f"getusertorrentlistajax.php?userid={ins.userid}&type=seeding&page={m.group(1)}"
                return urljoin(ins._base_url_str + "/", next_url)
        if ins.userid and "userid" not in next_url:
            next_url = f"{next_url}&userid={ins.userid}&type=seeding"
        return urljoin(ins._base_url_str + "/", next_url)
    return None


def _parse_detail(ins: ConfigHtmlUserInfo) -> None:
    if not ins.userid:
        return
    page_url = urljoin(ins._base_url_str + "/", f"userdetails.php?id={ins.userid}")
    html_text = ins._fetch_html(page_url)
    if not html_text:
        return
    doc: Any = etree.HTML(html_text)
    if doc is None:
        return
    level = doc.xpath(
        '//tr/td[text()="等級" or text()="等级" or *[text()="等级"]]/following-sibling::td[1]/img[1]/@title'
    )
    if level:
        ins.user_level = level[0].strip()
    else:
        level = doc.xpath(
            '//tr/td[text()="等級" or text()="等级"]/following-sibling::td[1 and not(img)]'
            '|//tr/td[text()="等級" or text()="等级"]/following-sibling::td[1 and img[not(@title)]]'
        )
        if level:
            ins.user_level = level[0].xpath("string(.)").strip()
    if not ins.user_level:
        level = doc.xpath('//a[contains(@href,"userdetails")]/text()')
        for label in level or []:
            m = re.search(r"\[(.*)]", label)
            if m and m.group(1):
                ins.user_level = m.group(1).strip()
                break
    join = doc.xpath(
        '//tr/td[text()="加入日期" or text()="注册日期" or *[text()="加入日期"]]/following-sibling::td[1]//text()'
        '|//div/b[text()="加入日期"]/../text()'
    )
    if join:
        ins.join_at = StringUtils.unify_datetime_str(str(join[0]).split(" (")[0].strip())
    if not ins.bonus:
        ui = ins._def.user_info if isinstance(ins._def.user_info, dict) else {}
        labels = ui.get("bonus_labels", ["魔力值", "猫粮"])
        if not isinstance(labels, list):
            labels = [labels]
        cond = " or ".join(f'text()="{label}"' for label in labels)
        bonus = doc.xpath(f"//tr/td[{cond}]/following-sibling::td[1]/text()")
        if bonus:
            ins.bonus = StringUtils.str_float(bonus[0].strip())
