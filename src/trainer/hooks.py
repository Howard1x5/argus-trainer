"""Safety hooks — dangerous command blocker, cwd boundary, score gaming prevention, activity logger."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

# SDK types — stubs used for both CLI and non-SDK environments.
# If SDK is installed, these are overridden. Otherwise stubs are fine
# since hooks.py is only used for activity logging in v2 (CLI mode).
from dataclasses import dataclass
from typing import Any


@dataclass
class PermissionResultAllow:
    behavior: str = "allow"
    updated_input: dict | None = None


@dataclass
class PermissionResultDeny:
    behavior: str = "deny"
    message: str = ""
    interrupt: bool = False


@dataclass
class ToolPermissionContext:
    signal: Any = None

logger = logging.getLogger(__name__)

# Commands that should never be executed
BLOCKED_COMMANDS = [
    r"\brm\s+-rf\s+/",
    r"\bsudo\s+rm\b",
    r"\bsystemctl\b",
    r"\breboot\b",
    r"\bshutdown\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bchmod\s+777\b",
    r"\bcurl\b.*\|\s*(ba)?sh",
    r"\bwget\b.*\|\s*(ba)?sh",
    r"\bpip\s+install\b",  # Don't let agent install packages
    r"\bnpm\s+install\b",
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+reset\s+--hard\b",
]

# Files the agent must not modify (score gaming prevention)
PROTECTED_FILES = [
    "improvement/comparator.py",
    "improvement/runner.py",
    "improvement/fix_generator.py",
]

# Allowed directory prefixes for file operations
ALLOWED_PATHS = [
    "/opt/argus",
    "/opt/argus-trainer",
]


def _is_path_allowed(file_path: str) -> bool:
    """Check if a file path is within allowed boundaries."""
    resolved = str(Path(file_path).resolve())
    return any(resolved.startswith(prefix) for prefix in ALLOWED_PATHS)


def _is_protected_file(file_path: str) -> bool:
    """Check if a file is protected from modification."""
    resolved = str(Path(file_path).resolve())
    return any(protected in resolved for protected in PROTECTED_FILES)


def _is_dangerous_command(command: str) -> str | None:
    """Check if a command matches any blocked pattern. Returns match or None."""
    for pattern in BLOCKED_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern
    return None


class ActivityLogger:
    """Logs every tool use to a JSONL file."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, tool_name: str, input_data: dict, result: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "input": self._sanitize(input_data),
            "result": result,
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _sanitize(self, data: dict) -> dict:
        """Truncate large values for logging."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 500:
                sanitized[k] = v[:500] + "...[truncated]"
            else:
                sanitized[k] = v
        return sanitized


def create_permission_handler(
    activity_logger: ActivityLogger | None = None,
    allowed_paths: list[str] | None = None,
):
    """Create a can_use_tool handler with safety guardrails.

    Returns an async function compatible with ClaudeAgentOptions.can_use_tool.
    """
    paths = allowed_paths or ALLOWED_PATHS

    async def permission_handler(
        tool_name: str,
        input_data: dict,
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:

        result = "allowed"

        # Check Bash commands for dangerous patterns
        if tool_name == "Bash":
            command = input_data.get("command", "")
            match = _is_dangerous_command(command)
            if match:
                result = f"denied:dangerous_command:{match}"
                if activity_logger:
                    activity_logger.log(tool_name, input_data, result)
                return PermissionResultDeny(
                    message=f"Blocked dangerous command matching: {match}",
                )

        # Check file operations for path boundaries
        if tool_name in ("Read", "Write", "Edit", "Glob", "Grep"):
            file_path = input_data.get("file_path") or input_data.get("path", "")
            if file_path and not _is_path_allowed(file_path):
                result = f"denied:path_boundary:{file_path}"
                if activity_logger:
                    activity_logger.log(tool_name, input_data, result)
                return PermissionResultDeny(
                    message=f"Path outside allowed boundaries: {file_path}. Allowed: {paths}",
                )

        # Check for score gaming (modifying comparator/runner)
        if tool_name in ("Write", "Edit"):
            file_path = input_data.get("file_path", "")
            if _is_protected_file(file_path):
                result = f"denied:protected_file:{file_path}"
                if activity_logger:
                    activity_logger.log(tool_name, input_data, result)
                return PermissionResultDeny(
                    message=f"Cannot modify protected file: {file_path}. This file is part of the scoring infrastructure.",
                    interrupt=True,
                )

        if activity_logger:
            activity_logger.log(tool_name, input_data, result)

        return PermissionResultAllow(updated_input=input_data)

    return permission_handler
