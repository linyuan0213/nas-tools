from typing import TypeVar

T = TypeVar("T", bound=type)
_registry: dict[str, type] = {}


def register(cls: T) -> T:
    if not hasattr(cls, "schema") or not cls.schema:
        raise ValueError(f"消息客户端类 {cls.__name__} 必须定义 schema")
    _registry[cls.schema] = cls
    return cls


def unregister(schema: str) -> None:
    """注销消息渠道类（插件卸载时调用）"""
    _registry.pop(schema, None)


def get_client_class(schema: str) -> type | None:
    return _registry.get(schema)


def get_all_clients() -> list[type]:
    return list(_registry.values())
