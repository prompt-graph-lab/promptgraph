"""Test-only subprocess host for exercising the real MCP stdio transport."""

import copy
import json
import os
from pathlib import Path

import anyio

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from agent_adapters.mcp_stdio_runner import serve_stdio
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine


def _line(line_id: str, text: str, *, line_type: str | None = None) -> PromptLine:
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=parse_prompt(text),
        line_type=line_type,
    )


def _project() -> Project:
    return build_graph(Project(
        prompt_lines=[
            _line("baseline", "baseline prompt"),
            _line("scene-1", "First Scene", line_type="separator"),
            _line("illustration-1", "red, blue"),
            _line("scene-2", "Empty Scene", line_type="separator"),
        ],
        module_library={},
        attribute_groups={},
    ))


def main() -> None:
    project = _project()
    original_project = copy.deepcopy(project)
    provider_calls = 0

    def project_provider() -> Project:
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 8:
            raise RuntimeError("private stdio fixture diagnostic")
        return project

    adapter = PromptGraphMCPAdapter(project_provider)
    pid_marker = os.environ.get("PROMPTGRAPH_TEST_STDIO_PID_FILE")
    report_path = os.environ.get("PROMPTGRAPH_TEST_STDIO_REPORT_FILE")
    if pid_marker:
        Path(pid_marker).write_text(str(os.getpid()), encoding="utf-8")

    shutdown = "returned"
    try:
        anyio.run(serve_stdio, adapter)
    except BaseException:
        shutdown = "raised"
        raise
    finally:
        if report_path:
            report = {
                "pid": os.getpid(),
                "provider_calls": provider_calls,
                "shutdown": shutdown,
                "project_unchanged": project == original_project,
                "line_texts": [
                    {"id": line.id, "text": line.current_text}
                    for line in project.prompt_lines
                ],
            }
            Path(report_path).write_text(
                json.dumps(report, sort_keys=True),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()