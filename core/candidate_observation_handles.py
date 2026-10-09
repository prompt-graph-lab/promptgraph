"""Process-local signing only: no Candidate records, paths or filesystem access."""

import hashlib
import hmac
import json
import secrets
import threading
import time
import weakref


HANDLE_WINDOW_SECONDS = 300
_KEY = secrets.token_bytes(32)
_IDENTITIES = {}
_LOCK = threading.Lock()


def project_identity(project):
    """Weak identity nonce prevents object-ID reuse from reviving old handles."""
    key = id(project)
    with _LOCK:
        previous = _IDENTITIES.get(key)
        if previous is not None and previous[0]() is project:
            return previous[1]

        def release(reference):
            with _LOCK:
                if _IDENTITIES.get(key, (None,))[0] is reference:
                    _IDENTITIES.pop(key, None)

        identity = secrets.token_hex(32)
        _IDENTITIES[key] = (weakref.ref(project, release), identity)
        return identity


def sign_candidate(binding, revision, index):
    window = int(time.monotonic() // HANDLE_WINDOW_SECONDS)
    payload = json.dumps([binding, revision, index, window], sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "candidate_" + hmac.new(_KEY, payload, hashlib.sha256).hexdigest()
