"""Tests for configuration loading."""

import pytest
from pathlib import Path

from trainer.config import load_config


@pytest.fixture
def config_dir(tmp_path):
    """Create a minimal config setup for testing."""
    config = tmp_path / "config.yaml"
    config.write_text("""
target:
  name: test-project
  repo_url: https://example.com/repo.git
  local_path: /opt/test
  venv_path: /opt/test/.venv

runner:
  add_case: "python runner.py add-case"
  run: "python runner.py run"
  regression: "python runner.py regression"
  scores: "python runner.py scores"

cases:
  - name: testcase1
    status: active
  - name: testcase2
    walkthrough_url: https://example.com/walkthrough
    status: pending

budget:
  max_per_cycle_usd: 3.00
  max_total_usd: 25.00

cycles:
  max_cycles_per_case: 3
  target_score: 90.0
""")

    env = tmp_path / ".env"
    env.write_text("""
ANTHROPIC_API_KEY=sk-test-key
TELEGRAM_BOT_TOKEN=test-token
TELEGRAM_CHAT_ID=12345
""")

    return tmp_path


class TestConfig:
    def test_loads_yaml(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert config.target.name == "test-project"
        assert config.target.local_path == Path("/opt/test")

    def test_loads_env(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert config.anthropic_api_key == "sk-test-key"
        assert config.telegram_bot_token == "test-token"
        assert config.telegram_chat_id == "12345"

    def test_cases_parsed(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert len(config.cases) == 2
        assert config.cases[0].name == "testcase1"
        assert config.cases[0].status == "active"
        assert config.cases[1].walkthrough_url == "https://example.com/walkthrough"

    def test_budget_config(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert config.budget.max_per_cycle_usd == 3.0
        assert config.budget.max_total_usd == 25.0

    def test_cycle_config(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert config.cycles.max_cycles_per_case == 3
        assert config.cycles.target_score == 90.0

    def test_derived_paths(self, config_dir):
        config = load_config(
            config_path=config_dir / "config.yaml",
            env_path=config_dir / ".env",
            project_root=config_dir,
        )
        assert config.state_dir == config_dir / "state"
        assert config.logs_dir == config_dir / "logs"
