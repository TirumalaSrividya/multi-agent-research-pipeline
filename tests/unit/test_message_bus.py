import asyncio

import pytest

from src.message_bus import InMemoryMessageBus


async def test_publish_and_consume_roundtrip(bus: InMemoryMessageBus):
    await bus.ensure_group("test_stream", "group_a")

    async def consumer():
        async for msg_id, data in bus.consume("test_stream", "group_a", "c1"):
            return msg_id, data

    consume_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)  # let the consumer subscribe first
    await bus.publish("test_stream", {"type": "ping", "value": 42})

    msg_id, data = await asyncio.wait_for(consume_task, timeout=1)
    assert data == {"type": "ping", "value": 42}
    assert isinstance(msg_id, str)


async def test_multiple_consumer_groups_each_get_the_message(bus: InMemoryMessageBus):
    await bus.ensure_group("fanout", "group_a")
    await bus.ensure_group("fanout", "group_b")

    async def consume_from(group):
        async for _, data in bus.consume("fanout", group, f"c-{group}"):
            return data

    task_a = asyncio.create_task(consume_from("group_a"))
    task_b = asyncio.create_task(consume_from("group_b"))
    await asyncio.sleep(0.01)
    await bus.publish("fanout", {"hello": "world"})

    result_a = await asyncio.wait_for(task_a, timeout=1)
    result_b = await asyncio.wait_for(task_b, timeout=1)
    assert result_a == {"hello": "world"}
    assert result_b == {"hello": "world"}
