"""Bounded local parser subprocess. Input is bytes on stdin, never executable instructions."""

import json
import resource
import sys
from dataclasses import asdict

resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))

from app.knowledge.parsing import ParseFailure, parse  # noqa: E402

try:
    content = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ParseFailure("FILE_TOO_LARGE")
    result = {"units": [asdict(unit) for unit in parse(content, sys.argv[1])]}
except ParseFailure as error:
    result = {"error": str(error)}
except Exception:
    result = {"error": "PARSER_FAILED"}
sys.stdout.write(json.dumps(result, ensure_ascii=False))
