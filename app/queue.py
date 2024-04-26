import pickle
from app.utils import RedisStore


class RedisQueue:
    r = None
    queue_name = None
    size = None

    def __init__(self) -> None:
        self.r = RedisStore()
        self.queue_name = 'scheduler:queue'

    def put(self, element: dict) -> None:
        element_str = pickle.dumps(element)
        self.r.lpush(self.queue_name, element_str)

    def get(self) -> dict:
        element_str = self.r.rpop(self.queue_name)
        if element_str:
            return pickle.loads(element_str)
        return None

    def clear(self) -> None:
        self.r.delete(self.queue_name)


scheduler_queue = RedisQueue()
