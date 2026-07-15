"""
Pydantic v2 models defining every message contract used by the pipeline.

These are the single source of truth for:
  * the external Input / Output schema described in the spec
  * the internal messages agents pass to each other over the message bus

Keeping them all in one module means every agent and the orchestrator
import from here, so contracts can never silently drift apart.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# External input
# --------------------------------------------------------------------------- #
class Depth(str, Enum):
    shallow = "shallow"
    moderate = "moderate"
    deep = "deep"


class OutputFormat(str, Enum):
    markdown = "markdown"
    pdf = "pdf"
    json = "json"


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=200)
    depth: Depth = Depth.moderate
    max_sources: int = Field(15, ge=5, le=50)
    output_format: OutputFormat = OutputFormat.markdown

    @field_validator("topic")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


# --------------------------------------------------------------------------- #
# Planner -> Searcher
# --------------------------------------------------------------------------- #
class SearchStrategy(str, Enum):
    breadth_first = "breadth_first"
    iterative_deepening = "iterative_deepening"


class SubQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: new_id("q_"))
    text: str
    priority: int = 1  # lower = searched first


class ResearchPlan(BaseModel):
    report_id: str
    topic: str
    depth: Depth
    strategy: SearchStrategy
    sub_queries: list[SubQuery]
    max_sources: int
    created_at: str = Field(default_factory=_now_iso)


# --------------------------------------------------------------------------- #
# Searcher -> Synthesizer
# --------------------------------------------------------------------------- #
class ScrapedSource(BaseModel):
    source_id: str = Field(default_factory=lambda: new_id("src_"))
    url: str
    title: str
    snippet: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    matched_query_id: str
    scraped_at: str = Field(default_factory=_now_iso)


class SearchBundle(BaseModel):
    report_id: str
    plan: ResearchPlan
    sources: list[ScrapedSource]
    urls_visited: int
    duplicates_dropped: int


# --------------------------------------------------------------------------- #
# Synthesizer -> Critic
# --------------------------------------------------------------------------- #
class ReportSection(BaseModel):
    heading: str
    content: str
    citations: list[str]  # source_ids
    sub_query_id: str


class DraftReport(BaseModel):
    report_id: str
    topic: str
    summary: str
    sections: list[ReportSection]
    sources: list[ScrapedSource]
    plan: ResearchPlan


# --------------------------------------------------------------------------- #
# Critic output
# --------------------------------------------------------------------------- #
class Critique(BaseModel):
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    section_confidence: dict[str, float] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    bias_flags: list[str] = Field(default_factory=list)
    needs_research: bool = False
    additional_queries: list[SubQuery] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Final external output
# --------------------------------------------------------------------------- #
class Metadata(BaseModel):
    total_urls_visited: int
    agent_interactions: int
    wall_clock_seconds: float
    phase_timings: dict[str, float] = Field(default_factory=dict)
    research_iterations: int = 1


class ResearchReport(BaseModel):
    report_id: str
    topic: str
    summary: str = Field(..., min_length=1)
    sections: list[ReportSection]
    sources: list[ScrapedSource]
    critique: Critique
    metadata: Metadata

    @field_validator("summary")
    @classmethod
    def _word_bounds(cls, v: str) -> str:
        n = len(v.split())
        if not (500 <= n <= 2000):
            raise ValueError(f"summary must be 500-2000 words, got {n}")
        return v
