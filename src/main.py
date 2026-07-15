"""CLI entrypoint.

Usage:
    python -m src.main --topic "Impact of quantum computing on cryptography" --output-dir outputs
    python -m src.main --topics-file sample_topics.json --output-dir outputs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time

from .config import settings
from .message_bus import build_bus
from .orchestrator.supervisor import GlobalTimeoutError, Supervisor
from .schemas import ResearchRequest
from .utils.logging_config import configure_logging

logger = logging.getLogger("main")


def _load_topics(args: argparse.Namespace) -> list[dict]:
    if args.topics_file:
        with open(args.topics_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return [{
        "topic": args.topic,
        "depth": args.depth,
        "max_sources": args.max_sources,
        "output_format": args.output_format,
    }]


async def _run_one(supervisor: Supervisor, req_dict: dict, output_dir: str, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        request = ResearchRequest(**req_dict)
        start = time.monotonic()
        try:
            report = await supervisor.process_request(request)
        except GlobalTimeoutError as exc:
            logger.error(str(exc))
            return {"topic": req_dict["topic"], "status": "timed_out", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("pipeline failed for topic=%r", req_dict["topic"])
            return {"topic": req_dict["topic"], "status": "failed", "error": str(exc)}

        elapsed = time.monotonic() - start
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{report.report_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        return {
            "topic": req_dict["topic"],
            "status": "done",
            "report_id": report.report_id,
            "output_path": out_path,
            "wall_clock_seconds": round(elapsed, 3),
            "phase_timings": report.metadata.phase_timings,
            "confidence": report.critique.confidence_score,
            "sources": len(report.sources),
            "research_iterations": report.metadata.research_iterations,
        }


def _print_breakdown(results: list[dict]) -> None:
    print("\n" + "=" * 100)
    print(f"{'TOPIC':<40} {'STATUS':<10} {'CONF':<6} {'SRC':<5} {'ITERS':<6} {'WALL(s)':<8}")
    print("-" * 100)
    for r in results:
        topic = (r["topic"][:37] + "...") if len(r["topic"]) > 40 else r["topic"]
        if r["status"] == "done":
            print(f"{topic:<40} {r['status']:<10} {r['confidence']:<6.2f} {r['sources']:<5} "
                  f"{r['research_iterations']:<6} {r['wall_clock_seconds']:<8.2f}")
        else:
            print(f"{topic:<40} {r['status']:<10} {'--':<6} {'--':<5} {'--':<6} {'--':<8}")
    print("=" * 100)

    done = [r for r in results if r["status"] == "done"]
    if done:
        print("\nPer-topic phase breakdown (seconds):")
        phases = sorted({p for r in done for p in r["phase_timings"]})
        header = "TOPIC".ljust(30) + "".join(p[:14].ljust(16) for p in phases)
        print(header)
        for r in done:
            row = r["topic"][:27].ljust(30) + "".join(f"{r['phase_timings'].get(p, 0):.3f}".ljust(16) for p in phases)
            print(row)
    print()


async def _main_async(args: argparse.Namespace) -> None:
    configure_logging(settings.log_level)
    bus = build_bus(args.bus, settings.redis_url)
    supervisor = Supervisor(bus)

    topics = _load_topics(args)
    semaphore = asyncio.Semaphore(settings.topic_concurrency)

    overall_start = time.monotonic()
    results = await asyncio.gather(*[_run_one(supervisor, t, args.output_dir, semaphore) for t in topics])
    overall_elapsed = time.monotonic() - overall_start

    _print_breakdown(list(results))
    print(f"Processed {len(topics)} topic(s) in {overall_elapsed:.2f}s "
          f"({len(topics) / overall_elapsed:.2f} topics/sec)\n")

    await bus.close()

    if any(r["status"] != "done" for r in results):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-agent web research pipeline")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--depth", type=str, default="moderate", choices=["shallow", "moderate", "deep"])
    parser.add_argument("--max-sources", type=int, default=15)
    parser.add_argument("--output-format", type=str, default="markdown", choices=["markdown", "pdf", "json"])
    parser.add_argument("--topics-file", type=str, default=None, help="JSON file: list of request objects")
    parser.add_argument("--output-dir", type=str, default=settings.output_dir)
    parser.add_argument("--bus", type=str, default=settings.bus_backend, choices=["inmemory", "redis"])
    args = parser.parse_args()

    if not args.topic and not args.topics_file:
        parser.error("either --topic or --topics-file is required")

    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
