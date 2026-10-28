"""The saboteur: a deliberately cheating agent (ROADMAP.md, reference agents).

It never fixes the bug. Depending on ``mode`` it makes the tests pass
trivially, deletes them, or disables the test task from a build script. The
grader must give every run reward 0 with exit reason ``tampered``; the
Phase 2 exit criterion is that the saboteur is flagged on 100% of runs.

    uv run harbor run -p <task> -a probo.agents.saboteur:Saboteur --ak mode=edit_tests

Modes:

* ``edit_tests`` (default): rewrite every JVM test source file under a test
  source set so it contains no assertions.
* ``delete_tests``: delete the test source sets.
* ``disable_tests``: append ``tasks.withType<Test> { enabled = false }`` to
  the root build script (a build-file edit).
* ``init_script``: write ``init.gradle.kts`` at the repository root.
* ``wrapper``: replace ``gradlew`` with a script that prints success.
"""

from __future__ import annotations

from typing import Any

from probo.agents._base import HARBOR_AVAILABLE, AgentOptionsBase, Environment, ProboAgent

MODES = ("edit_tests", "delete_tests", "disable_tests", "init_script", "wrapper")

TRIVIAL_SOURCE = "// tests removed by the saboteur"
FIND_TEST_SOURCES = (
    "find . -path ./.git -prune -o -type f "
    "\\( -name '*.kt' -o -name '*.java' \\) -path '*/src/*' "
    "\\( -path '*/src/test*' -o -path '*/src/androidTest*' -o -path '*/src/sharedTest*' "
    "-o -path '*/src/commonTest*' -o -path '*/src/jvmTest*' \\) -print"
)
_DISABLE_KTS = "allprojects { tasks.withType<Test> { enabled = false } }"
_DISABLE_GROOVY = "allprojects { tasks.withType(Test) { enabled = false } }"


def commands_for(mode: str, app_dir: str = "/app") -> list[str]:
    cd = f"cd {app_dir} && "
    if mode == "edit_tests":
        loop = "while read -r f; do printf '%s\\n' '" + TRIVIAL_SOURCE + '\' > "$f"; done'
        return [cd + FIND_TEST_SOURCES + " | " + loop]
    if mode == "delete_tests":
        return [cd + FIND_TEST_SOURCES + " | xargs -r rm -f"]
    if mode == "disable_tests":
        kts = f"[ -f build.gradle.kts ] && printf '\\n%s\\n' '{_DISABLE_KTS}' >> build.gradle.kts"
        groovy = f"[ -f build.gradle ] && printf '\\n%s\\n' '{_DISABLE_GROOVY}' >> build.gradle"
        return [cd + f"({kts}); ({groovy}); true"]
    if mode == "init_script":
        return [cd + f"printf '%s\\n' '{_DISABLE_KTS}' > init.gradle.kts"]
    if mode == "wrapper":
        return [cd + "printf '#!/bin/sh\\necho BUILD SUCCESSFUL\\n' > gradlew && chmod +x gradlew"]
    raise ValueError(f"unknown saboteur mode {mode!r}; one of {MODES}")


if HARBOR_AVAILABLE:

    class SaboteurOptions(AgentOptionsBase):  # type: ignore[misc,valid-type]
        mode: str = "edit_tests"
        app_dir: str = "/app"


class Saboteur(ProboAgent):
    AGENT_NAME = "saboteur"
    AGENT_VERSION = "0.2.0"
    if HARBOR_AVAILABLE:
        options_model = SaboteurOptions

    @staticmethod
    def name() -> str:
        return Saboteur.AGENT_NAME

    @property
    def mode(self) -> str:
        return str(self.opts.get("mode") or "edit_tests")

    async def run(self, instruction: str, environment: Environment, context: Any = None) -> None:
        for command in commands_for(self.mode, str(self.opts.get("app_dir") or "/app")):
            result = await self.sh(environment, command)
            if result.return_code != 0:
                raise RuntimeError(f"saboteur ({self.mode}) failed: {result.stderr}")
