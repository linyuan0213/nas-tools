import json
from enum import Enum


class JsonUtils:

    @staticmethod
    def json_serializable(obj):
        """
        将普通对象转化为支持json序列化的对象
        @param obj: 待转化的对象
        @return: 支持json序列化的对象
        """

        def _try(o):
            if isinstance(o, Enum):
                return o.value
            try:
                return o.__dict__
            except Exception as err:
                print(str(err))
                return str(o)

        return json.loads(json.dumps(obj, default=lambda o: _try(o)))

    @staticmethod
    def is_valid_json(text):
        """
        判断是否是有效的json格式字符串
        """
        try:
            if not text:
                return False
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False

    @staticmethod
    def get_nested_value(data, keys):
        """
        递归地获取嵌套结构中指定字段的值
        """
        if isinstance(data, dict):
            key, *remaining_keys = keys.split('.', 1)
            if '[' in key and ']' in key:
                key, index = key.split('[')
                index = int(index[:-1])
                value = data.get(key, [])
                if isinstance(value, list):
                    value = value[index] if len(value) > index else None
                else:
                    value = None
            else:
                value = data.get(key)
            if remaining_keys:
                return JsonUtils.get_nested_value(value, remaining_keys[0])
            return value
        elif isinstance(data, list):
            index, *remaining_keys = keys.split('.', 1)
            index = int(index)
            value = data[index] if len(data) > index else None
            if remaining_keys:
                return JsonUtils.get_nested_value(value, remaining_keys[0])
            return value
        else:
            return None

    @staticmethod
    def get_json_object(json_str, field):
        try:
            # 解析 JSON 字符串
            json_data = json.loads(json_str)
            # 提取指定字段的值
            field_value = JsonUtils.get_nested_value(json_data, field)
            return field_value
        except json.JSONDecodeError as e:
            print("JSON 解析错误:", e)
            return None
        except Exception as e:
            print("发生错误:", e)
            return None
