"""Offline /view wires only; no service, production owner or storage integration."""
import copy
from dataclasses import replace
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest

from core import comfy_http_view as owner
from core.comfy_http_submission import PromptHTTPPolicy, _destination
from core.comfy_http_view import PromptHTTPViewTransport, stdlib_view_wire_for_characterization
from core.comfy_output_containment import CHUNK_BYTES, ImageDownloadLookup
from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.comfy_remote_output_receipts import validate_remote_outputs
from test_agent_generation_executable_manifest import finalize, host_for
from test_comfy_output_containment import image_bytes, running, store, successful_metadata


def binding(endpoint="http://PRIVATE_ENDPOINT", *, images=None, success=True, preview=False):
    host = host_for(change=(lambda flow: flow['out'].update(class_type='PreviewImage')) if preview else None)
    def approved(project, runs):
        context = host(project, runs)
        context['generation_options']['comfyui_endpoint'] = endpoint
        return context
    manifest = finalize(runs=1, provider=approved).manifest
    prepared = prepare_frozen_prompt_request(manifest, manifest.requests[0], client_id=str(uuid.uuid4()))
    envelope = SimpleNamespace(job_id="job", claim_id="claim", manifest=manifest)
    prompt = str(uuid.uuid4())
    remote = validate_remote_outputs(envelope, prepared, prompt,
        successful_metadata(prompt, images, success=success))
    image = remote.images[0]
    lookup = ImageDownloadLookup(prepared.prompt_url.removesuffix('/prompt'), image.filename,
        image.subfolder, image.bucket, image.identity)
    return envelope, prepared, remote, lookup


@pytest.fixture
def bound():
    return binding()


class Response:
    def __init__(self, body=b"image", *, status=200, headers=None, error=None,
                 finish_error=None, close_error=None):
        self.source = io.BytesIO(body)
        self.status = status
        self.headers = [('Content-Length', str(len(body)))] if headers is None else headers
        self.error, self.finish_error, self.close_error = error, finish_error, close_error
        self.reads, self.closed, self.finished = [], False, False

    def read(self, size, timeout):
        self.reads.append((size, timeout))
        if self.error:
            raise self.error
        return self.source.read(size)

    def finish(self):
        self.finished = True
        if self.finish_error:
            raise self.finish_error

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class Wire:
    def __init__(self, response=None, *, connect_error=None, get_error=None, close_error=None):
        self.response = response or Response()
        self.connect_error, self.get_error, self.close_error = connect_error, get_error, close_error
        self.origins, self.gets, self.closed = [], [], False

    def __call__(self, origin, timeout):
        self.origins.append((origin, timeout))
        return self

    def connect(self):
        if self.connect_error:
            raise self.connect_error

    def get_view(self, path, timeout):
        self.gets.append((path, timeout))
        if self.get_error:
            raise self.get_error
        return self.response

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def transport(wire, **kwargs):
    return PromptHTTPViewTransport(wire_factory=wire, characterization=True, **kwargs)


def consume(stream):
    parts = []
    try:
        while True:
            part = stream.read(CHUNK_BYTES)
            if not part:
                return b''.join(parts)
            parts.append(part)
    finally:
        stream.close()


@pytest.mark.parametrize('endpoint,host,port', [
    ('http://127.0.0.1', '127.0.0.1', None), ('http://127.0.0.1:8188', '127.0.0.1', 8188),
    ('https://127.0.0.1', '127.0.0.1', None), ('https://127.0.0.1:443', '127.0.0.1', 443),
    ('http://[::1]', '[::1]', None), ('http://[::1]:8188', '[::1]', 8188),
    ('https://[2001:db8::1]', '[2001:db8::1]', None), ('https://[2001:db8::1]:8443', '[2001:db8::1]', 8443),
])
def test_exact_frozen_origin_safe_query_and_streaming(endpoint, host, port):
    images = [{'filename': 'PRIVATE a&+雪.png', 'subfolder': 'PRIVATE/x &+雪', 'type': 'output'}]
    bound = binding(endpoint, images=images)
    data = b'x' * (CHUNK_BYTES + 2)
    wire, read = Wire(Response(data)), None
    read = transport(wire, policy=PromptHTTPPolicy(2, 3))
    stream = read(*bound)
    assert stream.content_length == len(data) and not wire.response.reads  # no buffering at open
    assert consume(stream) == data
    origin, timeout = wire.origins[0]
    assert (origin.host, origin.port, timeout) == (host, port, 2)
    path, timeout = wire.gets[0]
    assert path == '/view?filename=PRIVATE+a%26%2B%E9%9B%AA.png&subfolder=PRIVATE%2Fx+%26%2B%E9%9B%AA&type=output'
    assert urlsplit(path).path == '/view' and timeout == 3
    assert parse_qs(urlsplit(path).query) == {key: [value] for key, value in images[0].items()}
    assert all(0 < size <= CHUNK_BYTES and 0 < timeout <= 3 for size, timeout in wire.response.reads)
    assert wire.closed and wire.response.closed and wire.response.finished
    assert read.observation().status == 'downloaded'
    assert not read.execution_available and not read.protected_storage_available


def test_preview_bucket_comes_from_validated_descriptor():
    bound = binding(preview=True, images=[{'filename': 'a.png', 'subfolder': '', 'type': 'temp'}])
    wire = Wire()
    assert consume(transport(wire)(*bound)) == b'image'
    assert wire.gets[0][0] == '/view?filename=a.png&subfolder=&type=temp'


@pytest.mark.parametrize('change', ['origin', 'filename', 'subfolder', 'bucket', 'descriptor',
    'prepared_copy', 'prepared_origin', 'receipt_identity', 'receipt_request', 'receipt_descriptor',
    'receipt_evidence', 'receipt_success', 'raw_lookup'])
def test_forged_mismatched_binding_never_touches_wire(bound, change):
    envelope, prepared, remote, lookup = bound
    if change == 'origin': lookup = replace(lookup, endpoint_origin='http://other')
    elif change == 'filename': lookup = replace(lookup, filename='other.png')
    elif change == 'subfolder': lookup = replace(lookup, subfolder='other')
    elif change == 'bucket': lookup = replace(lookup, bucket='temp')
    elif change == 'descriptor': lookup = replace(lookup, descriptor_identity='other')
    elif change == 'prepared_copy': prepared = replace(prepared)
    elif change == 'prepared_origin': prepared = replace(prepared, prompt_url='http://other/prompt')
    elif change == 'receipt_identity': remote = replace(remote, identity='other')
    elif change == 'receipt_request': remote = replace(remote, request_id='other')
    elif change == 'receipt_descriptor': remote = replace(remote, images=(replace(remote.images[0], filename='other.png'),))
    elif change == 'receipt_evidence': remote = replace(remote, _validated_history_json=b'{}')
    elif change == 'receipt_success': remote = replace(remote, execution_succeeded=False)
    else: lookup = vars(lookup)
    wire, read = Wire(), None
    read = transport(wire)
    with pytest.raises(ValueError, match='^view_download_failed$'):
        read(envelope, prepared, remote, lookup)
    assert not wire.origins and not wire.gets
    assert read.observation().failure_class == 'local_validation'


def test_statusless_and_forged_execution_success_cannot_download():
    envelope, prepared, remote, lookup = binding(success=False)
    wire, read = Wire(), None
    read = transport(wire)
    for receipt in (remote, replace(remote, execution_succeeded=True)):
        with pytest.raises(ValueError, match='^view_download_failed$'):
            read(envelope, prepared, receipt, lookup)
    assert not wire.origins


@pytest.mark.parametrize('characterization', [False, None, 1, 'true'])
def test_opt_in_and_no_default_wire(bound, characterization):
    wire = Wire()
    for read in (PromptHTTPViewTransport(wire_factory=wire, characterization=characterization),
                 PromptHTTPViewTransport(characterization=True)):
        with pytest.raises(ValueError, match='^view_download_failed$'):
            read(*bound)
    assert not wire.origins


@pytest.mark.parametrize('policy', [PromptHTTPPolicy(0, 1), PromptHTTPPolicy(True, 1),
    PromptHTTPPolicy(1, float('nan')), PromptHTTPPolicy(1, 121), {}])
def test_invalid_policy_never_touches_wire(bound, policy):
    wire = Wire()
    with pytest.raises(ValueError, match='^view_download_failed$'):
        transport(wire, policy=policy)(*bound)
    assert not wire.origins


@pytest.mark.parametrize('headers', [[], [('Content-Length', '5'), ('content-length', '5')],
    [('Content-Length', '5'), ('Content-Length', '6')], [('Content-Length', '5, 5')],
    [('Content-Length', '-1')], [('Content-Length', '0')], [('Content-Length', ' 5')],
    [('Content-Length', '５')], [('Content-Length', '999999999999999999999999')],
    [('Content-Length', str(owner.MAX_IMAGE_BYTES + 1))],
    [('Content-Length', '5'), ('Transfer-Encoding', 'chunked')],
    [('Transfer-Encoding', 'chunked')], [('Content-Length', '5'), ('Content-Encoding', 'gzip')]])
def test_missing_ambiguous_unsupported_or_oversized_length_closes_without_reads(bound, headers):
    wire = Wire(Response(headers=headers))
    read = transport(wire)
    with pytest.raises(ValueError, match='^view_download_failed$'):
        read(*bound)
    assert not wire.response.reads and wire.response.closed and wire.closed
    with pytest.raises(ValueError, match='^view_download_failed$'):
        read(*bound)
    assert len(wire.origins) == len(wire.gets) == 1


@pytest.mark.parametrize('body,declared,failure', [(b'1234', 5, 'short_response'),
    (b'123456', 5, 'response_limit'), (b'', 5, 'short_response')])
def test_short_and_overrun_streams_fail_and_never_retry(bound, body, declared, failure):
    wire = Wire(Response(body, headers=[('Content-Length', str(declared))]))
    read = transport(wire)
    with pytest.raises(ValueError, match='^view_download_failed$'):
        consume(read(*bound))
    assert read.observation().failure_class == failure
    assert wire.response.closed and wire.closed
    with pytest.raises(ValueError, match='^view_download_failed$'):
        read(*bound)
    assert len(wire.gets) == 1


def test_exact_32_mib_stream_ceiling_is_incremental(bound):
    class Generated(Response):
        def __init__(self):
            super().__init__(headers=[('Content-Length', str(owner.MAX_IMAGE_BYTES))])
            self.remaining = owner.MAX_IMAGE_BYTES
        def read(self, size, timeout):
            self.reads.append((size, timeout))
            count = min(size, self.remaining)
            self.remaining -= count
            return b'x' * count
    wire = Wire(Generated())
    stream = transport(wire)(*bound)
    count = 0
    while chunk := stream.read(CHUNK_BYTES):
        count += len(chunk)
    stream.close()
    assert count == owner.MAX_IMAGE_BYTES and wire.response.reads[-1][0] == 1
    assert wire.closed and wire.response.closed


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308, 400, 404, 429, 500, 503, True])
def test_non_2xx_and_redirects_never_read_or_retry(bound, status):
    wire = Wire(Response(status=status, headers=[('Location', 'http://PRIVATE_REDIRECT/view')]))
    read = transport(wire)
    with pytest.raises(ValueError, match='^view_download_failed$'):
        read(*bound)
    assert read.observation().failure_class == 'http_status'
    assert not wire.response.reads and wire.closed and wire.response.closed
    with pytest.raises(ValueError): read(*bound)
    assert len(wire.gets) == 1


@pytest.mark.parametrize('phase', ['connect', 'get', 'read', 'finish'])
@pytest.mark.parametrize('error', [TimeoutError('PRIVATE_ENDPOINT filename'), ConnectionResetError('PRIVATE_ENDPOINT filename')])
def test_timeout_loss_and_framing_failure_close_and_redact(bound, phase, error):
    wire = Wire(Response(error=error if phase == 'read' else None,
                         finish_error=error if phase == 'finish' else None),
        connect_error=error if phase == 'connect' else None, get_error=error if phase == 'get' else None)
    read = transport(wire)
    with pytest.raises(ValueError, match='^view_download_failed$') as caught:
        consume(read(*bound))
    assert 'PRIVATE' not in repr(read.observation()) + repr(caught.value)
    assert wire.closed
    if phase in {'read', 'finish'}: assert wire.response.closed
    assert read.observation().failure_class == ('timeout' if isinstance(error, TimeoutError) else
        'incomplete_framing' if phase == 'finish' else 'wire_failure')
    with pytest.raises(ValueError): read(*bound)
    assert len(wire.origins) == 1


@pytest.mark.parametrize('late_phase', ['chunk', 'eof', 'finish', 'headers'])
def test_nonrenewing_deadline_including_late_eof_and_finish(bound, late_phase):
    now = [0]
    class Dribble(Response):
        def read(self, size, timeout):
            self.reads.append((size, timeout))
            now[0] += 4 if late_phase == 'chunk' else 2 if late_phase == 'eof' else 1
            return self.source.read(size)
        def finish(self):
            if late_phase == 'finish': now[0] += 2
            super().finish()
    wire = Wire(Dribble())
    if late_phase == 'headers':
        original = wire.get_view
        def get(*args):
            now[0] += 3
            return original(*args)
        wire.get_view = get
    read = transport(wire, policy=PromptHTTPPolicy(1, 3), clock=lambda: now[0])
    with pytest.raises(ValueError): consume(read(*bound))
    assert read.observation().failure_class == 'timeout'
    assert wire.closed and wire.response.closed
    if late_phase == 'eof': assert [timeout for _, timeout in wire.response.reads] == [3, 1]


@pytest.mark.parametrize('phase', ['response', 'connection'])
def test_close_failure_invalidates_download_and_is_not_retried(bound, phase):
    wire = Wire(Response(close_error=RuntimeError('PRIVATE') if phase == 'response' else None),
        close_error=RuntimeError('PRIVATE') if phase == 'connection' else None)
    read = transport(wire)
    with pytest.raises(ValueError): consume(read(*bound))
    assert read.observation().failure_class == 'cleanup_failure'
    assert wire.closed and wire.response.closed
    with pytest.raises(ValueError): read(*bound)
    assert len(wire.gets) == 1


def test_reentry_pins_attempt_before_wire_callbacks(bound):
    wire, read = Wire(), None
    read = transport(wire)
    def connect():
        with pytest.raises(ValueError): read(*bound)
    wire.connect = connect
    assert consume(read(*bound)) == b'image'
    assert len(wire.origins) == len(wire.gets) == 1


@pytest.mark.parametrize('substitution', ['client', 'prompt', 'descriptor'])
def test_new_validated_identity_cannot_bypass_attempt_pin(bound, substitution):
    envelope, prepared, remote, lookup = bound
    wire = Wire(get_error=TimeoutError('PRIVATE'))
    read = transport(wire)
    with pytest.raises(ValueError): read(*bound)
    if substitution == 'client':
        prepared = prepare_frozen_prompt_request(envelope.manifest, envelope.manifest.requests[0],
            client_id=str(uuid.uuid4()))
    prompt = str(uuid.uuid4()) if substitution == 'prompt' else remote.prompt_id
    images = [{'filename': 'other.png', 'subfolder': '', 'type': 'output'}] if substitution == 'descriptor' else None
    changed = validate_remote_outputs(envelope, prepared, prompt, successful_metadata(prompt, images))
    descriptor = changed.images[0]
    lookup = ImageDownloadLookup(prepared.prompt_url.removesuffix('/prompt'), descriptor.filename,
        descriptor.subfolder, descriptor.bucket, descriptor.identity)
    with pytest.raises(ValueError): read(envelope, prepared, changed, lookup)
    assert read.observation().failure_class == 'binding_conflict'
    assert len(wire.origins) == len(wire.gets) == 1


@pytest.mark.parametrize('chunk', ['text', bytearray(b'abc'), b'x' * (CHUNK_BYTES + 1)],
                         ids=['text', 'bytearray', 'oversized'])
def test_invalid_wire_chunk_is_bounded_failure(bound, chunk):
    wire = Wire()
    wire.response.read = lambda *_: chunk
    read = transport(wire)
    with pytest.raises(ValueError): consume(read(*bound))
    assert read.observation().failure_class == 'read_contract'
    assert wire.response.closed and wire.closed


def test_early_close_and_read_after_close_cannot_resume_or_retry(bound):
    wire = Wire()
    read = transport(wire)
    stream = read(*bound)
    stream.close()
    stream.close()
    assert read.observation().failure_class == 'incomplete_stream'
    with pytest.raises(ValueError): stream.read(1)
    with pytest.raises(ValueError): read(*bound)
    assert not wire.response.reads and len(wire.gets) == 1


@pytest.mark.parametrize('format,extension', [('PNG', 'png'), ('JPEG', 'jpg'), ('JPEG', 'jpeg'),
    ('WEBP', 'webp'), ('BMP', 'bmp')])
def test_existing_downloadstream_containment_and_verifier_compatibility(store, format, extension):
    values, adapter, sent, accepted = running(images=[{'filename': f'PRIVATE.{extension}', 'subfolder': '', 'type': 'output'}])
    try:
        before = copy.deepcopy(values[2])
        data = image_bytes(format)
        wire, read = Wire(Response(data)), None
        read = transport(wire)
        provider = read.provider_for_characterization(adapter._envelope, sent[0], adapter.remote_receipts()[0])
        with (patch('urllib.request.urlopen', side_effect=AssertionError('network')),
             patch('threading.Thread.start', side_effect=AssertionError('worker')),
             patch('core.gallery_generation.ingest_gallery_generation_outputs', side_effect=AssertionError('publication'))):
            outcome = adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=provider)
        assert outcome.status == 'local_outputs_ready'
        local = adapter.local_receipts()[0]
        assert local.state == 'verified' and local.images[0].image_format == format
        assert local.images[0].byte_count == len(data) and values[2] == before
        snapshot = values[0].generation_jobs.snapshot(accepted.job_id)
        assert snapshot['registered_count'] == 0 and snapshot['save_state'] == 'not_attempted'
        assert not read.execution_available and not read.protected_storage_available
        assert not adapter.execution_available and not store.execution_available
        adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=provider)
        assert len(wire.gets) == 1
    finally:
        values[0].close()


def test_transport_bytes_never_bypass_existing_image_verifier(store):
    values, adapter, sent, _ = running()
    try:
        wire = Wire(Response(b'not an image'))
        read = transport(wire)
        provider = read.provider_for_characterization(adapter._envelope, sent[0], adapter.remote_receipts()[0])
        assert adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=provider).status == 'local_outputs_quarantined'
        assert not adapter.local_receipts()[0].images
        assert read.observation().status == 'downloaded'  # transport makes no image-validity claim
        adapter.contain_local_outputs_for_characterization(store, fake_stream_provider=provider)
        assert len(wire.gets) == 1
    finally:
        values[0].close()


def test_recognized_but_unsupported_gif_never_downloads():
    bound = binding(images=[{'filename': 'a.gif', 'subfolder': '', 'type': 'output'}])
    wire = Wire()
    with pytest.raises(ValueError): transport(wire)(*bound)
    assert not wire.origins


def native_response(data, *, declared=None, headers=None):
    response = Mock(status=200, chunked=False, length=len(data) if declared is None else declared)
    response.getheaders.return_value = headers if headers is not None else [('Content-Length', str(response.length))]
    response.fp = io.BufferedReader(io.BytesIO(data))
    return response


@pytest.mark.parametrize('scheme', ['http', 'https'])
def test_optional_stdlib_wire_exact_request_no_ambient_features(bound, monkeypatch, scheme):
    bound = binding(f'{scheme}://[::1]:8188')
    for key in ('http_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
        monkeypatch.setenv(key, 'http://user:secret@proxy.example')
    native = Mock()
    response = native_response(b'image')
    native.getresponse.return_value = response
    ctor_name = 'HTTPSConnection' if scheme == 'https' else 'HTTPConnection'
    with (patch.object(owner.http.client, ctor_name, return_value=native) as ctor,
         patch('urllib.request.urlopen', side_effect=AssertionError('ambient opener'))):
        assert consume(transport(stdlib_view_wire_for_characterization)(*bound)) == b'image'
    ctor.assert_called_once_with('[::1]', 8188, timeout=5)
    native.request.assert_called_once_with('GET', '/view?filename=private_image.png&subfolder=private%2Ffolder&type=output',
        body=None, headers={'Accept': 'image/*', 'Connection': 'close'})
    response.read1.assert_not_called()  # native Content-Length clipping cannot conceal overrun
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('body,declared', [(b'1234', 5), (b'123456', 5)])
def test_stdlib_raw_body_short_or_overrun_is_rejected(bound, body, declared):
    native, response = Mock(), native_response(body, declared=declared)
    native.getresponse.return_value = response
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        with pytest.raises(ValueError): consume(transport(stdlib_view_wire_for_characterization)(*bound))
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('body,expected', [(b'image', True), (b'image!', False), (b'ima', False)])
def test_real_stdlib_header_parser_with_offline_socket_preserves_raw_framing(bound, body, expected):
    class Socket:
        def __init__(self):
            self.timeouts = []
        def settimeout(self, timeout): self.timeouts.append(timeout)
        def makefile(self, mode):
            return io.BufferedReader(io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\n' + body))
    sock = Socket()
    response = owner.http.client.HTTPResponse(sock)
    response.begin()
    assert response.will_close and response.length == 5
    native = Mock(sock=sock)
    def getresponse():
        native.sock = None
        return response
    native.getresponse.side_effect = getresponse
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        read = transport(stdlib_view_wire_for_characterization)
        if expected:
            assert consume(read(*bound)) == body
        else:
            with pytest.raises(ValueError): consume(read(*bound))
    assert len(sock.timeouts) >= 2 and all(0 < timeout <= 10 for timeout in sock.timeouts)
    assert response.isclosed() and native.sock is None
    native.close.assert_called_once()


def test_stdlib_connection_close_retains_shrinking_body_timeout(bound):
    now = [0]
    class Body:
        def __init__(self): self.parts = [b'im', b'age']
        def read1(self, size):
            now[0] += 2
            return self.parts.pop(0)
    response = native_response(b'image')
    response.fp = Body()
    native = Mock()
    sock = native.sock
    def getresponse():
        native.sock = None
        return response
    native.getresponse.side_effect = getresponse
    read = transport(stdlib_view_wire_for_characterization, policy=PromptHTTPPolicy(1, 3), clock=lambda: now[0])
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        with pytest.raises(ValueError): consume(read(*bound))
    assert [call.args[0] for call in sock.settimeout.call_args_list] == [3, 3, 1]
    assert read.observation().failure_class == 'timeout'
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('headers', [[], [('Content-Length', '5'), ('Content-Length', '5')],
    [('Content-Length', '5'), ('Transfer-Encoding', 'chunked')]])
def test_stdlib_header_validation_closes_native_response_on_constructor_failure(bound, headers):
    native, response = Mock(), native_response(b'image', headers=headers)
    native.getresponse.return_value = response
    with patch.object(owner.http.client, 'HTTPConnection', return_value=native):
        with pytest.raises(ValueError): transport(stdlib_view_wire_for_characterization)(*bound)
    assert response.fp.tell() == 0
    response.close.assert_called_once()
    native.close.assert_called_once()


@pytest.mark.parametrize('scheme,port', [('http', None), ('http', 8188), ('https', None), ('https', 8443)])
def test_stdlib_ipv6_constructor_default_and_explicit_ports(scheme, port):
    endpoint = f'{scheme}://[::1]' + (f':{port}' if port else '')
    connection = stdlib_view_wire_for_characterization(_destination(binding(endpoint)[1]), 5)
    try:
        assert connection._connection.host == '::1'
        assert connection._connection.port == (port or (80 if scheme == 'http' else 443))
    finally:
        connection.close()
