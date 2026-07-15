"""
Supervisor: the orchestration framework's core (requirement #1).

For each research request the Supervisor:
  1. drives the Planner -> Searcher -> Synthesizer -> Critic pipeline
  2. runs entirely through the message bus (agents never call each other)
  3. handles the Critic's re-search loop (max `settings.max_research_iterations`)
  4. tracks per-phase AgentState + timing for observability
  5. enforces a single global timeout (`settings.global_timeout_seconds`) for
     the whole request, via asyncio.wait_for
  6. retries are handled one level down, inside AbstractAgent.handle_one()
  7. assembles and validates the final ResearchReport against the schema

This module runs agents "in-process" (as asyncio coroutines) by default,
which is what `make run` uses for a fast, dependency-light path. Exactly
the same agent classes can instead be launched as standalone OS processes
via `agent.run_worker_loop()` talking over Redis Streams (see
docker-compose's `distributed` profile and each agents/*.py module's
`__main__` block) - the Supervisor doesn't care which mode is active,
because in both cases all interaction goes through `MessageBus`.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from ..agents.critic import CriticAgent
from ..agents.planner import PlannerAgent
from ..agents.searcher import SearcherAgent
from ..agents.synthesizer import SynthesizerAgent
from ..config import settings
from ..message_bus import MessageBus
from ..schemas import Critique, Metadata, ReportSection, ResearchReport, ResearchRequest, ScrapedSource
from ..utils.tracing import InteractionTrace
from .state import AgentState, ReportState

logger = logging.getLogger("supervisor")


class GlobalTimeoutError(Exception):
    pass


class Supervisor:
    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus
        self.planner = PlannerAgent(bus)
        self.searcher = SearcherAgent(bus)
        self.synthesizer = SynthesizerAgent(bus)
        self.critic = CriticAgent(bus)

    @property
    def total_interactions(self) -> int:
        return (
            self.planner.interactions
            + self.searcher.interactions
            + self.synthesizer.interactions
            + self.critic.interactions
        )

    async def process_request(self, request: ResearchRequest) -> ResearchReport:
        report_id = f"rpt_{uuid.uuid4().hex[:12]}"
        state = ReportState(report_id=report_id, topic=request.topic)
        trace = InteractionTrace(report_id=report_id)

        try:
            report = await asyncio.wait_for(
                self._run_pipeline(report_id, request, state, trace),
                timeout=settings.global_timeout_seconds,
            )
            return report
        except asyncio.TimeoutError as exc:
            for phase, s in state.phase_states.items():
                if s == AgentState.RUNNING:
                    state.set_state(phase, AgentState.TIMED_OUT)
            logger.error("report %s exceeded global timeout of %ss", report_id, settings.global_timeout_seconds)
            raise GlobalTimeoutError(f"report {report_id} exceeded {settings.global_timeout_seconds}s") from exc
        finally:
            trace.write(settings.output_dir)

    async def _timed_phase(self, phase: str, state: ReportState, coro):
        state.set_state(phase, AgentState.RUNNING)
        start = time.monotonic()
        try:
            result = await coro
            state.set_state(phase, AgentState.DONE)
            return result
        except Exception:
            state.set_state(phase, AgentState.FAILED)
            raise
        finally:
            state.record_timing(phase, time.monotonic() - start)

    async def _bus_step(self, agent, message: dict, trace: InteractionTrace) -> dict:
        """Publish -> (agent consumes conceptually) -> process -> publish
        result. In in-process mode we call handle_one directly rather than
        polling the queue back out, but we still record both bus hops so
        the trace accurately reflects the architecture."""
        await self.bus.publish(agent.input_stream, message)
        trace.record("supervisor", "publish", agent.input_stream, message.get("type", "?"))
        result = await agent.handle_one(message, trace=trace)
        await self.bus.publish(agent.output_stream, result)
        trace.record(agent.name, "publish", agent.output_stream, result.get("type", "?"))
        return result

    async def _run_pipeline(self, report_id: str, request: ResearchRequest, state: ReportState, trace: InteractionTrace) -> ResearchReport:
        wall_start = time.monotonic()

        plan_msg = {
            "type": "plan_request",
            "report_id": report_id,
            "topic": request.topic,
            "depth": request.depth.value,
            "max_sources": request.max_sources,
        }
        plan_result = await self._timed_phase("planning", state, self._bus_step(self.planner, plan_msg, trace))

        search_result = await self._timed_phase("search", state, self._bus_step(self.searcher, plan_result, trace))

        total_urls_visited = search_result["urls_visited"]

        synth_result = await self._timed_phase("synthesis", state, self._bus_step(self.synthesizer, search_result, trace))

        iteration = 1
        critique_result = await self._timed_phase(
            "critique", state, self._bus_step(self.critic, {**synth_result, "iteration": iteration}, trace)
        )

        # --- Re-search loop (max settings.max_research_iterations) ---------
        # Iterative deepening: only the Critic's *new* queries are searched
        # each round; results are merged with everything gathered so far
        # (deduped, re-ranked, re-capped at max_sources) rather than
        # re-fetching the original sub-queries from scratch.
        while critique_result["critique"]["needs_research"] and iteration < settings.max_research_iterations + 1:
            iteration += 1
            logger.info("report %s: triggering re-search, iteration %d", report_id, iteration)

            extra_queries = critique_result["critique"]["additional_queries"]
            plan = critique_result["draft"]["plan"]
            extra_plan = {**plan, "sub_queries": extra_queries}

            research_search_msg = {"type": "research_plan", "report_id": report_id, "plan": extra_plan}
            extra_search_result = await self._timed_phase(
                f"research_search_iter{iteration}", state, self._bus_step(self.searcher, research_search_msg, trace)
            )
            total_urls_visited += extra_search_result["urls_visited"]

            merged_by_url = {s["url"]: s for s in critique_result["draft"]["sources"]}
            for s in extra_search_result["sources"]:
                existing = merged_by_url.get(s["url"])
                if existing is None or s["relevance_score"] > existing["relevance_score"]:
                    merged_by_url[s["url"]] = s
            merged_sources = sorted(merged_by_url.values(), key=lambda s: s["relevance_score"], reverse=True)
            merged_sources = merged_sources[: plan["max_sources"]]

            # Keep the ORIGINAL sub_queries (and therefore the original
            # section/heading set) so re-search reinforces existing weak
            # sections with new evidence rather than growing the report with
            # new, equally-thin sections each iteration.
            merged_plan = plan
            merged_bundle = {
                "type": "search_bundle",
                "report_id": report_id,
                "plan": merged_plan,
                "sources": merged_sources,
                "urls_visited": extra_search_result["urls_visited"],
                "duplicates_dropped": extra_search_result["duplicates_dropped"],
            }

            synth_result = await self._timed_phase(
                f"research_synthesis_iter{iteration}", state, self._bus_step(self.synthesizer, merged_bundle, trace)
            )
            critique_result = await self._timed_phase(
                f"research_critique_iter{iteration}",
                state,
                self._bus_step(self.critic, {**synth_result, "iteration": iteration}, trace),
            )


        state.research_iterations = iteration
        wall_clock = time.monotonic() - wall_start

        draft = critique_result["draft"]
        critique = Critique(**critique_result["critique"])

        report = ResearchReport(
            report_id=report_id,
            topic=draft["topic"],
            summary=draft["summary"],
            sections=[ReportSection(**s) for s in draft["sections"]],
            sources=[ScrapedSource(**s) for s in draft["sources"]],
            critique=critique,
            metadata=Metadata(
                total_urls_visited=total_urls_visited,
                agent_interactions=trace.count,
                wall_clock_seconds=round(wall_clock, 3),
                phase_timings={k: round(v, 3) for k, v in state.phase_timings.items()},
                research_iterations=state.research_iterations,
            ),
        )
        logger.info(
            "report %s complete: confidence=%.2f wall_clock=%.2fs interactions=%d iterations=%d",
            report_id, critique.confidence_score, wall_clock, trace.count, state.research_iterations,
        )
        return report
