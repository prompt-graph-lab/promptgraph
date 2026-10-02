"""PoC-1b integration tests through the official MCP SDK in-memory Client."""

import asyncio
import copy
import json

from mcp import Client

from agent_adapters import mcp_adapter, mcp_sdk_binding
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine


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
    return build_graph(Project(prompt_lines=[
        _line("baseline", "baseline prompt"),
        _line("scene-1", "First Scene", line_type="separator"),
        _line("illustration-1", "red, blue"),
        _line("scene-2", "Empty Scene", line_type="separator"),
    ], module_library={}, attribute_groups={}))


def _request(**updates):
    return {
        "illustration_ids": ["illustration-1"],
        "find_text": "red",
        "replace_text": "gold",
        **updates,
    }


def _run(coroutine):
    return asyncio.run(coroutine)


def test_sdk_registration_uses_exact_adapter_catalog_and_excludes_apply():
    provider_calls = []
    adapter = mcp_adapter.PromptGraphMCPAdapter(
        lambda: provider_calls.append(True) or _project()
    )
    server = mcp_sdk_binding.build_mcp_server(adapter)
    catalog = mcp_adapter.get_tool_catalog()

    async def exercise():
        async with Client(server) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert names == [entry["name"] for entry in catalog]
            assert len(names) == len(set(names))
            assert all("apply" not in name.casefold() for name in names)

            by_name = {tool.name: tool for tool in listed.tools}
            for entry in catalog:
                tool = by_name[entry["name"]]
                assert tool.description == entry["description"]
                assert tool.input_schema == entry["inputSchema"]
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is False
                assert tool.meta == {"promptgraph/effect": entry["effect"]}

            # The SDK accepts a call request for an unlisted name at this
            # low-level API, so verify the adapter rejects it without exposing
            # Apply or asking the host for its Project.
            denied = await client.call_tool(
                "promptgraph_apply_batch_replace", {"plan": {"plan_id": "x"}}
            )
            assert denied.structured_content["reason"] == "unknown_tool"
            assert denied.is_error is True

    _run(exercise())
    assert provider_calls == []


def test_real_sdk_call_path_delegates_all_six_tools_without_project_mutation():
    value = _project()
    before = copy.deepcopy(value)
    provider_calls = []
    adapter = mcp_adapter.PromptGraphMCPAdapter(
        lambda: provider_calls.append(True) or value
    )
    server = mcp_sdk_binding.build_mcp_server(adapter)

    calls = [
        ("promptgraph_capabilities", {}),
        ("promptgraph_project_summary", {}),
        ("promptgraph_list_scenes", {"limit": 1}),
        ("promptgraph_list_illustrations", {}),
        ("promptgraph_get_illustration", {"illustration_id": "illustration-1"}),
        ("promptgraph_preview_batch_replace", _request()),
    ]
    expected = [adapter.call_tool(name, arguments) for name, arguments in calls]
    provider_calls.clear()

    async def exercise():
        async with Client(server) as client:
            actual = []
            for (name, arguments), direct in zip(calls, expected, strict=True):
                result = await client.call_tool(name, arguments)
                assert result.structured_content == direct
                assert json.loads(result.content[0].text) == direct
                assert result.is_error is (direct.get("ok") is False)
                actual.append(result.structured_content)
            return actual

    actual = _run(exercise())
    assert actual == expected
    # Capabilities is provider-free; all other calls resolve the host Project
    # separately for each invocation.
    assert len(provider_calls) == 5
    assert expected[3]["illustrations"][0]["illustration_id"] == "baseline"
    assert expected[3]["illustrations"][0]["scene_id"] is None
    assert value == before


def test_transport_errors_and_provider_failures_remain_bounded_through_sdk():
    value = _project()
    provider_calls = []
    fail_provider = False

    def provider():
        provider_calls.append(True)
        if fail_provider:
            raise RuntimeError("private path C:\\secret\\project.json")
        return value

    adapter = mcp_adapter.PromptGraphMCPAdapter(provider)
    server = mcp_sdk_binding.build_mcp_server(adapter)

    async def exercise():
        nonlocal fail_provider
        async with Client(server) as client:
            # v2's low-level Server preserves explicit input schemas but does
            # not enforce them. The adapter therefore rejects this malformed
            # transport shape before the host Project provider runs.
            invalid = await client.call_tool(
                "promptgraph_preview_batch_replace", {"illustration_ids": ["illustration-1"]}
            )
            assert invalid.structured_content["reason"] == "invalid_arguments"
            assert invalid.is_error is True
            assert provider_calls == []

            # A transport-valid but domain-invalid target reaches the existing
            # adapter/facade and preserves its structured reason.
            unknown = await client.call_tool(
                "promptgraph_get_illustration", {"illustration_id": "unknown"}
            )
            assert unknown.structured_content == adapter.call_tool(
                "promptgraph_get_illustration", {"illustration_id": "unknown"}
            )
            assert unknown.structured_content["reason"] == "unknown_illustration_id"
            assert len(provider_calls) == 2

            fail_provider = True
            failed = await client.call_tool("promptgraph_project_summary", {})
            assert failed.structured_content["reason"] == "project_provider_failed"
            assert "private path" not in failed.content[0].text
            assert "project.json" not in failed.content[0].text
            return failed

    _run(exercise())


def test_each_call_uses_a_fresh_host_project_and_preview_has_no_hidden_state():
    first, second = _project(), _project()
    second.prompt_lines[-2].current_text = "green, blue"
    projects = iter((first, second, first, second))
    provider_calls = []

    def provider():
        provider_calls.append(True)
        return next(projects)

    adapter = mcp_adapter.PromptGraphMCPAdapter(provider)
    server = mcp_sdk_binding.build_mcp_server(adapter)

    async def exercise():
        async with Client(server) as client:
            first_observation = await client.call_tool(
                "promptgraph_get_illustration", {"illustration_id": "illustration-1"}
            )
            second_observation = await client.call_tool(
                "promptgraph_get_illustration", {"illustration_id": "illustration-1"}
            )
            first_preview = await client.call_tool(
                "promptgraph_preview_batch_replace", _request()
            )
            second_preview = await client.call_tool(
                "promptgraph_preview_batch_replace", _request()
            )
            return first_observation, second_observation, first_preview, second_preview

    first_observation, second_observation, first_preview, second_preview = _run(exercise())
    assert first_observation.structured_content != second_observation.structured_content
    assert first_preview.structured_content != second_preview.structured_content
    assert len(provider_calls) == 4


def test_binding_rejects_other_adapter_implementations():
    class AdapterSubclass(mcp_adapter.PromptGraphMCPAdapter):
        pass

    try:
        mcp_sdk_binding.build_mcp_server(AdapterSubclass(None))
    except TypeError:
        pass
    else:
        raise AssertionError("the SDK binding must preserve the exact adapter owner")
