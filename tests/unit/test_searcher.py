import pytest

from src.agents.planner import PlannerAgent
from src.agents.searcher import SearcherAgent
from src.schemas import ScrapedSource


async def _make_plan(bus, topic="climate change adaptation strategies", max_sources=12):
    planner = PlannerAgent(bus)
    plan_result = await planner.process({
        "report_id": "rpt_search_test",
        "topic": topic,
        "depth": "moderate",
        "max_sources": max_sources,
    })
    return plan_result


async def test_searcher_returns_deduplicated_sources_within_cap(bus):
    plan_result = await _make_plan(bus, max_sources=10)
    searcher = SearcherAgent(bus)
    bundle = await searcher.process(plan_result)

    sources = [ScrapedSource(**s) for s in bundle["sources"]]
    assert len(sources) <= 10
    urls = [s.url for s in sources]
    assert len(urls) == len(set(urls)), "searcher must deduplicate by URL"
    assert bundle["urls_visited"] >= len(sources)
    for s in sources:
        assert 0.0 <= s.relevance_score <= 1.0


async def test_searcher_sorts_by_relevance_descending(bus):
    plan_result = await _make_plan(bus)
    searcher = SearcherAgent(bus)
    bundle = await searcher.process(plan_result)
    scores = [s["relevance_score"] for s in bundle["sources"]]
    assert scores == sorted(scores, reverse=True)


async def test_searcher_handles_low_signal_topic_without_crashing(bus):
    plan_result = await _make_plan(bus, topic="xk9 zephyrblorp nonsense keyword")
    searcher = SearcherAgent(bus)
    bundle = await searcher.process(plan_result)
    # should not raise, and should still return a list (possibly small)
    assert isinstance(bundle["sources"], list)
