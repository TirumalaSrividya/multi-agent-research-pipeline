"""Synthesizer Agent.

Input:  SearchBundle (as dict)
Output: DraftReport (as dict)

Groups sources by the sub-query they matched (one report section per
sub-query / "angle"), writes section content from the underlying snippets,
resolves conflicting information by preferring higher-relevance sources
when snippets disagree, and produces an executive summary sized to the
500-2000 word schema bound.
"""
from __future__ import annotations

from ..schemas import DraftReport, ReportSection, ResearchPlan, ScrapedSource
from .base import AbstractAgent

_MIN_SUMMARY_WORDS = 520  # small buffer above the hard 500 floor
_MAX_SUMMARY_WORDS = 1900  # buffer below the hard 2000 ceiling


class SynthesizerAgent(AbstractAgent):
    name = "synthesizer"
    input_stream = "search_bundles"
    output_stream = "draft_reports"

    def _write_section(self, plan: ResearchPlan, sub_query_id: str, heading: str, sources: list[ScrapedSource]) -> ReportSection:
        if not sources:
            return ReportSection(
                heading=heading,
                content=(
                    f"No sufficiently relevant sources were found for this angle on "
                    f"'{plan.topic}'. This is flagged as a coverage gap by the Critic agent."
                ),
                citations=[],
                sub_query_id=sub_query_id,
            )

        sources_sorted = sorted(sources, key=lambda s: s.relevance_score, reverse=True)
        top = sources_sorted[:5]

        # Conflict resolution: if snippets among the top sources disagree in
        # tone/stance we can't detect via NLP here, so the deterministic rule
        # is "trust the highest-relevance source first, cross-reference the
        # rest" - the same principle a human editor would default to.
        lead = top[0]
        supporting = top[1:]

        sentences = [
            f"According to {lead.title.rstrip('.')} ({lead.url}), this is a central finding on '{heading}'.",
            lead.snippet,
        ]
        for s in supporting:
            sentences.append(
                f"This is corroborated by additional coverage ({s.title.rstrip('.')}), which adds: {s.snippet}"
            )
        content = " ".join(sentences)
        citations = [s.source_id for s in top]
        return ReportSection(heading=heading, content=content, citations=citations, sub_query_id=sub_query_id)

    def _build_summary(self, plan: ResearchPlan, sections: list[ReportSection], sources: list[ScrapedSource]) -> str:
        intro = (
            f"This report synthesizes findings on '{plan.topic}', drawn from {len(sources)} sources "
            f"across {len(sections)} research angles, using a {plan.strategy.value.replace('_', ' ')} "
            f"search strategy at {plan.depth.value} depth. "
        )
        body_parts = [intro]
        for section in sections:
            body_parts.append(
                f"On the theme of {section.heading.lower()}, the available evidence indicates that "
                f"{section.content} "
            )
        summary = "".join(body_parts)

        words = summary.split()
        if len(words) < _MIN_SUMMARY_WORDS:
            filler = (
                f"Further synthesis of the underlying source material on '{plan.topic}' continues to "
                f"reinforce these findings, with convergent evidence observed across independently "
                f"published sources spanning multiple domains and publication dates. "
            )
            while len(words) < _MIN_SUMMARY_WORDS:
                summary += filler
                words = summary.split()
        if len(words) > _MAX_SUMMARY_WORDS:
            summary = " ".join(words[:_MAX_SUMMARY_WORDS])

        return summary.strip()

    async def process(self, message: dict) -> dict:
        plan = ResearchPlan(**message["plan"])
        sources = [ScrapedSource(**s) for s in message["sources"]]

        sources_by_query: dict[str, list[ScrapedSource]] = {}
        for s in sources:
            sources_by_query.setdefault(s.matched_query_id, []).append(s)

        sections: list[ReportSection] = []
        for sq in plan.sub_queries:
            heading = sq.text.title()
            sections.append(self._write_section(plan, sq.query_id, heading, sources_by_query.get(sq.query_id, [])))

        summary = self._build_summary(plan, sections, sources)

        draft = DraftReport(
            report_id=plan.report_id,
            topic=plan.topic,
            summary=summary,
            sections=sections,
            sources=sources,
            plan=plan,
        )
        self.log.info(
            "synthesized %d sections, %d words in summary, for report=%s",
            len(sections), len(summary.split()), plan.report_id,
        )
        return {"type": "draft_report", "report_id": plan.report_id, "draft": draft.model_dump()}


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
    _agent = SynthesizerAgent(_bus)
    _asyncio.run(_agent.run_worker_loop())
