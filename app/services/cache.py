from redis.asyncio import Redis

class Coordination:
    def __init__(self,redis:Redis): self.redis=redis
    async def acquire(self,key:str,ttl:int)->bool: return bool(await self.redis.set(key,"1",ex=ttl,nx=True))
    async def release(self,key:str): await self.redis.delete(key)
    async def enqueue(self,queue:str,payload:str): await self.redis.lpush(queue,payload)
    async def dequeue_reliably(self, queue: str, processing_queue: str, timeout: int = 10):
        return await self.redis.brpoplpush(queue, processing_queue, timeout=timeout)
    async def acknowledge(self, processing_queue: str, payload: str):
        await self.redis.lrem(processing_queue, 1, payload)
    async def recover_processing(self, processing_queue: str, queue: str):
        payloads = await self.redis.lrange(processing_queue, 0, -1)
        if not payloads:
            return
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(processing_queue)
            pipe.rpush(queue, *payloads)
            await pipe.execute()
    async def heartbeat(self, service: str, ttl: int):
        await self.redis.set(f"heartbeat:{service}", "1", ex=ttl)

    async def enabled_chains(self, fallback: tuple[str, ...]) -> tuple[str, ...]:
        raw = await self.redis.get("config:enabled_chains")
        if not raw:
            return fallback
        chains = tuple(item.strip().lower() for item in str(raw).split(",") if item.strip())
        allowed = {"solana", "ethereum", "bsc", "base"}
        cleaned = tuple(item for item in chains if item in allowed)
        return cleaned or fallback

    async def set_enabled_chains(self, chains: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        cleaned = tuple(item for item in chains if item in {"solana", "ethereum", "bsc", "base"})
        if not cleaned:
            cleaned = ("solana",)
        await self.redis.set("config:enabled_chains", ",".join(cleaned))
        return cleaned
