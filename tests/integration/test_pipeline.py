import json

import pytest

from src.message_bus import InMemoryMessageBus
from src.orchestrator.supervisor import Supervisor
from src.schemas import ResearchRequest

TOPICS = [
    {"topic": "Impact of artificial intelligence on labor markets", "depth": "moderate", "max_sources": 12},
    {"topic": "Renewable energy adoption and grid stability", "depth": "shallow", "max_sources": 8},
    {"topic": "Cybersecurity risks in critical infrastructure", "depth": "deep", "max_sources": 15},
]


@pytest.mark.parametrize("topic_spec", TOPICS)
async def test_full_pipeline_produces_valid_report(topic_spec):
    bus = InMemoryMessageBus()
    supervisor = Supervisor(bus)
    request = ResearchRequest(**topic_spec)

    report = await supervisor.process_request(request)

    # schema-level sanity (ResearchReport() already validated this on construction)
    assert report.topic == topic_spec["topic"]
    assert 500 <= len(report.summary.split()) <= 2000
    assert len(report.sections) >= 3
    assert 0.0 <= report.critique.confidence_score <= 1.0
    assert report.metadata.agent_interactions > 0
    assert report.metadata.wall_clock_seconds > 0
    assert report.metadata.research_iterations >= 1

    # every citation resolves
    source_ids = {s.source_id for s in report.sources}
    for section in report.sections:
        for cid in section.citations:
            assert cid in source_ids

    # round-trips through JSON cleanly (what verify.sh checks on disk)
    dumped = report.model_dump_json()
    reloaded = json.loads(dumped)
    assert reloaded["report_id"] == report.report_id


async def test_pipeline_produces_unique_report_ids_across_runs():
    bus = InMemoryMessageBus()
    supervisor = Supervisor(bus)
    ids = set()
    for spec in TOPICS:
        report = await supervisor.process_request(ResearchRequest(**spec))
        assert report.report_id not in ids
        ids.add(report.report_id)
