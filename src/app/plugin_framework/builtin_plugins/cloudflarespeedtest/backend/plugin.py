"""
CloudflareSpeedTest Plugin v2
测试 Cloudflare CDN 延迟和速度，自动优选IP
"""

import ipaddress
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import zipfile
from pathlib import Path

import log
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.plugin_framework.context import PluginContext
from app.utils import IpUtils, SystemUtils
from app.utils.config_tools import get_proxies


def _safe_extractall(tar, path):
    base = os.path.realpath(path)
    safe_members = []
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(base, member.name))
        if not target.startswith(base + os.sep):
            continue
        safe_members.append(member)
    # Python 3.11 不支持 filter 参数；已通过 members 过滤危险路径
    tar.extractall(path, members=safe_members)  # nosec B202


def _safe_zip_extractall(zip_ref, path):
    base = os.path.realpath(path)
    safe_members = []
    for member in zip_ref.namelist():
        target = os.path.realpath(os.path.join(base, member))
        if not target.startswith(base + os.sep):
            continue
        safe_members.append(member)
    # Python 3.11 不支持 filter 参数；已通过 namelist 过滤危险路径
    zip_ref.extractall(path, members=safe_members)  # nosec B202


class CloudflareSpeedTestPlugin:
    """Cloudflare IP优选插件"""

    # Cloudflare 官方 IPv4 段 (https://www.cloudflare.com/ips-v4)
    _CF_CIDRS = [
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
    ]

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx
        self._release_prefix = "https://github.com/XIU2/CloudflareSpeedTest/releases/download"
        self._binary_name = "cfst"
        self._CF_NETWORKS = [ipaddress.ip_network(c) for c in self._CF_CIDRS]

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("Cloudflare IP优选插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("Cloudflare IP优选插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行优选"""
        self.ctx.info("手动触发Cloudflare IP优选")
        self._do_speedtest(manual=True)

    def _start_service(self):
        config = self._get_config()
        cron = config.get("cron")

        if not cron:
            return

        if cron:
            self.ctx.info(f"Cloudflare CDN优选服务启动，周期：{cron}")
            self.ctx.schedule_cron("speedtest", self._do_speedtest, cron=str(cron))

    def _stop_service(self):
        try:
            self.ctx.remove_schedule("speedtest")
            self.ctx.remove_schedule("speedtest_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")

    def _do_speedtest(self, manual=False):
        config = self._get_config()
        if not config.get("cron") and not manual:
            return
        cf_ip = config.get("cf_ip")
        ipv4 = config.get("ipv4", True)
        ipv6 = config.get("ipv6", False)
        re_install = config.get("re_install", False)
        additional_args = config.get("additional_args", "")
        notify = config.get("notify", False)
        check = config.get("check", False)

        if not cf_ip:
            self.ctx.error("未配置优选IP")
            return

        if not ipv4 and not ipv6:
            ipv4 = True
            self.ctx.warn("未指定ip类型，默认ipv4")

        cf_path = self.ctx.data_dir
        cf_ipv4 = os.path.join(cf_path, "ip.txt")
        cf_ipv6 = os.path.join(cf_path, "ipv6.txt")
        result_file = os.path.join(cf_path, "result_hosts.txt")

        # 获取自定义Hosts插件配置
        customhosts_config = self._get_customhosts_config()
        if not customhosts_config or not customhosts_config.get("hosts"):
            self.ctx.error("Cloudflare CDN优选依赖于自定义Hosts，请先维护hosts")
            return

        # 校正优选ip
        if check:
            cf_ip = self._check_cf_ip(customhosts_config.get("hosts", []), cf_ip)

        err_flag, release_version = self._check_environment(cf_path, re_install)
        if err_flag and release_version:
            self.ctx.set_config("version", release_version)

        if not err_flag:
            self.ctx.error("环境检查失败，停止运行")
            return

        # 执行优选
        self.ctx.info("正在进行Cloudflare CDN优选，请耐心等待")
        cf_command = [f"./{self._binary_name}"]
        if additional_args:
            cf_command.extend(additional_args.split())
        cf_command.extend(["-o", result_file])
        if ipv4:
            cf_command.extend(["-f", cf_ipv4])
        if ipv6:
            cf_command.extend(["-f", cf_ipv6])

        try:
            subprocess.run(cf_command, cwd=cf_path, check=True)  # nosec B603
        except subprocess.CalledProcessError as e:
            self.ctx.error(f"CloudflareSpeedTest执行失败: {e}")
            return

        # 获取最优ip
        try:
            with open(result_file) as f:
                lines = f.readlines()
                if len(lines) >= 2:
                    best_ip = lines[1].strip().split(",")[0]
                else:
                    self.ctx.error("结果文件格式不正确")
                    return
        except Exception as e:
            self.ctx.error(f"获取最优IP失败: {e}")
            return

        self.ctx.info(f"获取到最优ip==>[{best_ip}]")

        if not (IpUtils.is_ipv4(best_ip) or IpUtils.is_ipv6(best_ip)):
            self.ctx.error("获取到最优ip格式错误")
            return

        if best_ip == cf_ip:
            self.ctx.info("CloudflareSpeedTest CDN优选ip未变，不做处理")
            return

        # 替换自定义Hosts插件配置
        hosts = customhosts_config.get("hosts", [])
        if isinstance(hosts, str):
            hosts = hosts.split("\n")

        new_hosts = []
        replaced = 0
        skipped_non_cf = []
        for host in hosts:
            if host and host != "\n":
                host_arr = str(host).split()
                if host_arr and host_arr[0] == cf_ip:
                    domain = host_arr[1] if len(host_arr) > 1 else ""
                    if domain and not self._is_cloudflare_domain(domain):
                        new_hosts.append(host)
                        skipped_non_cf.append(domain)
                        continue
                    new_hosts.append(host.replace(cf_ip, best_ip))
                    replaced += 1
                else:
                    new_hosts.append(host)

        if skipped_non_cf:
            self.ctx.warn(f"以下域名非 Cloudflare 托管，已跳过替换（避免 SSL 握手失败）：{', '.join(skipped_non_cf)}")

        if replaced == 0:
            self.ctx.warn(
                f"自定义Hosts中未找到与当前优选IP [{cf_ip}] 匹配且属于 Cloudflare 的行，未替换。"
                f"请确认Hosts中的IP与优选IP一致，或开启「自动校准」"
            )
            self.ctx.set_config("cf_ip", best_ip)
            return

        self._update_customhosts_config(
            {
                "hosts": "\n".join(h.rstrip("\n") for h in new_hosts),
                "err_hosts": customhosts_config.get("err_hosts"),
                "enable": customhosts_config.get("enable", False),
            }
        )

        old_ip = cf_ip
        self.ctx.set_config("cf_ip", best_ip)
        self.ctx.info(f"Cloudflare CDN优选ip [{best_ip}] 已替换 {replaced} 条自定义Hosts记录")

        if notify:
            self.ctx.notify(title="[Cloudflare优选任务完成]", text=f"原ip：{old_ip}\n新ip：{best_ip}")

    def _get_customhosts_config(self):
        try:
            config = self.ctx.get_plugin_config("customhosts")
            if config:
                return config
        except Exception as e:
            self.ctx.error(f"获取CustomHosts配置失败: {e}")
        return None

    def _update_customhosts_config(self, config):
        try:
            self.ctx.set_plugin_config("customhosts", config)
        except Exception as e:
            self.ctx.error(f"更新CustomHosts配置失败: {e}")

    def _is_cloudflare_domain(self, domain: str) -> bool:
        """通过真实DNS解析判断域名是否 Cloudflare 托管。

        customhosts 使用应用层映射，socket 解析返回真实 DNS IP，
        据此判断该域名是否落在 Cloudflare IP 段内。
        """
        try:
            real_ip = socket.getaddrinfo(domain, 443)[0][4][0]
        except Exception:
            self.ctx.debug(f"域名 {domain} 解析失败，默认按 Cloudflare 处理")
            return True
        try:
            ip_obj = ipaddress.ip_address(real_ip)
        except ValueError:
            return True
        for net in self._CF_NETWORKS:
            if ip_obj in net:
                return True
        return False

    def _check_cf_ip(self, hosts, cf_ip):
        """校正cf优选ip"""
        if isinstance(hosts, str):
            hosts = hosts.split("\n")
        ip_count = {}
        for host in hosts:
            if not host or not host.strip():
                continue
            ip = host.split()[0]
            ip_count[ip] = ip_count.get(ip, 0) + 1

        max_ips = []
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        if len(max_ips) != 1:
            return cf_ip

        if max_ips[0] != cf_ip:
            self.ctx.info(f"获取到自定义hosts插件中ip {max_ips[0]} 出现次数最多，已自动校正优选ip")
            return max_ips[0]
        return cf_ip

    def _check_environment(self, cf_path, re_install):
        install_flag = False
        if re_install:
            install_flag = True
            try:
                shutil.rmtree(cf_path)
                self.ctx.info(f"删除CloudflareSpeedTest目录 {cf_path}，开始重新安装")
            except Exception as e:
                self.ctx.error(f"删除目录失败: {e}")
                return False, None

        cf_path_obj = Path(cf_path)
        if not cf_path_obj.exists():
            try:
                cf_path_obj.mkdir(parents=True)
            except Exception as e:
                self.ctx.error(f"创建目录失败: {e}")
                return False, None

        release_version = self._get_release_version()
        config = self._get_config()
        version = config.get("version")

        if not release_version:
            if Path(f"{cf_path}/{self._binary_name}").exists():
                self.ctx.warn("获取版本失败，存在可执行版本，继续运行")
                return True, None
            elif version:
                release_version = version
                install_flag = True
            else:
                release_version = "v2.3.4"
                install_flag = True

        if not install_flag and release_version != version:
            self.ctx.info(f"检测到有新版本[{release_version}]，开始安装")
            install_flag = True

        if not install_flag and not Path(f"{cf_path}/{self._binary_name}").exists():
            install_flag = True

        if not install_flag:
            self.ctx.info("无新版本，继续运行")
            return True, None

        if SystemUtils.is_windows():
            self.ctx.error("暂不支持windows平台")
            return False, None
        elif SystemUtils.is_macos():
            machine = platform.machine().lower()
            arch = "amd64" if machine in ("x86_64", "amd64") else "arm64"
            cf_file_name = f"cfst_darwin_{arch}.zip"
            download_url = f"{self._release_prefix}/{release_version}/{cf_file_name}"
            return self._os_install(cf_path, download_url, cf_file_name, release_version, "zip")
        else:
            machine = platform.machine().lower()
            arch = "amd64" if machine in ("x86_64", "amd64") else "arm64"
            cf_file_name = f"cfst_linux_{arch}.tar.gz"
            download_url = f"{self._release_prefix}/{release_version}/{cf_file_name}"
            return self._os_install(cf_path, download_url, cf_file_name, release_version, "tar")

    def _os_install(self, cf_path, download_url, cf_file_name, release_version, archive_type):
        if not Path(f"{cf_path}/{cf_file_name}").exists():
            proxies = get_proxies()
            proxy_url = proxies.get("https") if proxies and proxies.get("https") else None
            try:
                response = HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=30)).get(download_url)
                response.raise_for_status()
                with open(f"{cf_path}/{cf_file_name}", "wb") as f:
                    f.write(response.content)
            except Exception as e:
                self.ctx.error(f"下载安装包失败: {e}")
                return False, None

        if Path(f"{cf_path}/{cf_file_name}").exists():
            try:
                archive_path = f"{cf_path}/{cf_file_name}"
                if archive_type == "zip":
                    with zipfile.ZipFile(archive_path, "r") as zip_ref:
                        _safe_zip_extractall(zip_ref, cf_path)  # nosec B202
                elif archive_type == "tar":
                    with tarfile.open(archive_path, "r:gz") as tar_ref:
                        _safe_extractall(tar_ref, cf_path)  # nosec B202

                Path(f"{cf_path}/{self._binary_name}").chmod(0o755)
                Path(f"{cf_path}/{cf_file_name}").unlink()
                if Path(f"{cf_path}/{self._binary_name}").exists():
                    self.ctx.info(f"安装成功，当前版本：{release_version}")
                    return True, release_version
                else:
                    self.ctx.error("安装失败")
                    shutil.rmtree(cf_path)
                    return False, None
            except Exception as err:
                if Path(f"{cf_path}/{self._binary_name}").exists():
                    self.ctx.error(f"安装失败：{err}，继续使用现版本")
                    return True, None
                else:
                    self.ctx.error(f"安装失败：{err}")
                    shutil.rmtree(cf_path)
                    return False, None
        return False, None

    @staticmethod
    def _get_release_version():
        proxies = get_proxies()
        proxy_url = proxies.get("http") if proxies else None
        try:
            res = HttpClient(config=HttpClientConfig(proxy_url=proxy_url)).get(
                "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest"
            )
            ver_json = res.json()
            return f"{ver_json['tag_name']}"
        except Exception:
            return None
