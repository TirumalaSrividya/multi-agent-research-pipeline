"""
Inter-agent message bus.

Two backends implement the same `MessageBus` interface:

  * `InMemoryMessageBus` - asyncio.Queue based, zero external deps. Used by
    default for `make run`, unit tests, and CI, so the whole pipeline works
    out of the box with no infrastructure.

  * `RedisStreamsMessageBus` - backed by Redis Streams + consumer groups.
    Used when BUS_BACKEND=redis (docker-compose default for the "distributed"
    profile). This is what lets each agent run as a genuinely independent
    OS process / container, per requirement #1: agents publish/consume
    exclusively through XADD / XREADGROUP / XACK, with no direct calls
    between agent classes.

Both backends expose:
    publish(stream, message: dict) -> str            # returns message id
    consume(stream, group, consumer) -> AsyncIterator[(msg_id, dict)]
    ack(stream, group, msg_id) -> None
"""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

logger = logging.getLogger("bus")


class MessageBus(abc.ABC):
    @abc.abstractmethod
    async def publish(self, stream: str, message: dict) -> str: ...

    @abc.abstractmethod
    async def consume(self, stream: str, group: str, consumer: str) -> AsyncIterator[tuple[str, dict]]: ...

    @abc.abstractmethod
    async def ack(self, stream: str, group: str, msg_id: str) -> None: ...

    @abc.abstractmethod
    async def ensure_group(self, stream: str, group: str) -> None: ...

    async def close(self) -> None:
        return None


# --------------------------------------------------------------------------- #
# In-memory backend
# --------------------------------------------------------------------------- #
class InMemoryMessageBus(MessageBus):
    """A minimal pub/sub-over-queues implementation. Each (stream, group)
    pair gets its own asyncio.Queue so multiple consumer groups can read the
    same stream independently, mirroring Redis Streams semantics closely
    enough for local development and tests."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], asyncio.Queue] = {}
        self._pending: dict[str, dict] = {}  # msg_id -> message, for ack bookkeeping
        self._lock = asyncio.Lock()

    def _queue(self, stream: str, group: str) -> asyncio.Queue:
        key = (stream, group)
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
        return self._queues[key]

    async def ensure_group(self, stream: str, group: str) -> None:
        self._queue(stream, group)

    async def publish(self, stream: str, message: dict) -> str:
        msg_id = str(uuid.uuid4())
        payload = {"id": msg_id, "data": message}
        async with self._lock:
            # fan the message out to every consumer group already registered
            # on this stream (mirrors Redis Streams: all groups see all msgs)
            targets = [k for k in self._queues if k[0] == stream]
            if not targets:
                targets = [(stream, "__default__")]
        for key in targets:
            await self._queues.setdefault(key, asyncio.Queue()).put(payload)
        logger.debug("published to %s: %s", stream, message.get("type", "?"))
        return msg_id

    async def consume(self, stream: str, group: str, consumer: str) -> AsyncIterator[tuple[str, dict]]:
        q = self._queue(stream, group)
        while True:
            payload = await q.get()
            yield payload["id"], payload["data"]

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        # queue-based bus has nothing to ack against; no-op kept for symmetry
        return None


# --------------------------------------------------------------------------- #
# Redis Streams backend
# --------------------------------------------------------------------------- #
class RedisStreamsMessageBus(MessageBus):
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # imported lazily so InMemory works without the dep

        self._redis = redis.from_url(url, decode_responses=True)
        self._consumer_created_groups: set[tuple[str, str]] = set()

    async def ensure_group(self, stream: str, group: str) -> None:
        key = (stream, group)
        if key in self._consumer_created_groups:
            return
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:  # BUSYGROUP if it already exists
            if "BUSYGROUP" not in str(exc):
                raise
        self._consumer_created_groups.add(key)

    async def publish(self, stream: str, message: dict) -> str:
        msg_id = await self._redis.xadd(stream, {"data": json.dumps(message)})
        logger.debug("published to %s: %s", stream, message.get("type", "?"))
        return msg_id

    async def consume(self, stream: str, group: str, consumer: str) -> AsyncIterator[tuple[str, dict]]:
        await self.ensure_group(stream, group)
        while True:
            resp = await self._redis.xreadgroup(group, consumer, {stream: ">"}, count=10, block=2000)
            if not resp:
                await asyncio.sleep(0.05)
                continue
            for _stream_name, entries in resp:
                for msg_id, fields in entries:
                    yield msg_id, json.loads(fields["data"])

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        await self._redis.xack(stream, group, msg_id)

    async def close(self) -> None:
        await self._redis.aclose()


def build_bus(backend: str, redis_url: str) -> MessageBus:
    if backend == "redis":
        return RedisStreamsMessageBus(redis_url)
    return InMemoryMessageBus()
