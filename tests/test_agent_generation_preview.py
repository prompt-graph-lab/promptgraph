"""Read-only generation preflight through real owners and trusted host wiring."""

import ast
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mcp import Client

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from agent_adapters.mcp_sdk_binding import build_mcp_server
from core import agent_facade as facade
from core.comfy_generation_prompt import prepare_generation_injection_line
from core.comfy_workflow_preparation import _build_line_workflow_from_text
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_agent_request_bridge as bridge, project_capture_safety as capture
from ui.project_agent_session_pump import ProjectAgentSessionRuntime, service_project_agent_session_request
from ui.project_agent_session_registry import ProjectAgentSessionRegistry


def line(identity, text="red", **kwargs):
    return PromptLine(id=identity, original_file_name=identity, original_index=0, current_index=0,
                      original_text=text, current_text=text, tokens=parse_prompt(text), **kwargs)


def project():
    return Project(prompt_lines=[line("scene", "Scene", line_type="separator"),
        line("two", negative_prompt="blur"), line("scratch", line_type="workbench"),
        line("deleted", deleted=True), line("one"), line("other", line_type="separator"), line("unselected")])


def workflow():
    return {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "red"}},
            "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "PRIVATE_WORKFLOW_SECRET"}}}


def host(value, runs):
    return {"generation_options": {"endpoint": "PRIVATE_ENDPOINT", "run_count": runs},
            "project_path": "PRIVATE_PROJECT_PATH", "request_builder": lambda item, index: {
                "workflow_json": workflow(), "warning": "PRIVATE_WARNING_PATH",
                "resolved_positive_prompt": item.current_text,
                "resolved_negative_prompt": item.negative_prompt}}


@pytest.fixture(autouse=True)
def safe_capture(monkeypatch):
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False)


def preview(value, **kwargs):
    return facade.preview_generation(value, "scene", host_context_provider=host, **kwargs)


def test_planner_order_counts_projection_and_no_secret_or_project_mutation():
    value = project()
    before = copy.deepcopy(value)
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        result = preview(value, run_count=3)
    assert result["ok"] and result["valid"]
    assert [item["illustration_id"] for item in result["illustrations"]] == ["two", "one"]
    assert result["request_count"] == 6 and result["expected_output_node_count"] == 6
    assert result["skipped_count"] == 2 and len(result["skipped"]) == 2
    assert result["output_count_is_estimate"] and not result["job_submitted"]
    assert not result["review_requested"] and value == before
    assert "PRIVATE" not in json.dumps(result)
    assert result == preview(value, run_count=3)


@pytest.mark.parametrize("change", ["prompt", "module", "structure", "configuration", "workflow", "binding"])
def test_content_and_host_freshness_change_plan_identity(change):
    value = project()
    first = preview(value)
    provider = host
    binding = None
    if change == "prompt":
        value.prompt_lines[1].current_text = "gold"
    elif change == "module":
        value.module_library["hero"] = {"body": "gold"}
    elif change == "structure":
        value.prompt_lines[1], value.prompt_lines[4] = value.prompt_lines[4], value.prompt_lines[1]
    elif change == "configuration":
        def provider(p, runs):
            context = host(p, runs)
            context["generation_options"]["endpoint"] = "changed"
            return context
    elif change == "workflow":
        def provider(p, runs):
            context = host(p, runs)
            def build(item, index):
                record = host(p, runs)["request_builder"](item, index)
                record["workflow_json"]["1"]["inputs"]["text"] = "changed"
                return record
            context["request_builder"] = build
            return context
    else:
        binding = ["another-session", "another-pairing", "another-epoch"]
    second = facade.preview_generation(value, "scene", host_context_provider=provider, observation_binding=binding)
    assert second["valid"] and first["plan_id"] != second["plan_id"]


def test_configuration_changes_during_preflight_fail_closed():
    calls = 0
    def unstable(p, runs):
        nonlocal calls
        calls += 1
        result = host(p, runs)
        result["generation_options"]["revision"] = calls
        return result
    result = facade.preview_generation(project(), "scene", host_context_provider=unstable)
    assert result["reason"] == "generation_configuration_changed" and "plan_id" not in result


@pytest.mark.parametrize("invalid", [None, {}, {"nodes": []}, {"1": {"inputs": {}}}])
def test_missing_or_unsupported_workflow_blocks_whole_plan_without_partial_submission(invalid):
    def provider(p, runs):
        context = host(p, runs)
        good = context["request_builder"]
        def build(item, index):
            result = good(item, index)
            if item.id == "one":
                result["workflow_json"] = invalid
            return result
        context["request_builder"] = build
        return context
    result = facade.preview_generation(project(), "scene", host_context_provider=provider)
    assert result["ok"] and not result["valid"] and result["request_count"] == 0
    assert result["blocked_count"] == 1 and result["blockers"] == ["workflow_preflight_failed"]
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("args", [{}, {"scene_id": ""}, {"scene_id": " scene "},
    {"scene_id": "scene", "run_count": False}, {"scene_id": "scene", "run_count": 6},
    {"scene_id": "scene", "workflow": {}}, {"scene_id": "scene", "approved": True}])
def test_transport_schema_before_capture_and_host_access(args):
    def forbidden(*a):
        raise AssertionError("must not capture/read host configuration")
    adapter = PromptGraphMCPAdapter(forbidden, generation_context_provider=forbidden)
    assert adapter.call_tool("promptgraph_preview_generation", args)["reason"] == "invalid_arguments"


def test_unknown_empty_overlimit_and_standalone_host_unavailable():
    value = project()
    assert facade.preview_generation(None, "scene")["reason"] == "missing_project"
    assert facade.preview_generation(value, "two", host_context_provider=host)["reason"] == "unknown_scene_id"
    assert facade.preview_generation(value, "scene")["reason"] == "generation_host_unavailable"
    value.prompt_lines = [line("scene", line_type="separator")]
    assert preview(value)["reason"] == "no_generation_targets"
    value.prompt_lines.extend(line(str(index)) for index in range(21))
    assert preview(value, run_count=5)["reason"] == "generation_target_limit_exceeded"


class State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


def app_host(tmp_path):
    source = Path(__file__).resolve().parents[1] / "app.py"
    names = {"_selected_routes_generation_options", "_prepare_agent_generation_context"}
    definitions = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
                   if isinstance(node, ast.FunctionDef) and node.name in names]
    path = tmp_path / "configured.json"
    raw = workflow()
    raw["1"]["inputs"]["text"] = "__PROMPT__"
    path.write_text(json.dumps(raw), encoding="utf-8")
    state = State(settings={"comfyui_workflow_path": str(path), "fallback_prompt": "fallback"},
                  disabled_modules=set(), gallery_selected_route_ids=["other"])
    namespace = {"st": SimpleNamespace(session_state=state), "os": os, "hashlib": hashlib,
                 "copy": copy, "prepare_generation_injection_line": prepare_generation_injection_line,
                 "_build_line_workflow_from_text": _build_line_workflow_from_text,
                 "resolve_effective_comfy_workflow_path": lambda configured: (str(path), "project"),
                 "_project_generation_output_dir_path": lambda p: "PRIVATE_OUTPUT_PATH"}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_prepare_agent_generation_context"], state, path


def test_actual_host_workflow_read_expansion_binding_and_immutability(tmp_path):
    provider, state, path = app_host(tmp_path)
    value = project()
    before, settings, contents = copy.deepcopy(value), copy.deepcopy(state), path.read_bytes()
    with patch("urllib.request.urlopen", side_effect=AssertionError("submission")):
        result = facade.preview_generation(value, "scene", host_context_provider=provider)
    assert result["valid"] and result["illustrations"][0]["positive_prompt"]["text"] == "red"
    assert value == before and state == settings and path.read_bytes() == contents
    assert "PRIVATE" not in json.dumps(result) and str(path) not in json.dumps(result)
    first_id = result["plan_id"]
    path.write_text(path.read_text().replace("PRIVATE_WORKFLOW_SECRET", "changed"), encoding="utf-8")
    assert facade.preview_generation(value, "scene", host_context_provider=provider)["plan_id"] != first_id
    path.unlink()
    result = facade.preview_generation(value, "scene", host_context_provider=provider)
    assert result["reason"] == "generation_preflight_unavailable" and str(path) not in json.dumps(result)


def test_sdk_and_paired_full_run_preview_never_creates_custody(tmp_path):
    provider, state, path = app_host(tmp_path)
    value = project()
    state["project"] = value
    state["current_project_path"] = "PRIVATE_PROJECT_PATH"
    adapter = PromptGraphMCPAdapter(lambda: value, generation_context_provider=provider)
    async def sdk():
        async with Client(build_mcp_server(adapter)) as client:
            result = await client.call_tool("promptgraph_preview_generation", {"scene_id": "scene"})
            assert result.structured_content["valid"] and not result.is_error
            assert (await client.call_tool("promptgraph_request_generation_review", {})).structured_content["reason"] == "unknown_tool"
    asyncio.run(sdk())
    registry = ProjectAgentSessionRegistry()
    runtime = ProjectAgentSessionRuntime(_registry=registry)
    epoch = runtime.synchronize_target(value, state["current_project_path"])
    offer = runtime.arm_local_pairing().bootstrap
    route = registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability).paired_route
    before = runtime.inspect_review_custody()
    route.submit(epoch, {"request_id": "r", "tool": "promptgraph_preview_generation", "arguments": {"scene_id": "scene"}})
    token = capture.begin_project_capture_run(state)
    assert service_project_agent_session_request(runtime, state, token, generation_context_provider=provider) == "completed"
    reply = route.consume_reply(epoch)
    assert reply.reply["result"]["valid"] and runtime.inspect_review_custody() == before
    runtime.close()


def test_capture_switch_during_preflight_discards_reply():
    value = project()
    state = {"project": value}
    token = capture.begin_project_capture_run(state)
    def replace(p, runs):
        state["project"] = copy.deepcopy(value)
        return host(p, runs)
    result = bridge.dispatch_project_agent_request(state, token,
        {"request_id": "r", "tool": "promptgraph_preview_generation", "arguments": {"scene_id": "scene"}},
        generation_context_provider=replace)
    assert result["reason"] == "project_capture_invalidated"


@pytest.mark.parametrize("change", ["prompt", "module"])
def test_in_place_live_content_change_during_capture_discards_reply(change):
    value = project()
    state = {"project": value}
    token = capture.begin_project_capture_run(state)
    def alter(p, runs):
        if change == "prompt":
            value.prompt_lines[1].current_text = "new prompt"
        else:
            value.module_library["hero"] = {"body": "changed"}
        return host(p, runs)
    result = bridge.dispatch_project_agent_request(state, token,
        {"request_id": "r", "tool": "promptgraph_preview_generation", "arguments": {"scene_id": "scene"}},
        generation_context_provider=alter)
    assert result["reason"] == "project_capture_invalidated"


def test_host_file_budget_and_invalid_json_fail_without_leaking_contents(tmp_path):
    provider, state, path = app_host(tmp_path)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    result = facade.preview_generation(project(), "scene", host_context_provider=provider)
    assert result["reason"] == "generation_preflight_unavailable" and str(path) not in json.dumps(result)
    path.write_text("PRIVATE_INVALID_JSON", encoding="utf-8")
    result = facade.preview_generation(project(), "scene", host_context_provider=provider)
    assert result["ok"] and not result["valid"] and "PRIVATE" not in json.dumps(result)


def test_aggregate_workflow_budget_blocks_whole_plan_and_stops_heavy_preparation():
    value = Project(prompt_lines=[line("scene", line_type="separator")] + [line(str(i)) for i in range(12)])
    calls = []
    def provider(p, runs):
        context = host(p, runs)
        def build(item, index):
            calls.append(item.id)
            return {"workflow_json": {"1": {"class_type": "SaveImage", "inputs": {"private": "x" * 900000}}},
                    "warning": "", "resolved_positive_prompt": item.current_text, "resolved_negative_prompt": ""}
        context["request_builder"] = build
        return context
    result = facade.preview_generation(value, "scene", host_context_provider=provider)
    assert result["ok"] and not result["valid"] and result["request_count"] == 0
    assert len(calls) == 10 and result["blocked_count"] == 3
    assert result["expected_output_node_count"] == 0
