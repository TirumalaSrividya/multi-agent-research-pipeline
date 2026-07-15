"""Searcher Agent.

Input:  {"type": "research_plan", "report_id", "plan"}
Output: SearchBundle (as dict)

Executes every sub-query from the plan against the mock search dataset,
deduplicates results by URL across sub-queries, enforces a concurrency
limit + a simple token-bucket rate limiter (requirement: "must handle rate
limiting and deduplication across sub-queries"), and caps the final source
list at plan.max_sources by relevance.
"""
from __future__ import annotations

import asyncio
import time

from ..config import settings
from ..data.mock_search_dataset import search
from ..schemas import ResearchPlan, ScrapedSource
from .base import AbstractAgent


class _RateLimiter:
    """Simple token-bucket limiter shared across concurrent search calls."""

    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            self._next_slot = max(now, self._next_slot) + self._interval
            wait = self._next_slot - now
        if wait > 0:
            await asyncio.sleep(wait)


class SearcherAgent(AbstractAgent):
    name = "searcher"
    input_stream = "research_plans"
    output_stream = "search_bundles"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._semaphore = asyncio.Semaphore(settings.searcher_concurrency)
        self._rate_limiter = _RateLimiter(settings.search_rate_limit_per_sec)

    async def _search_one(self, query_id: str, text: str, k: int) -> list[ScrapedSource]:
        async with self._semaphore:
            await self._rate_limiter.acquire()
            raw_results = search(text, k=k)
        return [
            ScrapedSource(
                url=r["url"],
                title=r["title"],
                snippet=r["snippet"],
                relevance_score=r["relevance_score"],
                matched_query_id=query_id,
            )
            for r in raw_results
        ]

    async def process(self, message: dict) -> dict:
        plan = ResearchPlan(**message["plan"])
        per_query_k = max(3, plan.max_sources // max(1, len(plan.sub_queries)) + 2)

        tasks = [self._search_one(sq.query_id, sq.text, per_query_k) for sq in plan.sub_queries]
        results_per_query = await asyncio.gather(*tasks)

        seen_urls: dict[str, ScrapedSource] = {}
        duplicates = 0
        urls_visited = 0
        for results in results_per_query:
            for src in results:
                urls_visited += 1
                if src.url in seen_urls:
                    duplicates += 1
                    # keep whichever copy has higher relevance
                    if src.relevance_score > seen_urls[src.url].relevance_score:
                        seen_urls[src.url] = src
                    continue
                seen_urls[src.url] = src

        ranked = sorted(seen_urls.values(), key=lambda s: s.relevance_score, reverse=True)
        capped = ranked[: plan.max_sources]

        self.log.info(
            "searched %d sub-queries -> %d unique sources (of %d visited, %d dupes) for report=%s",
            len(plan.sub_queries), len(capped), urls_visited, duplicates, plan.report_id,
        )

        return {
            "type": "search_bundle",
            "report_id": plan.report_id,
            "plan": plan.model_dump(),
            "sources": [s.model_dump() for s in capped],
            "urls_visited": urls_visited,
            "duplicates_dropped": duplicates,
        }


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
    _agent = SearcherAgent(_bus)
    _asyncio.run(_agent.run_worker_loop())
