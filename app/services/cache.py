from redis.asyncio import Redis

class Coordination:
    def __init__(self,redis:Redis): self.redis=redis
    async def acquire(self,key:str,ttl:int)->bool: return bool(await self.redis.set(key,"1",ex=ttl,nx=True))
    async def release(self,key:str): await self.redis.delete(key)
    async def enqueue(self,queue:str,payload:str): await self.redis.rpush(queue,payload)
    async def dequeue_reliably(self, queue: str, processing_queue: str, timeout: int = 10):
        return await self.redis.brpoplpush(queue, processing_queue, timeout=timeout)
    async def acknowledge(self, processing_queue: str, payload: str):
        await self.redis.lrem(processing_queue, 1, payload)
    async def recover_processing(self, processing_queue: str, queue: str):
        while payload := await self.redis.rpop(processing_queue):
            await self.redis.lpush(queue, payload)
    async def heartbeat(self, service: str, ttl: int):
        await self.redis.set(f"heartbeat:{service}", "1", ex=ttl)
