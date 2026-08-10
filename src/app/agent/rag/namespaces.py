"""知识域命名空间常量"""


class Namespace:
    """知识库命名空间"""

    MEDIA_LIBRARY = "media_library"
    MESSAGES = "messages"
    FAQ = "faq"
    OPERATIONS = "operations"

    @classmethod
    def all(cls) -> list[str]:
        return [cls.MEDIA_LIBRARY, cls.MESSAGES, cls.FAQ, cls.OPERATIONS]

    @classmethod
    def valid(cls, namespace: str) -> bool:
        return namespace in cls.all()
