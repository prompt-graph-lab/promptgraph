"""Metadata-only observations through the facade, SDK and paired host boundary."""

import asyncio
import copy
import json
from unittest.mock import patch

import pytest
from mcp import Client

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from agent_adapters.mcp_sdk_binding import build_mcp_server
from core import agent_facade as facade, candidate_observation_handles as handles
from core.project import Project, PromptLine
from ui import project_agent_request_bridge as bridge, project_capture_safety as capture
from ui.project_agent_session_mailbox import ProjectAgentSessionMailbox
from ui.project_agent_session_registry import ProjectAgentSessionRegistry


def project():
    return Project(prompt_lines=[PromptLine(
        id="one", original_file_name="one", original_index=0, current_index=0,
        original_text="original", current_text="current", tokens=[],
        generated_candidates=[
            "../private.png",
            {"path": "C:\\outside\\secret.png", "seed": 0, "pinned": True,
             "source": "manual_import", "prompt_text": "untrusted import",
             "metadata": {"secret": "NEVER_EXPOSE"}},
            {"path": "C:\\outside\\secret.png", "prompt_text": "generated", "seed": 42},
            {"path": "trash.png", "trashed": True},
        ])])


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(handles.time, "monotonic", lambda: 600)
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False)


def listed(value, **kwargs):
    result = facade.list_candidates(value, "one", **kwargs)
    assert result["ok"], result
    return result


def test_order_legacy_duplicates_trash_source_gate_seed_and_privacy():
    value = project()
    before = copy.deepcopy(value)
    result = listed(value, limit=2)
    assert result["total_count"] == 3 and result["truncated"]
    rows = listed(value)["candidates"]
    assert [row["pinned"] for row in rows] == [True, False, False]
    assert rows[0]["seed"] == 0 and rows[0]["positive_prompt"]["text"] == ""
    assert rows[1]["legacy_record"] is True
    assert rows[2]["positive_prompt"]["text"] == "generated"
    assert len({row["candidate_handle"] for row in rows}) == 3
    assert all(row["image_availability"] == "unknown" for row in rows)
    for row in rows:
        assert facade.get_candidate(value, "one", row["candidate_handle"])["candidate"] == row
    all_rows = listed(value, include_trashed=True)["candidates"]
    assert len(all_rows) == 4 and all_rows[-1]["trashed"]
    assert not facade.get_candidate(value, "one", all_rows[-1]["candidate_handle"])["ok"]
    assert facade.get_candidate(value, "one", all_rows[-1]["candidate_handle"], include_trashed=True)["ok"]
    serialized = json.dumps(result)
    assert "NEVER_EXPOSE" not in serialized and "private.png" not in serialized
    assert "secret.png" not in serialized and '"path"' not in serialized
    assert value == before


@pytest.mark.parametrize("path", ["../x", "/etc/private", "C:\\private.png", "C:relative.png",
                                  "\\\\host\\share\\x", "\\rooted", "C:/private/x", "link.png"])
def test_no_filesystem_resolution_for_any_path_or_symlink(tmp_path, path):
    value = project()
    value.prompt_lines[0].generated_candidates = [{"path": path}]
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    before_files = list(tmp_path.iterdir())
    # No filesystem resolver, existence probe, or network owner is needed.
    with patch("os.path.isfile", side_effect=AssertionError("file probe")), \
         patch("os.stat", side_effect=AssertionError("stat probe")), \
         patch("builtins.open", side_effect=AssertionError("file read")):
        result = listed(value)
        assert result["candidates"][0]["image_availability"] == "unknown"
    assert list(tmp_path.iterdir()) == before_files and sentinel.read_bytes() == b"unchanged"


@pytest.mark.parametrize("change", ["remove", "reorder", "trash", "pin", "prompt", "path", "metadata", "structure"])
def test_revision_changes_invalidate_handles(change):
    value = project()
    handle = listed(value)["candidates"][0]["candidate_handle"]
    line = value.prompt_lines[0]
    if change == "remove":
        line.generated_candidates.pop()
    elif change == "reorder":
        line.generated_candidates.reverse()
    elif change == "structure":
        value.prompt_lines.append(copy.deepcopy(line))
        value.prompt_lines[-1].id = "two"
    elif change == "prompt":
        line.current_text = "changed"
    else:
        line.generated_candidates[1][{"trash": "trashed", "pin": "pinned"}.get(change, change)] = (
            False if change == "pin" else True if change == "trash" else "changed")
    assert not facade.get_candidate(value, "one", handle)["ok"]


def test_identity_expiry_and_bound_prompt_metadata(monkeypatch):
    value = project()
    candidate = value.prompt_lines[0].generated_candidates[1]
    candidate.update(candidate_prompt_source="imported_image_metadata", prompt_text="a" * 10000,
                     negative_prompt=None)
    row = listed(value)["candidates"][0]
    assert row["positive_prompt"]["truncated"] and row["positive_prompt"]["length"] == 10000
    assert not facade.get_candidate(copy.deepcopy(value), "one", row["candidate_handle"])["ok"]
    monkeypatch.setattr(handles.time, "monotonic", lambda: 900)
    assert facade.get_candidate(value, "one", row["candidate_handle"])["reason"] == "unknown_or_stale_candidate_handle"


def test_unknown_handle_and_prompt_json_suppression():
    value = project()
    value.prompt_lines[0].generated_candidates = [{"path": "x", "prompt_text": '{"workflow": "private"}'}]
    row = listed(value)["candidates"][0]
    assert row["positive_prompt"]["text"] == ""
    assert facade.get_candidate(value, "one", "candidate_" + "0" * 64)["reason"] == "unknown_or_stale_candidate_handle"


def test_real_symlink_is_never_followed(tmp_path):
    target = tmp_path / "outside.png"
    target.write_bytes(b"private image")
    link = tmp_path / "candidate.png"
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error.winerror if hasattr(error, 'winerror') else error.errno}")
    value = project()
    value.prompt_lines[0].generated_candidates = [{"path": str(link)}]
    with patch("os.stat", side_effect=AssertionError("stat")), \
         patch("os.path.realpath", side_effect=AssertionError("resolve")), \
         patch("builtins.open", side_effect=AssertionError("read")):
        assert listed(value)["candidates"][0]["image_availability"] == "unknown"
    assert target.read_bytes() == b"private image" and link.is_symlink()


def test_candidate_reply_is_rejected_when_capture_target_changes(monkeypatch):
    value = project()
    session = {"project": value}
    token = capture.begin_project_capture_run(session)
    original = facade.list_candidates
    def replace(*args, **kwargs):
        result = original(*args, **kwargs)
        session["project"] = copy.deepcopy(value)
        return result
    monkeypatch.setattr(facade, "list_candidates", replace)
    reply = bridge.dispatch_project_agent_request(session, token,
        {"request_id": "r", "tool": "promptgraph_list_candidates", "arguments": {"illustration_id": "one"}})
    assert reply["status"] == "rejected" and reply["reason"] == "project_capture_invalidated"


@pytest.mark.parametrize("records", [None, {}, [None], [False], [{}], [{"path": "x", "pinned": []}],
                                     [{"path": "x", "seed": False}], [{"path": "x", "prompt_text": {}}]])
def test_malformed_records_fail_closed(records):
    value = project()
    value.prompt_lines[0].generated_candidates = records
    assert not facade.list_candidates(value, "one")["ok"]


@pytest.mark.parametrize("kind", ["missing", "deleted", "separator", "workbench", "ambiguous", "unknown"])
def test_invalid_targets(kind):
    value = project()
    if kind == "missing":
        value = None
    elif kind == "deleted":
        value.prompt_lines[0].deleted = True
    elif kind == "ambiguous":
        value.prompt_lines.append(copy.deepcopy(value.prompt_lines[0]))
    elif kind in ("separator", "workbench"):
        value.prompt_lines[0].line_type = kind
    assert not facade.list_candidates(value, "unknown" if kind == "unknown" else "one")["ok"]


@pytest.mark.parametrize("tool,args", [
    ("promptgraph_list_candidates", {}),
    ("promptgraph_list_candidates", {"illustration_id": ""}),
    ("promptgraph_list_candidates", {"illustration_id": " one "}),
    ("promptgraph_list_candidates", {"illustration_id": "one", "limit": False}),
    ("promptgraph_list_candidates", {"illustration_id": "one", "limit": 101}),
    ("promptgraph_list_candidates", {"illustration_id": "one", "limit": 0}),
    ("promptgraph_list_candidates", {"illustration_id": "one", "include_trashed": 1}),
    ("promptgraph_list_candidates", {"illustration_id": "one", "path": "x"}),
    ("promptgraph_get_candidate", {"illustration_id": "one", "candidate_handle": False}),
    ("promptgraph_get_candidate", {"illustration_id": "one", "candidate_handle": "unknown"}),
])
def test_validation_before_project_capture(tool, args):
    def forbidden():
        raise AssertionError("capture must not occur")
    assert PromptGraphMCPAdapter(forbidden).call_tool(tool, args)["reason"] == "invalid_arguments"
    with patch.object(bridge, "capture_active_project", side_effect=forbidden):
        reply = bridge.dispatch_project_agent_request({}, "token", {"request_id": "x", "tool": tool, "arguments": args})
    assert reply["result"]["reason"] == "invalid_arguments"


def test_sdk_list_get_and_unavailable_authorities_are_exact_and_read_only():
    value = project()
    before = copy.deepcopy(value)
    adapter = PromptGraphMCPAdapter(lambda: value)
    async def exercise():
        async with Client(build_mcp_server(adapter)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name in ("promptgraph_list_candidates", "promptgraph_get_candidate"):
                assert tools[name].annotations.read_only_hint
            result = await client.call_tool("promptgraph_list_candidates", {"illustration_id": "one"})
            row = result.structured_content["candidates"][0]
            single = await client.call_tool("promptgraph_get_candidate", {"illustration_id": "one", "candidate_handle": row["candidate_handle"]})
            assert single.structured_content["candidate"] == row
            assert json.loads(single.content[0].text) == single.structured_content
            for name in ("promptgraph_generate", "promptgraph_adopt_candidate", "promptgraph_get_image"):
                assert (await client.call_tool(name, {})).structured_content["reason"] == "unknown_tool"
    asyncio.run(exercise())
    assert value == before


def test_bridge_repeated_capture_and_binding_staleness(monkeypatch):
    value = project()
    session = {"project": value, "current_project_path": "private-project.json",
               "line_generated_candidates": {"one": [{"path": "SESSION_ONLY"}]},
               "settings": {"untouched": True}}
    before = copy.deepcopy(session)
    token = capture.begin_project_capture_run(session)
    def call(name, args, pairing=1, epoch=1, route="route-1"):
        reply = bridge.dispatch_project_agent_request(session, token,
            {"request_id": "r", "tool": name, "arguments": args},
            pairing_generation=pairing, target_epoch=epoch, candidate_session_identity=route)
        assert reply["status"] == "completed"
        return reply["result"]
    result = call("promptgraph_list_candidates", {"illustration_id": "one"})
    assert call("promptgraph_list_candidates", {"illustration_id": "one"}) == result
    assert "SESSION_ONLY" not in json.dumps(result)
    handle = result["candidates"][0]["candidate_handle"]
    args = {"illustration_id": "one", "candidate_handle": handle}
    assert call("promptgraph_get_candidate", args)["ok"]
    assert not call("promptgraph_get_candidate", args, pairing=2)["ok"]
    assert not call("promptgraph_get_candidate", args, epoch=2)["ok"]
    assert not call("promptgraph_get_candidate", args, route="route-2")["ok"]
    assert value == before["project"] and session["settings"] == before["settings"]
    assert session["line_generated_candidates"] == before["line_generated_candidates"]
    session["project"] = copy.deepcopy(value)
    assert not call("promptgraph_get_candidate", args)["ok"]


def test_paired_route_round_trip_release_and_repair_invalidates_handle():
    value = project()
    session = {"project": value}
    token = capture.begin_project_capture_run(session)
    mailbox = ProjectAgentSessionMailbox()
    mailbox.synchronize_target_epoch("epoch-1")
    registry = ProjectAgentSessionRegistry()
    registration = registry.register_session(mailbox)
    def pair():
        offer = registry.arm_pairing(registration).bootstrap
        return registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability).paired_route
    # The actual paired route is the only submit/consume owner.
    route = pair()
    def call(name, args):
        request = {"request_id": "r", "tool": name, "arguments": args}
        assert route.submit("epoch-1", request).status == "accepted"
        claim = mailbox._claim_for_service("epoch-1")
        reply = bridge.dispatch_project_agent_request(session, token, claim.request,
                    pairing_generation=claim.pairing_generation, target_epoch=claim.target_epoch,
                    candidate_session_identity=registration.route_id)
        mailbox.complete(claim, reply, "epoch-1")
        return route.consume_reply("epoch-1")
    first = call("promptgraph_list_candidates", {"illustration_id": "one"})
    # Access the bounded mailbox outcome, not private Project state via route.
    handle = first.reply["result"]["candidates"][0]["candidate_handle"]
    assert route.release().status == "released"
    route = pair()
    result = call("promptgraph_get_candidate", {"illustration_id": "one", "candidate_handle": handle})
    assert result.reply["result"]["reason"] == "unknown_or_stale_candidate_handle"
