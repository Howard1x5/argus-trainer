"""State machine — 12 states, JSON persistence, resume capability."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class State(str, Enum):
    """Training loop states."""

    IDLE = "IDLE"
    FETCHING_WALKTHROUGH = "FETCHING_WALKTHROUGH"
    BUILDING_ANSWER_KEY = "BUILDING_ANSWER_KEY"
    ANALYZING_GAPS = "ANALYZING_GAPS"
    IMPLEMENTING_FIXES = "IMPLEMENTING_FIXES"
    RUNNING_EXTRACTION = "RUNNING_EXTRACTION"
    RUNNING_FULL_PIPELINE = "RUNNING_FULL_PIPELINE"
    COMPARING_RESULTS = "COMPARING_RESULTS"
    RUNNING_REGRESSION = "RUNNING_REGRESSION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMMITTING = "COMMITTING"
    FAILED = "FAILED"


# Valid transitions
TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.FETCHING_WALKTHROUGH, State.ANALYZING_GAPS, State.RUNNING_FULL_PIPELINE},
    State.FETCHING_WALKTHROUGH: {State.BUILDING_ANSWER_KEY, State.FAILED},
    State.BUILDING_ANSWER_KEY: {State.ANALYZING_GAPS, State.FAILED},
    State.ANALYZING_GAPS: {State.IMPLEMENTING_FIXES, State.RUNNING_FULL_PIPELINE, State.FAILED},
    State.IMPLEMENTING_FIXES: {State.RUNNING_EXTRACTION, State.RUNNING_FULL_PIPELINE, State.FAILED},
    State.RUNNING_EXTRACTION: {State.ANALYZING_GAPS, State.RUNNING_FULL_PIPELINE, State.FAILED},
    State.RUNNING_FULL_PIPELINE: {State.COMPARING_RESULTS, State.FAILED},
    State.COMPARING_RESULTS: {State.IMPLEMENTING_FIXES, State.RUNNING_REGRESSION, State.AWAITING_APPROVAL, State.FAILED},
    State.RUNNING_REGRESSION: {State.AWAITING_APPROVAL, State.IMPLEMENTING_FIXES, State.FAILED},
    State.AWAITING_APPROVAL: {State.COMMITTING, State.IMPLEMENTING_FIXES, State.IDLE, State.FAILED},
    State.COMMITTING: {State.IDLE, State.FAILED},
    State.FAILED: {State.IDLE},
}


@dataclass
class CycleScore:
    """Score snapshot for a single cycle iteration."""

    iteration: int
    score_numeric: float
    score_display: str
    gaps: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class AgentState:
    """Full agent state — persisted to JSON between cycles."""

    status: str = State.IDLE.value
    case_name: str = ""
    cycle: int = 0
    iteration: int = 0
    walkthrough_url: str = ""
    answer_key_path: str = ""
    current_branch: str = ""
    scores: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    last_error: str = ""
    session_id: str = ""
    updated_at: str = ""

    @property
    def state(self) -> State:
        return State(self.status)


class StateMachine:
    """Manages state transitions and persistence."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_file = state_dir / "agent_state.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    @property
    def current(self) -> AgentState:
        return self._state

    @property
    def status(self) -> State:
        return self._state.state

    def _load(self) -> AgentState:
        """Load state from disk, or return fresh state."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                return AgentState(**data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Corrupt state file, starting fresh: %s", e)
        return AgentState()

    def save(self) -> None:
        """Persist current state to disk."""
        self._state.updated_at = datetime.now(timezone.utc).isoformat()
        self.state_file.write_text(json.dumps(asdict(self._state), indent=2))

    def transition(self, new_state: State) -> None:
        """Transition to a new state with validation."""
        current = self.status
        if new_state not in TRANSITIONS.get(current, set()):
            raise InvalidTransition(
                f"Cannot transition from {current.value} to {new_state.value}. "
                f"Valid: {[s.value for s in TRANSITIONS.get(current, set())]}"
            )
        logger.info("State: %s -> %s", current.value, new_state.value)
        self._state.status = new_state.value
        self.save()

    def record_score(self, score: CycleScore) -> None:
        """Record a score snapshot."""
        self._state.scores.append(asdict(score))
        self.save()

    def record_cost(self, cost_usd: float) -> None:
        """Add to running cost total."""
        self._state.cost_usd += cost_usd
        self.save()

    def set_error(self, error: str) -> None:
        """Record an error and transition to FAILED."""
        self._state.last_error = error
        self._state.status = State.FAILED.value
        self.save()

    def reset(self) -> None:
        """Reset to IDLE (e.g., after approval or rejection)."""
        self._state.status = State.IDLE.value
        self._state.last_error = ""
        self.save()

    def init_cycle(self, case_name: str, cycle: int) -> None:
        """Initialize a new training cycle."""
        self._state.case_name = case_name
        self._state.cycle = cycle
        self._state.iteration = 0
        self._state.scores = []
        self._state.cost_usd = 0.0
        self._state.last_error = ""
        self.save()

    def increment_iteration(self) -> None:
        self._state.iteration += 1
        self.save()

    def can_resume(self) -> bool:
        """Check if there's a resumable state."""
        return self.status not in (State.IDLE, State.FAILED) and self._state.case_name != ""


class InvalidTransition(Exception):
    pass
