import base64

from app.helper import ProgressHelper, OcrHelper
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import StringUtils, RequestUtils
from app.utils.commons import SingletonMeta


class SiteCookie(metaclass=SingletonMeta):
    progress = None
    sites = None
    siteconf = None
    ocrhelper = None
    captcha_code = {}

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.progress = ProgressHelper()
        self.sites = Sites()
        self.siteconf = SiteConf()
        self.ocrhelper = OcrHelper()
        self.captcha_code = {}

    def set_code(self, code, value):
        """
        设置验证码的值
        """
        self.captcha_code[code] = value

    def get_code(self, code):
        """
        获取验证码的值
        """
        return self.captcha_code.get(code)

    def get_captcha_text(self, chrome, code_url):
        """
        识别验证码图片的内容
        """
        code_b64 = self.get_captcha_base64(chrome=chrome,
                                           image_url=code_url)
        if not code_b64:
            return ""
        return self.ocrhelper.get_captcha_text(image_b64=code_b64)

    @staticmethod
    def __get_captcha_url(siteurl, imageurl):
        """
        获取验证码图片的URL
        """
        if not siteurl or not imageurl:
            return ""
        if imageurl.startswith("/"):
            imageurl = imageurl[1:]
        return "%s/%s" % (StringUtils.get_base_url(siteurl), imageurl)

    @staticmethod
    def get_captcha_base64(chrome, image_url):
        """
        根据图片地址，使用浏览器获取验证码图片base64编码
        """
        if not image_url:
            return ""
        ret = RequestUtils(headers=chrome.get_ua(),
                           cookies=chrome.get_cookies()).get_res(image_url)
        if ret:
            return base64.b64encode(ret.content).decode()
        return ""
