"""Cost tracker — per-cycle and total budget enforcement."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CostEntry:
    timestamp: str
    case_name: str
    cycle: int
    phase: str
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CostSummary:
    total_usd: float = 0.0
    cycle_usd: float = 0.0
    entries: list[dict] = field(default_factory=list)


class BudgetExceeded(Exception):
    """Raised when a budget limit is hit."""

    def __init__(self, message: str, current: float, limit: float):
        super().__init__(message)
        self.current = current
        self.limit = limit


class CostTracker:
    """Tracks API costs per cycle and total, enforces budget limits."""

    def __init__(
        self,
        state_dir: Path,
        max_per_cycle_usd: float = 5.0,
        max_total_usd: float = 50.0,
        warn_threshold_pct: float = 80.0,
    ):
        self.cost_file = state_dir / "cost_history.json"
        self.max_per_cycle = max_per_cycle_usd
        self.max_total = max_total_usd
        self.warn_threshold = warn_threshold_pct / 100.0
        self._current_cycle_cost = 0.0
        self._total_cost = self._load_total()

    def _load_total(self) -> float:
        """Load total cost from history file."""
        if not self.cost_file.exists():
            return 0.0
        try:
            entries = json.loads(self.cost_file.read_text())
            return sum(e.get("cost_usd", 0) for e in entries)
        except (json.JSONDecodeError, TypeError):
            return 0.0

    def reset_cycle(self) -> None:
        """Reset per-cycle cost counter."""
        self._current_cycle_cost = 0.0

    def record(self, entry: CostEntry) -> None:
        """Record a cost entry and check budgets."""
        self._current_cycle_cost += entry.cost_usd
        self._total_cost += entry.cost_usd

        # Append to history
        entries = []
        if self.cost_file.exists():
            try:
                entries = json.loads(self.cost_file.read_text())
            except (json.JSONDecodeError, TypeError):
                entries = []
        entries.append(asdict(entry))
        self.cost_file.write_text(json.dumps(entries, indent=2))

        # Check warn threshold
        if self._total_cost >= self.max_total * self.warn_threshold:
            logger.warning(
                "Budget warning: $%.2f / $%.2f total (%.0f%%)",
                self._total_cost,
                self.max_total,
                (self._total_cost / self.max_total) * 100,
            )

    def check_budget(self) -> None:
        """Raise BudgetExceeded if limits are hit."""
        if self._current_cycle_cost >= self.max_per_cycle:
            raise BudgetExceeded(
                f"Cycle budget exceeded: ${self._current_cycle_cost:.2f} >= ${self.max_per_cycle:.2f}",
                self._current_cycle_cost,
                self.max_per_cycle,
            )
        if self._total_cost >= self.max_total:
            raise BudgetExceeded(
                f"Total budget exceeded: ${self._total_cost:.2f} >= ${self.max_total:.2f}",
                self._total_cost,
                self.max_total,
            )

    @property
    def cycle_cost(self) -> float:
        return self._current_cycle_cost

    @property
    def total_cost(self) -> float:
        return self._total_cost

    def summary(self) -> CostSummary:
        entries = []
        if self.cost_file.exists():
            try:
                entries = json.loads(self.cost_file.read_text())
            except (json.JSONDecodeError, TypeError):
                pass
        return CostSummary(
            total_usd=self._total_cost,
            cycle_usd=self._current_cycle_cost,
            entries=entries,
        )
