"""Contract tests for the SDK-independent MCP-facing Agent Facade adapter."""

import ast
import copy
import inspect
import json
from pathlib import Path

import pytest

from agent_adapters import mcp_adapter
from core import agent_facade
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine


TOOL_NAMES = [
    "promptgraph_capabilities",
    "promptgraph_project_summary",
    "promptgraph_list_scenes",
    "promptgraph_list_illustrations",
    "promptgraph_get_illustration",
    "promptgraph_preview_batch_replace",
]


def line(line_id, text="red, blue", **kwargs):
    return PromptLine(id=line_id, original_file_name=f"{line_id}.png", original_index=0,
                      current_index=0, original_text=text, current_text=text,
                      tokens=parse_prompt(text), **kwargs)


def project():
    return build_graph(Project(prompt_lines=[
        line("baseline"), line("scene-1", "First", line_type="separator"),
        line("one"), line("workbench", line_type="workbench"),
        line("deleted", deleted=True),
        line("deleted-scene", "Removed", line_type="separator", deleted=True),
        line("two", "blue, red"), line("scene-2", "Empty", line_type="separator"),
    ], module_library={"opaque": {"reference_assets": {"unknown": [1, 2]}}},
        project_metadata={"future": {"keep": True}}))


def request(**updates):
    return {"illustration_ids": ["one"], "find_text": "red", "replace_text": "gold",
            **updates}


class HostileValue:
    def __str__(self):
        raise AssertionError("must not stringify")

    def __repr__(self):
        raise AssertionError("must not repr")

    def __iter__(self):
        raise AssertionError("must not iterate")

    def __deepcopy__(self, memo):
        raise AssertionError("must not copy")


def json_only(value):
    assert type(value) in (dict, list, str, int, float, bool, type(None))
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            json_only(child)
    elif type(value) is list:
        for child in value:
            json_only(child)
    assert json.loads(json.dumps(value, allow_nan=False)) == value


def identity_state(value):
    return (id(value), id(value.prompt_lines), [id(item) for item in value.prompt_lines],
            id(value.module_library), id(value.project_metadata), id(value.nodes), id(value.line_map))


def test_tool_catalog_is_deterministic_unique_and_preview_only():
    first = mcp_adapter.get_tool_catalog()
    second = mcp_adapter.get_tool_catalog()
    assert first == second and first is not second
    names = [tool["name"] for tool in first]
    assert names == TOOL_NAMES and len(names) == len(set(names))
    assert not any("apply" in name.lower() for name in names)
    assert [tool["effect"] for tool in first] == [
        "read_only", "read_only", "read_only", "read_only", "read_only", "reviewed_preview"]
    assert "illustration_ids" in first[-1]["inputSchema"]["required"]
    first[-1]["inputSchema"]["properties"].clear()
    assert "illustration_ids" in mcp_adapter.get_tool_catalog()[-1]["inputSchema"]["properties"]
    json_only(second)


def test_capability_mapping_is_facade_derived_and_does_not_need_a_project():
    adapter = mcp_adapter.PromptGraphMCPAdapter(None)
    capabilities = adapter.call_tool("promptgraph_capabilities", {})
    facade_mutation, = agent_facade.discover_capabilities()["capabilities"]["mutations"]
    assert capabilities["facade_contract_version"] == agent_facade.CONTRACT_VERSION
    assert capabilities["batch_replace_preview_modes"] == facade_mutation["modes"]
    assert capabilities["batch_replace_requires_explicit_illustration_ids"] is True
    assert capabilities["agent_callable_apply"] is False
    assert [tool["name"] for tool in capabilities["tools"]] == TOOL_NAMES
    assert capabilities["tools"][-1]["effect"] == "reviewed_preview"
    json_only(capabilities)


def test_observations_and_preview_delegate_exactly_without_mutating_project():
    value = project()
    before = copy.deepcopy(value)
    identity = identity_state(value)
    provider_calls = []

    def provider():
        provider_calls.append(value)
        return value

    adapter = mcp_adapter.PromptGraphMCPAdapter(provider)
    calls = [
        ("promptgraph_project_summary", {}, agent_facade.summarize_project(value)),
        ("promptgraph_list_scenes", {"limit": 2}, agent_facade.observe_scenes(value, limit=2)),
        ("promptgraph_list_illustrations", {}, agent_facade.list_illustrations(value)),
        ("promptgraph_list_illustrations", {"scene_id": "scene-1"},
         agent_facade.list_illustrations(value, scene_id="scene-1")),
        ("promptgraph_get_illustration", {"illustration_id": "one"},
         agent_facade.get_illustration(value, "one")),
        ("promptgraph_preview_batch_replace", request(),
         agent_facade.preview_batch_replace(value, request())),
    ]
    for name, arguments, expected in calls:
        result = adapter.call_tool(name, arguments)
        assert result == expected
        json_only(result)
    assert len(provider_calls) == len(calls)
    assert calls[2][2]["illustrations"][0]["illustration_id"] == "baseline"
    assert calls[2][2]["illustrations"][0]["scene_id"] is None
    assert value == before and identity_state(value) == identity


def test_provider_is_called_for_each_call_and_project_state_is_not_retained():
    first, second = project(), project()
    second.prompt_lines[2].current_text = "blue, red, new detail"
    projects = iter((first, second))
    calls = []

    def provider():
        calls.append(True)
        return next(projects)

    adapter = mcp_adapter.PromptGraphMCPAdapter(provider)
    one = adapter.call_tool("promptgraph_get_illustration", {"illustration_id": "one"})
    two = adapter.call_tool("promptgraph_get_illustration", {"illustration_id": "one"})
    assert one == agent_facade.get_illustration(first, "one")
    assert two == agent_facade.get_illustration(second, "one")
    assert one != two and len(calls) == 2


def test_preview_is_a_direct_facade_envelope_and_repeated_calls_retain_no_approval_state(monkeypatch):
    value = project()
    adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: value)
    expected = agent_facade.preview_batch_replace(value, request())
    assert adapter.call_tool("promptgraph_preview_batch_replace", request()) == expected
    assert adapter.call_tool("promptgraph_preview_batch_replace", request()) == expected

    envelope = {"contract_version": "facade-test", "plan_id": "opaque", "extra": [1, True]}
    monkeypatch.setattr(agent_facade, "preview_batch_replace", lambda _project, _request: envelope)
    assert adapter.call_tool("promptgraph_preview_batch_replace", request()) is envelope
    json_only(envelope)
    assert not hasattr(adapter, "apply_batch_replace")


@pytest.mark.parametrize("provider,reason", [
    (None, "missing_project_provider"),
    ("not callable", "invalid_project_provider"),
    (lambda: None, "missing_project"),
    (lambda: object(), "invalid_project"),
])
def test_missing_or_invalid_host_project_fails_with_bounded_json(provider, reason):
    result = mcp_adapter.PromptGraphMCPAdapter(provider).call_tool("promptgraph_project_summary", {})
    assert result["ok"] is False and result["reason"] == reason
    json_only(result)


def test_provider_failure_does_not_leak_exception_details():
    secret = r"C:\private\workspace\do-not-leak"

    def provider():
        raise RuntimeError(secret)

    result = mcp_adapter.PromptGraphMCPAdapter(provider).call_tool("promptgraph_project_summary", {})
    assert result["reason"] == "project_provider_failed"
    assert secret not in json.dumps(result)
    assert "RuntimeError" not in json.dumps(result)
    json_only(result)


@pytest.mark.parametrize("tool_name,arguments,facade_call", [
    ("promptgraph_list_illustrations", {"scene_id": "missing"},
     lambda value: agent_facade.list_illustrations(value, scene_id="missing")),
    ("promptgraph_get_illustration", {"illustration_id": "missing"},
     lambda value: agent_facade.get_illustration(value, "missing")),
    ("promptgraph_get_illustration", {"illustration_id": "scene-1"},
     lambda value: agent_facade.get_illustration(value, "scene-1")),
    ("promptgraph_get_illustration", {"illustration_id": "workbench"},
     lambda value: agent_facade.get_illustration(value, "workbench")),
    ("promptgraph_get_illustration", {"illustration_id": "deleted"},
     lambda value: agent_facade.get_illustration(value, "deleted")),
    ("promptgraph_preview_batch_replace", request(illustration_ids=[]),
     lambda value: agent_facade.preview_batch_replace(value, request(illustration_ids=[]))),
    ("promptgraph_preview_batch_replace", request(illustration_ids=["scene-1"]),
     lambda value: agent_facade.preview_batch_replace(value, request(illustration_ids=["scene-1"]))),
])
def test_unknown_scene_and_unsupported_illustration_targets_keep_facade_reasons(
        tool_name, arguments, facade_call):
    value = project()
    result = mcp_adapter.PromptGraphMCPAdapter(lambda: value).call_tool(tool_name, arguments)
    assert result == facade_call(value)
    assert result.get("ok", True) is False or result.get("valid", True) is False
    json_only(result)


def test_adapter_rejects_hostile_arguments_without_invoking_hooks_or_project_provider():
    class HostileKey:
        hash_calls = 0

        def __hash__(self):
            type(self).hash_calls += 1
            return 1

        def __eq__(self, other):
            raise AssertionError("must not compare a non-JSON key")

    key = HostileKey()
    bad_object = {key: "not-json"}
    HostileKey.hash_calls = 0
    provider_calls = []
    adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: provider_calls.append(True) or project())
    result = adapter.call_tool("promptgraph_get_illustration", bad_object)
    assert result["reason"] == "invalid_arguments"
    assert HostileKey.hash_calls == 0 and not provider_calls
    result = adapter.call_tool("promptgraph_preview_batch_replace", bad_object)
    assert result["reason"] == "invalid_arguments"
    assert HostileKey.hash_calls == 0 and not provider_calls
    assert adapter.call_tool("promptgraph_get_illustration", HostileValue())["reason"] == "invalid_arguments"
    assert not provider_calls


@pytest.mark.parametrize("arguments", [
    None,
    HostileValue(),
    {"find_text": "red", "replace_text": "gold"},
    {"illustration_ids": ["one"], "find_text": "red", "replace_text": "gold",
     "extra": "ignored?"},
    request(illustration_ids="one"),
    request(illustration_ids=[HostileValue()]),
    request(find_text=HostileValue()),
    request(replace_text=[]),
    request(match_mode=HostileValue()),
    request(preserve_weights=1),
])
def test_preview_transport_invalid_shapes_do_not_invoke_project_provider(arguments):
    calls = []
    adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: calls.append(True) or project())
    result = adapter.call_tool("promptgraph_preview_batch_replace", arguments)
    assert result["ok"] is False and result["reason"] == "invalid_arguments"
    assert not calls
    json_only(result)


def test_preview_domain_invalid_request_reaches_facade_and_preserves_its_reason():
    calls = []
    value = project()
    adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: calls.append(True) or value)
    arguments = request(illustration_ids=["missing"])
    result = adapter.call_tool("promptgraph_preview_batch_replace", arguments)
    assert calls == [True]
    assert result == agent_facade.preview_batch_replace(value, arguments)
    assert result["valid"] is False and result["reason"] == "unknown_illustration_id"
    json_only(result)


def test_invalid_transport_shape_and_unknown_tool_do_not_access_host_project():
    calls = []
    adapter = mcp_adapter.PromptGraphMCPAdapter(lambda: calls.append(True) or project())
    assert adapter.call_tool("promptgraph_get_illustration", {})["reason"] == "invalid_arguments"
    assert adapter.call_tool("promptgraph_list_scenes", {"limit": True})["reason"] == "invalid_arguments"
    assert adapter.call_tool("promptgraph_project_summary", {"unused": True})["reason"] == "invalid_arguments"
    assert adapter.call_tool("promptgraph_apply_batch_replace", {})["reason"] == "unknown_tool"
    assert not calls


def test_production_adapter_has_no_ui_transport_or_model_runtime_imports():
    source = Path(inspect.getsourcefile(mcp_adapter)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    assert roots <= {"copy", "typing", "core"}
    assert not roots & {"streamlit", "app", "mcp", "openai", "anthropic", "transformers", "ollama"}
