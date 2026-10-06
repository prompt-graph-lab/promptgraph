import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import threading

import pytest

import ui.project_agent_named_pipe as named_pipe
from ui.project_agent_named_pipe import (
    LOCAL_PIPE_CONTRACT,
    LocalNamedPipeClient,
    WindowsNamedPipeBroker,
    _MAX_REQUEST_FRAME_BYTES,
    _read_client_frame,
    _win32,
    read_local_pairing_descriptor,
)
from ui.project_agent_session_mailbox import ProjectAgentSessionMailbox
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.project_agent_session_registry import ProjectAgentSessionRegistry


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Named Pipe transport")


class _ProjectToken:
    pass


class _FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _new_session(registry, broker, path):
    mailbox = ProjectAgentSessionMailbox()
    runtime = ProjectAgentSessionRuntime(mailbox=mailbox, _registry=registry)
    project = _ProjectToken()
    epoch = runtime.synchronize_target(project, path)
    delivery = runtime.publish_local_pairing_descriptor(broker)
    assert delivery.status == "armed"
    return runtime, mailbox, project, epoch, delivery


def _finish_request(mailbox, epoch, reply):
    mailbox.begin_full_app_run(epoch)
    claim = mailbox._claim_for_service(epoch)
    assert claim is not None
    outcome = mailbox.complete(claim, reply, epoch)
    assert outcome.status == "completed"


def test_real_named_pipe_round_trip_uses_exact_mailbox_reply_and_redacts_descriptor(caplog):
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, mailbox, _project, epoch, delivery = _new_session(
        registry, broker, "project-a.json",
    )
    descriptor_path = delivery.descriptor_file.path
    try:
        descriptor = read_local_pairing_descriptor(descriptor_path)
        assert descriptor.contract_version == LOCAL_PIPE_CONTRACT
        assert descriptor.server_pid == os.getpid()
        assert descriptor.capability not in repr(descriptor)
        assert descriptor.capability not in repr(delivery)
        assert descriptor_path not in repr(delivery)
        assert os.path.exists(descriptor_path)

        connection = LocalNamedPipeClient.connect(descriptor)
        assert connection.status == "paired"
        client = connection.client
        assert not os.path.exists(descriptor_path)

        target = client.current_target_epoch()
        assert target == {"status": "ok", "target_epoch": epoch}
        request = {
            "request_id": "pipe-roundtrip-1",
            "tool": "promptgraph_project_summary",
            "arguments": {},
        }
        assert client.submit(epoch, request) == {"status": "accepted"}

        bridge_reply = {
            "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
            "request_id": "pipe-roundtrip-1",
            "status": "completed",
            "result": {"ok": True, "summary": "same reply"},
        }
        _finish_request(mailbox, epoch, bridge_reply)
        assert client.consume_reply(epoch) == {
            "status": "completed",
            "reply": bridge_reply,
        }
        assert client.release() == {"status": "released"}
        assert descriptor.capability not in caplog.text

        route_id = runtime._registration.route_id
        endpoint = broker._leases.get(route_id)
        if endpoint is not None:
            endpoint.endpoint._thread.join(timeout=2)
    finally:
        runtime.close()
        broker.close()


def test_paired_connection_remains_usable_after_idle_longer_than_frame_timeout(
    monkeypatch,
):
    partial_frame_timeout = 0.02
    monkeypatch.setattr(
        named_pipe,
        "_PIPE_PARTIAL_FRAME_TIMEOUT_SECONDS",
        partial_frame_timeout,
    )
    idle_read_started = threading.Event()
    original_read_frame = named_pipe._PipeEndpoint._read_frame

    def observe_paired_idle(endpoint, timeout_seconds, *, allow_idle=False):
        if allow_idle:
            idle_read_started.set()
        return original_read_frame(
            endpoint,
            timeout_seconds,
            allow_idle=allow_idle,
        )

    monkeypatch.setattr(
        named_pipe._PipeEndpoint,
        "_read_frame",
        observe_paired_idle,
    )
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, _mailbox, _project, epoch, delivery = _new_session(
        registry, broker, "paired-idle.json",
    )
    client = None
    try:
        connection = LocalNamedPipeClient.connect_from_descriptor_file(
            delivery.descriptor_file.path,
        )
        assert connection.status == "paired"
        client = connection.client
        endpoint = broker._leases[runtime._registration.route_id].endpoint

        assert idle_read_started.wait(timeout=3)
        # Exercise the same boundary as the old read timeout without a
        # wall-clock 30-second wait.
        threading.Event().wait(partial_frame_timeout * 3)
        assert not endpoint._orphan_cleanup_started.is_set()
        assert client.current_target_epoch() == {
            "status": "ok",
            "target_epoch": epoch,
        }
        assert client.release() == {"status": "released"}
        endpoint._thread.join(timeout=2)
        assert not endpoint._thread.is_alive()
        assert not endpoint._orphan_cleanup_started.is_set()
    finally:
        if client is not None:
            client.close()
        runtime.close()
        broker.close()


def test_large_reply_is_not_given_a_narrower_transport_payload_limit():
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, mailbox, _project, epoch, delivery = _new_session(
        registry, broker, "large-reply.json",
    )
    client = None
    try:
        connection = LocalNamedPipeClient.connect_from_descriptor_file(
            delivery.descriptor_file.path,
        )
        assert connection.status == "paired"
        client = connection.client
        assert client.submit(epoch, {
            "request_id": "large-reply-1",
            "tool": "promptgraph_list_illustrations",
            "arguments": {"limit": 100},
        })["status"] == "accepted"
        bridge_reply = {
            "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
            "request_id": "large-reply-1",
            "status": "completed",
            "result": {"payload": "x" * 2_500_000},
        }
        _finish_request(mailbox, epoch, bridge_reply)
        received = client.consume_reply(epoch)
        assert received["status"] == "completed"
        assert received["reply"] == bridge_reply
        assert client.release()["status"] == "released"
    finally:
        if client is not None:
            client.close()
        runtime.close()
        broker.close()


def test_route_capability_and_incarnation_are_independently_bound():
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime_a, _mailbox_a, _project_a, _epoch_a, delivery_a = _new_session(
        registry, broker, "session-a.json",
    )
    runtime_b, _mailbox_b, _project_b, _epoch_b, delivery_b = _new_session(
        registry, broker, "session-b.json",
    )
    clients = []
    try:
        descriptor_a = read_local_pairing_descriptor(delivery_a.descriptor_file.path)
        descriptor_b = read_local_pairing_descriptor(delivery_b.descriptor_file.path)
        remote_pipe = replace(
            descriptor_a,
            pipe_name=r"\\remote-host\pipe\PromptGraph-invalid",
        )
        assert LocalNamedPipeClient.connect(remote_pipe).status == "invalid_descriptor"

        wrong_route_to_b = replace(
            descriptor_a,
            pipe_name=descriptor_b.pipe_name,
            route_id=descriptor_b.route_id,
        )
        assert LocalNamedPipeClient.connect(wrong_route_to_b).status == "invalid_pairing"

        wrong_route = replace(descriptor_a, route_id=descriptor_b.route_id)
        assert LocalNamedPipeClient.connect(wrong_route).status == "invalid_pairing"
        wrong_capability = replace(descriptor_a, capability="A" * len(descriptor_a.capability))
        assert LocalNamedPipeClient.connect(wrong_capability).status == "invalid_pairing"
        wrong_incarnation = replace(
            descriptor_a,
            process_incarnation="other-process-incarnation",
        )
        assert LocalNamedPipeClient.connect(wrong_incarnation).status == "invalid_pairing"

        connection_a = LocalNamedPipeClient.connect(descriptor_a)
        connection_b = LocalNamedPipeClient.connect(descriptor_b)
        assert connection_a.status == connection_b.status == "paired"
        clients.extend([connection_a.client, connection_b.client])
        assert connection_a.client.current_target_epoch()["target_epoch"] == _epoch_a
        assert connection_b.client.current_target_epoch()["target_epoch"] == _epoch_b

        assert connection_a.client.release()["status"] == "released"
        assert connection_b.client.release()["status"] == "released"
        assert LocalNamedPipeClient.connect(descriptor_a).status == "pipe_unavailable"
    finally:
        for client in clients:
            client.close()
        runtime_a.close()
        runtime_b.close()
        broker.close()


def test_target_transition_keeps_pairing_and_uses_mailbox_stale_semantics():
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, mailbox, project_a, epoch_a, delivery = _new_session(
        registry, broker, "project-a.json",
    )
    client = None
    try:
        connection = LocalNamedPipeClient.connect_from_descriptor_file(
            delivery.descriptor_file.path,
        )
        assert connection.status == "paired"
        client = connection.client
        request = {
            "request_id": "old-target-1",
            "tool": "promptgraph_project_summary",
            "arguments": {},
        }
        assert client.submit(epoch_a, request)["status"] == "accepted"

        project_b = _ProjectToken()
        epoch_b = runtime.synchronize_target(project_b, "project-b.json")
        assert epoch_b != epoch_a
        assert client.current_target_epoch() == {
            "status": "ok",
            "target_epoch": epoch_b,
        }
        assert client.consume_reply(epoch_a)["status"] == "stale_target"

        assert client.submit(epoch_b, {
            "request_id": "new-target-1",
            "tool": "promptgraph_project_summary",
            "arguments": {},
        })["status"] == "accepted"
        bridge_reply = {
            "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
            "request_id": "new-target-1",
            "status": "completed",
            "result": {"active": "project-b"},
        }
        _finish_request(mailbox, epoch_b, bridge_reply)
        assert client.consume_reply(epoch_b) == {
            "status": "completed",
            "reply": bridge_reply,
        }
        assert client.release()["status"] == "released"
        assert project_a is not project_b
    finally:
        if client is not None:
            client.close()
        runtime.close()
        broker.close()


def test_disconnect_drains_old_generation_before_fresh_pairing_can_claim():
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, mailbox, _project, epoch, delivery = _new_session(
        registry, broker, "disconnect.json",
    )
    old_client = None
    new_client = None
    try:
        old_connection = LocalNamedPipeClient.connect_from_descriptor_file(
            delivery.descriptor_file.path,
        )
        assert old_connection.status == "paired"
        old_client = old_connection.client
        assert old_client.submit(epoch, {
            "request_id": "disconnect-1",
            "tool": "promptgraph_project_summary",
            "arguments": {},
        })["status"] == "accepted"
        lease = broker._leases[runtime._registration.route_id]
        endpoint = lease.endpoint
        old_client.close()
        assert endpoint._orphan_cleanup_started.wait(timeout=3)

        _finish_request(mailbox, epoch, {
            "bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
            "request_id": "disconnect-1",
            "status": "completed",
            "result": {"must_not_transfer": True},
        })
        endpoint._thread.join(timeout=3)
        assert not endpoint._thread.is_alive()
        assert mailbox.state == "idle"

        fresh = runtime.publish_local_pairing_descriptor(broker)
        assert fresh.status == "armed"
        connection = LocalNamedPipeClient.connect_from_descriptor_file(
            fresh.descriptor_file.path,
        )
        assert connection.status == "paired"
        new_client = connection.client
        assert new_client.consume_reply(epoch)["status"] == "idle"
        assert new_client.submit(epoch, {
            "request_id": "fresh-generation-1",
            "tool": "promptgraph_project_summary",
            "arguments": {},
        })["status"] == "accepted"
        assert new_client.release()["status"] == "in_flight"
    finally:
        if old_client is not None:
            old_client.close()
        if new_client is not None:
            new_client.close()
        runtime.close()
        broker.close()


def test_expired_pairing_capability_fails_without_claiming_the_route():
    clock = _FakeClock()
    registry = ProjectAgentSessionRegistry(clock=clock)
    broker = WindowsNamedPipeBroker(registry)
    runtime, _mailbox, _project, _epoch, delivery = _new_session(
        registry, broker, "expired.json",
    )
    try:
        descriptor = read_local_pairing_descriptor(delivery.descriptor_file.path)
        clock.advance(descriptor.expires_in_seconds + 1)
        connection = LocalNamedPipeClient.connect(descriptor)
        assert connection.status == "expired_pairing"
        assert runtime._registration.arm_pairing().status == "armed"
    finally:
        runtime.close()
        broker.close()


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        (struct.pack(">I", len(b"{not-json")) + b"{not-json", "invalid_request"),
        (struct.pack(">I", _MAX_REQUEST_FRAME_BYTES + 1), "invalid_request"),
    ],
)
def test_malformed_claim_frames_fail_boundedly_without_consuming_the_offer(wire, expected):
    registry = ProjectAgentSessionRegistry()
    broker = WindowsNamedPipeBroker(registry)
    runtime, _mailbox, _project, _epoch, delivery = _new_session(
        registry, broker, "malformed.json",
    )
    raw_handle = None
    client = None
    try:
        descriptor = read_local_pairing_descriptor(delivery.descriptor_file.path)
        api = _win32()
        raw_handle = api.open_pipe_client(descriptor.pipe_name)
        assert api.pipe_server_pid(raw_handle) == descriptor.server_pid
        api.write_all(raw_handle, wire)
        response = json.loads(_read_client_frame(api, raw_handle).decode("utf-8"))
        assert response == {"status": expected}
        api.close_handle(raw_handle)
        raw_handle = None

        valid = LocalNamedPipeClient.connect(descriptor)
        assert valid.status == "paired"
        client = valid.client
        assert client.current_target_epoch()["status"] == "ok"
    finally:
        if raw_handle is not None:
            _win32().close_handle(raw_handle)
        if client is not None:
            client.close()
        runtime.close()
        broker.close()


def test_named_pipe_policy_rejects_remote_clients_and_uses_single_instance_per_route(
    monkeypatch,
):
    registry = ProjectAgentSessionRegistry()
    api = _win32()
    native_create_pipe = api.kernel32.CreateNamedPipeW
    native_convert_security_descriptor = (
        api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    )
    create_pipe_arguments = []
    sddl_arguments = []

    def capture_pipe_configuration(
        pipe_name,
        open_mode,
        pipe_mode,
        max_instances,
        out_buffer_bytes,
        in_buffer_bytes,
        default_timeout,
        security_attributes,
    ):
        create_pipe_arguments.append((pipe_mode, max_instances))
        return native_create_pipe(
            pipe_name,
            open_mode,
            pipe_mode,
            max_instances,
            out_buffer_bytes,
            in_buffer_bytes,
            default_timeout,
            security_attributes,
        )

    def capture_security_descriptor(sddl, revision, descriptor, size):
        sddl_arguments.append(sddl)
        return native_convert_security_descriptor(sddl, revision, descriptor, size)

    monkeypatch.setattr(
        api.kernel32,
        "CreateNamedPipeW",
        capture_pipe_configuration,
    )
    monkeypatch.setattr(
        api.advapi32,
        "ConvertStringSecurityDescriptorToSecurityDescriptorW",
        capture_security_descriptor,
    )
    broker = WindowsNamedPipeBroker(registry)
    runtime, _mailbox, _project, _epoch, _delivery = _new_session(
        registry, broker, "pipe-policy.json",
    )
    try:
        assert create_pipe_arguments
        pipe_mode, max_instances = create_pipe_arguments[0]
        assert pipe_mode & 0x00000008  # PIPE_REJECT_REMOTE_CLIENTS
        assert max_instances == 1
        assert sddl_arguments == [
            f"D:P(A;;GA;;;{api.current_logon_sid()})(A;;GA;;;SY)"
        ]
    finally:
        runtime.close()
        broker.close()


def test_transport_module_does_not_import_streamlit_project_capture_or_bridge():
    module_path = Path(__file__).resolve().parents[1] / "ui" / (
        "project_agent_named_pipe.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = (
        "streamlit",
        "core.project",
        "ui.project_agent_request_bridge",
        "ui.project_capture_safety",
    )
    assert not any(
        imported == blocked or imported.startswith(f"{blocked}.")
        for imported in imports
        for blocked in forbidden
    )
