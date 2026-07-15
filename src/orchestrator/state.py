from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class ReportState:
    report_id: str
    topic: str
    phase_states: dict[str, AgentState] = field(default_factory=dict)
    phase_timings: dict[str, float] = field(default_factory=dict)
    research_iterations: int = 1

    def set_state(self, phase: str, state: AgentState) -> None:
        self.phase_states[phase] = state

    def record_timing(self, phase: str, seconds: float) -> None:
        self.phase_timings[phase] = self.phase_timings.get(phase, 0.0) + seconds
