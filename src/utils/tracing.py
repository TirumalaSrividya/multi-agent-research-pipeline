"""Per-report agent interaction trace: an ordered log of every message that
crossed the bus while processing a given report_id. Written to
outputs/<report_id>.trace.json so the full message flow can be inspected
for debugging or auditing (requirement #7)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field


@dataclass
class TraceEvent:
    ts: float
    agent: str
    direction: str  # "publish" | "consume"
    stream: str
    summary: str


@dataclass
class InteractionTrace:
    report_id: str
    events: list[TraceEvent] = field(default_factory=list)

    def record(self, agent: str, direction: str, stream: str, summary: str) -> None:
        self.events.append(TraceEvent(ts=time.time(), agent=agent, direction=direction, stream=stream, summary=summary))

    @property
    def count(self) -> int:
        return len(self.events)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "total_interactions": self.count,
            "events": [
                {"ts": e.ts, "agent": e.agent, "direction": e.direction, "stream": e.stream, "summary": e.summary}
                for e in self.events
            ],
        }

    def write(self, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{self.report_id}.trace.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path
