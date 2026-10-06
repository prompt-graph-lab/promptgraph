"""Test-only stdio subprocess for the real Named Pipe gateway integration."""

import json
import os
from pathlib import Path
import sys

import anyio

from agent_adapters.mcp_named_pipe_gateway import serve_stdio_over_named_pipe


def main():
    if len(sys.argv) != 2:
        raise SystemExit("a protected descriptor path is required")
    shutdown = "raised"
    try:
        anyio.run(serve_stdio_over_named_pipe, sys.argv[1])
        shutdown = "returned"
    finally:
        report = os.environ.get("PROMPTGRAPH_TEST_GATEWAY_REPORT")
        if report:
            Path(report).write_text(
                json.dumps({"shutdown": shutdown}, sort_keys=True),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
