import pytest

from src.agents.planner import PlannerAgent
from src.schemas import ResearchPlan


@pytest.mark.parametrize("depth,expected_count,expected_strategy", [
    ("shallow", 3, "breadth_first"),
    ("moderate", 5, "iterative_deepening"),
    ("deep", 8, "iterative_deepening"),
])
async def test_planner_query_count_and_strategy(bus, depth, expected_count, expected_strategy):
    agent = PlannerAgent(bus)
    result = await agent.process({
        "report_id": "rpt_test",
        "topic": "renewable energy storage",
        "depth": depth,
        "max_sources": 15,
    })

    plan = ResearchPlan(**result["plan"])
    assert len(plan.sub_queries) == expected_count
    assert plan.strategy.value == expected_strategy
    assert plan.report_id == "rpt_test"
    # sub-queries must be unique and non-empty
    texts = [q.text for q in plan.sub_queries]
    assert len(texts) == len(set(texts))
    assert all(t.strip() for t in texts)


async def test_planner_bounds_are_within_spec(bus):
    agent = PlannerAgent(bus)
    for depth in ("shallow", "moderate", "deep"):
        result = await agent.process({
            "report_id": "rpt_bounds",
            "topic": "quantum computing applications",
            "depth": depth,
            "max_sources": 15,
        })
        n = len(result["plan"]["sub_queries"])
        assert 3 <= n <= 8
