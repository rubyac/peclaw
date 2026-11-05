"""Operator command: actual eight-demo regression with honest protocol/live distinctions."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.demos import DEMOS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = next(
        (p for p in Path(__file__).resolve().parents if (p / "tests/conftest.py").exists()), None
    )
    if repo is None:
        parser.error(
            "Requires a full development checkout and dev dependencies; "
            "not a production HTTP capability."
        )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    outcomes_path = output / "test-outcomes.json"
    outcomes_path.unlink(missing_ok=True)
    env = dict(os.environ, PECLAW_DEMO_OUTCOMES=str(outcomes_path))
    nodes = list(dict.fromkeys(node for d in DEMOS for node in d["nodes"]))
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "app.evaluation.pytest_recorder",
        *[
            str(repo / node.split("::")[0]) + "::" + "::".join(node.split("::")[1:])
            for node in nodes
        ],
    ]
    run = subprocess.run(command, cwd=repo / "services/api", env=env, check=False)
    results = (
        json.loads(outcomes_path.read_text())
        if outcomes_path.exists()
        else {"tests": {}, "exit_code": run.returncode}
    )
    tests = results["tests"]
    demos = []
    for demo in DEMOS:
        rows = []
        for node in demo["nodes"]:
            row = next(
                (value for key, value in tests.items() if key.endswith(node)),
                {"outcome": "not_run"},
            )
            rows.append({"node": node, **row})
        passed = all(row["outcome"] == "passed" for row in rows)
        demos.append(
            {
                **demo,
                "results": rows,
                "regression_status": "passed" if passed else "incomplete_or_failed",
                "live_business_status": "not_evaluated",
                "evidence_scope": demo["scope"],
            }
        )
    final_exit = run.returncode or (
        0 if all(d["regression_status"] == "passed" for d in demos) else 1
    )
    paths = sorted(
        [
            *(repo / "services/api/app").rglob("*.py"),
            *(repo / "services/api/alembic").rglob("*.py"),
            *(repo / "tests").rglob("*.py"),
            repo / "services/api/uv.lock",
        ]
    )
    code_hash = hashlib.sha256()
    for path in paths:
        code_hash.update(str(path.relative_to(repo)).encode())
        code_hash.update(path.read_bytes())
    manifest = {
        "schema_version": "eight-demos@1.0.0",
        "data_kind": "synthetic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": final_exit,
        "code_hash": code_hash.hexdigest(),
        "python_version": sys.version.split()[0],
        "demos": demos,
        "limitations": [
            (
                "Fixture-driven engineering regressions; "
                "no real customer pilot or external model evaluation."
            ),
            (
                "Protocol-only demos use explicitly synthetic HTTP provider responses, "
                "never presented as live analysis."
            ),
            (
                "A passing timeout/denial test validates the guard, "
                "not production availability or financial truth."
            ),
        ],
    }
    (output / "eight-demos.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    lines = [
        "# 八项演示回归证据",
        "",
        "数据：合成；真实业务效果：未评测。",
        "",
        "| 演示 | 实际回归 | 证据范围 |",
        "|---|---|---|",
    ]
    for demo in demos:
        lines.append(
            f"| {demo['title']} | {demo['regression_status']} | {demo['evidence_scope']} |"
        )
    (output / "README.md").write_text("\n".join(lines) + "\n")
    print("Demo manifest:", output / "eight-demos.json")
    return final_exit


if __name__ == "__main__":
    raise SystemExit(main())
