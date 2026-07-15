"""Planner Agent.

Input:  {"type": "plan_request", "report_id", "topic", "depth", "max_sources"}
Output: ResearchPlan (as dict)

Decomposes the topic into 3-8 sub-queries and picks a search strategy:
breadth_first for shallow requests (many parallel narrow queries), or
iterative_deepening for deep requests (a smaller seed set that the Critic
can expand across re-search iterations).
"""
from __future__ import annotations

from ..schemas import Depth, ResearchPlan, SearchStrategy, SubQuery
from .base import AbstractAgent

_ANGLE_TEMPLATES = [
    "{topic} overview",
    "{topic} recent developments",
    "{topic} challenges and risks",
    "{topic} economic impact",
    "{topic} case studies",
    "{topic} expert opinions",
    "{topic} regulatory landscape",
    "{topic} future outlook",
]

_DEPTH_TO_QUERY_COUNT = {
    Depth.shallow: 3,
    Depth.moderate: 5,
    Depth.deep: 8,
}


class PlannerAgent(AbstractAgent):
    name = "planner"
    input_stream = "plan_requests"
    output_stream = "research_plans"

    async def process(self, message: dict) -> dict:
        topic = message["topic"]
        depth = Depth(message.get("depth", "moderate"))
        max_sources = int(message.get("max_sources", 15))
        report_id = message["report_id"]

        n_queries = _DEPTH_TO_QUERY_COUNT[depth]
        angles = _ANGLE_TEMPLATES[:n_queries]
        sub_queries = [
            SubQuery(text=angle.format(topic=topic), priority=i)
            for i, angle in enumerate(angles)
        ]

        strategy = (
            SearchStrategy.breadth_first
            if depth == Depth.shallow
            else SearchStrategy.iterative_deepening
        )

        plan = ResearchPlan(
            report_id=report_id,
            topic=topic,
            depth=depth,
            strategy=strategy,
            sub_queries=sub_queries,
            max_sources=max_sources,
        )
        self.log.info(
            "planned %d sub-queries for topic=%r depth=%s strategy=%s",
            len(sub_queries), topic, depth.value, strategy.value,
        )
        return {"type": "research_plan", "report_id": report_id, "plan": plan.model_dump()}


if __name__ == "__main__":
    # Standalone worker process entrypoint, used by docker-compose's
    # "distributed" profile: `python -m src.agents.PLACEHOLDER`.
    # Talks exclusively over Redis Streams so this can be a fully separate
    # container/process from the orchestrator and every other agent.
    import asyncio as _asyncio

    from ..config import settings as _settings
    from ..message_bus import build_bus as _build_bus
    from ..utils.logging_config import configure_logging as _configure_logging

    _configure_logging(_settings.log_level)
    _bus = _build_bus("redis", _settings.redis_url)
    _agent = PlannerAgent(_bus)
    _asyncio.run(_agent.run_worker_loop())
