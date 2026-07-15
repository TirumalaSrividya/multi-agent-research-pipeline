"""Critic Agent.

Input:  DraftReport (as dict) [+ "iteration" int]
Output: {"type": "critique_result", "report_id", "draft", "critique"}

Scores confidence per section (based on citation count and average
relevance of cited sources), flags gaps (sections with weak coverage),
flags potential bias (source-domain concentration), and decides whether a
re-search loop should be triggered - capped at settings.max_research_iterations.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from ..config import settings
from ..schemas import Critique, DraftReport, ScrapedSource, SubQuery
from .base import AbstractAgent

_MIN_CITATIONS_FOR_CONFIDENCE = 2


class CriticAgent(AbstractAgent):
    name = "critic"
    input_stream = "draft_reports"
    output_stream = "critique_results"

    def _section_confidence(self, citations: list[str], sources_by_id: dict[str, ScrapedSource]) -> float:
        if not citations:
            return 0.0
        cited_sources = [sources_by_id[c] for c in citations if c in sources_by_id]
        if not cited_sources:
            return 0.0
        avg_relevance = sum(s.relevance_score for s in cited_sources) / len(cited_sources)
        coverage_factor = min(1.0, len(cited_sources) / _MIN_CITATIONS_FOR_CONFIDENCE)
        return round(avg_relevance * 0.7 + coverage_factor * 0.3, 4)

    def _bias_flags(self, sources: list[ScrapedSource]) -> list[str]:
        if not sources:
            return ["no sources available to assess bias"]
        domains = Counter(urlparse(s.url).netloc for s in sources)
        total = sum(domains.values())
        flags = []
        for domain, count in domains.most_common(3):
            share = count / total
            if share > 0.4:
                flags.append(f"over-concentration of sources from '{domain}' ({share:.0%} of all sources)")
        return flags

    async def process(self, message: dict) -> dict:
        draft = DraftReport(**message["draft"])
        iteration = int(message.get("iteration", 1))
        sources_by_id = {s.source_id: s for s in draft.sources}

        section_confidence: dict[str, float] = {}
        gaps: list[str] = []
        for section in draft.sections:
            conf = self._section_confidence(section.citations, sources_by_id)
            section_confidence[section.heading] = conf
            if conf < settings.confidence_threshold:
                gaps.append(f"weak coverage on '{section.heading}' (confidence={conf:.2f})")

        overall_confidence = (
            round(sum(section_confidence.values()) / len(section_confidence), 4)
            if section_confidence else 0.0
        )
        bias_flags = self._bias_flags(draft.sources)

        needs_research = (
            overall_confidence < settings.confidence_threshold
            and iteration <= settings.max_research_iterations
            and len(gaps) > 0
        )

        additional_queries: list[SubQuery] = []
        if needs_research:
            for section in draft.sections:
                if section_confidence[section.heading] < settings.confidence_threshold:
                    # Reuse the *same* sub_query_id as the weak section so
                    # the Synthesizer folds freshly found sources into that
                    # existing section on re-search, rather than spawning a
                    # brand-new (likely equally thin) section. Keep the
                    # query text lean (topic + heading only) - generic
                    # filler words like "additional sources" only dilute
                    # the mock index's word-overlap match ratio.
                    additional_queries.append(
                        SubQuery(
                            query_id=section.sub_query_id,
                            text=f"{draft.topic} {section.heading.lower()}",
                            priority=0,
                        )
                    )

        critique = Critique(
            confidence_score=overall_confidence,
            section_confidence=section_confidence,
            gaps=gaps,
            bias_flags=bias_flags,
            needs_research=needs_research,
            additional_queries=additional_queries,
        )

        self.log.info(
            "critique for report=%s: confidence=%.2f gaps=%d bias_flags=%d needs_research=%s (iteration %d)",
            draft.report_id, overall_confidence, len(gaps), len(bias_flags), needs_research, iteration,
        )

        return {
            "type": "critique_result",
            "report_id": draft.report_id,
            "draft": draft.model_dump(),
            "critique": critique.model_dump(),
            "iteration": iteration,
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
    _agent = CriticAgent(_bus)
    _asyncio.run(_agent.run_worker_loop())
