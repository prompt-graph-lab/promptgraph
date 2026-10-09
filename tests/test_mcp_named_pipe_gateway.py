"""Focused tests for the stdio-to-Named-Pipe MCP gateway boundary."""

import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import threading

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from streamlit.testing.v1.util import patch_config_options

from agent_adapters import mcp_adapter, mcp_sdk_binding
from agent_adapters.mcp_named_pipe_gateway import (
    GATEWAY_CONTRACT_VERSION,
    NamedPipeMCPToolCaller,
)
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui.project_agent_named_pipe import WindowsNamedPipeBroker
from ui import project_agent_request_bridge
from ui.project_agent_session_pump import (
    ProjectAgentSessionRuntime,
    service_project_agent_session_request,
)
from ui.project_agent_session_registry import ProjectAgentSessionRegistry
from ui.project_capture_safety import begin_project_capture_run


_REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakePipeClient:
    def __init__(self, outcome_factory, *, target_status="ok", submit_status="accepted"):
        self._outcome_factory = outcome_factory
        self._target_status = target_status
        self._submit_status = submit_status
        self._outcome = None
        self.target_calls = 0
        self.submissions = []
        self.consume_calls = 0
        self.release_calls = 0
        self.close_calls = 0

    def current_target_epoch(self):
        self.target_calls += 1
        if self._target_status == "ok":
            return {"status": "ok", "target_epoch": "target-a"}
        return {"status": self._target_status}

    def submit(self, epoch, request):
        self.submissions.append((epoch, request))
        if self._submit_status == "accepted":
            self._outcome = self._outcome_factory(request)
        return {"status": self._submit_status}

    def consume_reply(self, _epoch):
        self.consume_calls += 1
        if self._outcome is None:
            return {"status": "busy"}
        return self._outcome

    def release(self):
        self.release_calls += 1
        return {"status": "released"}

    def close(self):
        self.close_calls += 1


class _FakeClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


def _bridge_completed(request_id, result):
    return {
        "status": "completed",
        "reply": {
            "request_id": request_id,
            "status": "completed",
            "result": result,
        },
    }


def _run(coroutine):
    return asyncio.run(coroutine)


def _line(line_id, text, *, line_type=None):
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


def _project():
    return build_graph(Project(
        prompt_lines=[
            _line("baseline", "baseline prompt"),
            _line("scene-1", "First Scene", line_type="separator"),
            _line("illustration-1", "red, blue"),
            _line("scene-2", "Empty Scene", line_type="separator"),
        ],
        project_metadata={"name": "gateway test", "revision": 3},
        module_library={},
        attribute_groups={},
    ))


def test_proxy_preserves_result_and_reuses_one_route_for_multiple_calls():
    first_payload = {"ok": True, "nested": ["same", {"value": 9}]}
    second_payload = {"ok": True, "sequence": 2}

    class MultiReplyPipe(_FakePipeClient):
        def submit(self, epoch, request):
            self.submissions.append((epoch, request))
            result = first_payload if len(self.submissions) == 1 else second_payload
            self._outcome = _bridge_completed(request["request_id"], result)
            return {"status": "accepted"}

    pipe = MultiReplyPipe(lambda _request: None)
    caller = NamedPipeMCPToolCaller(pipe)
    first = caller.call_tool("promptgraph_capabilities", None)
    second = caller.call_tool("promptgraph_project_summary", {})
    assert first is first_payload
    assert second is second_payload
    assert pipe.target_calls == 2
    assert [epoch for epoch, _request in pipe.submissions] == ["target-a", "target-a"]
    assert pipe.submissions[0][1]["arguments"] == {}
    assert pipe.submissions[0][1]["tool"] == "promptgraph_capabilities"
    assert pipe.submissions[1][1]["tool"] == "promptgraph_project_summary"
    assert pipe.submissions[0][1]["request_id"] != pipe.submissions[1][1]["request_id"]
    caller.close()
    assert pipe.release_calls == 1
    assert pipe.close_calls == 1


@pytest.mark.parametrize(
    ("outcome_factory", "target_status", "submit_status", "expected_reason"),
    [
        (lambda _request: {"status": "stale_target"}, "ok", "accepted", "stale_target"),
        (
            lambda request: {
                "status": "completed",
                "reply": {
                    "request_id": request["request_id"],
                    "status": "rejected",
                    "reason": "project_capture_failed",
                    "diagnostics": [{"code": "private_path_should_not_escape"}],
                },
            },
            "ok",
            "accepted",
            "project_capture_failed",
        ),
        (lambda _request: {"status": "busy"}, "ok", "busy", "request_busy"),
        (
            lambda _request: {"status": "busy"},
            "session_unavailable",
            "accepted",
            "session_unavailable",
        ),
    ],
)
def test_proxy_maps_stale_transport_and_bridge_failures_boundedly(
    outcome_factory, target_status, submit_status, expected_reason
):
    pipe = _FakePipeClient(
        outcome_factory,
        target_status=target_status,
        submit_status=submit_status,
    )
    caller = NamedPipeMCPToolCaller(pipe, result_wait_seconds=0.01)
    result = caller.call_tool("promptgraph_project_summary", {})
    assert result["gateway_contract_version"] == GATEWAY_CONTRACT_VERSION
    assert result["ok"] is False
    assert result["reason"] == expected_reason
    assert result["diagnostics"] == [{"code": expected_reason}]
    assert "private_path" not in repr(result)
    if expected_reason == "stale_target":
        assert pipe.target_calls == 1
        assert len(pipe.submissions) == 1
    if target_status != "ok":
        assert pipe.submissions == []


def test_proxy_has_no_new_large_reply_limit():
    payload = {"ok": True, "payload": "x" * 2_500_000}
    pipe = _FakePipeClient(lambda request: _bridge_completed(request["request_id"], payload))
    caller = NamedPipeMCPToolCaller(pipe)
    server = mcp_sdk_binding.build_mcp_server(tool_caller=caller)

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("promptgraph_list_illustrations", {})
            assert result.structured_content == payload
            assert result.is_error is False

    _run(exercise())
    assert pipe.consume_calls == 1
    assert len(payload["payload"]) == 2_500_000


def test_proxy_timeout_disconnects_uncertain_in_flight_route():
    clock = _FakeClock()
    pipe = _FakePipeClient(lambda _request: {"status": "busy"})
    caller = NamedPipeMCPToolCaller(
        pipe,
        result_wait_seconds=0.1,
        poll_interval_seconds=0.05,
        clock=clock,
        sleep=clock.sleep,
    )
    result = caller.call_tool("promptgraph_project_summary", {})
    assert result["reason"] == "request_timeout"
    assert pipe.close_calls == 1
    assert pipe.release_calls == 0
    assert caller.call_tool("promptgraph_project_summary", {})["reason"] == "gateway_unavailable"


def test_sdk_binding_accepts_only_the_explicit_tool_caller_seam():
    class Caller:
        def __init__(self):
            self.calls = []

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"ok": True, "name": name, "arguments": arguments}

    caller = Caller()
    server = mcp_sdk_binding.build_mcp_server(tool_caller=caller)
    catalog = mcp_adapter.get_tool_catalog()

    async def exercise():
        async with Client(server) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                entry["name"] for entry in catalog
            ]
            assert [tool.input_schema for tool in listed.tools] == [
                entry["inputSchema"] for entry in catalog
            ]
            result = await client.call_tool("promptgraph_capabilities", {})
            assert result.structured_content == {
                "ok": True,
                "name": "promptgraph_capabilities",
                "arguments": {},
            }

    _run(exercise())
    assert caller.calls == [("promptgraph_capabilities", {})]


@pytest.mark.parametrize(
    ("outcome_factory", "expected_reason"),
    [
        (lambda _request: {"status": "stale_target"}, "stale_target"),
        (
            lambda request: {
                "status": "completed",
                "reply": {
                    "request_id": request["request_id"],
                    "status": "rejected",
                    "reason": "project_capture_failed",
                    "diagnostics": [{"code": "C:\\private\\project.json"}],
                },
            },
            "project_capture_failed",
        ),
    ],
)
def test_stale_and_bridge_rejections_are_bounded_mcp_errors(
    outcome_factory, expected_reason
):
    pipe = _FakePipeClient(outcome_factory)
    caller = NamedPipeMCPToolCaller(pipe)
    server = mcp_sdk_binding.build_mcp_server(tool_caller=caller)

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool("promptgraph_project_summary", {})
            assert result.is_error is True
            assert result.structured_content["ok"] is False
            assert result.structured_content["reason"] == expected_reason
            assert result.structured_content["diagnostics"] == [
                {"code": expected_reason},
            ]
            assert "private\\project.json" not in result.content[0].text

    _run(exercise())
    assert pipe.target_calls == 1
    assert len(pipe.submissions) == 1


def test_gateway_module_has_no_host_project_streamlit_or_approval_imports():
    import agent_adapters.mcp_named_pipe_gateway as gateway

    tree = ast.parse(Path(gateway.__file__).read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = {
        "streamlit",
        "core.project",
        "core.agent_facade",
        "ui.project_capture_safety",
        "ui.project_agent_request_bridge",
    }
    assert imports.isdisjoint(forbidden)


@pytest.mark.skipif(os.name != "nt", reason="real Named Pipe gateway integration requires Windows")
def test_real_stdio_gateway_round_trips_through_one_live_session_route(
    tmp_path,
    monkeypatch,
):
    project = _project()
    observed_line = next(line for line in project.prompt_lines if line.id == "illustration-1")
    observed_line.generated_candidates = [{"path": "../not-readable.png", "seed": 0}]
    original = copy.deepcopy(project)
    state = {
        "project": project,
        "current_project_path": str(tmp_path / "active-project.json"),
    }
    registry = ProjectAgentSessionRegistry()
    runtime = ProjectAgentSessionRuntime(_registry=registry)
    broker = WindowsNamedPipeBroker(registry)
    runtime.synchronize_target(project, state["current_project_path"])
    endpoint_released = threading.Event()
    original_endpoint_finished = broker._endpoint_finished

    def observe_endpoint_finished(lease, outcome):
        original_endpoint_finished(lease, outcome)
        if outcome == "released":
            endpoint_released.set()

    broker._endpoint_finished = observe_endpoint_finished
    armed = runtime.arm_launcher_rendezvous(broker)
    assert armed.status == "ready"
    rendezvous_path = broker._api.launcher_rendezvous_path()

    capture_calls = []
    original_capture = project_agent_request_bridge.capture_active_project

    def track_capture(*args, **kwargs):
        capture_calls.append(True)
        return original_capture(*args, **kwargs)

    monkeypatch.setattr(
        project_agent_request_bridge,
        "capture_active_project",
        track_capture,
    )

    stop_pump = threading.Event()
    service_results = []
    service_lock = threading.Lock()
    shutdown_pairing_status = None

    def generation_context(p, runs):
        return {"generation_options": {"run_count": runs}, "project_path": state["current_project_path"],
                "request_builder": lambda item, index: {
                    "workflow_json": {"1": {"class_type": "SaveImage", "inputs": {}}},
                    "warning": "", "resolved_positive_prompt": item.current_text,
                    "resolved_negative_prompt": item.negative_prompt}}

    def host_run_pump():
        while not stop_pump.is_set():
            if runtime.mailbox.fragment_tick():
                run_token = begin_project_capture_run(state)
                runtime.begin_full_app_run(
                    state.get("project"), state.get("current_project_path", ""),
                )
                status = service_project_agent_session_request(
                    runtime,
                    state,
                    run_token,
                    generation_context_provider=generation_context,
                )
                with service_lock:
                    service_results.append(status)
            stop_pump.wait(0.01)

    pump_thread = threading.Thread(target=host_run_pump, daemon=True)
    pump_thread.start()
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agent_adapters.mcp_named_pipe_launcher"],
        cwd=str(_REPO_ROOT),
        env={
            "PYTHONPATH": str(_REPO_ROOT),
        },
    )

    async def exercise():
        async with asyncio.timeout(60):
            async with Client(
                stdio_client(parameters),
                read_timeout_seconds=10,
            ) as client:
                listed = await client.list_tools()
                catalog = mcp_adapter.get_tool_catalog()
                assert [tool.name for tool in listed.tools] == [
                    entry["name"] for entry in catalog
                ]
                assert len(listed.tools) == 13
                assert all("apply" not in tool.name.casefold() for tool in listed.tools)
                for tool, entry in zip(listed.tools, catalog, strict=True):
                    assert tool.description == entry["description"]
                    assert tool.input_schema == entry["inputSchema"]
                    assert tool.meta == {"promptgraph/effect": entry["effect"]}

                capabilities = await client.call_tool(
                    "promptgraph_capabilities", {},
                )
                expected_capabilities = mcp_adapter.PromptGraphMCPAdapter(
                    lambda: project
                ).call_tool("promptgraph_capabilities", {})
                assert capabilities.is_error is False
                assert capabilities.structured_content == expected_capabilities

                summary = await client.call_tool(
                    "promptgraph_project_summary", {},
                )
                expected_summary = mcp_adapter.PromptGraphMCPAdapter(
                    lambda: project
                ).call_tool("promptgraph_project_summary", {})
                assert summary.is_error is False
                assert summary.structured_content == expected_summary

                search = await client.call_tool(
                    "promptgraph_search_illustrations",
                    {"query_text": "red"},
                )
                expected_search = mcp_adapter.PromptGraphMCPAdapter(
                    lambda: project
                ).call_tool(
                    "promptgraph_search_illustrations",
                    {"query_text": "red"},
                )
                assert search.is_error is False
                assert search.structured_content == expected_search

                candidates = await client.call_tool(
                    "promptgraph_list_candidates", {"illustration_id": "illustration-1"},
                )
                assert candidates.is_error is False
                row = candidates.structured_content["candidates"][0]
                assert row["seed"] == 0 and row["image_availability"] == "unknown"
                assert "not-readable.png" not in candidates.content[0].text
                candidate = await client.call_tool(
                    "promptgraph_get_candidate",
                    {"illustration_id": "illustration-1", "candidate_handle": row["candidate_handle"]},
                )
                assert candidate.is_error is False
                assert candidate.structured_content["candidate"] == row

                generation = await client.call_tool("promptgraph_preview_generation", {"scene_id": "scene-1"})
                assert generation.is_error is False and generation.structured_content["valid"]
                assert not generation.structured_content["job_submitted"]
                assert generation.structured_content["request_count"] == 1
                review = await client.call_tool("promptgraph_request_generation_review", {
                    "scene_id": "scene-1", "run_count": 1,
                    "expected_plan_id": generation.structured_content["plan_id"]})
                assert not review.is_error and review.structured_content["status"] == "queued_for_review"
                assert runtime.generation_review_custodian.inspect()["state"] == "pending"

                preview = await client.call_tool(
                    "promptgraph_preview_batch_replace",
                    {
                        "illustration_ids": ["illustration-1"],
                        "find_text": "red",
                        "replace_text": "gold",
                    },
                )
                expected_preview = mcp_adapter.PromptGraphMCPAdapter(
                    lambda: project
                ).call_tool(
                    "promptgraph_preview_batch_replace",
                    {
                        "illustration_ids": ["illustration-1"],
                        "find_text": "red",
                        "replace_text": "gold",
                    },
                )
                assert preview.is_error is False
                assert preview.structured_content == expected_preview
                rendezvous_payload = json.loads(
                    broker._api.read_launcher_rendezvous_file(rendezvous_path)
                )
                assert rendezvous_payload["status"] == "claimed"
                assert rendezvous_payload["descriptor_path"] == ""

    try:
        with patch_config_options({"runner.fastReruns": False}):
            _run(exercise())
        assert endpoint_released.wait(timeout=5)
        shutdown_pairing_status = runtime.launcher_rendezvous_status().status
        assert shutdown_pairing_status == "released"
        assert not os.path.exists(rendezvous_path)
        assert runtime.arm_launcher_rendezvous(broker).status == "ready"
        assert runtime.disarm_launcher_rendezvous().status == "disarmed"
    finally:
        stop_pump.set()
        pump_thread.join(timeout=5)
        runtime.close()
        broker.close()

    assert not pump_thread.is_alive()
    assert project == original
    assert service_results == ["completed"] * 8
    assert len(capture_calls) == 8
    assert shutdown_pairing_status == "released"
