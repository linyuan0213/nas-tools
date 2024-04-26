import pickle
from app.utils import RedisStore


class RedisQueue:
    r = None
    queue_name = None
    size = None

    def __init__(self) -> None:
        self.r = RedisStore()
        self.queue_name = 'scheduler_queue'
        self.size = 0

    def put(self, element: dict) -> None:
        element_str = pickle.dumps(element)
        self.r.lpush(self.queue_name, element_str)
        self.size = self.size + 1

    def get(self) -> dict:
        element_str = self.r.rpop(self.queue_name)
        self.size = self.size - 1
        if element_str:
            return pickle.loads(element_str)
        return None

    def clear(self) -> None:
        self.r.delete(self.queue_name)

    def qsize(self):
        return self.size


scheduler_queue = RedisQueue()
