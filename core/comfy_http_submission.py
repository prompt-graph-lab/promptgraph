"""Characterization-only POST /prompt, consuming exact frozen host material.

No default transport is installed. The injected wire is trusted host code;
remote status, body and exceptions remain untrusted and privately bounded.
"""
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import math
import threading
import time
import uuid
from urllib.parse import urlsplit

from core.comfy_prompt_request import FrozenPromptRequest, is_owner_prepared_frozen_request
from core.comfy_remote_output_receipts import MAX_REMOTE_BYTES, decode_remote_json, valid_prompt_id
from core.comfy_workflow_outputs import _workflow_output_nodes
from core.generation_executable_manifest import MAX_WORKFLOW_BYTES, encode


@dataclass(frozen=True)
class SubmissionResult:
    """Only local rejected_before_submission proves no HTTP attempt occurred."""
    status: str
    response_json: bytes = field(default=b"", repr=False)


@dataclass(frozen=True)
class PromptHTTPPolicy:
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class SubmissionObservation:
    status: str
    failure_class: str = "none"


@dataclass(frozen=True, repr=False)
class _Origin:
    scheme: str
    host: str
    port: int | None


def _destination(prepared):
    if (not is_owner_prepared_frozen_request(prepared)
            or type(prepared.request_id) is not str or not 0 < len(prepared.request_id) <= 160
            or type(prepared.request_index) is not int or not 0 <= prepared.request_index < 100
            or type(prepared.client_id) is not str or str(uuid.UUID(prepared.client_id)) != prepared.client_id
            or type(prepared.prompt_url) is not str or not 0 < len(prepared.prompt_url) <= 4103
            or any(ord(c) <= 32 or ord(c) >= 127 or c in "\\%" for c in prepared.prompt_url)
            or type(prepared.body_json) is not bytes
            or not 0 < len(prepared.body_json) <= MAX_WORKFLOW_BYTES + 128):
        raise ValueError("invalid_frozen_request")
    parts = urlsplit(prepared.prompt_url)
    if (parts.scheme not in {"http", "https"} or not parts.hostname or not parts.netloc
            or parts.username is not None or parts.password is not None
            or parts.path != "/prompt" or parts.query or parts.fragment
            or (parts.port is not None and not 1 <= parts.port <= 65535)):
        raise ValueError("unsupported_origin")
    # Frozen preparation embeds the exact canonical workflow bytes. Recheck
    # their digest/body framing without changing a seed or serializing for send.
    prefix = b'{"prompt":'
    suffix = b',"client_id":' + json.dumps(prepared.client_id).encode("ascii") + b'}'
    if not prepared.body_json.startswith(prefix) or not prepared.body_json.endswith(suffix):
        raise ValueError("invalid_frozen_body")
    workflow_bytes = prepared.body_json[len(prefix):-len(suffix)]
    if (not 0 < len(workflow_bytes) <= MAX_WORKFLOW_BYTES
            or hashlib.sha256(workflow_bytes).hexdigest() != prepared.workflow_identity):
        raise ValueError("invalid_frozen_body")
    workflow = json.loads(workflow_bytes)
    if type(workflow) is not dict or encode(workflow) != workflow_bytes:
        raise ValueError("invalid_frozen_body")
    outputs = _workflow_output_nodes(workflow)
    expected = tuple((node, "temp" if workflow[node].get("class_type") == "PreviewImage" else "output")
                     for node in outputs)
    if (not 1 <= len(outputs) <= 100 or type(prepared.output_nodes) is not tuple
            or expected != prepared.output_nodes
            or any(workflow[node].get("class_type") not in {"SaveImage", "PreviewImage"} for node in outputs)):
        raise ValueError("invalid_output_provenance")
    return _Origin(parts.scheme, parts.hostname, parts.port)


class PromptHTTPSubmissionTransport:
    """Explicit one-owner characterization, at most 100 distinct attempts.

    The wire factory receives only the verified frozen origin and connect
    timeout. Its connection supports connect(), post_prompt(body, timeout),
    close(). A response supports status, read(size, timeout), finish(), close().
    Wire code must not add redirects, retries, proxies, cookies or auth.
    connect() must send no HTTP request. Once post_prompt() invocation begins
    every failure conservatively remains unknown.
    """
    execution_available = False

    def __init__(self, *, wire_factory=None, policy=PromptHTTPPolicy(), characterization=False,
                 clock=time.monotonic):
        self._wire_factory, self._policy = wire_factory, policy
        self._enabled = characterization is True and type(characterization) is bool
        self._clock = clock
        self._attempts, self._prompts = set(), set()
        self._lock = threading.RLock()
        self._observation = SubmissionObservation("rejected_before_submission", "unavailable")

    def observation(self):
        return self._observation

    def __call__(self, prepared):
        with self._lock:
            try:
                if not self._enabled or not callable(self._wire_factory) or not callable(self._clock):
                    raise ValueError("unavailable")
                policy = self._policy
                if (type(policy) is not PromptHTTPPolicy or any(
                        type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 120
                        for v in (policy.connect_timeout_seconds, policy.read_timeout_seconds))):
                    raise ValueError("invalid_policy")
                origin = _destination(prepared)
            except Exception:
                return self._result("rejected_before_submission", "local_validation")
            key = prepared.request_id
            if key in self._attempts:
                return self._result("unknown", "already_attempted")
            if len(self._attempts) >= 100:
                return self._result("rejected_before_submission", "capacity_unavailable")
            self._attempts.add(key)  # reserve before callback/reentry
        connection = response = None
        result = SubmissionResult("unknown")
        send_attempted = False
        failure = "wire_failure"
        try:
            connection = self._wire_factory(origin, policy.connect_timeout_seconds)
            connection.connect()
            deadline = self._clock() + policy.read_timeout_seconds
            send_attempted = True  # any error from here may follow transmitted bytes
            response = connection.post_prompt(prepared.body_json, policy.read_timeout_seconds)
            if type(response.status) is not int or not 200 <= response.status < 300:
                failure = "http_status"
            else:
                chunks, size = [], 0
                while True:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise TimeoutError()
                    chunk = response.read(min(8192, MAX_REMOTE_BYTES + 1 - size), remaining)
                    if type(chunk) is not bytes:
                        raise ValueError()
                    size += len(chunk)
                    if size > MAX_REMOTE_BYTES:
                        failure = "response_limit"
                        break
                    if not chunk:
                        response.finish()  # wire must verify framing completed
                        body = b"".join(chunks)
                        failure = "invalid_response"
                        payload = decode_remote_json(body)
                        prompt = payload.get("prompt_id") if type(payload) is dict else None
                        if not valid_prompt_id(prompt):
                            break
                        with self._lock:
                            if prompt in self._prompts:
                                failure = "duplicate_prompt_id"
                                break
                            self._prompts.add(prompt)
                        result, failure = SubmissionResult("accepted", body), "none"
                        break
                    chunks.append(chunk)
        except TimeoutError:
            failure = "timeout"
        except Exception:
            pass  # never retain or echo arbitrary transport/remote details
        finally:
            if not send_attempted:
                result = SubmissionResult("rejected_before_submission")
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        result, failure = SubmissionResult("unknown"), "cleanup_failure"
        return self._result(result.status, failure, result.response_json)

    def _result(self, status, failure, raw=b""):
        self._observation = SubmissionObservation(status, failure)
        return SubmissionResult(status, raw)


class _HTTPResponse:
    def __init__(self, response, connection):
        self._response, self._connection = response, connection
        self.status = response.status
        headers = response.getheaders()
        lengths = [value for name, value in headers if name.lower() == "content-length"]
        encodings = [value for name, value in headers if name.lower() == "transfer-encoding"]
        if (len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings)
                or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit()))
                or (encodings and encodings[0].lower().strip() != "chunked")):
            raise ValueError("unverifiable_http_framing")

    def read(self, size, timeout):
        if self._connection.sock is not None:
            self._connection.sock.settimeout(timeout)
        return self._response.read(size)

    def finish(self):
        if self._response.length not in {None, 0}:
            raise http.client.IncompleteRead(b"")

    def close(self):
        self._response.close()


class _HTTPConnection:
    def __init__(self, origin, connect_timeout):
        cls = http.client.HTTPSConnection if origin.scheme == "https" else http.client.HTTPConnection
        self._connection = cls(origin.host, origin.port, timeout=connect_timeout)

    def connect(self):
        self._connection.connect()

    def post_prompt(self, body, read_timeout):
        self._connection.sock.settimeout(read_timeout)
        self._connection.request("POST", "/prompt", body=body,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = self._connection.getresponse()
        try:
            return _HTTPResponse(response, self._connection)
        except Exception:
            response.close()
            raise

    def close(self):
        self._connection.close()


def stdlib_prompt_wire_for_characterization(origin, connect_timeout):
    """Explicit opt-in wire; http.client uses no environment proxy/auth jar.

    TLS uses the standard verifying HTTPS context. There is no custom CA,
    client certificate, userinfo/header auth, redirect handler or retry loop.
    Only PromptHTTPSubmissionTransport may supply this private origin.
    """
    if type(origin) is not _Origin:
        raise ValueError("invalid_private_origin")
    return _HTTPConnection(origin, connect_timeout)
