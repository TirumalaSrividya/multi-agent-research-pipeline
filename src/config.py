"""Centralized configuration, read from environment variables so behaviour
can be tuned per-deployment (docker-compose, CI, local dev) without code
changes."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # message bus
    bus_backend: str = os.environ.get("BUS_BACKEND", "inmemory")  # inmemory | redis
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # concurrency / throughput tuning (see docs/architecture.md#tuning)
    searcher_concurrency: int = _int("SEARCHER_CONCURRENCY", 8)
    topic_concurrency: int = _int("TOPIC_CONCURRENCY", 6)
    search_rate_limit_per_sec: float = _float("SEARCH_RATE_LIMIT", 40.0)

    # retry / reliability
    max_agent_retries: int = _int("MAX_AGENT_RETRIES", 3)
    retry_backoff_base_seconds: float = _float("RETRY_BACKOFF_BASE", 0.25)

    # global SLA
    global_timeout_seconds: float = _float("GLOBAL_TIMEOUT_SECONDS", 300.0)

    # critic re-search loop
    max_research_iterations: int = _int("MAX_RESEARCH_ITERATIONS", 2)
    confidence_threshold: float = _float("CONFIDENCE_THRESHOLD", 0.55)

    # data
    dataset_path: str = os.environ.get(
        "MOCK_DATASET_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "mock_dataset.json")
    )
    dataset_size: int = _int("MOCK_DATASET_SIZE", 10_000)

    # logging
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    output_dir: str = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "outputs"))


settings = Settings()
