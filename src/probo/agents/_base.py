"""Shared plumbing for Probo's custom Harbor agents.

Harbor is an optional dependency of the package: with it installed the
agents are real ``harbor.agents.base.BaseAgent`` subclasses whose ``--ak``
options are validated by a pydantic ``options_model``; without it they still
import (unit tests, ``--help``) but cannot run inside a trial.
"""

from __future__ import annotations

import shlex
import tempfile
from pathlib import Path
from typing import Any, Protocol

try:  # Harbor 0.24.x
    from harbor.agents.base import BaseAgent as _HarborBaseAgent
    from harbor.agents.options import AgentOptions as AgentOptionsBase

    HARBOR_AVAILABLE = True
except Exception:  # noqa: BLE001 - harbor not installed
    HARBOR_AVAILABLE = False

    class AgentOptionsBase:  # type: ignore[no-redef]
        """Placeholder so option classes can be declared without Harbor."""

    class _HarborBaseAgent:  # type: ignore[no-redef]
        options_model = None

        def __init__(self, logs_dir: Any = None, model_name: str | None = None, **kwargs: Any) -> None:
            self.logs_dir = logs_dir
            self.model_name = model_name
            self.options = None


_FRAMEWORK_KEYS = {
    "logger",
    "mcp_servers",
    "skills_dir",
    "extra_env",
    "load_trajectory",
    "environment_logs_dir",
    "override_setup_timeout_sec",
}


class ExecResult(Protocol):
    return_code: int
    stdout: str
    stderr: str


class Environment(Protocol):
    async def exec(self, command: str, **kwargs: Any) -> ExecResult: ...


class ProboAgent(_HarborBaseAgent):
    """Base for the agents below. ``self.opts`` is a plain dict of the user
    options whatever the framework did with them, and ``commands_run`` records
    every command so a trial's agent log shows exactly what happened."""

    AGENT_NAME = "probo-agent"
    AGENT_VERSION = "0.1.0"

    def __init__(self, logs_dir: Any = None, model_name: str | None = None, **kwargs: Any) -> None:
        if logs_dir is None:  # only outside Harbor (tests); Harbor always passes it
            logs_dir = Path(tempfile.mkdtemp(prefix="probo-agent."))
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.commands_run: list[str] = []
        parsed = getattr(self, "options", None)
        if parsed is not None and hasattr(parsed, "model_dump"):
            self.opts: dict[str, Any] = dict(parsed.model_dump())
        else:
            self.opts = {k: v for k, v in kwargs.items() if k not in _FRAMEWORK_KEYS}

    @staticmethod
    def name() -> str:  # Harbor calls this on the class
        return ProboAgent.AGENT_NAME

    def version(self) -> str:
        return self.AGENT_VERSION

    async def setup(self, environment: Environment) -> None:
        return None

    async def sh(self, environment: Environment, command: str) -> ExecResult:
        self.commands_run.append(command)
        return await environment.exec(command=command)


def quote(text: str) -> str:
    return shlex.quote(text)
