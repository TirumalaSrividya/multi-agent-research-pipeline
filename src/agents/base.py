"""
Abstract agent interface (requirement #6: ABC for the agent contract).

Every agent:
  * consumes messages from exactly one input stream
  * publishes results to exactly one output stream
  * never calls another agent directly - all communication is via the bus
  * implements only `process(message) -> dict`; retry/timeout/logging/
    tracing/ack handling live once, here, in `handle_one()`.

This is what "each agent runs as an independent process" means in practice:
an agent object has no reference to any other agent, only to the bus.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time

from ..config import settings
from ..message_bus import MessageBus


class AgentError(Exception):
    """Raised by an agent's process() to signal a recoverable failure that
    the supervisor's retry logic should catch."""


class AbstractAgent(abc.ABC):
    name: str = "agent"
    input_stream: str = ""
    output_stream: str = ""
    consumer_group: str = "workers"

    def __init__(self, bus: MessageBus, consumer_id: str | None = None) -> None:
        self.bus = bus
        self.consumer_id = consumer_id or f"{self.name}-{id(self)}"
        self.log = logging.getLogger(self.name)
        self.interactions = 0

    @abc.abstractmethod
    async def process(self, message: dict) -> dict:
        """Pure transformation: input message dict -> output message dict.
        Must raise AgentError (or let exceptions propagate) on failure;
        must not touch the bus directly."""
        raise NotImplementedError

    async def handle_one(self, message: dict, trace=None) -> dict:
        """Runs process() with retry + exponential backoff. Used directly by
        the in-process orchestrator, and by the standalone worker loop
        below for distributed/Redis mode."""
        last_exc: Exception | None = None
        for attempt in range(1, settings.max_agent_retries + 1):
            start = time.monotonic()
            try:
                result = await self.process(message)
                self.interactions += 1
                elapsed = time.monotonic() - start
                self.log.info("processed in %.3fs (attempt %d)", elapsed, attempt)
                if trace:
                    trace.record(self.name, "consume", self.input_stream, f"attempt={attempt} ok")
                return result
            except Exception as exc:  # noqa: BLE001 - deliberately broad, retried below
                last_exc = exc
                backoff = settings.retry_backoff_base_seconds * (2 ** (attempt - 1))
                self.log.warning(
                    "attempt %d/%d failed: %s (retrying in %.2fs)",
                    attempt, settings.max_agent_retries, exc, backoff,
                )
                if trace:
                    trace.record(self.name, "consume", self.input_stream, f"attempt={attempt} error={exc}")
                await asyncio.sleep(backoff)
        assert last_exc is not None
        raise AgentError(f"{self.name} failed after {settings.max_agent_retries} attempts") from last_exc

    async def run_worker_loop(self) -> None:
        """Standalone process mode: consume -> process -> publish -> ack,
        forever. Used when the agent is launched as its own OS process
        (see docker-compose 'distributed' profile) talking only through
        Redis Streams."""
        await self.bus.ensure_group(self.input_stream, self.consumer_group)
        self.log.info("worker loop started on stream=%s group=%s", self.input_stream, self.consumer_group)
        async for msg_id, message in self.bus.consume(self.input_stream, self.consumer_group, self.consumer_id):
            try:
                result = await self.handle_one(message)
                if self.output_stream:
                    await self.bus.publish(self.output_stream, result)
            except Exception:  # noqa: BLE001
                self.log.exception("unrecoverable failure processing message %s", msg_id)
                if self.output_stream:
                    await self.bus.publish(self.output_stream, {"type": "error", "agent": self.name, "original": message})
            finally:
                await self.bus.ack(self.input_stream, self.consumer_group, msg_id)
