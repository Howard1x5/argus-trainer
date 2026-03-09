"""Configuration loader — merges .env + config.yaml.

v2 changes: replaced sdk section with cli section, added max_pipeline_runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class TargetConfig:
    name: str
    repo_url: str
    local_path: Path
    venv_path: Path


@dataclass
class RunnerConfig:
    add_case: str
    run: str
    regression: str
    scores: str
    run_timeout: int = 1800
    extraction_timeout: int = 600


@dataclass
class CaseConfig:
    name: str
    walkthrough_url: str = ""
    status: str = "pending"


@dataclass
class BudgetConfig:
    max_per_cycle_usd: float = 5.0
    max_total_usd: float = 50.0
    warn_threshold_pct: float = 80.0


@dataclass
class CycleConfig:
    max_pipeline_runs: int = 2
    min_improvement: float = 2.0
    target_score: float = 95.0


@dataclass
class ApprovalConfig:
    poll_interval: int = 60
    auto_approve: bool = False
    approval_timeout: int = 0


@dataclass
class SyncConfig:
    """Sync approved ARGUS changes back to workstation."""
    enabled: bool = False
    remote_host: str = ""  # e.g., "user@training-vm"
    remote_port: int = 22
    remote_argus_path: str = "/opt/argus"
    local_argus_path: str = ""  # path to local ARGUS repo on workstation
    # Only sync these paths (source code, not evidence/cases)
    include_paths: list[str] | None = None


@dataclass
class GitConfig:
    branch_pattern: str = "training/cycle-{cycle}-{case}"
    auto_commit: bool = True


@dataclass
class CliConfig:
    """Claude Code CLI configuration."""
    cli_path: str = "claude"
    default_timeout: int = 300
    max_timeout: int = 900
    max_turns: int = 50
    allowed_tools: str = "Read,Write,Edit,Bash,Glob,Grep"


@dataclass
class LoggingConfig:
    tool_log: str = "logs/tool_use.jsonl"
    level: str = "INFO"


@dataclass
class Config:
    target: TargetConfig
    runner: RunnerConfig
    cases: list[CaseConfig]
    budget: BudgetConfig
    cycles: CycleConfig
    approval: ApprovalConfig
    git: GitConfig
    cli: CliConfig
    sync: SyncConfig
    logging: LoggingConfig

    # From .env
    anthropic_api_key: str = ""  # Only needed if switching back to SDK
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Derived
    project_root: Path = field(default_factory=lambda: Path.cwd())

    @property
    def cli_path(self) -> str:
        return self.cli.cli_path

    @property
    def state_dir(self) -> Path:
        return self.project_root / "state"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"


def load_config(
    config_path: str | Path = "config.yaml",
    env_path: str | Path | None = None,
    project_root: Path | None = None,
) -> Config:
    """Load configuration from .env and config.yaml."""
    if project_root is None:
        project_root = Path.cwd()

    # Load .env
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv(project_root / ".env")

    # Load YAML
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = project_root / config_file

    with open(config_file) as f:
        raw = yaml.safe_load(f)

    target_raw = raw.get("target", {})
    runner_raw = raw.get("runner", {})
    cases_raw = raw.get("cases", [])
    budget_raw = raw.get("budget", {})
    cycles_raw = raw.get("cycles", {})
    approval_raw = raw.get("approval", {})
    git_raw = raw.get("git", {})
    cli_raw = raw.get("cli", {})
    sync_raw = raw.get("sync", {})
    logging_raw = raw.get("logging", {})

    # Backwards compat: old 'sdk' section had cli_path
    if not cli_raw and "sdk" in raw:
        sdk_raw = raw["sdk"]
        cli_raw = {"cli_path": sdk_raw.get("cli_path", "claude")}

    return Config(
        target=TargetConfig(
            name=target_raw.get("name", "argus"),
            repo_url=target_raw.get("repo_url", ""),
            local_path=Path(target_raw.get("local_path", "/opt/argus")),
            venv_path=Path(target_raw.get("venv_path", "/opt/argus/.venv")),
        ),
        runner=RunnerConfig(
            add_case=runner_raw.get("add_case", ""),
            run=runner_raw.get("run", ""),
            regression=runner_raw.get("regression", ""),
            scores=runner_raw.get("scores", ""),
            run_timeout=runner_raw.get("run_timeout", 1800),
            extraction_timeout=runner_raw.get("extraction_timeout", 600),
        ),
        cases=[
            CaseConfig(
                name=c.get("name", ""),
                walkthrough_url=c.get("walkthrough_url", ""),
                status=c.get("status", "pending"),
            )
            for c in cases_raw
        ],
        budget=BudgetConfig(**budget_raw) if budget_raw else BudgetConfig(),
        cycles=CycleConfig(**{
            k: v for k, v in cycles_raw.items()
            if k in CycleConfig.__dataclass_fields__
        }) if cycles_raw else CycleConfig(),
        approval=ApprovalConfig(**approval_raw) if approval_raw else ApprovalConfig(),
        git=GitConfig(**git_raw) if git_raw else GitConfig(),
        cli=CliConfig(**{
            k: v for k, v in cli_raw.items()
            if k in CliConfig.__dataclass_fields__
        }) if cli_raw else CliConfig(),
        sync=SyncConfig(**{
            k: v for k, v in sync_raw.items()
            if k in SyncConfig.__dataclass_fields__
        }) if sync_raw else SyncConfig(),
        logging=LoggingConfig(**logging_raw) if logging_raw else LoggingConfig(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        project_root=project_root,
    )
