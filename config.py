"""Central configuration. Fail fast, fail loud."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model: str = "claude-sonnet-4-6"
    mock_mode: bool = True

    # Limits
    max_transcript_chars: int = 80_000     # ~20k tokens, well within context
    min_transcript_chars: int = 40
    max_agent_iterations: int = 15
    max_tickets_per_run: int = 25          # runaway guard
    api_max_retries: int = 4
    api_timeout_s: float = 120.0
    jira_timeout_s: float = 15.0
    jira_max_retries: int = 3
    max_sprint_issues: int = 100           # one page of the sprint board

    # Jira (only required when mock_mode is False)
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""


def make_settings(*, api_key: str, model: str = "claude-sonnet-4-6",
                  mock_mode: bool = True, jira_base_url: str = "",
                  jira_email: str = "", jira_api_token: str = "",
                  jira_project_key: str = "") -> Settings:
    """Build + validate Settings from explicit values (UI or env).

    Validates Jira credentials only when mock_mode is False.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        raise ConfigError("Anthropic API key is required — add it in Settings.")

    s = Settings(
        anthropic_api_key=api_key,
        model=(model or "claude-sonnet-4-6"),
        mock_mode=mock_mode,
        jira_base_url=(jira_base_url or "").strip().rstrip("/"),
        jira_email=(jira_email or "").strip(),
        jira_api_token=(jira_api_token or "").strip(),
        jira_project_key=(jira_project_key or "").strip(),
    )

    if not s.mock_mode:
        missing = [name for name, val in [
            ("Jira URL", s.jira_base_url),
            ("Jira email", s.jira_email),
            ("Jira API token", s.jira_api_token),
            ("Jira project key", s.jira_project_key),
        ] if not val]
        if missing:
            raise ConfigError(
                f"Real Jira mode needs: {', '.join(missing)}.")
        if not s.jira_base_url.startswith("https://"):
            raise ConfigError("Jira URL must start with https://")

    return s


def load_settings(api_key_override: str | None = None) -> Settings:
    """Build Settings from environment (.env), with optional key override."""
    return make_settings(
        api_key=api_key_override or os.getenv("ANTHROPIC_API_KEY", ""),
        model=os.getenv("MODEL", "claude-sonnet-4-6"),
        mock_mode=os.getenv("MOCK_MODE", "true").strip().lower() != "false",
        jira_base_url=os.getenv("JIRA_BASE_URL", ""),
        jira_email=os.getenv("JIRA_EMAIL", ""),
        jira_api_token=os.getenv("JIRA_API_TOKEN", ""),
        jira_project_key=os.getenv("JIRA_PROJECT_KEY", ""),
    )
