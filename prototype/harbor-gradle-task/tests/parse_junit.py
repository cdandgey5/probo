"""Parse Gradle JUnit XML reports and print one JSON object.

usage: parse_junit.py RESULTS_DIR EXPECTED_TESTS_FILE TARGET_TEST

RESULTS_DIR         build/test-results/test (may not exist on build failure)
EXPECTED_TESTS_FILE one classname#name per line; a listed test that is
                    missing from the reports counts as not passed
TARGET_TEST         classname#name of the fail-to-pass test

Exit status is always 0; the shell decides the verdict from the JSON.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def normalize(test_id: str) -> str:
    """Gradle writes JUnit 5 method names with trailing parentheses, e.g.
    ``fullDiscountYieldsZero()``; the task metadata lists them without."""
    test_id = test_id.strip()
    if test_id.endswith("()"):
        test_id = test_id[:-2]
    return test_id


def main() -> None:
    results_dir = Path(sys.argv[1])
    expected = [
        normalize(line)
        for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = normalize(sys.argv[3])

    status = {}
    reports = sorted(results_dir.glob("TEST-*.xml")) if results_dir.is_dir() else []
    for report in reports:
        try:
            root = ET.parse(report).getroot()
        except ET.ParseError as exc:
            print("warning: could not parse %s: %s" % (report, exc), file=sys.stderr)
            continue
        for case in root.iter("testcase"):
            key = normalize("%s#%s" % (case.get("classname"), case.get("name")))
            if case.find("failure") is not None:
                status[key] = "failed"
            elif case.find("error") is not None:
                status[key] = "error"
            elif case.find("skipped") is not None:
                status[key] = "skipped"
            else:
                status[key] = "passed"

    missing = [t for t in expected if t not in status]
    not_passed = [t for t in expected if status.get(t) != "passed"]
    p2p_not_passed = [t for t in not_passed if t != target]
    out = {
        "reports": len(reports),
        "tests_seen": len(status),
        "target": target,
        "target_status": status.get(target, "missing"),
        "expected": len(expected),
        "n_missing": len(missing),
        "n_p2p_not_passed": len(p2p_not_passed),
        "missing": missing,
        "not_passed": not_passed,
        "p2p_not_passed": p2p_not_passed,
        "status": status,
    }
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
