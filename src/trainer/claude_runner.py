"""Claude Code CLI wrapper — invokes `claude -p`, handles timeout, parses JSON output.

Adapted from telegram-orchestrator pattern. Transport-agnostic: all prompts work
identically whether routed through CLI (Max subscription, $0) or SDK (API credits).

To switch back to SDK: replace `claude_runner.invoke()` calls with `query()`,
set ANTHROPIC_API_KEY. Everything else stays the same.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClaudeResult:
    """Result from a Claude Code CLI invocation."""

    success: bool
    result: str
    session_id: str | None
    error: str | None
    error_type: str | None  # "auth", "rate_limit", "context_full", "timeout", "unknown"
    exit_code: int
    cost_usd: float


async def invoke(
    prompt: str,
    session_id: str | None = None,
    timeout: int = 300,
    max_turns: int = 50,
    allowed_tools: str = "Read,Write,Edit,Bash,Glob,Grep",
    system_prompt: str = "",
    cwd: str | None = None,
    cli_path: str = "claude",
) -> ClaudeResult:
    """Invoke Claude Code CLI and return parsed result.

    Args:
        prompt: The user prompt to send.
        session_id: Resume an existing session (--resume).
        timeout: Max seconds before SIGTERM (then SIGKILL after 5s).
        max_turns: Maximum agentic turns (--max-turns).
        allowed_tools: Comma-separated tool names (--allowedTools).
        system_prompt: Appended to system prompt (--append-system-prompt).
        cwd: Working directory for the claude process.
        cli_path: Path to claude CLI binary.

    Returns:
        ClaudeResult with parsed output, session_id, and cost.
    """
    cmd = [cli_path, "-p", prompt, "--output-format", "json", "--max-turns", str(max_turns)]

    if session_id:
        cmd.extend(["--resume", session_id])

    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])

    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])

    logger.info(
        "Invoking Claude Code (timeout=%ds, turns=%d, session=%s)",
        timeout, max_turns, session_id or "new",
    )
    logger.debug("Prompt (first 200 chars): %s", prompt[:200])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Claude Code timed out after %ds, sending SIGTERM", timeout)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("SIGTERM ignored, sending SIGKILL")
                process.kill()
                await process.wait()

            return ClaudeResult(
                success=False,
                result="",
                session_id=session_id,
                error=f"Timed out after {timeout}s",
                error_type="timeout",
                exit_code=-1,
                cost_usd=0.0,
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        exit_code = process.returncode

        if exit_code != 0:
            error_type = _categorize_error(stderr_text, stdout_text)
            logger.error(
                "Claude Code failed (exit=%d, type=%s): %s",
                exit_code, error_type, stderr_text[:300],
            )
            return ClaudeResult(
                success=False,
                result=stdout_text,
                session_id=_extract_session_id(stdout_text, session_id),
                error=stderr_text or f"Exit code {exit_code}",
                error_type=error_type,
                exit_code=exit_code,
                cost_usd=0.0,
            )

        # Parse JSON output
        parsed = _parse_output(stdout_text)
        result_text = parsed.get("result", "")
        if not result_text and stdout_text:
            result_text = stdout_text

        return ClaudeResult(
            success=True,
            result=result_text,
            session_id=parsed.get("session_id", session_id),
            error=None,
            error_type=None,
            exit_code=0,
            cost_usd=parsed.get("cost_usd", 0.0),
        )

    except FileNotFoundError:
        return ClaudeResult(
            success=False,
            result="",
            session_id=None,
            error=f"Claude Code CLI not found at '{cli_path}'. Is it installed?",
            error_type="unknown",
            exit_code=-1,
            cost_usd=0.0,
        )
    except Exception as e:
        logger.exception("Unexpected error invoking Claude Code")
        return ClaudeResult(
            success=False,
            result="",
            session_id=session_id,
            error=str(e),
            error_type="unknown",
            exit_code=-1,
            cost_usd=0.0,
        )


def check_pipeline_leak(response: str) -> list[str]:
    """Post-query validation: detect if the agent tried to run the pipeline.

    Returns list of detected violations (empty = clean).
    """
    import re

    violations = []
    patterns = [
        (r"runner\.py\s+run\b", "runner.py run"),
        (r"runner\.py\s+regression\b", "runner.py regression"),
        (r"python\s+-m\s+argus\b", "python -m argus"),
        (r"\bargus\s+init\b", "argus init"),
        (r"\bargus\s+analyze\b", "argus analyze"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, response, re.IGNORECASE):
            violations.append(label)

    return violations


def _categorize_error(stderr: str, stdout: str) -> str:
    """Categorize error type from stderr/stdout content."""
    combined = (stderr + stdout).lower()

    if any(kw in combined for kw in ["auth", "unauthorized", "login", "credential", "token expired"]):
        return "auth"
    if any(kw in combined for kw in ["rate limit", "rate_limit", "429", "too many requests"]):
        return "rate_limit"
    if any(kw in combined for kw in ["context window", "context length", "too long", "token limit"]):
        return "context_full"
    return "unknown"


def _extract_session_id(output: str, fallback: str | None) -> str | None:
    """Try to extract session_id from partial JSON output."""
    try:
        data = json.loads(output)
        return data.get("session_id", fallback)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _parse_output(stdout: str) -> dict:
    """Parse Claude Code JSON output, handling malformed responses."""
    if not stdout:
        return {}

    try:
        data = json.loads(stdout)
        return data
    except json.JSONDecodeError:
        pass

    # Try to find JSON object boundaries
    for start in range(len(stdout)):
        if stdout[start] == "{":
            for end in range(len(stdout), start, -1):
                if stdout[end - 1] == "}":
                    try:
                        return json.loads(stdout[start:end])
                    except json.JSONDecodeError:
                        continue

    return {"result": stdout}


async def health_check(cli_path: str = "claude") -> tuple[bool, str]:
    """Quick health check — verify Claude Code auth works."""
    result = await invoke(
        prompt="Say exactly: OK",
        timeout=30,
        max_turns=1,
        allowed_tools="",
        cli_path=cli_path,
    )
    if result.success:
        return True, "Claude Code is authenticated and working"
    return False, result.error or "Unknown error"
