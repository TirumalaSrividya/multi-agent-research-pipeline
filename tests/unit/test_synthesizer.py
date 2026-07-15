from src.agents.planner import PlannerAgent
from src.agents.searcher import SearcherAgent
from src.agents.synthesizer import SynthesizerAgent
from src.schemas import DraftReport


async def _make_bundle(bus, topic="supply chain resilience planning"):
    planner = PlannerAgent(bus)
    plan_result = await planner.process({
        "report_id": "rpt_synth_test",
        "topic": topic,
        "depth": "moderate",
        "max_sources": 15,
    })
    searcher = SearcherAgent(bus)
    return await searcher.process(plan_result)


async def test_synthesizer_produces_valid_summary_length(bus):
    bundle = await _make_bundle(bus)
    synthesizer = SynthesizerAgent(bus)
    result = await synthesizer.process(bundle)
    draft = DraftReport(**result["draft"])

    word_count = len(draft.summary.split())
    assert 500 <= word_count <= 2000


async def test_synthesizer_sections_match_plan_sub_queries(bus):
    bundle = await _make_bundle(bus)
    synthesizer = SynthesizerAgent(bus)
    result = await synthesizer.process(bundle)
    draft = DraftReport(**result["draft"])

    assert len(draft.sections) == len(draft.plan.sub_queries)


async def test_synthesizer_citations_reference_real_sources(bus):
    bundle = await _make_bundle(bus)
    synthesizer = SynthesizerAgent(bus)
    result = await synthesizer.process(bundle)
    draft = DraftReport(**result["draft"])

    source_ids = {s.source_id for s in draft.sources}
    for section in draft.sections:
        for cid in section.citations:
            assert cid in source_ids
