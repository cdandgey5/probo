"""A stand-in for the Gradle binary used by the grader's end-to-end tests.

It never compiles anything. It reads the project handed to it with ``-p`` and
writes the JUnit XML a real run would have produced for the fixture project:

* if ``src/main/kotlin/Calc.kt`` is missing, main "compiles" but the tests do
  not (the hidden tests reference it): prints a test-compile failure;
* if the main file contains ``BROKEN``, prints a main-compile failure;
* if the test file contains ``fullDiscountYieldsZero`` and the main file
  contains ``coerceIn(0, 100)`` every test passes, otherwise that test fails;
* ``FAKE_GRADLE_SLEEP`` seconds of sleep first (timeout tests);
* ``FAKE_GRADLE_OOM=1`` prints an OOM signature and exits 137 with no reports.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

CLS = "com.example.pricing.DiscountCalculatorTest"
TESTS = ["halfDiscountHalvesPrice", "fullDiscountYieldsZero", "zeroDiscountKeepsPrice"]


def main(argv: list[str]) -> int:
    if os.environ.get("FAKE_GRADLE_SLEEP"):
        time.sleep(float(os.environ["FAKE_GRADLE_SLEEP"]))
    if os.environ.get("FAKE_GRADLE_OOM"):
        print("Gradle build daemon disappeared unexpectedly (it may have been killed or may have crashed)")
        return 137
    app = Path(argv[argv.index("-p") + 1])
    tasks = [a for a in argv if a.startswith(":")]
    print("> Task :compileKotlin")
    main_file = app / "src" / "main" / "kotlin" / "Calc.kt"
    test_file = app / "src" / "test" / "kotlin" / "CalcTest.kt"
    if main_file.is_file() and "BROKEN" in main_file.read_text("utf-8"):
        print("> Task :compileKotlin FAILED")
        print("e: file:///app/src/main/kotlin/Calc.kt:1:1 Expecting an element")
        print("Execution failed for task ':compileKotlin'.")
        return 1
    if not main_file.is_file():
        print("> Task :compileTestKotlin FAILED")
        print("e: Unresolved reference 'DiscountCalculator'")
        print("Execution failed for task ':compileTestKotlin'.")
        return 1
    fixed = "coerceIn(0, 100)" in main_file.read_text("utf-8")
    hidden = test_file.is_file() and "fullDiscountYieldsZero" in test_file.read_text("utf-8")
    for task in tasks:
        name = task.rsplit(":", 1)[-1]
        out = app / "build" / "test-results" / name
        out.mkdir(parents=True, exist_ok=True)
        cases = []
        for t in TESTS:
            if t == "fullDiscountYieldsZero" and not hidden:
                continue
            if t == "fullDiscountYieldsZero" and not fixed:
                cases.append(
                    f'<testcase name="{t}()" classname="{CLS}"><failure message="expected 0 but was 2"/></testcase>'
                )
            else:
                cases.append(f'<testcase name="{t}()" classname="{CLS}"/>')
        (out / f"TEST-{CLS}.xml").write_text(
            '<?xml version="1.0"?>\n<testsuite name="{}">\n{}\n</testsuite>\n'.format(CLS, "\n".join(cases)),
            encoding="utf-8",
        )
        print(f"> Task {task}" + ("" if fixed or not hidden else " FAILED"))
    if hidden and not fixed:
        print("Execution failed for task ':test'.")
        return 1
    print("BUILD SUCCESSFUL in 1s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
