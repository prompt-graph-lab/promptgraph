"""Explicit offline-characterization GET history; never submit or validate images.

The executor retains accepted-prompt ownership. This transport checks bounded
HTTP/JSON framing and exact history correlation, returning original bytes to
the existing remote-output validator. No polling or default wire is installed.
"""
from dataclasses import dataclass, field
import math
import time

from core.comfy_http_submission import (
    PromptHTTPPolicy, _destination, stdlib_prompt_wire_for_characterization,
)
from core.comfy_remote_output_receipts import MAX_REMOTE_BYTES, decode_remote_json, valid_prompt_id


@dataclass(frozen=True)
class HistoryResult:
    status: str
    history_json: bytes = field(default=b"", repr=False)


@dataclass(frozen=True)
class HistoryObservation:
    status: str
    failure_class: str = "none"


class PromptHTTPHistoryTransport:
    """One explicit GET per invocation using only a verified frozen origin.

    Wire connections expose connect(), get_history(prompt_id, timeout), close();
    responses use the submission wire's bounded read/finish/close contract.
    Later calls may observe the same accepted prompt; they never resubmit it.
    Metadata readiness is not verified execution or local-output authority.
    """
    execution_available = False

    def __init__(self, *, wire_factory=None, policy=PromptHTTPPolicy(), characterization=False,
                 clock=time.monotonic):
        self._wire_factory, self._policy, self._clock = wire_factory, policy, clock
        self._enabled = characterization is True and type(characterization) is bool
        self._observation = HistoryObservation("unknown", "unavailable")

    def observation(self):
        return self._observation

    def __call__(self, prepared, prompt_id):
        try:
            if not self._enabled or not callable(self._wire_factory) or not callable(self._clock):
                raise ValueError("unavailable")
            policy = self._policy
            if (type(policy) is not PromptHTTPPolicy or any(
                    type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 120
                    for v in (policy.connect_timeout_seconds, policy.read_timeout_seconds))
                    or not valid_prompt_id(prompt_id)):
                raise ValueError("invalid_history_request")
            origin = _destination(prepared)
        except Exception:
            return self._result("unknown", "local_validation")
        connection = response = None
        result, failure = HistoryResult("unknown"), "wire_failure"
        try:
            connection = self._wire_factory(origin, policy.connect_timeout_seconds)
            connection.connect()
            deadline = self._clock() + policy.read_timeout_seconds
            response = connection.get_history(prompt_id, policy.read_timeout_seconds)
            if type(response.status) is not int or not 200 <= response.status < 300:
                failure = "http_status"
            else:
                chunks, size = [], 0
                while True:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise TimeoutError()
                    chunk = response.read(min(8192, MAX_REMOTE_BYTES + 1 - size), remaining)
                    if self._clock() >= deadline:
                        raise TimeoutError()
                    if type(chunk) is not bytes:
                        raise ValueError()
                    size += len(chunk)
                    if size > MAX_REMOTE_BYTES:
                        failure = "response_limit"
                        break
                    if not chunk:
                        response.finish()
                        body = b"".join(chunks)
                        failure = "invalid_history"
                        history = decode_remote_json(body)
                        if type(history) is not dict:
                            break
                        if not history:
                            result, failure = HistoryResult("pending"), "none"
                        elif set(history) == {prompt_id} and type(history[prompt_id]) is dict:
                            result, failure = HistoryResult("ready", body), "none"
                        else:
                            failure = "prompt_correlation_mismatch"
                        break
                    chunks.append(chunk)
        except TimeoutError:
            result, failure = HistoryResult("timeout"), "timeout"
        except Exception:
            pass  # Untrusted remote/wire details are never retained or echoed.
        finally:
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        result, failure = HistoryResult("unknown"), "cleanup_failure"
        return self._result(result.status, failure, result.history_json)

    def _result(self, status, failure, raw=b""):
        self._observation = HistoryObservation(status, failure)
        return HistoryResult(status, raw)


def stdlib_history_wire_for_characterization(origin, connect_timeout):
    """Same explicit HTTP(S) wire and framing/deadline policy as POST /prompt."""
    return stdlib_prompt_wire_for_characterization(origin, connect_timeout)
