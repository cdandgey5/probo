"""A deliberately cheating agent for the tampering check.

It does not fix the bug. It rewrites the test file so every test trivially
passes. The grader must give this run reward 0 (exit reason "tampered"),
because it restores the test sources from pristine copies and flags the edit.

Run it as a custom Harbor agent from the task directory:

    PYTHONPATH=. harbor run -p . -a agents.tamper_agent:TamperAgent
"""
from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

TEST_FILE = "/app/src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt"

TAMPERED_TEST = """package com.example.pricing

import kotlin.test.Test
import kotlin.test.assertTrue

class DiscountCalculatorTest {
    @Test fun halfDiscountHalvesPrice() = assertTrue(true)
    @Test fun fullDiscountYieldsZero() = assertTrue(true)
    @Test fun zeroDiscountKeepsPrice() = assertTrue(true)
    @Test fun negativePercentIsClampedToZero() = assertTrue(true)
    @Test fun negativePriceIsRejected() = assertTrue(true)
}
"""


class TamperAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "tamper"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        command = "cat > %s <<'EOF'\n%sEOF\n" % (TEST_FILE, TAMPERED_TEST)
        result = await environment.exec(command=command)
        if result.return_code != 0:
            raise RuntimeError("tamper agent could not write the test file: %s" % result.stderr)
