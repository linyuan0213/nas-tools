import json
import httpx
from openai import Client
from app.utils import OpenAISessionCache
from app.utils.commons import SingletonMeta
from config import Config


class OpenAiHelper(metaclass=SingletonMeta):
    def __init__(self):
        self.client = None
        self.init_config()

    def init_config(self):
        """
        初始化 OpenAI 客户端配置，包括 API 密钥和代理设置
        """
        config = Config().get_config("openai")
        api_key = config.get("api_key")
        api_url = config.get("api_url")
        api_base = None
        if api_url:
            api_base = f"{api_url}/v1"

        proxy_conf = Config().get_proxies()
        proxy = proxy_conf.get("https")
        if api_key:
            self.client = Client(api_key=api_key, 
                                base_url=api_base,
                                http_client=httpx.Client(proxy=proxy),
            )
        
    def get_state(self):
        """
        检查客户端是否已初始化
        """
        return self.client is not None

    @staticmethod
    def __save_session(session_id, message):
        """
        保存会话
        :param session_id: 会话ID
        :param message: 消息
        :return:
        """
        seasion = OpenAISessionCache.get(session_id)
        if seasion:
            seasion.append({
                "role": "assistant",
                "content": message
            })
            OpenAISessionCache.set(session_id, seasion)

    @staticmethod
    def __get_session(session_id, message):
        """
        获取会话
        :param session_id: 会话ID
        :return: 会话上下文
        """
        session = OpenAISessionCache.get(session_id)
        if session:
            session.append({
                "role": "user",
                "content": message
            })
        else:
            session = [
                {
                    "role": "system",
                    "content": "请在接下来的对话中请使用中文回复，并且内容尽可能详细。"
                },
                {
                    "role": "user",
                    "content": message
                }]
            OpenAISessionCache.set(session_id, session)
        return session

    def __get_model(self, messages, prompt=None, user="NAStool", **kwargs):
        """
        调用 OpenAI 模型生成响应
        """
        if not isinstance(messages, list):
            if prompt:
                messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": messages},
                ]
            else:
                messages = [{"role": "user", "content": messages}]
        return self.client.chat.completions.create(
            model=Config().get_config("openai").get("api_model") or "gpt-3.5-turbo",
            user=user,
            messages=messages,
            **kwargs,
        )

    @staticmethod
    def __clear_session(session_id):
        """
        清除会话
        :param session_id: 会话ID
        :return:
        """
        if OpenAISessionCache.get(session_id):
            OpenAISessionCache.delete(session_id)

    def get_media_name(self, filename):
        """
        从文件名中提取媒体信息
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _filename_prompt = (
                "I will give you a movie/tv show file name. You need to return a JSON."
                "\nPay attention to correctly identifying the film name."
                "\n{\"title\":string,\"version\":string,\"part\":string,\"year\":string,\"resolution\":string,\"season\":number|null,\"episode\":number|null}"
            )
            completion = self.__get_model(prompt=_filename_prompt, messages=filename)
            result = completion.choices[0].message.content
            return json.loads(result)
        except Exception as e:
            print(f"Error: {str(e)} | Result: {result}")
            return {}

    def get_answer(self, text, userid):
        """
        获取对话答案
        """
        if not self.get_state():
            return ""
        try:
            if not userid:
                return "用户信息错误"
            userid = str(userid)

            if text == "#清除":
                self.__clear_session(userid)
                return "会话已清除"

            messages = self.__get_session(userid, text)
            completion = self.__get_model(messages=messages, user=userid)
            result = completion.choices[0].message.content

            if result:
                self.__save_session(userid, result)
            return result
        except Exception as e:
            return f"请求 OpenAI API 出现错误：{str(e)}"

    def translate_to_zh(self, text):
        """
        翻译文本为中文
        """
        if not self.get_state():
            return False, None

        system_prompt = (
            "You are a translation engine that can only translate text and cannot interpret it."
        )
        user_prompt = f"translate to zh-CN:\n\n{text}"
        try:
            completion = self.__get_model(
                prompt=system_prompt,
                messages=user_prompt,
                temperature=0,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
            )
            result = completion.choices[0].message.content.strip()
            return True, result
        except Exception as e:
            return False, str(e)

    def get_question_answer(self, question):
        """
        从问题及选项中获取答案
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _question_prompt = (
                "下面我们来玩一个游戏，你是老师，我是学生，你需要回答我的问题。"
                "我会给你一个题目和几个选项，你的回复必须是给定选项中正确答案对应的序号，请直接回复数字。"
            )
            completion = self.__get_model(prompt=_question_prompt, messages=question)
            result = completion.choices[0].message.content
            return result
        except Exception as e:
            return {}