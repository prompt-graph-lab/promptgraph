"""Subprocess coverage for PromptGraph's official MCP stdio transport."""

import asyncio
import ctypes
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from agent_adapters import mcp_adapter
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_SERVER = _REPO_ROOT / "tests" / "fixtures" / "mcp_stdio_test_server.py"


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
        module_library={
            "source": {"body": "red, blue", "core_tokens": ["red", "blue"]},
            "target": {"body": "gold, green"},
        },
        attribute_groups={},
    ))


def _stdio_transport(parameters: StdioServerParameters):
    @asynccontextmanager
    async def transport():
        async with stdio_client(parameters) as streams:
            yield streams

    return transport()


def _assert_plain_json(value: Any) -> None:
    if value is None or type(value) in (bool, int, float, str):
        return
    if type(value) is list:
        for child in value:
            _assert_plain_json(child)
        return
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            _assert_plain_json(child)
        return
    raise AssertionError(f"non-JSON value crossed MCP boundary: {type(value)!r}")


def _windows_process_is_alive(pid: int) -> bool:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_exit_code.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        error = ctypes.get_last_error()
        if error in (87, 1168):  # ERROR_INVALID_PARAMETER / ERROR_NOT_FOUND
            return False
        raise ctypes.WinError(error)
    try:
        exit_code = wintypes.DWORD()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        close_handle(handle)


def _process_is_alive(pid: int) -> bool:
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_process_exits(pid: int, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_is_alive(pid):
            return True
        time.sleep(0.02)
    return not _process_is_alive(pid)


def test_stdio_subprocess_serves_catalog_tools_and_shuts_down_cleanly(tmp_path):
    pid_marker = tmp_path / "server.pid"
    report_path = tmp_path / "server-report.json"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(_TEST_SERVER)],
        cwd=str(_REPO_ROOT),
        env={
            "PYTHONPATH": str(_REPO_ROOT),
            "PROMPTGRAPH_TEST_STDIO_PID_FILE": str(pid_marker),
            "PROMPTGRAPH_TEST_STDIO_REPORT_FILE": str(report_path),
        },
    )

    request = {
        "illustration_ids": ["illustration-1"],
        "find_text": "red",
        "replace_text": "gold",
    }
    expected_adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: _project())

    async def exercise() -> None:
        async with asyncio.timeout(30):
            async with Client(
                _stdio_transport(parameters),
                read_timeout_seconds=5,
            ) as client:
                listed = await client.list_tools()
                catalog = mcp_adapter.get_tool_catalog()
                assert [tool.name for tool in listed.tools] == [
                    entry["name"] for entry in catalog
                ]
                assert len({tool.name for tool in listed.tools}) == 9
                assert all("apply" not in tool.name.casefold() for tool in listed.tools)
                for registered, entry in zip(listed.tools, catalog, strict=True):
                    assert registered.description == entry["description"]
                    assert registered.input_schema == entry["inputSchema"]
                    assert registered.meta == {"promptgraph/effect": entry["effect"]}

                calls = [
                    ("promptgraph_capabilities", {}),
                    ("promptgraph_project_summary", {}),
                    ("promptgraph_list_scenes", {"limit": 10}),
                    ("promptgraph_list_illustrations", {}),
                    ("promptgraph_search_illustrations", {"query_text": "red"}),
                    (
                        "promptgraph_get_illustration",
                        {"illustration_id": "illustration-1"},
                    ),
                    ("promptgraph_preview_batch_replace", request),
                    ("promptgraph_preview_scene_module_swap", {
                        "scene_id": "scene-1", "source_module_name": "source",
                        "target_module_name": "target",
                    }),
                ]
                expected_results = [
                    expected_adapter.call_tool(name, arguments)
                    for name, arguments in calls
                ]
                results = []
                for (name, arguments), expected in zip(
                    calls,
                    expected_results,
                    strict=True,
                ):
                    result = await client.call_tool(name, arguments)
                    assert result.is_error is False
                    payload = result.structured_content
                    _assert_plain_json(payload)
                    assert json.loads(result.content[0].text) == payload
                    assert payload == expected
                    results.append(payload)

                # The first Scene observation retains baseline Illustrations
                # before any separator with scene_id=null, as owned by facade.
                illustrations = results[3]["illustrations"]
                assert illustrations[0]["illustration_id"] == "baseline"
                assert illustrations[0]["scene_id"] is None
                assert [scene["label"]["text"] for scene in results[2]["scenes"]] == [
                    "First Scene",
                    "Empty Scene",
                ]
                assert results[6] == expected_results[6]
                assert results[7]["valid"] is True
                assert results[7]["operation"] == "scene_module_swap"

                repeated_preview = await client.call_tool(
                    "promptgraph_preview_batch_replace",
                    request,
                )
                assert repeated_preview.structured_content == expected_results[6]

                # Low-level SDK transport reaches the adapter's bounded shape
                # error; this malformed request does not become a Project call.
                malformed = await client.call_tool(
                    "promptgraph_preview_batch_replace",
                    {"illustration_ids": ["illustration-1"]},
                )
                assert malformed.structured_content["reason"] == "invalid_arguments"
                assert malformed.is_error is True

                unknown_id = await client.call_tool(
                    "promptgraph_get_illustration",
                    {"illustration_id": "not-present"},
                )
                assert unknown_id.structured_content["reason"] == "unknown_illustration_id"
                assert unknown_id.is_error is True

                denied_apply = await client.call_tool(
                    "promptgraph_apply_batch_replace",
                    {"plan": {"plan_id": "not-an-approval"}},
                )
                assert denied_apply.structured_content["reason"] == "unknown_tool"
                assert denied_apply.is_error is True

                provider_failed = await client.call_tool(
                    "promptgraph_project_summary",
                    {},
                )
                assert provider_failed.structured_content["reason"] == "project_provider_failed"
                assert provider_failed.is_error is True
                assert "private stdio fixture" not in provider_failed.content[0].text

                for failed_result in (malformed, unknown_id, denied_apply, provider_failed):
                    _assert_plain_json(failed_result.structured_content)
                    assert json.loads(failed_result.content[0].text) == failed_result.structured_content

    asyncio.run(exercise())

    pid = int(pid_marker.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["pid"] == pid
    assert report["shutdown"] == "returned"
    assert report["project_unchanged"] is True
    assert report["provider_calls"] == 10
    assert report["line_texts"] == [
        {"id": "baseline", "text": "baseline prompt"},
        {"id": "scene-1", "text": "First Scene"},
        {"id": "illustration-1", "text": "red, blue"},
        {"id": "scene-2", "text": "Empty Scene"},
    ]
    assert _wait_until_process_exits(pid), f"MCP server subprocess {pid} remained alive"
