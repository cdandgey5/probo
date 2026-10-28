"""The reference agents, against a fake Harbor environment."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from probo.agents.command import INSTRUCTION_FILE, CommandAgent, expand, write_instruction_command
from probo.agents.saboteur import MODES, Saboteur, commands_for


@dataclass
class Result:
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeEnvironment:
    def __init__(self, fail_on: str | None = None):
        self.commands: list[str] = []
        self.fail_on = fail_on

    async def exec(self, command: str, **kwargs: object) -> Result:
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            return Result(return_code=1, stderr="boom")
        return Result()


def test_saboteur_modes_touch_only_protected_files() -> None:
    for mode in MODES:
        cmds = commands_for(mode)
        assert cmds and all(c.startswith("cd /app && ") for c in cmds)
    assert "src/test" in commands_for("edit_tests")[0]
    assert "rm -f" in commands_for("delete_tests")[0]
    assert "enabled = false" in commands_for("disable_tests")[0]
    assert "init.gradle.kts" in commands_for("init_script")[0]
    assert "gradlew" in commands_for("wrapper")[0]
    with pytest.raises(ValueError):
        commands_for("fix_the_bug")


def test_saboteur_runs_its_mode() -> None:
    agent = Saboteur(mode="delete_tests")
    assert Saboteur.name() == "saboteur" and agent.version() == "0.2.0"
    env = FakeEnvironment()
    asyncio.run(agent.run("fix it", env))
    assert env.commands == commands_for("delete_tests")
    assert agent.commands_run == env.commands
    default = Saboteur()
    assert default.mode == "edit_tests"
    failing = FakeEnvironment(fail_on="find .")
    with pytest.raises(RuntimeError):
        asyncio.run(default.run("fix it", failing))


def test_command_agent_expands_template_and_records_exit() -> None:
    assert expand("tool --f {instruction_file} --p {instruction} -C {app_dir}", "do it", "/app") == (
        f"tool --f {INSTRUCTION_FILE} --p 'do it' -C /app"
    )
    assert write_instruction_command("a'b").startswith("printf '%s' 'a'\"'\"'b' > ")
    agent = CommandAgent(command="my-cli --task {instruction_file}", env="A=1, B=two")
    env = FakeEnvironment()
    asyncio.run(agent.run("Fix the bug", env))
    assert env.commands[0].startswith("printf '%s' 'Fix the bug' > /tmp/probo-instruction.md")
    assert env.commands[1] == "cd /app && export A=1; export B=two; my-cli --task /tmp/probo-instruction.md"
    failing = FakeEnvironment(fail_on="my-cli")
    agent2 = CommandAgent(command="my-cli {instruction_file}")
    asyncio.run(agent2.run("x", failing))
    assert agent2.commands_run[-1] == "# exit code 1"
    with pytest.raises(ValueError):
        asyncio.run(CommandAgent().run("x", FakeEnvironment()))


def test_agents_are_harbor_base_agents_when_harbor_is_installed() -> None:
    try:
        from harbor.agents.base import BaseAgent
    except Exception:  # noqa: BLE001
        pytest.skip("harbor not installed")
    assert issubclass(Saboteur, BaseAgent) and issubclass(CommandAgent, BaseAgent)
