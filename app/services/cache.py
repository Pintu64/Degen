from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import CoordKV, CoordQueue


class Coordination:
    """Locks, heartbeats, chain config, and the Telegram queue — Postgres only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def ping(self) -> bool:
        async with self.sessions() as session:
            await session.execute(select(1))
        return True

    async def _purge(self, session: AsyncSession) -> None:
        await session.execute(delete(CoordKV).where(CoordKV.expires_at.is_not(None), CoordKV.expires_at < self._now()))

    async def acquire(self, key: str, ttl: int) -> bool:
        expires = self._now() + timedelta(seconds=max(1, ttl))
        async with self.sessions() as session:
            await self._purge(session)
            try:
                session.add(CoordKV(key=key, value="1", expires_at=expires))
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    async def release(self, key: str) -> None:
        async with self.sessions() as session:
            await session.execute(delete(CoordKV).where(CoordKV.key == key))
            await session.commit()

    async def exists(self, key: str) -> bool:
        async with self.sessions() as session:
            await self._purge(session)
            value = await session.scalar(select(CoordKV.key).where(CoordKV.key == key))
            await session.commit()
            return value is not None

    async def heartbeat(self, service: str, ttl: int) -> None:
        key = f"heartbeat:{service}"
        expires = self._now() + timedelta(seconds=max(1, ttl))
        async with self.sessions() as session:
            stmt = insert(CoordKV).values(key=key, value="1", expires_at=expires)
            stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": "1", "expires_at": expires})
            await session.execute(stmt)
            await session.commit()

    async def alive(self, service: str) -> bool:
        return await self.exists(f"heartbeat:{service}")

    async def enqueue(self, queue: str, payload: str) -> None:
        async with self.sessions() as session:
            session.add(CoordQueue(queue=queue, payload=payload, status="pending"))
            await session.commit()

    async def dequeue_reliably(self, queue: str, processing_queue: str, timeout: int = 10):
        deadline = asyncio.get_event_loop().time() + max(0, timeout)
        while True:
            async with self.sessions() as session:
                row_id = await session.scalar(
                    select(CoordQueue.id)
                    .where(CoordQueue.queue == queue, CoordQueue.status == "pending")
                    .order_by(CoordQueue.id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row_id is not None:
                    await session.execute(update(CoordQueue).where(CoordQueue.id == row_id).values(status="processing", queue=processing_queue))
                    payload = await session.scalar(select(CoordQueue.payload).where(CoordQueue.id == row_id))
                    await session.commit()
                    return payload
                await session.rollback()
            if asyncio.get_event_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.4)

    async def acknowledge(self, processing_queue: str, payload: str) -> None:
        async with self.sessions() as session:
            row_id = await session.scalar(
                select(CoordQueue.id)
                .where(CoordQueue.queue == processing_queue, CoordQueue.payload == payload, CoordQueue.status == "processing")
                .limit(1)
            )
            if row_id is not None:
                await session.execute(delete(CoordQueue).where(CoordQueue.id == row_id))
            await session.commit()

    async def replace(self, processing_queue: str, old: str, new: str) -> None:
        async with self.sessions() as session:
            row_id = await session.scalar(
                select(CoordQueue.id)
                .where(CoordQueue.queue == processing_queue, CoordQueue.payload == old, CoordQueue.status == "processing")
                .limit(1)
            )
            if row_id is not None:
                await session.execute(update(CoordQueue).where(CoordQueue.id == row_id).values(payload=new))
            await session.commit()

    async def requeue(self, processing_queue: str, target: str, old: str, new: str) -> None:
        async with self.sessions() as session:
            row_id = await session.scalar(
                select(CoordQueue.id)
                .where(CoordQueue.queue == processing_queue, CoordQueue.payload == old, CoordQueue.status == "processing")
                .limit(1)
            )
            if row_id is not None:
                await session.execute(
                    update(CoordQueue).where(CoordQueue.id == row_id).values(queue=target, payload=new, status="pending")
                )
            await session.commit()

    async def recover_processing(self, processing_queue: str, queue: str) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(CoordQueue)
                .where(CoordQueue.queue == processing_queue, CoordQueue.status == "processing")
                .values(queue=queue, status="pending")
            )
            await session.commit()

    async def enabled_chains(self, fallback: tuple[str, ...]) -> tuple[str, ...]:
        async with self.sessions() as session:
            raw = await session.scalar(select(CoordKV.value).where(CoordKV.key == "config:enabled_chains"))
        if not raw:
            return fallback
        allowed = {"solana", "ethereum", "bsc", "base"}
        cleaned = tuple(item.strip().lower() for item in str(raw).split(",") if item.strip() in allowed)
        return cleaned or fallback

    async def set_enabled_chains(self, chains: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        cleaned = tuple(item for item in chains if item in {"solana", "ethereum", "bsc", "base"})
        if not cleaned:
            cleaned = ("solana",)
        value = ",".join(cleaned)
        async with self.sessions() as session:
            stmt = insert(CoordKV).values(key="config:enabled_chains", value=value, expires_at=None)
            stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value, "expires_at": None})
            await session.execute(stmt)
            await session.commit()
        return cleaned
