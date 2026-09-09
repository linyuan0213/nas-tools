import copy
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from app.plugin_framework.builtin_plugins.autosignin.backend.handlers._browser import BrowserSigninHandler
from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.base import SiteSigninContext
from app.plugin_framework.builtin_plugins.autosignin.backend.registry import HandlerRegistry
from app.utils.browser_mode import get_chrome_server_url

_BROWSER_FALLBACK_RE = re.compile(
    r"slg-bg|slg-box|雷池|安全拦截|challenge|cf-browser|Checking your browser|验证您不是机器人|DDoS",
    re.IGNORECASE,
)


def _should_browser_fallback(msg: str) -> bool:
    """判断 HTTP 签到失败是否需要回退到浏览器模式（HTML/403/468/雷池 WAF）"""
    if not msg:
        return False
    if "403 Forbidden" in msg or "403" in msg and "Forbidden" in msg:
        return True
    if "468" in msg:
        return True
    if any(tag in msg for tag in ["<!DOCTYPE", "<html", "<HTML"]):
        return True
    if _BROWSER_FALLBACK_RE.search(msg):
        return True
    return False


class SigninEngine:
    def __init__(self, ctx, registry: HandlerRegistry, site_cache=None, site_engine=None):
        self.ctx = ctx
        self._registry = registry
        self._site_cache = site_cache
        self._site_engine = site_engine

    def run(self, config: dict, get_history, update_history, delete_history):
        sign_sites_cfg = config.get("sign_sites", [])
        special_sites = config.get("special_sites") or []
        browser_sites = config.get("browser_sites") or []
        retry_keyword = config.get("retry_keyword")
        queue_cnt = config.get("queue_cnt", 10)
        notify = config.get("notify", False)

        today = datetime.today()
        yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        delete_history(yesterday_str)

        today_str = today.strftime("%Y-%m-%d")
        today_history = get_history(key=today_str)

        if not today_history:
            sign_sites = sign_sites_cfg
            self.ctx.info(f"今日 {today_str} 未签到，开始签到已选站点")
        else:
            retry_sites_hist = today_history.get("retry", [])
            already_sign_sites = today_history.get("sign", [])
            no_sign_sites = [s for s in sign_sites_cfg if s not in already_sign_sites]
            sign_sites = list(set(retry_sites_hist + no_sign_sites + special_sites))
            if sign_sites:
                self.ctx.info(f"今日 {today_str} 已签到，开始重签重试站点、特殊站点、未签站点")
            else:
                self.ctx.info(f"今日 {today_str} 已签到，无重新签到站点，本次任务结束")
                return

        browser_set = set(str(s) for s in browser_sites)
        sign_sites = copy.deepcopy(self._site_cache.get_sites(siteids=sign_sites))  # type: ignore
        if not sign_sites:
            self.ctx.info("没有可签到站点，停止运行")
            return

        new_sign_sites = []
        for site in sign_sites:
            if site.get("public"):
                self.ctx.info(f"站点 {site.get('name')} 是BT站点，跳过签到")
                continue
            if str(site.get("id")) in browser_set or str(site.get("id", "")) in browser_set:
                site["is_browser"] = True
            new_sign_sites.append(site)

        sign_sites = new_sign_sites
        if not sign_sites:
            self.ctx.info("没有可签到站点（已过滤BT站点），停止运行")
            return

        self.ctx.info("开始执行签到任务")
        with ThreadPoolExecutor(min(len(sign_sites), int(queue_cnt) if queue_cnt else 10)) as p:
            status = list(p.map(self._signin_site, sign_sites))

        if status:
            self._process_results(
                status,
                sign_sites_cfg,
                special_sites,
                retry_keyword,
                notify,
                today_str,
                get_history,
                update_history,
            )

    def _signin_site(self, site_info: dict) -> str:
        site_ctx = SiteSigninContext.from_site_info(site_info, self._site_engine)
        self.ctx.debug(
            f"开始处理站点 {site_ctx.site} (输入id={site_info.get('id')}, "
            f"解析site_id={site_ctx.site_id}, url={site_ctx.site_url}, "
            f"browser={site_ctx.is_browser})"
        )
        dedicated = self._registry.get(site_ctx.site_id)
        handler_name = dedicated.__name__ if dedicated else "无"
        self.ctx.debug(f"站点 {site_ctx.site} 命中 handler: {handler_name}")

        handler = None
        if dedicated:
            handler = dedicated()
        elif site_ctx.is_browser:
            # 配置了浏览器自动化且无专用 handler → 直接走浏览器自动化，
            # 避免 HTTP 过盾失败返回 WAF 页面而误报签到失败
            self.ctx.debug(f"站点 {site_ctx.site} 配置浏览器自动化，直接使用浏览器签到")
            handler = self._registry.get_browser()()
        else:
            fallback = self._registry.get_fallback(site_ctx.site_id)
            if fallback:
                self.ctx.debug(f"站点 {site_ctx.site} 未命中专用配置，使用通用 HTTP 兜底")
                handler = fallback()
            if not handler:
                handler = self._registry.get_generic()()

        used_browser = getattr(handler, "site_id", "") == BrowserSigninHandler.site_id

        try:
            result = handler.signin(site_ctx)
            self.ctx.debug(f"站点 {site_ctx.site} 结果: {result.msg}")
            msg = result.msg or ""
            if not used_browser and _should_browser_fallback(msg) and get_chrome_server_url():
                self.ctx.info(f"站点 {site_ctx.site} HTTP 签到疑似需要浏览器，自动回退")
                br_ctx = SiteSigninContext.from_site_info(site_info, self._site_engine)
                br_ctx.is_browser = True
                return self._signin_with_browser_fallback(br_ctx)
            return msg
        except Exception as e:
            self.ctx.warn(f"站点 {site_ctx.site} 签到异常: {e}")
            # 异常也可能是浏览器相关（403/Cloudflare），尝试回退
            if not used_browser and _should_browser_fallback(str(e)) and get_chrome_server_url():
                self.ctx.info(f"站点 {site_ctx.site} 异常疑似需要浏览器，自动回退")
                br_ctx = SiteSigninContext.from_site_info(site_info, self._site_engine)
                br_ctx.is_browser = True
                return self._signin_with_browser_fallback(br_ctx)
            return f"[{site_ctx.site}]签到失败：{str(e)}"

    def _signin_with_browser_fallback(self, site_ctx: SiteSigninContext) -> str:
        try:
            br_handler = self._registry.get_browser()()
            result = br_handler.signin(site_ctx)
            self.ctx.debug(f"站点 {site_ctx.site} 浏览器回退结果: {result.msg}")
            return result.msg
        except Exception as e:
            self.ctx.warn(f"站点 {site_ctx.site} 浏览器回退异常: {e}")
            return f"[{site_ctx.site}]签到失败：{str(e)}"

    def _process_results(
        self, status, sign_sites_cfg, special_sites, retry_keyword, notify, today_str, get_history, update_history
    ):
        self.ctx.info("站点签到任务完成！")
        retry_sites: list = []
        retry_msg: list = []
        login_success_msg: list = []
        sign_success_msg: list = []
        already_sign_msg: list = []
        fz_sign_msg: list = []
        failed_msg: list = []

        sites_map = {site.get("name"): site.get("id") for site in self._site_cache.get_site_dict()}  # type: ignore
        for s in status:
            if not s:
                continue
            # 站点未到开放签到时间（如 U2 仅 9 点后）：不统计为失败、不通知、不重试
            if re.search(r"9点(?:前|后开放)|9:00后", s):
                self.ctx.debug(f"{s}，跳过本次统计，等待后续调度补签")
                continue
            if "登录成功" in s:
                login_success_msg.append(s)
            elif "浏览器签到成功" in s:
                fz_sign_msg.append(s)
            elif "签到成功" in s:
                sign_success_msg.append(s)
            elif "已签到" in s:
                already_sign_msg.append(s)
            else:
                failed_msg.append(s)
                site_names = re.findall(r"\[(.*?)\]", s)
                if site_names:
                    site_id = sites_map.get(site_names[0])
                    if site_id and (not retry_keyword or re.search(retry_keyword, s)):
                        self.ctx.debug(f"站点 {site_names[0]} 加入重试列表")
                        retry_sites.append(str(site_id))
                        retry_msg.append(s)

        id_to_name = {str(site.get("id")): site.get("name") for site in self._site_cache.get_site_dict()}  # type: ignore
        retry_names = [id_to_name.get(str(sid), sid) for sid in retry_sites]
        failed_detail = "\n".join(failed_msg + retry_msg) or "无"

        def _extract_site_ids(messages: list[str]) -> list[str]:
            ids: list[str] = []
            for msg in messages:
                names = re.findall(r"\[(.*?)\]", msg)
                if names:
                    sid = sites_map.get(names[0])
                    if sid:
                        ids.append(str(sid))
            return ids

        sign_sites = _extract_site_ids(sign_success_msg + already_sign_msg + login_success_msg + fz_sign_msg)
        sign_sites = list(set(sign_sites))

        self.ctx.debug(
            f"签到结果统计: 成功={len(sign_success_msg)}, 已签={len(already_sign_msg)}, "
            f"登录={len(login_success_msg)}, 浏览器={len(fz_sign_msg)}, 失败={len(failed_msg)}, 重试={len(retry_sites)}"
        )
        self.ctx.debug(f"失败详情:\n{failed_detail}")
        self.ctx.debug(f"下次签到重试站点 {retry_names}")

        today_history = get_history(key=today_str) or {}
        # 合并历史已签名单：多次调度（0/8/16点）各自只处理重试+未签站点，
        # 不能只用本次成功项覆盖，否则某一轮无成功项会把已签记录清空导致下轮全站重签
        prev_sign = set((today_history.get("sign") or []) if isinstance(today_history.get("sign"), list) else [])
        sign_sites = sorted(set(sign_sites) | prev_sign)
        today_history.update({"sign": sign_sites, "retry": retry_sites, "names": id_to_name})
        update_history(today_str, today_history)

        if notify:
            signin_message = login_success_msg + sign_success_msg + already_sign_msg + fz_sign_msg + failed_msg
            if retry_msg:
                signin_message.append("——————命中重试—————")
                signin_message += retry_msg
            self.ctx._message.send_site_signin_message(signin_message)

            self.ctx.notify(
                title="[自动签到任务完成]",
                text=f"本次签到数量: {len(status)} \n"
                f"命中重试数量: {len(retry_sites)} \n"
                f"强制签到数量: {len(special_sites)} \n"
                f"下次签到数量: {len(set(retry_sites + special_sites))} \n"
                f"详见签到消息",
            )
