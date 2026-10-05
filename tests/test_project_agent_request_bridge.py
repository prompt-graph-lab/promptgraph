"""Contract tests for the request-scoped host agent bridge."""

import copy
import json

import pytest

from agent_adapters import mcp_adapter
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_agent_request_bridge as bridge
from ui import project_capture_safety as capture_safety


def _line(line_id, text="red shirt", **kwargs):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=parse_prompt(text),
        **kwargs,
    )


def _project(text="red shirt"):
    return build_graph(Project(
        prompt_lines=[
            _line("baseline", "baseline prompt"),
            _line("scene-1", "First Scene", line_type="separator"),
            _line("illustration-1", text),
            _line("scene-2", "Empty Scene", line_type="separator"),
        ],
        project_metadata={"revision": 1},
    ))


def _request(tool, arguments, request_id="req-1"):
    return {"request_id": request_id, "tool": tool, "arguments": arguments}


def _session(project=None):
    value = {} if project is None else {"project": project}
    token = capture_safety.begin_project_capture_run(value)
    return value, token


def _fast_reruns(monkeypatch, enabled=False):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: enabled if key == "runner.fastReruns" else None,
    )


def _assert_json_only(value):
    assert type(value) in (dict, list, str, int, float, bool, type(None))
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            _assert_json_only(child)
    elif type(value) is list:
        for child in value:
            _assert_json_only(child)
    json.dumps(value, allow_nan=False)


def _cyclic_json_result():
    result = {}
    result["self"] = result
    return result


class _Hostile:
    def __str__(self):
        raise AssertionError("bridge must not stringify hostile values")

    def __repr__(self):
        raise AssertionError("bridge must not repr hostile values")

    def __iter__(self):
        raise AssertionError("bridge must not iterate hostile values")

    def __deepcopy__(self, memo):
        raise AssertionError("bridge must not copy hostile values")


def test_contract_version_and_completed_reply_preserve_adapter_result(monkeypatch):
    _fast_reruns(monkeypatch, True)
    marker = {"ok": False, "reason": "unknown_tool", "nested": [1, True]}
    monkeypatch.setattr(
        mcp_adapter.PromptGraphMCPAdapter,
        "call_tool",
        lambda self, name, arguments: marker,
    )
    session, token = _session()

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("unknown", {}, request_id="correlation-only")
    )

    assert reply == {
        "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
        "request_id": "correlation-only",
        "status": "completed",
        "result": marker,
    }
    assert reply["result"] is marker
    _assert_json_only(reply)


@pytest.mark.parametrize(
    ("envelope", "expected_code"),
    [
        ([], "invalid_envelope"),
        ({"request_id": "r", "tool": "promptgraph_project_summary"}, "invalid_envelope"),
        ({**_request("promptgraph_project_summary", {}), "extra": True}, "invalid_envelope"),
        (_request("promptgraph_project_summary", {}, request_id=""), "invalid_request_id"),
        (_request("promptgraph_project_summary", {}, request_id="r" * 129), "invalid_request_id"),
        (_request(_Hostile(), {}), "invalid_tool"),
        (_request("promptgraph_project_summary", []), "invalid_arguments"),
        (_request("promptgraph_project_summary", {"bad": _Hostile()}), "invalid_json_arguments"),
        (_request("promptgraph_project_summary", {"bad": float("nan")}), "invalid_json_arguments"),
    ],
)
def test_invalid_outer_requests_are_bounded_and_never_capture(
        monkeypatch, envelope, expected_code):
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )
    session, token = _session(_project())

    reply = bridge.dispatch_project_agent_request(session, token, envelope)

    assert reply["status"] == "rejected"
    assert reply["reason"] == "invalid_request"
    assert reply["diagnostics"] == [{"code": expected_code}]
    assert capture_calls == []
    _assert_json_only(reply)
    assert "Hostile" not in json.dumps(reply)


def test_hostile_outer_object_is_rejected_without_hooks(monkeypatch):
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )
    request = _Hostile()

    reply = bridge.dispatch_project_agent_request({}, None, request)

    assert reply["diagnostics"] == [{"code": "invalid_envelope"}]
    assert reply["request_id"] is None
    assert capture_calls == []
    _assert_json_only(reply)


def test_cyclic_and_overdeep_arguments_are_rejected_safely(monkeypatch):
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )
    cyclic = {}
    cyclic["self"] = cyclic
    overdeep = []
    cursor = overdeep
    for _ in range(70):
        child = []
        cursor.append(child)
        cursor = child

    for arguments in (cyclic, {"deep": overdeep}):
        reply = bridge.dispatch_project_agent_request(
            {}, None, _request("promptgraph_project_summary", arguments)
        )
        assert reply["reason"] == "invalid_request"
        assert reply["diagnostics"] == [{"code": "invalid_json_arguments"}]
        _assert_json_only(reply)
    assert capture_calls == []


def test_outer_request_string_and_node_budgets_remain_enforced(monkeypatch):
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )
    session, token = _session(_project())

    oversized_string = {"payload": "x" * 500_001}
    oversized_node_list = {"payload": [None] * 20_000}
    for arguments in (oversized_string, oversized_node_list):
        reply = bridge.dispatch_project_agent_request(
            session, token, _request("promptgraph_project_summary", arguments)
        )
        assert reply["reason"] == "invalid_request"
        assert reply["diagnostics"] == [{"code": "invalid_json_arguments"}]
        _assert_json_only(reply)

    assert capture_calls == []


def test_non_string_top_level_key_is_rejected_without_key_hooks(monkeypatch):
    class HostileKey:
        hash_calls = 0
        equality_calls = 0

        def __hash__(self):
            type(self).hash_calls += 1
            return 1

        def __eq__(self, other):
            type(self).equality_calls += 1
            return False

    key = HostileKey()
    request = _request("promptgraph_project_summary", {})
    request[key] = "value"
    HostileKey.hash_calls = 0
    HostileKey.equality_calls = 0
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )

    reply = bridge.dispatch_project_agent_request({}, None, request)

    assert reply["diagnostics"] == [{"code": "invalid_envelope"}]
    assert capture_calls == []
    assert HostileKey.hash_calls == HostileKey.equality_calls == 0


def test_capabilities_need_no_project_and_ignore_unsafe_capture_mode(monkeypatch):
    _fast_reruns(monkeypatch, True)
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: (_ for _ in ()).throw(AssertionError("must stay lazy")),
    )

    reply = bridge.dispatch_project_agent_request(
        {}, None, _request("promptgraph_capabilities", {})
    )

    assert reply["status"] == "completed"
    assert reply["result"]["agent_callable_apply"] is False
    _assert_json_only(reply)


@pytest.mark.parametrize(
    ("tool", "arguments", "expected_reason"),
    [
        ("future_unknown_tool", {}, "unknown_tool"),
        ("promptgraph_apply_batch_replace", {}, "unknown_tool"),
        ("promptgraph_get_illustration", {}, "invalid_arguments"),
        ("promptgraph_list_scenes", {"limit": True}, "invalid_arguments"),
    ],
)
def test_unknown_apply_and_adapter_transport_invalid_calls_do_not_capture(
        monkeypatch, tool, arguments, expected_reason):
    capture_calls = []
    monkeypatch.setattr(
        bridge,
        "capture_active_project",
        lambda *args: capture_calls.append(args),
    )
    session, token = _session(_project())

    reply = bridge.dispatch_project_agent_request(
        session, token, _request(tool, arguments)
    )

    assert reply["status"] == "completed"
    assert reply["result"]["reason"] == expected_reason
    assert capture_calls == []
    _assert_json_only(reply)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("promptgraph_project_summary", {}),
        ("promptgraph_list_scenes", {"limit": 10}),
        ("promptgraph_list_illustrations", {}),
        ("promptgraph_get_illustration", {"illustration_id": "illustration-1"}),
        ("promptgraph_preview_batch_replace", {
            "illustration_ids": ["illustration-1"],
            "find_text": "red",
            "replace_text": "blue",
            "match_mode": "contains_token",
        }),
    ],
)
def test_project_dependent_tools_delegate_with_one_isolated_capture(
        monkeypatch, tool, arguments):
    _fast_reruns(monkeypatch)
    project = _project()
    before_live = copy.deepcopy(project)
    session, token = _session(project)
    capture_results = []
    original_capture = bridge.capture_active_project

    def capture_spy(state, run_token):
        result = original_capture(state, run_token)
        capture_results.append(result)
        return result

    monkeypatch.setattr(bridge, "capture_active_project", capture_spy)

    reply = bridge.dispatch_project_agent_request(session, token, _request(tool, arguments))

    assert reply["status"] == "completed"
    assert len(capture_results) == 1 and capture_results[0].ok
    captured = capture_results[0].capture
    assert captured is not None
    assert captured.project is not project
    assert captured.project == before_live
    assert reply["result"] == mcp_adapter.PromptGraphMCPAdapter(
        lambda: captured.project
    ).call_tool(tool, arguments)
    assert project == before_live
    _assert_json_only(reply)


def test_baseline_illustration_semantics_survive_the_bridge(monkeypatch):
    _fast_reruns(monkeypatch)
    project = _project()
    session, token = _session(project)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_list_illustrations", {})
    )

    assert reply["status"] == "completed"
    illustrations = reply["result"]["illustrations"]
    baseline = next(item for item in illustrations if item["illustration_id"] == "baseline")
    assert baseline["scene_id"] is None


def test_transport_valid_domain_invalid_request_captures_once_and_completes(monkeypatch):
    _fast_reruns(monkeypatch)
    calls = []
    original_capture = bridge.capture_active_project

    def capture_spy(state, run_token):
        calls.append(True)
        return original_capture(state, run_token)

    monkeypatch.setattr(bridge, "capture_active_project", capture_spy)
    session, token = _session(_project())

    reply = bridge.dispatch_project_agent_request(
        session, token,
        _request("promptgraph_get_illustration", {"illustration_id": "missing"}),
    )

    assert reply["status"] == "completed"
    assert reply["result"]["reason"] == "unknown_illustration_id"
    assert calls == [True]


def test_provider_reuses_the_same_captured_snapshot_within_one_dispatch(
        monkeypatch):
    _fast_reruns(monkeypatch)
    project = _project()
    session, token = _session(project)
    original_class = bridge.PromptGraphMCPAdapter
    capture_results = []
    original_capture = bridge.capture_active_project

    def capture_spy(state, run_token):
        result = original_capture(state, run_token)
        capture_results.append(result)
        return result

    class DoubleProviderAccessAdapter:
        def __init__(self, provider):
            self._provider = provider
            self._delegate = original_class(provider)

        def call_tool(self, name, arguments):
            first = self._provider()
            second = self._provider()
            assert first is second
            return self._delegate.call_tool(name, arguments)

    monkeypatch.setattr(bridge, "PromptGraphMCPAdapter", DoubleProviderAccessAdapter)
    monkeypatch.setattr(bridge, "capture_active_project", capture_spy)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    assert reply["status"] == "completed"
    assert len(capture_results) == 1 and capture_results[0].ok
    assert capture_results[0].capture.project is not project


@pytest.mark.parametrize(
    ("project_factory", "prepare", "expected_code"),
    [
        (lambda: None, lambda session: None, "missing_project"),
        (_project, lambda session: capture_safety.begin_project_capture_run(session),
         "run_not_current"),
    ],
)
def test_capture_failures_are_bridge_rejections_with_bounded_diagnostics(
        monkeypatch, project_factory, prepare, expected_code):
    _fast_reruns(monkeypatch)
    project = project_factory()
    session, token = _session(project)
    if expected_code == "run_not_current":
        prepare(session)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    assert reply["status"] == "rejected"
    assert reply["reason"] == "project_capture_failed"
    assert reply["diagnostics"] == [{"code": expected_code}]
    assert "Traceback" not in json.dumps(reply)
    _assert_json_only(reply)


def test_unsafe_fast_rerun_override_is_a_bounded_capture_failure(monkeypatch):
    _fast_reruns(monkeypatch, True)
    session, token = _session(_project())

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    assert reply["reason"] == "project_capture_failed"
    assert reply["diagnostics"] == [{"code": "overlapping_reruns_enabled"}]


def test_clone_exception_detail_does_not_escape_capture_failure(monkeypatch):
    _fast_reruns(monkeypatch)
    session, token = _session(_project())
    secret = r"C:\private\project\source.json"

    def fail_clone(self):
        raise RuntimeError(secret)

    monkeypatch.setattr(Project, "clone", fail_clone)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    serialized = json.dumps(reply)
    assert reply["diagnostics"] == [{"code": "capture_failed"}]
    assert secret not in serialized and "RuntimeError" not in serialized
    _assert_json_only(reply)


def test_unexpected_capture_owner_exception_is_bounded(monkeypatch):
    session, token = _session(_project())
    secret = r"C:\private\session\internal-state"

    def fail_capture(*args):
        raise RuntimeError(secret)

    monkeypatch.setattr(bridge, "capture_active_project", fail_capture)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    serialized = json.dumps(reply)
    assert reply["reason"] == "project_capture_failed"
    assert reply["diagnostics"] == [{"code": "capture_unavailable"}]
    assert secret not in serialized and "RuntimeError" not in serialized


def test_project_replacement_during_capture_is_reported_without_leaking_state(
        monkeypatch):
    _fast_reruns(monkeypatch)
    project = _project()
    replacement = _project("replacement")
    session, token = _session(project)
    clone = Project.clone

    def replace_during_clone(self):
        snapshot = clone(self)
        session["project"] = replacement
        return snapshot

    monkeypatch.setattr(Project, "clone", replace_during_clone)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    assert reply["reason"] == "project_capture_failed"
    assert reply["diagnostics"] == [{"code": "project_changed"}]
    assert session["project"] is replacement
    _assert_json_only(reply)


@pytest.mark.parametrize("invalidated_boundary", ["project", "run"])
def test_post_dispatch_invalidation_rejects_adapter_result(
        monkeypatch, invalidated_boundary):
    _fast_reruns(monkeypatch)
    project = _project()
    replacement = _project("new live state")
    session, token = _session(project)
    original_class = bridge.PromptGraphMCPAdapter

    class ReplacingAdapter:
        def __init__(self, provider):
            self._delegate = original_class(provider)

        def call_tool(self, name, arguments):
            result = self._delegate.call_tool(name, arguments)
            if invalidated_boundary == "project":
                session["project"] = replacement
            else:
                capture_safety.begin_project_capture_run(session)
            return result

    monkeypatch.setattr(bridge, "PromptGraphMCPAdapter", ReplacingAdapter)

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_project_summary", {})
    )

    assert reply["status"] == "rejected"
    assert reply["reason"] == "project_capture_invalidated"
    assert reply["diagnostics"] == [{"code": "capture_no_longer_current"}]
    assert "result" not in reply
    _assert_json_only(reply)


def test_each_request_captures_current_live_state_without_cross_request_cache(
        monkeypatch):
    _fast_reruns(monkeypatch)
    project = _project("red shirt")
    session, token = _session(project)
    capture_calls = []
    original_capture = bridge.capture_active_project

    def capture_spy(state, run_token):
        capture_calls.append(True)
        return original_capture(state, run_token)

    monkeypatch.setattr(bridge, "capture_active_project", capture_spy)

    first = bridge.dispatch_project_agent_request(
        session, token,
        _request("promptgraph_get_illustration", {"illustration_id": "illustration-1"}),
    )
    project.prompt_lines[2].current_text = "blue shirt"
    project.prompt_lines[2].tokens = parse_prompt("blue shirt")
    project.project_metadata["revision"] = 2
    second = bridge.dispatch_project_agent_request(
        session, token,
        _request("promptgraph_get_illustration", {"illustration_id": "illustration-1"}),
    )

    assert first["status"] == second["status"] == "completed"
    assert first["result"]["illustration"]["positive_prompt"]["text"] == "red shirt"
    assert second["result"]["illustration"]["positive_prompt"]["text"] == "blue shirt"
    assert capture_calls == [True, True]


def test_preview_does_not_mutate_live_or_captured_snapshot(monkeypatch):
    _fast_reruns(monkeypatch)
    project = _project()
    before_live = copy.deepcopy(project)
    session, token = _session(project)
    captures = []
    original_capture = bridge.capture_active_project

    def capture_spy(state, run_token):
        result = original_capture(state, run_token)
        captures.append(result.capture)
        return result

    monkeypatch.setattr(bridge, "capture_active_project", capture_spy)
    arguments = {
        "illustration_ids": ["illustration-1"],
        "find_text": "red",
        "replace_text": "blue",
        "match_mode": "contains_token",
    }

    reply = bridge.dispatch_project_agent_request(
        session, token, _request("promptgraph_preview_batch_replace", arguments)
    )

    assert reply["status"] == "completed"
    assert len(captures) == 1 and captures[0] is not None
    assert project == before_live
    assert captures[0].project == before_live
    _assert_json_only(reply)


def test_adapter_result_must_be_json_safe(monkeypatch):
    monkeypatch.setattr(
        mcp_adapter.PromptGraphMCPAdapter,
        "call_tool",
        lambda self, name, arguments: {"unsafe": _Hostile()},
    )

    reply = bridge.dispatch_project_agent_request(
        {}, None, _request("promptgraph_capabilities", {})
    )

    assert reply["status"] == "rejected"
    assert reply["reason"] == "invalid_adapter_result"
    assert reply["diagnostics"] == [{"code": "adapter_result_not_json"}]
    _assert_json_only(reply)


@pytest.mark.parametrize(
    "result_factory",
    [
        pytest.param(lambda: {"unsafe": _Hostile()}, id="custom-object"),
        pytest.param(lambda: {"unsafe": float("nan")}, id="non-finite"),
        pytest.param(_cyclic_json_result, id="cycle"),
    ],
)
def test_adapter_custom_non_finite_and_cyclic_results_are_rejected(
        monkeypatch, result_factory):
    monkeypatch.setattr(
        mcp_adapter.PromptGraphMCPAdapter,
        "call_tool",
        lambda self, name, arguments: result_factory(),
    )

    reply = bridge.dispatch_project_agent_request(
        {}, None, _request("promptgraph_capabilities", {})
    )

    assert reply["status"] == "rejected"
    assert reply["reason"] == "invalid_adapter_result"
    assert reply["diagnostics"] == [{"code": "adapter_result_not_json"}]
    _assert_json_only(reply)


def test_large_real_illustration_result_passes_unchanged_through_bridge(monkeypatch):
    _fast_reruns(monkeypatch)
    long_text = "x" * 4_000
    lines = [_line("baseline", "baseline prompt"),
             _line("scene-1", long_text, line_type="separator",
                   separator_label=long_text)]
    for index in range(100):
        lines.append(_line(
            f"illustration-{index}", long_text,
            negative_prompt=long_text,
            image_path=long_text,
            generated_image_path=long_text,
            selected_candidate_path=long_text,
        ))
    project = build_graph(Project(prompt_lines=lines))
    request = _request("promptgraph_list_illustrations", {"limit": 100})
    direct_result = mcp_adapter.PromptGraphMCPAdapter(
        lambda: project
    ).call_tool(request["tool"], request["arguments"])
    direct_payload_size = len(json.dumps(
        direct_result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ))

    assert direct_result["ok"] is True
    assert direct_payload_size > 500_000

    session, token = _session(project)
    reply = bridge.dispatch_project_agent_request(session, token, request)

    assert reply["status"] == "completed"
    assert reply["result"] == direct_result
    assert len(json.dumps(
        reply["result"], ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )) == direct_payload_size
