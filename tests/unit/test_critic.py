from src.agents.critic import CriticAgent
from src.agents.planner import PlannerAgent
from src.agents.searcher import SearcherAgent
from src.agents.synthesizer import SynthesizerAgent
from src.schemas import Critique


async def _make_draft(bus, topic="genomics research funding trends"):
    planner = PlannerAgent(bus)
    plan_result = await planner.process({
        "report_id": "rpt_critic_test",
        "topic": topic,
        "depth": "moderate",
        "max_sources": 15,
    })
    searcher = SearcherAgent(bus)
    bundle = await searcher.process(plan_result)
    synthesizer = SynthesizerAgent(bus)
    return await synthesizer.process(bundle)


async def test_critic_confidence_in_range(bus):
    draft_result = await _make_draft(bus)
    critic = CriticAgent(bus)
    result = await critic.process({**draft_result, "iteration": 1})
    critique = Critique(**result["critique"])
    assert 0.0 <= critique.confidence_score <= 1.0
    for v in critique.section_confidence.values():
        assert 0.0 <= v <= 1.0


async def test_critic_flags_gap_for_empty_sections(bus):
    draft_result = await _make_draft(bus)
    # artificially strip all citations from every section to force gaps
    for section in draft_result["draft"]["sections"]:
        section["citations"] = []

    critic = CriticAgent(bus)
    result = await critic.process({**draft_result, "iteration": 1})
    critique = Critique(**result["critique"])

    assert critique.confidence_score == 0.0
    assert len(critique.gaps) == len(draft_result["draft"]["sections"])


async def test_critic_stops_research_after_max_iterations(bus):
    draft_result = await _make_draft(bus)
    for section in draft_result["draft"]["sections"]:
        section["citations"] = []

    critic = CriticAgent(bus)
    # settings.max_research_iterations default is 2; iteration=3 exceeds it
    result = await critic.process({**draft_result, "iteration": 3})
    critique = Critique(**result["critique"])
    assert critique.needs_research is False
