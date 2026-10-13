"""Offline history GET characterization, no server or actual HTTP requests."""
from dataclasses import replace
import http.client
import json
from unittest.mock import Mock, patch
import uuid

import pytest

from core import comfy_http_submission as submission
from core.comfy_http_history import PromptHTTPHistoryTransport, stdlib_history_wire_for_characterization
from core.comfy_http_submission import PromptHTTPPolicy, SubmissionResult
from core.comfy_remote_output_receipts import MAX_REMOTE_BYTES
from ui.agent_generation_comfy_executor import history_result_provider_for_characterization
from test_comfy_http_submission import Response, issued, prepared
from test_agent_generation_comfy_executor import harness, metadata, raw
from test_agent_generation_executor_handoff import start
from test_comfy_output_containment import store, successful_metadata
from ui.agent_generation_executor_handoff import local_output_custody_current_for_characterization as current

PROMPT = "b13d2c9a-5374-469f-9730-1c5ad17e1b04"


class Wire:
    def __init__(self, response=None, *, connect_error=None, get_error=None, close_error=None):
        self.response = response if response is not None else Response(b"{}")
        self.connect_error, self.get_error, self.close_error = connect_error, get_error, close_error
        self.origins, self.gets, self.closed = [], [], False

    def __call__(self, origin, timeout):
        self.origins.append((origin, timeout))
        return self

    def connect(self):
        if self.connect_error:
            raise self.connect_error

    def get_history(self, prompt_id, timeout):
        self.gets.append((prompt_id, timeout))
        if self.get_error:
            raise self.get_error
        return self.response

    def post_prompt(self, *args):
        raise AssertionError("GET must never submit POST")

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def transport(wire, **kwargs):
    return PromptHTTPHistoryTransport(wire_factory=wire, characterization=True, **kwargs)


@pytest.mark.parametrize("body", [b"{}", b" { } \n"])
def test_only_valid_empty_object_is_pending(prepared, body):
    wire = Wire(Response(body))
    read = transport(wire)
    reply = read(prepared, PROMPT)
    assert reply.status == "pending" and reply.history_json == b""
    assert wire.gets == [(PROMPT, 10)]
    assert wire.closed and wire.response.closed and wire.response.finished
    assert read.observation().failure_class == "none" and read.execution_available is False


@pytest.mark.parametrize("endpoint,host,port", [
    ("http://127.0.0.1", "127.0.0.1", None), ("http://127.0.0.1:8188", "127.0.0.1", 8188),
    ("http://[::1]", "[::1]", None), ("https://[2001:db8::1]:443", "[2001:db8::1]", 443),
    ("https://example.test", "example.test", None), ("https://example.test:8443", "example.test", 8443),
])
def test_frozen_origin_exact_request_and_original_history_bytes(endpoint, host, port):
    prepared = issued(endpoint)
    body = successful_metadata(PROMPT)
    wire = Wire(Response(body))
    reply = transport(wire, policy=PromptHTTPPolicy(2, 3))(prepared, PROMPT)
    assert reply.status == "ready" and reply.history_json is body
    origin, timeout = wire.origins[0]
    assert (origin.host, origin.port, timeout) == (host, port, 2)
    assert wire.gets == [(PROMPT, 3)] and wire.closed and wire.response.closed
    assert all(0 < size <= 8192 and 0 < timeout <= 3 for size, timeout in wire.response.reads)
    assert prepared.body_json  # GET never serializes or submits these bytes.


@pytest.mark.parametrize("body", [b"", b"null", b"[]", b"not JSON", b'{"x":NaN}',
    b'{"x":{},"x":{}}', raw({str(uuid.uuid4()): {}}), raw({PROMPT: {}, str(uuid.uuid4()): {}}),
    raw({PROMPT: []}), b"x" * (MAX_REMOTE_BYTES + 1)], ids=[
        "empty", "null", "array", "non-json", "nonfinite", "duplicate-key", "unrelated",
        "conflicting", "non-object-record", "oversized"])
def test_unrelated_conflicting_malformed_or_oversized_history_is_unknown(prepared, body):
    wire = Wire(Response(body))
    reply = transport(wire)(prepared, PROMPT)
    assert reply.status == "unknown" and reply.history_json == b""
    assert wire.closed and wire.response.closed
    assert sum(size for size, _ in wire.response.reads) <= MAX_REMOTE_BYTES + 1


def test_exact_metadata_limit_is_accepted_without_reencoding(prepared):
    body = successful_metadata(PROMPT)
    body += b" " * (MAX_REMOTE_BYTES - len(body))
    assert transport(Wire(Response(body)))(prepared, PROMPT).history_json == body


@pytest.mark.parametrize("prompt", ["bad", "../view", PROMPT.upper(), True, None])
def test_invalid_uuid_never_touches_wire(prepared, prompt):
    wire = Wire()
    assert transport(wire)(prepared, prompt).status == "unknown"
    assert not wire.origins and not wire.gets


def test_no_default_no_arbitrary_destination_and_replaced_request_is_rejected(prepared):
    wire = Wire()
    assert PromptHTTPHistoryTransport()(prepared, PROMPT).status == "unknown"
    assert PromptHTTPHistoryTransport(wire_factory=wire)(prepared, PROMPT).status == "unknown"
    read = transport(wire)
    for clone in (replace(prepared), replace(prepared, prompt_url="http://other/prompt")):
        assert read(clone, PROMPT).status == "unknown"
    with pytest.raises(TypeError):
        read(prepared, PROMPT, url="http://other/history/" + PROMPT)
    assert not wire.origins


@pytest.mark.parametrize("policy", [PromptHTTPPolicy(0, 1), PromptHTTPPolicy(True, 1),
    PromptHTTPPolicy(1, float("nan")), PromptHTTPPolicy(1, 121), {}])
def test_invalid_policy_never_touches_wire(prepared, policy):
    wire = Wire()
    assert transport(wire, policy=policy)(prepared, PROMPT).status == "unknown"
    assert not wire.origins


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 404, 429, 500, 503])
def test_http_errors_redirects_never_prove_failure_or_retry(prepared, status):
    wire = Wire(Response(status=status))
    read = transport(wire)
    assert read(prepared, PROMPT).status == "unknown"
    assert read.observation().failure_class == "http_status"
    assert len(wire.gets) == 1 and not wire.response.reads
    assert wire.closed and wire.response.closed


@pytest.mark.parametrize("phase", ["connect", "get", "read", "finish"])
@pytest.mark.parametrize("error", [TimeoutError("PRIVATE_URL"), ConnectionResetError("PRIVATE_AUTH")])
def test_timeout_connection_loss_and_framing_uncertainty_close_resources(prepared, phase, error):
    wire = Wire(Response(error=error if phase == "read" else None,
                         finish_error=error if phase == "finish" else None),
                connect_error=error if phase == "connect" else None,
                get_error=error if phase == "get" else None)
    read = transport(wire)
    assert read(prepared, PROMPT).status == ("timeout" if isinstance(error, TimeoutError) else "unknown")
    assert wire.closed
    if phase in {"read", "finish"}:
        assert wire.response.closed
    assert "PRIVATE" not in repr(read.observation())


def test_incomplete_read_never_returns_pending(prepared):
    wire = Wire(Response(b"{}", finish_error=http.client.IncompleteRead(b"private")))
    assert transport(wire)(prepared, PROMPT).status == "unknown"
    assert wire.closed and wire.response.closed


def test_nonrenewing_deadline_rejects_late_eof_and_shrinks_timeout(prepared):
    now = [0]
    class Dribble(Response):
        def read(self, size, timeout):
            self.reads.append((size, timeout))
            now[0] += 2
            return b"{}" if len(self.reads) == 1 else b""
    wire = Wire(Dribble())
    read = transport(wire, policy=PromptHTTPPolicy(1, 3), clock=lambda: now[0])
    reply = read(prepared, PROMPT)
    assert reply.status == "timeout" and reply.history_json == b""
    assert [timeout for _, timeout in wire.response.reads] == [3, 1]
    assert wire.closed and wire.response.closed


@pytest.mark.parametrize("resource", ["response", "connection"])
def test_cleanup_failure_is_unknown_even_after_valid_body(prepared, resource):
    wire = Wire(Response(b"{}", close_error=ValueError() if resource == "response" else None),
                close_error=ValueError() if resource == "connection" else None)
    assert transport(wire)(prepared, PROMPT).status == "unknown"
    assert wire.closed and wire.response.closed


@pytest.mark.parametrize("scheme,address,port", [("http", "127.0.0.1", None),
    ("http", "127.0.0.1", 8188), ("http", "[::1]", None), ("http", "[::1]", 8188),
    ("https", "[2001:db8::1]", None), ("https", "[2001:db8::1]", 8443)])
def test_stdlib_exact_get_no_proxy_auth_cookies_or_body(scheme, address, port, monkeypatch):
    for key in ("http_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(key, "http://user:credential@proxy.test")
    endpoint = f"{scheme}://{address}" + (f":{port}" if port else "")
    prepared = issued(endpoint)
    native = Mock()
    response = Mock(status=200, length=0)
    response.getheaders.return_value = []
    response.read1.side_effect = [b"{}", b""]
    native.getresponse.return_value = response
    cls = "HTTPSConnection" if scheme == "https" else "HTTPConnection"
    with patch.object(submission.http.client, cls, return_value=native) as ctor, \
         patch("urllib.request.urlopen", side_effect=AssertionError("ambient opener")):
        assert transport(stdlib_history_wire_for_characterization)(prepared, PROMPT).status == "pending"
    ctor.assert_called_once_with(address, port, timeout=5)
    native.request.assert_called_once_with("GET", "/history/" + PROMPT, body=None,
                                          headers={"Accept": "application/json"})
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize("headers,length", [([("Content-Length", "42")], 2),
    ([("Content-Length", "2"), ("Content-Length", "3")], 0),
    ([("Content-Length", "2"), ("Transfer-Encoding", "chunked")], 0),
    ([("Transfer-Encoding", "custom")], 0)])
def test_stdlib_incomplete_ambiguous_framing_is_unknown(prepared, headers, length):
    native = Mock()
    response = Mock(status=200, length=length)
    response.getheaders.return_value = headers
    response.read1.side_effect = [b"{}", b""]
    native.getresponse.return_value = response
    with patch.object(submission.http.client, "HTTPConnection", return_value=native):
        assert transport(stdlib_history_wire_for_characterization)(prepared, PROMPT).status == "unknown"
    response.close.assert_called_once()
    native.close.assert_called_once()


def test_stdlib_connection_close_keeps_captured_socket_and_nonrenewing_deadline(prepared):
    now, timeouts = [0], []
    class Socket:
        def settimeout(self, timeout):
            timeouts.append(timeout)
    class Dribble:
        status, length, closed = 200, None, False
        def getheaders(self):
            return [("Connection", "close")]
        def read1(self, size):
            now[0] += 2
            return b"{}" if now[0] == 2 else b""
        def close(self):
            self.closed = True
    response = Dribble()
    class Native:
        def __init__(self):
            self.sock, self.closed, self.gets = Socket(), False, []
        def connect(self):
            pass
        def request(self, method, path, **kwargs):
            self.gets.append((method, path))
        def getresponse(self):
            self.sock = None
            return response
        def close(self):
            self.closed = True
    native = Native()
    with patch.object(submission.http.client, "HTTPConnection", return_value=native):
        read = transport(stdlib_history_wire_for_characterization,
                         policy=PromptHTTPPolicy(1, 3), clock=lambda: now[0])
        assert read(prepared, PROMPT).status == "timeout"
    assert native.gets == [("GET", "/history/" + PROMPT)]
    assert timeouts[-2:] == [3, 1] and native.sock is None
    assert native.closed and response.closed


def test_explicit_later_history_read_executor_correlation_and_no_post_resubmission():
    wire = Wire()
    read = transport(wire)
    provider = history_result_provider_for_characterization(read)
    values, adapter, sent = harness(transport=lambda p: SubmissionResult("accepted", raw({"prompt_id": PROMPT})),
                                   provider=provider)
    try:
        accepted = start(values, adapter.accept_and_run_for_characterization)
        assert accepted.status == "characterized_acceptance"
        assert adapter.observation().status == "awaiting_remote_result"
        assert len(sent) == len(wire.gets) == 1
        adapter.advance_for_characterization()
        assert len(sent) == len(wire.gets) == 1
        wire.response = Response(successful_metadata(PROMPT))
        later = provider(sent[0], PROMPT)
        assert (later.request_id, later.prompt_id, later.status) == (sent[0].request_id, PROMPT, "ready")
        assert adapter.receive_result_for_characterization(later).status == "awaiting_download"
        assert adapter.remote_receipts()[0].execution_succeeded is True
        assert len(sent) == 1 and len(wire.gets) == 2
        snapshot = values[0].generation_jobs.snapshot(accepted.job_id)
        assert snapshot["registered_count"] == 0 and snapshot["save_state"] == "not_attempted"
        assert not adapter.execution_available and not read.execution_available
    finally:
        values[0].close()


def test_statusless_history_never_authorizes_download_or_local_outputs(store):
    wire = Wire(Response(metadata(PROMPT)))
    provider = history_result_provider_for_characterization(transport(wire))
    values, adapter, sent = harness(transport=lambda p: SubmissionResult("accepted", raw({"prompt_id": PROMPT})),
                                   provider=provider)
    runtime, _, state, *_ = values
    adapter._local_gate = lambda envelope, remote, local: current(state, runtime, envelope, remote, local)
    try:
        accepted = start(values, adapter.accept_and_run_for_characterization)
        assert adapter.remote_receipts()[0].execution_succeeded is False
        download = Mock(side_effect=AssertionError("unverified execution must not download"))
        outcome = adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=download)
        assert outcome.status != "local_outputs_ready"
        download.assert_not_called()
        snapshot = runtime.generation_jobs.snapshot(accepted.job_id)
        assert snapshot["output_count"] == snapshot["registered_count"] == 0
        assert snapshot["save_state"] == "not_attempted" and len(sent) == 1
        assert all(r.state != "verified" for r in adapter.local_receipts())
    finally:
        runtime.close()


def test_unresolved_execution_status_remains_downstream_quarantined():
    history = json.loads(metadata(PROMPT))
    history[PROMPT]["status"] = {"completed": False, "status_str": "error"}
    provider = history_result_provider_for_characterization(transport(Wire(Response(raw(history)))))
    values, adapter, sent = harness(transport=lambda p: SubmissionResult("accepted", raw({"prompt_id": PROMPT})),
                                   provider=provider)
    try:
        accepted = start(values, adapter.accept_and_run_for_characterization)
        assert adapter.observation().status == "remote_metadata_quarantined"
        assert not adapter.remote_receipts() and not adapter.local_receipts() and len(sent) == 1
        assert values[0].generation_jobs.snapshot(accepted.job_id)["state"] != "failed"
    finally:
        values[0].close()
