"""Offline POST /prompt transport: deterministic wires, no ComfyUI service."""
from dataclasses import replace
import http.client
import json
from unittest.mock import Mock, patch
import uuid

import pytest

from core import comfy_http_submission as owner
from core.comfy_http_submission import (
    PromptHTTPPolicy, PromptHTTPSubmissionTransport, stdlib_prompt_wire_for_characterization,
)
from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.comfy_remote_output_receipts import MAX_REMOTE_BYTES
from test_agent_generation_comfy_executor import harness, raw, result
from test_agent_generation_executable_manifest import finalize, host_for
from test_agent_generation_executor_handoff import ready, start


@pytest.fixture
def prepared():
    values = ready()
    try:
        manifest = values[4].review.manifest
        return prepare_frozen_prompt_request(manifest, manifest.requests[0], client_id=str(uuid.uuid4()))
    finally:
        values[0].close()


class Response:
    def __init__(self, body=None, *, status=200, error=None, finish_error=None, close_error=None):
        self.body = body if body is not None else raw({"prompt_id": str(uuid.uuid4())})
        self.status, self.error, self.finish_error, self.close_error = status, error, finish_error, close_error
        self.reads, self.closed, self.finished = [], False, False

    def read(self, size, timeout):
        self.reads.append((size, timeout))
        if self.error:
            raise self.error
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def finish(self):
        self.finished = True
        if self.finish_error:
            raise self.finish_error

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class Wire:
    def __init__(self, response=None, *, connect_error=None, send_error=None, close_error=None):
        self.response = response or Response()
        self.connect_error, self.send_error, self.close_error = connect_error, send_error, close_error
        self.origins, self.sent, self.connects, self.closed = [], [], 0, False

    def __call__(self, origin, timeout):
        self.origins.append((origin, timeout))
        return self

    def connect(self):
        self.connects += 1
        if self.connect_error:
            raise self.connect_error

    def post_prompt(self, body, timeout):
        self.sent.append((body, timeout))
        if self.send_error:
            raise self.send_error
        return self.response

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def issued(endpoint="PRIVATE_ENDPOINT", *, request_id=None, client_id=None, change=None):
    provider = host_for(change=change)
    def approved(project, runs):
        context = provider(project, runs)
        context['generation_options']['comfyui_endpoint'] = endpoint
        return context
    manifest = finalize(runs=1, provider=approved).manifest
    request = manifest.requests[0]
    if request_id is not None:
        # Identity must be resealed by the finalizer's exact content contract.
        from core.generation_executable_manifest import fingerprint
        request = replace(request, request_id=request_id)
        rows = [{'request_id': request.request_id, 'illustration_id': request.illustration_id,
                 'request_index': request.request_index, 'run_index': request.run_index,
                 'workflow_identity': request.workflow_identity,
                 'seed_provenance': json.loads(request.seed_provenance_json)}]
        manifest = replace(manifest, requests=(request,), manifest_identity=fingerprint([
            manifest.proposal_id, manifest.plan_id, manifest.scene_id, manifest.source_identity,
            manifest.seed_policy, rows, json.loads(manifest.host_config_json)]))
    return prepare_frozen_prompt_request(manifest, request, client_id=client_id or str(uuid.uuid4()))


def transport(wire, **kwargs):
    return PromptHTTPSubmissionTransport(wire_factory=wire, characterization=True, **kwargs)


@pytest.mark.parametrize("url", ["http://PRIVATE_ENDPOINT/prompt", "https://example.test:8443/prompt", "http://[::1]:8188/prompt"])
def test_exact_frozen_body_destination_and_response_bounds(prepared, url):
    prepared = issued(url[:-len("/prompt")])
    wire = Wire()
    send = transport(wire, policy=PromptHTTPPolicy(2, 3))
    with patch('core.comfy_prompt_request.random.randint', side_effect=AssertionError('seed randomizer')):
        reply = send(prepared)
    assert reply.status == 'accepted'
    assert wire.sent == [(prepared.body_json, 3)]
    assert prepared.workflow_identity == __import__('hashlib').sha256(
        prepared.body_json[len(b'{"prompt":'):-len(b',"client_id":' + json.dumps(prepared.client_id).encode() + b'}')]).hexdigest()
    origin, timeout = wire.origins[0]
    assert timeout == 2
    assert origin.scheme == url.split(':')[0]
    assert all(0 < size <= 8192 and 0 < timeout <= 3 for size, timeout in wire.response.reads)
    assert wire.closed and wire.response.closed and wire.response.finished
    assert send.observation().failure_class == 'none' and not send.execution_available


@pytest.mark.parametrize("url", ["file:///prompt", "http://u:secret@example/prompt", "http://example/base/prompt",
    "http://example/prompt?secret=x", "http://example/prompt#secret", "http://example:0/prompt",
    "http://example:99999/prompt", "http://example\\other/prompt", "http://%65xample/prompt", "http://例.test/prompt"])
def test_unsupported_endpoint_fails_before_wire(prepared, url):
    wire = Wire()
    send = transport(wire)
    assert send(replace(prepared, prompt_url=url)).status == 'rejected_before_submission'
    assert not wire.origins and not wire.sent


@pytest.mark.parametrize("field,value", [('body_json', b'{}'), ('client_id', 'bad'), ('workflow_identity', '0' * 64),
    ('request_index', True), ('request_index', -1), ('request_id', ''), ('output_nodes', (('unknown', 'output'),))])
def test_bad_frozen_material_cannot_send(prepared, field, value):
    wire = Wire()
    assert transport(wire)(replace(prepared, **{field: value})).status == 'rejected_before_submission'
    assert not wire.origins


@pytest.mark.parametrize("policy", [PromptHTTPPolicy(0, 3), PromptHTTPPolicy(True, 3), PromptHTTPPolicy(1, float('inf')),
    PromptHTTPPolicy(1, 121), {'timeout': 1}])
def test_invalid_policy_never_touches_wire(prepared, policy):
    wire = Wire()
    assert transport(wire, policy=policy)(prepared).status == 'rejected_before_submission'
    assert not wire.origins


def test_no_default_transport_or_endpoint_body_override(prepared):
    wire = Wire()
    assert PromptHTTPSubmissionTransport()(prepared).status == 'rejected_before_submission'
    assert PromptHTTPSubmissionTransport(wire_factory=wire)(prepared).status == 'rejected_before_submission'
    with pytest.raises(TypeError):
        transport(wire)(prepared, endpoint='http://other', body=b'{}')
    assert not wire.origins


@pytest.mark.parametrize("phase,error", [('connect', TimeoutError('secret endpoint')), ('send', TimeoutError('secret body')),
    ('send', ConnectionResetError('secret auth')), ('read', ConnectionResetError()), ('read', TimeoutError()),
    ('finish', http.client.IncompleteRead(b'private'))])
def test_before_and_after_possible_send_failures_are_conservative_unknown_and_close(prepared, phase, error):
    wire = Wire(connect_error=error if phase == 'connect' else None, send_error=error if phase == 'send' else None,
        response=Response(error=error if phase == 'read' else None, finish_error=error if phase == 'finish' else None))
    send = transport(wire)
    assert send(prepared).status == ('rejected_before_submission' if phase == 'connect' else 'unknown')
    assert wire.closed
    if phase in {'read', 'finish'}:
        assert wire.response.closed
    assert send(prepared).status == 'unknown' and len(wire.origins) == 1
    assert not any(secret in repr(send.observation()) for secret in ('secret', 'private', prepared.prompt_url))


@pytest.mark.parametrize('status', [301, 302, 307, 308, 400, 401, 429, 500, 503])
def test_redirects_and_non_success_are_unknown_without_body_read_or_retry(prepared, status):
    wire = Wire(Response(status=status, body=b'endpoint=secret'))
    send = transport(wire)
    assert send(prepared).status == 'unknown'
    assert send.observation().failure_class == 'http_status'
    assert not wire.response.reads and wire.closed and wire.response.closed
    assert send(prepared).status == 'unknown' and len(wire.sent) == 1


@pytest.mark.parametrize('body', [b'', b'not JSON private', b'{}', b'{"prompt_id":"bad"}',
    b'{"prompt_id":"x","prompt_id":"y"}', b'{"prompt_id":NaN}', b'x' * (MAX_REMOTE_BYTES + 1)], ids=['empty', 'non-json', 'missing', 'bad-id', 'duplicate-key', 'nan', 'oversized'])
def test_malformed_invalid_or_oversized_response_withheld(prepared, body):
    wire = Wire(Response(body))
    send = transport(wire)
    reply = send(prepared)
    assert reply.status == 'unknown' and reply.response_json == b''
    assert sum(size for size, _ in wire.response.reads) <= MAX_REMOTE_BYTES + 1
    assert wire.closed and wire.response.closed
    assert body.decode(errors='replace') not in repr(send.observation()) if body else True


def test_exact_remote_metadata_byte_limit_and_duplicate_prompt_id(prepared):
    prompt = str(uuid.uuid4())
    body = raw({'prompt_id': prompt})
    body += b' ' * (MAX_REMOTE_BYTES - len(body))
    wire = Wire(Response(body))
    send = transport(wire)
    assert send(prepared).response_json == body
    wire.response = Response(raw({'prompt_id': prompt}))
    other = issued(request_id='other-request')
    assert send(other).status == 'unknown'
    assert send.observation().failure_class == 'duplicate_prompt_id' and len(wire.sent) == 2


def test_read_body_deadline_is_total_not_renewed_per_chunk(prepared):
    wire = Wire(Response(b' ' * 9000))
    ticks = iter([0, 1, 4])
    send = transport(wire, policy=PromptHTTPPolicy(1, 3), clock=lambda: next(ticks))
    assert send(prepared).status == 'unknown'
    assert send.observation().failure_class == 'timeout'
    assert len(wire.response.reads) == 1 and wire.closed and wire.response.closed


@pytest.mark.parametrize('phase', ['response', 'connection'])
def test_cleanup_failure_is_unknown_and_all_resources_still_closed(prepared, phase):
    wire = Wire(Response(close_error=RuntimeError('secret') if phase == 'response' else None),
                close_error=RuntimeError('secret') if phase == 'connection' else None)
    send = transport(wire)
    assert send(prepared).status == 'unknown'
    assert send.observation().failure_class == 'cleanup_failure'
    assert wire.closed and wire.response.closed


def test_stdlib_characterization_wire_uses_exact_http_no_ambient_proxies_cookies_auth(prepared, monkeypatch):
    for key in ('http_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
        monkeypatch.setenv(key, 'http://user:credential@proxy.example')
    native = Mock()
    response = Mock(status=200, length=0)
    response.getheaders.return_value = []
    response.read1.side_effect = [raw({'prompt_id': str(uuid.uuid4())}), b'']
    native.getresponse.return_value = response
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native) as ctor, \
         patch('urllib.request.urlopen', side_effect=AssertionError('ambient opener')):
        send = transport(stdlib_prompt_wire_for_characterization, policy=PromptHTTPPolicy(2, 3))
        assert send(prepared).status == 'accepted'
    ctor.assert_called_once_with('private_endpoint', None, timeout=2)
    native.request.assert_called_once_with('POST', '/prompt', body=prepared.body_json,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    assert native.connect.call_count == 1 and native.request.call_count == 1
    response.close.assert_called_once()
    native.close.assert_called_once()


def test_tls_wire_and_incomplete_declared_length_fail_closed(prepared):
    native = Mock()
    response = Mock(status=200, length=2)
    response.getheaders.return_value = [('Content-Length', '42')]
    response.read1.side_effect = [raw({'prompt_id': str(uuid.uuid4())}), b'']
    native.getresponse.return_value = response
    prepared = issued('https://example.test:443')
    with patch.object(owner.http.client, 'HTTPSConnection', return_value=native) as ctor:
        assert transport(stdlib_prompt_wire_for_characterization)(prepared).status == 'unknown'
    ctor.assert_called_once_with('example.test', 443, timeout=5)
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('scheme,address,port', [
    ('http', '::1', None), ('http', '::1', 8188),
    ('https', '2001:db8::1', None), ('https', '2001:db8::1', 8443),
])
def test_stdlib_ipv6_constructor_preserves_default_and_explicit_ports(scheme, address, port):
    endpoint = f'{scheme}://[{address}]' + (f':{port}' if port is not None else '')
    request = issued(endpoint)
    origin = owner._destination(request)
    connection = owner.stdlib_prompt_wire_for_characterization(origin, 5)
    try:
        assert origin.host == f'[{address}]'
        assert connection._connection.host == address
        default_port = 80 if scheme == 'http' else 443
        assert connection._connection.port == (port if port is not None else default_port)
        assert connection._connection.default_port == default_port
    finally:
        connection.close()


def test_stdlib_connection_close_body_reads_keep_the_shared_deadline():
    now = [0]
    prompt_body = raw({'prompt_id': str(uuid.uuid4())})
    sock_timeouts = []

    class Socket:
        def settimeout(self, timeout):
            sock_timeouts.append(timeout)

    class DribblingResponse:
        status = 200
        length = None

        def getheaders(self):
            return [('Connection', 'close')]

        def __init__(self):
            self.parts = [prompt_body[:12], prompt_body[12:]]
            self.closed = False

        def read1(self, size):
            part = self.parts.pop(0)
            now[0] += 2
            return part

        def close(self):
            self.closed = True

    response = DribblingResponse()

    class NativeConnection:
        def __init__(self):
            self.sock = Socket()
            self.closed = False

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            self.sock = None  # CPython's Connection: close ownership transfer.
            return response

        def close(self):
            self.closed = True

    native = NativeConnection()
    request = issued('http://example.test')
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        send = transport(stdlib_prompt_wire_for_characterization,
                         policy=PromptHTTPPolicy(1, 3), clock=lambda: now[0])
        assert send(request).status == 'unknown'

    assert send.observation().failure_class == 'timeout'
    assert sock_timeouts[-2:] == [3, 1]
    assert native.sock is None and native.closed and response.closed


@pytest.mark.parametrize('unknown', [False, True])
def test_existing_executor_one_attempt_and_all_runtime_gates_remain_disabled(unknown):
    wire = Wire(Response(status=503)) if unknown else Wire()
    send = transport(wire)
    values, adapter, sent = harness(transport=send, provider=lambda p, prompt: result(p, prompt, 'pending'))
    try:
        accepted = start(values, adapter.accept_and_run_for_characterization)
        assert accepted.status == ('handoff_invalidated' if unknown else 'characterized_acceptance')
        assert adapter.observation().status == ('submission_outcome_unknown' if unknown else 'awaiting_remote_result')
        for _ in range(3):
            adapter.advance_for_characterization()
        assert len(sent) == len(wire.sent) == 1
        assert not adapter.remote_receipts() and not adapter.local_receipts()
        assert not adapter.execution_available and not values[0].generation_jobs.execution_available
        snapshot = values[0].generation_jobs.snapshot(accepted.job_id)
        assert snapshot['registered_count'] == 0 and snapshot['save_state'] == 'not_attempted'
    finally:
        values[0].close()


def test_prepared_origin_rejects_valid_origin_and_resealed_body_substitution(prepared):
    import hashlib
    wire = Wire()
    send = transport(wire)
    changed = prepared.body_json.replace(b'PRIVATE_PATH', b'OTHER_PREFIX')
    suffix = b',"client_id":' + json.dumps(prepared.client_id).encode() + b'}'
    body_clone = replace(prepared, body_json=changed, workflow_identity=hashlib.sha256(
        changed[len(b'{"prompt":'):-len(suffix)]).hexdigest())
    for clone in (replace(prepared, prompt_url='http://other-valid-host/prompt'), body_clone, replace(prepared)):
        assert send(clone).status == 'rejected_before_submission'
    assert not wire.origins
    assert send(prepared).status == 'accepted'


def test_same_request_new_genuinely_prepared_client_cannot_retry(prepared):
    wire = Wire(send_error=TimeoutError())
    send = transport(wire)
    assert send(prepared).status == 'unknown'
    other = issued(request_id=prepared.request_id)
    assert other.client_id != prepared.client_id
    assert send(other).status == 'unknown'
    assert send.observation().failure_class == 'already_attempted' and len(wire.sent) == 1


def test_wire_reentry_cannot_make_a_second_attempt(prepared):
    wire = Wire()
    send = transport(wire)
    connect = wire.connect
    def reentry():
        assert send(prepared).status == 'unknown'
        connect()
    wire.connect = reentry
    assert send(prepared).status == 'accepted'
    assert len(wire.origins) == len(wire.sent) == 1


@pytest.mark.parametrize('headers', [
    [('Content-Length', '40'), ('Content-Length', '50')],
    [('Content-Length', '40'), ('Transfer-Encoding', 'chunked')],
    [('Content-Length', '-1')], [('Transfer-Encoding', 'custom')],
])
def test_stdlib_ambiguous_or_unsupported_http_framing_is_unknown_and_closed(prepared, headers):
    native = Mock()
    response = Mock(status=200)
    response.getheaders.return_value = headers
    native.getresponse.return_value = response
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        assert transport(stdlib_prompt_wire_for_characterization)(prepared).status == 'unknown'
    response.read1.assert_not_called()
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('endpoint', ['http://%65xample', 'http://例.test', 'http://example.test:0'])
def test_issued_but_unsupported_origin_is_rejected_before_wire(endpoint):
    request = issued(endpoint)
    wire = Wire()
    assert transport(wire)(request).status == 'rejected_before_submission'
    assert not wire.origins


def test_manual_request_cannot_construct_host_preparation_authority(prepared):
    from core.comfy_prompt_request import FrozenPromptRequest
    request = FrozenPromptRequest(prepared.request_id, prepared.request_index, prepared.workflow_identity,
        prepared.client_id, prepared.prompt_url, prepared.body_json, prepared.output_nodes)
    assert request == prepared  # receipt equality is unchanged; issuance is separate
    wire = Wire()
    assert transport(wire)(request).status == 'rejected_before_submission'
    assert not wire.origins
