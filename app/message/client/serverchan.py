from serverchan_sdk import sc_send

from app.message.client._base import _IMessageClient
from app.utils import ExceptionUtils


class ServerChan(_IMessageClient):
    schema = "serverchan"

    _sckey = None
    _client_config = {}

    def __init__(self, config):
        self._client_config = config
        self.init_config()

    def init_config(self):
        if self._client_config:
            self._sckey = self._client_config.get('sckey')

    @classmethod
    def match(cls, ctype):
        return True if ctype == cls.schema else False

    def send_msg(self, title, text="", image="", url="", user_id=""):
        """
        发送ServerChan消息
        :param title: 消息标题
        :param text: 消息内容
        :param image: 图片URL地址
        :param url: 链接URL
        :param user_id: 未使用
        """
        
        if not title and not text:
            return False, "标题和内容不能同时为空"
        if not self._sckey:
            return False, "参数未配置"
        try:
            # 格式化消息内容，支持Markdown
            formatted_text = self._format_message_content(text, image, url)
            ret_json = sc_send(self._sckey, title, formatted_text, {"tags": "NASTOOL"})
            errno = ret_json.get('code')
            error = ret_json.get('message')
            if errno == 0:
                return True, error
            else:
                return False, error
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)

    def _format_message_content(self, text, image="", url=""):
        """
        格式化消息内容，支持Markdown格式
        :param text: 原始消息内容
        :param image: 图片URL
        :param url: 链接URL
        :return: 格式化后的消息内容
        """
        formatted_content = []
        
        # 添加文本内容
        if text:
            # 确保换行符正确显示
            formatted_text = text.replace("\n\n", "\n\n").replace("\n", "\n\n")
            formatted_content.append(formatted_text)
        
        # 添加图片（如果有）
        if image:
            formatted_content.append("")  # 空行分隔
            formatted_content.append(f"![封面图片]({image})")
        
        # 添加链接（如果有）
        if url:
            formatted_content.append("")  # 空行分隔
            formatted_content.append(f"[查看详情]({url})")
        
        return "\n\n".join(formatted_content)
    
    def send_list_msg(self, medias: list, user_id="", title="", **kwargs):
        """
        发送列表类消息
        :param medias: 媒体信息列表
        :param user_id: 未使用
        :param title: 消息标题
        """
        
        if not self._sckey:
            return False, "参数未配置"
        
        if not isinstance(medias, list) or not medias:
            return False, "数据错误或为空"
        
        try:
            # 构建列表消息内容
            content_parts = []
            
            # 添加第一个媒体的封面图片
            first_media = medias[0]
            if hasattr(first_media, 'get_message_image'):
                image_url = first_media.get_message_image()
                if image_url:
                    content_parts.append(f"![封面图片]({image_url})")
                    content_parts.append("")  # 空行分隔
            
            # 添加媒体列表
            for index, media in enumerate(medias, 1):
                media_info = []
                
                # 媒体标题和类型
                if hasattr(media, 'get_title_string'):
                    media_title = media.get_title_string()
                    media_info.append(f"**{index}. {media_title}**")
                
                # 媒体类型和评分
                type_info = []
                if hasattr(media, 'get_type_string'):
                    type_info.append(media.get_type_string())
                if hasattr(media, 'get_vote_string') and media.get_vote_string():
                    type_info.append(media.get_vote_string())
                
                if type_info:
                    media_info.append(f"*{', '.join(type_info)}*")
                
                # 详情链接
                if hasattr(media, 'get_detail_url') and media.get_detail_url():
                    media_info.append(f"[查看详情]({media.get_detail_url()})")
                
                content_parts.append("\n\n".join(media_info))
            
            formatted_content = "\n\n---\n\n".join(content_parts)
            
            ret_json = sc_send(self._sckey, title or "媒体推荐", formatted_content, {"tags": "NASTOOL"})
            errno = ret_json.get('code')
            error = ret_json.get('message')
            if errno == 0:
                return True, error
            else:
                return False, error
        except Exception as msg_e:
            ExceptionUtils.exception_traceback(msg_e)
            return False, str(msg_e)
