"""C2B-8C-1 disposable, read-only policy characterization; no runtime capability.

Path/stat observations are not handle-pinned Windows security observations.
No caller-supplied ACL, hash or durability assertion can upgrade readiness.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
import sys


PURPOSES = ("private_journal", "temporary_containment", "promoted_assets",
            "selected_project_json")
_FACTORY = object()


def _fail(code):
    raise ValueError(code)


def _ordinary(path, *, directory):
    # Observe every ancestor, including the drive root; never enumerate children.
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("reparse_or_link")
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            _fail("unsafe_path")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        _fail("unsafe_path")
    if not directory and info.st_nlink != 1:
        _fail("multiple_file_links")
    if not info.st_ino:
        _fail("identity_unavailable")
    return info.st_dev, info.st_ino


def _path(value):
    if type(value) is not str or not 1 <= len(value) <= 1024 or "\x00" in value:
        _fail("unsafe_path")
    path = Path(value)
    if (not path.is_absolute() or os.path.normpath(value) != value
            or ":" in value[len(path.drive):]):
        _fail("unsafe_path")
    return path


@dataclass(frozen=True)
class _RootObservation:
    purpose: str
    path: Path = field(repr=False)
    identity: tuple = field(repr=False)


class ProtectedStorageCharacterization:
    """Observe four explicit purposes beneath a host's disposable opt-in scope.

No discovery, read of file contents, ACL mutation, allocation or provisioning.
The selected JSON is a reference only, never a write destination.
"""
    execution_available = False

    @classmethod
    def capture_for_characterization(cls, disposable_scope, purpose_paths, *,
                                     characterization=False, disposable_opt_in=False):
        if characterization is not True or disposable_opt_in is not True:
            _fail("execution_unavailable")
        if type(purpose_paths) is not dict or set(purpose_paths) != set(PURPOSES):
            _fail("explicit_purposes_required")
        scope = _path(disposable_scope)
        paths = tuple(_path(purpose_paths[purpose]) for purpose in PURPOSES)
        # Reject unapproved paths lexically BEFORE any filesystem access to them.
        if any(path == scope or not path.is_relative_to(scope) for path in paths):
            _fail("unapproved_root")
        if paths[-1].suffix.lower() != ".json":
            _fail("selected_json_required")
        if any(a.is_relative_to(b) or b.is_relative_to(a)
               for index, a in enumerate(paths) for b in paths[index + 1:]):
            _fail("purpose_overlap")
        scope_identity = _ordinary(scope, directory=True)
        if scope.resolve() != scope:
            _fail("unsafe_path")
        roots = []
        for purpose, path in zip(PURPOSES, paths):
            identity = _ordinary(path, directory=purpose != "selected_project_json")
            if path.resolve() != path:
                _fail("unsafe_path")
            roots.append(_RootObservation(purpose, path, identity))
        # Distinct names must not alias the same object.
        if len({root.identity for root in roots}) != len(roots):
            _fail("purpose_alias")
        owner = cls(scope, scope_identity, tuple(roots), _factory=_FACTORY)
        if any(row["identity"] != "observed_unchanged" for row in owner.readiness()["roots"]):
            _fail("identity_changed")
        return owner

    def __init__(self, scope, scope_identity, roots, *, _factory=None):
        if _factory is not _FACTORY:
            _fail("host_storage_required")
        self._scope, self._scope_identity, self._roots = scope, scope_identity, roots

    def readiness(self):
        """Bounded, detached and redacted. Every platform/backend path is closed."""
        scope_state = self._identity_state(self._scope, self._scope_identity, True)
        rows = []
        for root in self._roots:
            state = scope_state if scope_state != "observed_unchanged" else self._identity_state(
                root.path, root.identity, root.purpose != "selected_project_json")
            rows.append({"purpose": root.purpose, "identity": state,
                         "acl": "unavailable", "integrity": "not_inspected"})
        return {"status": "inspect_only", "execution_available": False,
                "recovery_execution_allowed": False, "attachment_allowed": False,
                "publication_allowed": False, "project_save_allowed": False,
                "cleanup_allowed": False, "protected_storage_available": False,
                "roots": rows, "platform": "windows" if sys.platform == "win32" else "unsupported",
                "acl_inspection": "unavailable", "secure_provisioning": "unavailable",
                "filesystem": "unverified", "handle_pinning": "unavailable",
                "directory_durability": "unsupported", "power_loss_guarantee": False,
                "digest_chain": "not_inspected", "authorship": "unverified",
                "trusted_latest_head": "unavailable", "current_authorization": "absent",
                "same_user_process_authentication": False,
                "blocker": "native_observation_required" if sys.platform == "win32"
                           else "unsupported_platform"}

    @staticmethod
    def _identity_state(path, expected, directory):
        try:
            identity = _ordinary(path, directory=directory)
            if path.resolve() != path:
                return "unsafe"
            return "observed_unchanged" if identity == expected else "changed"
        except (ValueError, OSError):
            # No exception/path/principal text enters presentation.
            return "unsafe_or_unavailable"


@dataclass(frozen=True)
class AclPolicySample:
    """Synthetic policy input, NEVER an ACL verification result or capability.

Only exact owner SID allow entries are modeled. Other ACE types, inherited
access, missing/null DACLs and privilege/group effects require a native owner.
"""
    owner_sid: str = field(repr=False)
    current_user_sid: str = field(repr=False)
    protected_dacl: bool
    dacl_present: bool
    # (SID, ACE type, access mask, inherited). Limited model, not raw native ACEs.
    entries: tuple = field(repr=False)


def characterize_acl_policy(sample):
    """Evaluate the conservative model; compatible does not mean verified."""
    result = {"policy": "unsupported", "acl_verified": False,
              "authorship_authenticated": False, "same_user_process_authentication": False,
              "execution_available": False}
    if type(sample) is not AclPolicySample:
        return result
    sid = re.compile(r"S-1-(?:[0-9]{1,10}-){1,14}[0-9]{1,10}")
    if (type(sample.owner_sid) is not str or type(sample.current_user_sid) is not str
            or not sid.fullmatch(sample.owner_sid) or not sid.fullmatch(sample.current_user_sid)
            or type(sample.protected_dacl) is not bool or type(sample.dacl_present) is not bool
            or type(sample.entries) is not tuple or not 1 <= len(sample.entries) <= 64):
        return result
    result["policy"] = "unsafe"
    if (sample.owner_sid != sample.current_user_sid or not sample.protected_dacl
            or not sample.dacl_present):
        return result
    for entry in sample.entries:
        if (type(entry) is not tuple or len(entry) != 4 or type(entry[0]) is not str
                or type(entry[1]) is not str or type(entry[2]) is not int
                or type(entry[3]) is not bool):
            result["policy"] = "unsupported"
            return result
        principal, kind, mask, inherited = entry
        if kind != "allow" or mask <= 0 or mask & ~0x1F01FF:
            result["policy"] = "unsupported"
            return result
        if principal != sample.current_user_sid or inherited:
            return result
    result["policy"] = "compatible_model_only"
    return result


def characterize_write_boundary(boundary):
    """Interpret existing offline fault boundaries; perform no writes or effects."""
    states = {
        "file_sync_failed": ("old_or_absent", "unacknowledged"),
        "before_replace": ("old_or_absent", "unacknowledged"),
        "after_replace_before_ack": ("new_may_be_visible", "ambiguous"),
        "acknowledged": ("new_observed", "observed"),
    }
    if type(boundary) is not str or boundary not in states:
        _fail("unsupported_write_boundary")
    visible, acknowledgment = states[boundary]
    return {"visible_file": visible, "acknowledgment": acknowledgment,
            "directory_durability": "unsupported", "power_loss_guarantee": False,
            "cross_file_transaction": False, "external_effect_confirmed": False,
            "retry_allowed": False, "execution_available": False}
