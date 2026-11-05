"""Optional developer-only pytest plugin. Writes outcomes, never captured private output."""

import json
import os
from pathlib import Path

outcomes = {}


def pytest_runtest_logreport(report):
    node = report.nodeid.split("peclaw/")[-1]
    row = outcomes.setdefault(node, {"outcome": "not_run", "duration_seconds": 0})
    row["duration_seconds"] += report.duration
    if report.failed:
        row["outcome"] = "failed"
    elif report.skipped and row["outcome"] != "failed":
        row["outcome"] = "skipped"
    elif report.when == "call" and row["outcome"] not in {"failed", "skipped"}:
        row["outcome"] = "passed"


def pytest_sessionfinish(session, exitstatus):
    target = os.environ.get("PECLAW_DEMO_OUTCOMES")
    if target:
        Path(target).write_text(
            json.dumps({"exit_code": int(exitstatus), "tests": outcomes}, indent=2)
        )
