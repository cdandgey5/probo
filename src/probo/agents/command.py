"""A generic command-template agent (ROADMAP.md, agent integration ADR).

Runs any command-line tool already installed in the task image as a black
box. The instruction is written to a file inside the container and the
command template is expanded with:

* ``{instruction_file}``: path of that file (``/tmp/probo-instruction.md``);
* ``{instruction}``: the instruction text, shell-quoted;
* ``{app_dir}``: the working directory (``/app``).

Example, a team's own CLI:

    uv run probo run <task> -a probo.agents.command:CommandAgent \\
      --ak command='my-agent --repo {app_dir} --task-file {instruction_file}'

Options: ``command`` (required), ``app_dir`` (default ``/app``), ``env``
(``KEY=VALUE,KEY2=VALUE2``, exported before the command).
"""

from __future__ import annotations

from typing import Any

from probo.agents._base import HARBOR_AVAILABLE, AgentOptionsBase, Environment, ProboAgent, quote

INSTRUCTION_FILE = "/tmp/probo-instruction.md"


def expand(
    template: str, instruction: str, app_dir: str = "/app", instruction_file: str = INSTRUCTION_FILE
) -> str:
    return template.format(instruction_file=instruction_file, instruction=quote(instruction), app_dir=app_dir)


def write_instruction_command(instruction: str, instruction_file: str = INSTRUCTION_FILE) -> str:
    return f"printf '%s' {quote(instruction)} > {instruction_file}"


if HARBOR_AVAILABLE:

    class CommandOptions(AgentOptionsBase):  # type: ignore[misc,valid-type]
        command: str = ""
        app_dir: str = "/app"
        env: str = ""


class CommandAgent(ProboAgent):
    AGENT_NAME = "command"
    AGENT_VERSION = "0.1.0"
    if HARBOR_AVAILABLE:
        options_model = CommandOptions

    @staticmethod
    def name() -> str:
        return CommandAgent.AGENT_NAME

    async def run(self, instruction: str, environment: Environment, context: Any = None) -> None:
        template = str(self.opts.get("command") or "")
        if not template:
            raise ValueError("CommandAgent needs --ak command='...'")
        app_dir = str(self.opts.get("app_dir") or "/app")
        await self.sh(environment, write_instruction_command(instruction))
        env_pairs = str(self.opts.get("env") or "")
        exports = ""
        if env_pairs:
            exports = (
                " ".join("export " + quote(p.strip()) + ";" for p in env_pairs.split(",") if p.strip()) + " "
            )
        command = f"cd {app_dir} && {exports}{expand(template, instruction, app_dir)}"
        result = await self.sh(environment, command)
        if result.return_code != 0:
            # The agent failing is a graded outcome, not a harness error: the
            # verifier still grades whatever it left behind.
            self.commands_run.append(f"# exit code {result.return_code}")
