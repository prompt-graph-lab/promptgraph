"""Characterization-only bounded GET /view streams; no storage or activation.

The exact host-prepared request and revalidated remote receipt bind each lookup.
Returned DownloadStream values retain the existing containment/verifier contract.
Neither an injected wire nor the optional stdlib wire is installed by default.
"""
from dataclasses import dataclass
import http.client
import math
import threading
import time
from urllib.parse import urlencode

from core.comfy_http_submission import PromptHTTPPolicy, _Origin, _destination
from core.comfy_output_containment import (
    CHUNK_BYTES, ContainmentLimits, DownloadStream, ImageDownloadLookup,
    SUPPORTED_EXTENSIONS, _validate_binding,
)

MAX_IMAGE_BYTES = ContainmentLimits().image_bytes


@dataclass(frozen=True)
class ViewObservation:
    status: str
    failure_class: str = "none"


def _content_length(headers):
    """Only a single positive decimal Content-Length with identity framing."""
    lengths = [value for name, value in headers if name.lower() == "content-length"]
    transfer = [value for name, value in headers if name.lower() == "transfer-encoding"]
    encoding = [value for name, value in headers if name.lower() == "content-encoding"]
    if (len(lengths) != 1 or transfer or len(encoding) > 1
            or (encoding and encoding[0].lower().strip() != "identity")
            or type(lengths[0]) is not str or not 0 < len(lengths[0]) <= 10
            or not lengths[0].isascii() or not lengths[0].isdigit()):
        raise ValueError("unsupported_framing")
    length = int(lengths[0])
    if not 0 < length <= MAX_IMAGE_BYTES:
        raise ValueError("image_size_limit")
    return length


class PromptHTTPViewTransport:
    """Explicit bound stream owner, with no retries after any wire attempt.

    A trusted wire factory receives only the verified frozen origin and timeout.
    Its connection implements connect(), get_view(path, timeout), close(). Its
    response exposes status, headers, read(size, timeout), finish(), close().
    read must expose EOF/overrun rather than mask bytes at Content-Length;
    finish proves framing and body closure. No redirects/proxy/auth/cookie/retry
    behavior is permitted. Callbacks and I/O run outside the reservation lock.
    """
    execution_available = False
    protected_storage_available = False

    def __init__(self, *, wire_factory=None, policy=PromptHTTPPolicy(), characterization=False,
                 clock=time.monotonic):
        self._wire_factory, self._policy, self._clock = wire_factory, policy, clock
        self._enabled = characterization is True and type(characterization) is bool
        self._attempts, self._bindings, self._lock = set(), {}, threading.RLock()
        self._observation = ViewObservation("unavailable", "unavailable")

    def observation(self):
        return self._observation

    def provider_for_characterization(self, envelope, prepared, remote):
        """Adapt an explicit private binding to DownloadStream's lookup callback.

        This creates no storage or HTTP request. Binding is rechecked on every
        callback; an arbitrary lookup never supplies transport authority.
        """
        return lambda lookup: self(envelope, prepared, remote, lookup)

    def __call__(self, envelope, prepared, remote, lookup):
        try:
            if not self._enabled or not callable(self._wire_factory) or not callable(self._clock):
                raise ValueError()
            policy = self._policy
            if (type(policy) is not PromptHTTPPolicy or any(
                    type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 120
                    for v in (policy.connect_timeout_seconds, policy.read_timeout_seconds))):
                raise ValueError()
            origin = _destination(prepared)
            _validate_binding(envelope, prepared, remote)
            if not remote.execution_succeeded or any(
                    descriptor.image_format not in SUPPORTED_EXTENSIONS for descriptor in remote.images):
                raise ValueError()
            if type(lookup) is not ImageDownloadLookup:
                raise ValueError()
            expected = tuple(ImageDownloadLookup(prepared.prompt_url.removesuffix("/prompt"),
                item.filename, item.subfolder, item.bucket, item.identity) for item in remote.images)
            if lookup not in expected:
                raise ValueError()
            path = "/view?" + urlencode((('filename', lookup.filename),
                ('subfolder', lookup.subfolder), ('type', lookup.bucket)))
        except Exception:
            self._fail("local_validation")
        with self._lock:
            binding = (prepared, remote)
            previous = self._bindings.get(prepared.request_id)
            if previous is not None and previous != binding:
                self._fail("binding_conflict")
            key = (prepared.request_id, lookup.descriptor_identity)
            if key in self._attempts:
                self._fail("already_attempted")
            if len(self._attempts) >= 1600:  # 100 requests, at most 16 images each
                self._fail("capacity_unavailable")
            self._bindings[prepared.request_id] = binding
            self._attempts.add(key)  # pin before factory/connect/reentry
        connection = response = None
        failure = "wire_failure"
        try:
            connection = self._wire_factory(origin, policy.connect_timeout_seconds)
            connection.connect()
            deadline = self._clock() + policy.read_timeout_seconds
            response = connection.get_view(path, policy.read_timeout_seconds)
            if type(response.status) is not int or not 200 <= response.status < 300:
                failure = "http_status"
                raise ValueError()
            failure = "unsupported_framing"
            length = _content_length(response.headers)
            if self._clock() >= deadline:
                raise TimeoutError()
        except TimeoutError:
            failure = "timeout"
        except Exception:
            pass
        else:
            self._observation = ViewObservation("streaming")
            body = _ViewStream(self, response, connection, length, deadline)
            return DownloadStream(length, body.read, body.close)
        if _close_resources(response, connection):
            failure = "cleanup_failure"
        self._fail(failure)

    def _fail(self, failure):
        self._observation = ViewObservation("failed", failure)
        raise ValueError("view_download_failed") from None


def _close_resources(response, connection):
    failed = False
    for resource in (response, connection):
        if resource is not None:
            try:
                resource.close()
            except Exception:
                failed = True
    return failed


class _ViewStream:
    def __init__(self, owner, response, connection, length, deadline):
        self._owner, self._response, self._connection = owner, response, connection
        self._length, self._deadline = length, deadline
        self._count, self._finished, self._closed = 0, False, False

    def read(self, size):
        if self._closed:
            self._owner._fail("stream_closed")
        if self._finished:
            return b""
        failure = "wire_failure"
        try:
            if type(size) is not int or not 0 < size <= CHUNK_BYTES:
                failure = "read_contract"
                raise ValueError()
            remaining = self._deadline - self._owner._clock()
            if remaining <= 0:
                raise TimeoutError()
            limit = min(size, self._length - self._count + 1)
            chunk = self._response.read(limit, remaining)
            if self._owner._clock() >= self._deadline:
                raise TimeoutError()
            if type(chunk) is not bytes or len(chunk) > limit:
                failure = "read_contract"
                raise ValueError()
            self._count += len(chunk)
            if self._count > self._length or self._count > MAX_IMAGE_BYTES:
                failure = "response_limit"
                raise ValueError()
            if not chunk:
                if self._count != self._length:
                    failure = "short_response"
                    raise ValueError()
                failure = "incomplete_framing"
                self._response.finish()
                if self._owner._clock() >= self._deadline:
                    raise TimeoutError()
                self._finished = True
            return chunk
        except TimeoutError:
            failure = "timeout"
        except Exception:
            pass
        self._closed = True
        if _close_resources(self._response, self._connection):
            failure = "cleanup_failure"
        self._owner._fail(failure)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if _close_resources(self._response, self._connection):
            self._owner._fail("cleanup_failure")
        if not self._finished:
            self._owner._observation = ViewObservation("failed", "incomplete_stream")
        else:
            self._owner._observation = ViewObservation("downloaded")


class _ViewHTTPResponse:
    def __init__(self, response, response_socket):
        self._response, self._socket = response, response_socket
        self.status, self.headers = response.status, response.getheaders()
        self._length = _content_length(self.headers)
        if response.chunked or response.length != self._length or response.fp is None:
            raise ValueError("unsupported_framing")
        self._count, self._eof = 0, False

    def read(self, size, timeout):
        if self._socket is not None:
            self._socket.settimeout(timeout)
        # The Content-Length-aware HTTPResponse.read1 masks overruns and may
        # close fp at the declared length. Use the bounded raw body stream:
        # chunked/encoded bodies are rejected, and Connection: close is requested.
        chunk = self._response.fp.read1(size)
        self._count += len(chunk)
        self._eof = not chunk
        return chunk

    def finish(self):
        if not self._eof or self._count != self._length:
            raise ValueError("incomplete_framing")

    def close(self):
        self._response.close()


class _ViewHTTPConnection:
    def __init__(self, origin, connect_timeout):
        cls = http.client.HTTPSConnection if origin.scheme == "https" else http.client.HTTPConnection
        self._connection = cls(origin.host, origin.port, timeout=connect_timeout)

    def connect(self):
        self._connection.connect()

    def get_view(self, path, timeout):
        self._connection.sock.settimeout(timeout)
        self._connection.request("GET", path, body=None,
            headers={"Accept": "image/*", "Connection": "close"})
        sock = self._connection.sock  # retain when getresponse transfers socket ownership
        response = self._connection.getresponse()
        try:
            return _ViewHTTPResponse(response, sock)
        except Exception:
            response.close()
            raise

    def close(self):
        self._connection.close()


def stdlib_view_wire_for_characterization(origin, connect_timeout):
    """Explicit HTTP(S) wire, standard verifying TLS, no ambient HTTP features.

    http.client uses no environment proxies, auth/cookie jar, redirect handler
    or retry loop. No custom CA, client certificate or production registration.
    """
    if type(origin) is not _Origin:
        raise ValueError("invalid_private_origin")
    return _ViewHTTPConnection(origin, connect_timeout)
