"""Opt-in disposable Windows ACL observations. Never production readiness.

Only new private-journal or disposable asset children may be provisioned. Existing purpose paths are
inspected read-only. Handles deny delete sharing until explicit close. A settled scope-owner close
may release its zero-byte coordination marker; existing roots, Projects and evidence are not cleaned up.
"""
from contextlib import ExitStack
import ctypes
import hashlib
from ctypes import wintypes
import sys
import uuid

from core.generation_protected_storage import _path, _ordinary, _fail, PURPOSES


_FACTORY = object()
_FILE_ID_INFO = 18
_FILE_DISPOSITION_INFO = 4
_PERSISTENT_ACLS = 0x8
# Retained uncertain evidence is a separately selected native root. Keep it
# out of the older path-only policy owner so that owner remains four-purpose.
_NATIVE_PURPOSES = PURPOSES + ("retained_uncertain",)


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("identifier", ctypes.c_ubyte * 16)]


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("delete_file", wintypes.BOOLEAN)]


def _api():
    if sys.platform != "win32":
        _fail("unsupported_platform")
    try:
        import win32api
        import win32con
        import win32file
        import win32security
        import ntsecuritycon
        import pywintypes
    except ImportError:
        _fail("native_dependency_unavailable")
    return win32api, win32con, win32file, win32security, ntsecuritycon, pywintypes


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    return kernel


def _identity(handle):
    value = _FileIdInfo()
    if not _kernel().GetFileInformationByHandleEx(int(handle), _FILE_ID_INFO,
                                                 ctypes.byref(value), ctypes.sizeof(value)):
        _fail("native_identity_unavailable")
    identity = value.volume, int.from_bytes(value.identifier, "little")
    if not identity[1]:
        _fail("native_identity_unavailable")
    return identity


def _filesystem(handle):
    name, serial, maximum, flags = ctypes.create_unicode_buffer(32), wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    if not _kernel().GetVolumeInformationByHandleW(int(handle), None, 0, ctypes.byref(serial),
            ctypes.byref(maximum), ctypes.byref(flags), name, len(name)):
        _fail("filesystem_unavailable")
    # No remote filesystem or unreviewed filesystem fallback.
    if name.value != "NTFS" or not flags.value & _PERSISTENT_ACLS:
        _fail("unsupported_filesystem")
    return "local_ntfs_observed"


def _current_user(api):
    a, c, _, s, _, _ = api
    try:
        thread_token = s.OpenThreadToken(a.GetCurrentThread(), c.TOKEN_QUERY, True)
    except api[5].error as error:
        if error.winerror != 1008:  # ERROR_NO_TOKEN is the sole supported case
            _fail("token_inspection_unavailable")
    else:
        thread_token.Close()
        _fail("impersonation_unsupported")
    token = s.OpenProcessToken(a.GetCurrentProcess(), c.TOKEN_QUERY)
    try:
        return s.GetTokenInformation(token, s.TokenUser)[0]
    finally:
        token.Close()


def _security_attributes(api, user):
    _, _, _, s, n, types = api
    acl = s.ACL()
    acl.AddAccessAllowedAceEx(s.ACL_REVISION, 0x3, n.FILE_ALL_ACCESS, user)
    descriptor = s.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(user, False)
    descriptor.SetSecurityDescriptorDacl(True, acl, False)
    descriptor.SetSecurityDescriptorControl(s.SE_DACL_PROTECTED, s.SE_DACL_PROTECTED)
    attributes = types.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = False
    return attributes


def _acl(handle, api, user):
    _, _, _, s, n, _ = api
    descriptor = s.GetSecurityInfo(handle, s.SE_FILE_OBJECT,
                                  s.OWNER_SECURITY_INFORMATION | s.DACL_SECURITY_INFORMATION)
    control, _ = descriptor.GetSecurityDescriptorControl()
    owner = descriptor.GetSecurityDescriptorOwner()
    acl = descriptor.GetSecurityDescriptorDacl()
    if (owner is None or s.ConvertSidToStringSid(owner) != s.ConvertSidToStringSid(user)
            or not control & s.SE_DACL_PROTECTED or acl is None):
        _fail("unsafe_acl")
    if not 1 <= acl.GetAceCount() <= 64:
        _fail("unsupported_acl")
    snapshot = []
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if len(ace) != 3 or len(ace[0]) != 2:
            _fail("unsupported_acl")
        (kind, flags), mask, sid = ace
        # Explicit basic owner allow only. No inherited/object/callback ACEs.
        if kind != s.ACCESS_ALLOWED_ACE_TYPE or flags & ~0x3 or mask != n.FILE_ALL_ACCESS:
            _fail("unsupported_acl")
        sid_text = s.ConvertSidToStringSid(sid)
        if sid_text != s.ConvertSidToStringSid(user):
            _fail("unsafe_acl")
        snapshot.append((kind, flags, mask, sid_text))
    return tuple(snapshot)


def _open(path, directory, api):
    _, c, f, _, n, _ = api
    # Metadata-only desired access does not establish the tested delete-sharing
    # fence. GENERIC_READ participates in sharing checks; no content is read.
    handle = f.CreateFile(str(path), c.READ_CONTROL | c.GENERIC_READ,
        c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, None, c.OPEN_EXISTING,
        c.FILE_FLAG_BACKUP_SEMANTICS | 0x00200000, None)  # OPEN_REPARSE_POINT
    try:
        info = f.GetFileInformationByHandle(handle)
        if info[0] & 0x400 or bool(info[0] & 0x10) != directory:
            _fail("reparse_or_link")
        if not directory and info[7] != 1:
            _fail("multiple_file_links")
        if _identity(handle) != _ordinary(path, directory=directory):
            _fail("identity_changed")
        final = f.GetFinalPathNameByHandle(handle, 0)
        if final.startswith("\\\\?\\UNC\\") or final.removeprefix("\\\\?\\").casefold() != str(path).casefold():
            _fail("unsupported_path")
        # A drive-letter path can be an SMB mapping. Require the resolved
        # handle path's drive to be local/fixed as well as refusing UNC.
        if f.GetDriveType(_path(final.removeprefix("\\\\?\\")).anchor) != c.DRIVE_FIXED:
            _fail("unsupported_filesystem")
        return handle
    except BaseException:
        handle.Close()
        raise


def _revalidate(observations, api, user):
    # Retain the original observations, not merely a fresh pair of equal reads.
    # Two bounded passes also reject changes while the chain is being checked.
    for _ in range(2):
        for path, directory, handle, identity, acl in observations:
            if (_identity(handle) != identity
                    or _ordinary(path, directory=directory) != identity):
                _fail("identity_changed")
            if _acl(handle, api, user) != acl:
                _fail("native_observation_changed")


def _project_reference_acl(handle, api):
    """Validate a readable ordinary Project ACL without imposing the private-root ACL.

    The Project reference is opened with read-only access. Its DACL must be
    present and structurally ordinary, but may include inherited user,
    Administrators, or SYSTEM entries. This observes and pins the ACL shape;
    it does not claim same-user process isolation or deny writes by the user.
    """
    _, _, _, security, _, _ = api
    information = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
    try:
        descriptor = security.GetSecurityInfo(handle, security.SE_FILE_OBJECT, information)
        owner = descriptor.GetSecurityDescriptorOwner()
        dacl = descriptor.GetSecurityDescriptorDacl()
        if owner is None or dacl is None or not 1 <= dacl.GetAceCount() <= 64:
            _fail("unsupported_project_reference_acl")
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            if len(ace) != 3 or len(ace[0]) != 2:
                _fail("unsupported_project_reference_acl")
            (kind, flags), mask, sid = ace
            if (kind not in (security.ACCESS_ALLOWED_ACE_TYPE, security.ACCESS_DENIED_ACE_TYPE)
                    or flags & ~0x1F or type(mask) is not int or mask < 0 or sid is None):
                _fail("unsupported_project_reference_acl")
        return security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            descriptor, security.SDDL_REVISION_1, information)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("project_reference_acl_unavailable") from error


def _project_reference_revision(handle, api):
    """Observe file size and last-write metadata without reading Project JSON."""
    try:
        information = api[2].GetFileInformationByHandle(handle)
        high_size, low_size = information[5], information[6]
        if (len(information) < 10 or type(high_size) is not int or type(low_size) is not int
                or high_size < 0 or low_size < 0 or information[7] != 1):
            _fail("project_reference_metadata_unavailable")
        return information[3], high_size, low_size
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("project_reference_metadata_unavailable") from error


class WindowsProtectedScopeWriterLease:
    """Cross-process CREATE_NEW lease marker for one exact protected scope.

    An existing marker is never opened, interpreted, stolen, or removed. A
    normal explicit close removes only this owner's pinned zero-byte marker
    after its evidence has settled. Failure or uncertain work retains the
    marker, so later processes fail closed.
    """

    _FACTORY = object()
    execution_available = False

    @classmethod
    def _acquire_for_characterization(cls, scope, scope_identity, api, user):
        scope = _path(str(scope))
        digest = hashlib.sha256(
            f"{scope_identity[0]}:{scope_identity[1]}".encode("ascii")
        ).hexdigest()
        path = scope / f".promptgraph-scope-lease-v1-{digest}"
        _, constants, files, _, _, _ = api
        handle = None
        try:
            handle = files.CreateFile(
                str(path), constants.GENERIC_READ | constants.GENERIC_WRITE | constants.DELETE,
                0, _security_attributes(api, user), constants.CREATE_NEW,
                constants.FILE_ATTRIBUTE_NORMAL | 0x00200000, None,
            )
        except api[5].error as error:
            if error.winerror in (80, 183):  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
                _fail("scope_writer_lease_unavailable")
            raise ValueError("scope_writer_lease_unavailable") from error
        try:
            identity = _identity(handle)
            acl = _acl(handle, api, user)
            info = files.GetFileInformationByHandle(handle)
            final = files.GetFinalPathNameByHandle(handle, 0)
            scope_handle = _open(scope, True, api)
            try:
                scope_identity_matches = (
                    _identity(scope_handle) == scope_identity
                    and _ordinary(scope, directory=True) == scope_identity
                )
            finally:
                scope_handle.Close()
            if (info[0] & 0x400 or info[0] & 0x10 or info[7] != 1
                    or files.GetFileSize(handle) != 0
                    or identity != _ordinary(path, directory=False)
                    or final.removeprefix("\\\\?\\").casefold() != str(path).casefold()
                    or not scope_identity_matches):
                _fail("scope_writer_lease_identity_unavailable")
            if _filesystem(handle) != "local_ntfs_observed":
                _fail("scope_writer_lease_filesystem_unavailable")
            return cls(path, scope, scope_identity, handle, identity, acl, api, user,
                       _factory=cls._FACTORY)
        except BaseException:
            # A marker created but not fully verified is retained as a
            # fail-closed lease artifact; it is never auto-cleaned.
            if handle is not None:
                handle.Close()
            raise

    def __init__(self, path, scope, scope_identity, handle, identity, acl, api, user,
                 *, _factory=None):
        if _factory is not self._FACTORY:
            _fail("protected_scope_lease_required")
        self._path, self._scope, self._scope_identity = path, scope, scope_identity
        self._handle, self._identity, self._acl = handle, identity, acl
        self._api, self._user = api, user
        self._state = "held"

    def _revalidate(self):
        if self._state != "held" or self._handle is None:
            _fail("scope_writer_lease_unavailable")
        files = self._api[2]
        scope_handle = _open(self._scope, True, self._api)
        try:
            if (_identity(scope_handle) != self._scope_identity
                    or _ordinary(self._scope, directory=True) != self._scope_identity):
                _fail("scope_writer_lease_scope_changed")
        finally:
            scope_handle.Close()
        final = files.GetFinalPathNameByHandle(self._handle, 0)
        if (self._identity_value() != self._identity
                or _ordinary(self._path, directory=False) != self._identity
                or _acl(self._handle, self._api, self._user) != self._acl
                or files.GetFileSize(self._handle) != 0
                or final.removeprefix("\\\\?\\").casefold() != str(self._path).casefold()):
            _fail("scope_writer_lease_changed")

    def _identity_value(self):
        return _identity(self._handle)

    def readiness(self):
        if self._state != "held":
            return {"status": self._state, "native_identity": "unavailable",
                    "execution_available": False, "protected_storage_available": False}
        try:
            self._revalidate()
        except Exception:
            return {"status": "unsafe_or_unavailable", "native_identity": "unavailable",
                    "execution_available": False, "protected_storage_available": False}
        return {"status": "held", "native_identity": "observed_unchanged",
                "cross_process_exclusion": True, "stale_takeover": False,
                "execution_available": False, "protected_storage_available": False}

    def retain_uncertain_for_characterization(self):
        if self._state != "held":
            return self._state
        self._state = "retained_uncertain"
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.Close()
        return self._state

    def release_settled_for_characterization(self):
        if self._state == "released":
            return "released"
        if self._state != "held":
            return self._state
        try:
            self._revalidate()
            disposition = _FileDispositionInfo(True)
            if not _kernel().SetFileInformationByHandle(
                    int(self._handle), _FILE_DISPOSITION_INFO,
                    ctypes.byref(disposition), ctypes.sizeof(disposition)):
                _fail("scope_writer_lease_release_unavailable")
        except Exception:
            self._state = "retained_uncertain"
            handle, self._handle = self._handle, None
            if handle is not None:
                handle.Close()
            return self._state
        handle, self._handle = self._handle, None
        try:
            handle.Close()
        except Exception:
            self._state = "retained_uncertain"
            return self._state
        self._state = "released"
        return self._state


class WindowsProjectJsonReferenceCharacterization:
    """Pinned read-only handle to an independently selected local Project JSON.

    This uses a distinct policy from protected writable roots: an ordinary,
    structurally supported NTFS DACL is observed and must remain unchanged,
    but it is not required to be owner-only. The handle requests read access
    only; this owner has no Project write or save operation.
    """

    execution_available = False
    protected_storage_available = False
    project_save_allowed = False

    @classmethod
    def capture_for_characterization(cls, selected_project_json, *,
                                     characterization=False, disposable_opt_in=False):
        if characterization is not True or disposable_opt_in is not True:
            _fail("execution_unavailable")
        path = _path(selected_project_json)
        if path.suffix.lower() != ".json":
            _fail("selected_json_required")
        api = _api()
        handle = _open(path, False, api)
        try:
            filesystem = _filesystem(handle)
            identity = _identity(handle)
            acl = _project_reference_acl(handle, api)
            revision = _project_reference_revision(handle, api)
            if identity != _ordinary(path, directory=False) or path.resolve() != path:
                _fail("project_reference_identity_changed")
            return cls(path, handle, identity, filesystem, acl, revision, api,
                       _factory=cls._FACTORY)
        except BaseException:
            handle.Close()
            raise

    _FACTORY = object()

    def __init__(self, path, handle, identity, filesystem, acl, revision, api, *, _factory=None):
        if _factory is not self._FACTORY:
            _fail("project_reference_owner_required")
        self._path, self._handle = path, handle
        self._identity, self._filesystem, self._acl, self._revision = identity, filesystem, acl, revision
        self._api = api
        self._closed = False

    def _revalidate(self):
        if self._closed or self._handle is None:
            _fail("project_reference_closed")
        if (_filesystem(self._handle) != "local_ntfs_observed"
                or self._filesystem != "local_ntfs_observed"
                or _identity(self._handle) != self._identity
                or _ordinary(self._path, directory=False) != self._identity
                or self._path.resolve() != self._path
                or _project_reference_acl(self._handle, self._api) != self._acl
                or _project_reference_revision(self._handle, self._api) != self._revision):
            _fail("project_reference_changed")

    def readiness(self):
        try:
            self._revalidate()
        except Exception:
            state = "closed" if self._closed else "unsafe_or_unavailable"
        else:
            state = "read_only_reference_observed"
        return {"status": state,
                "identity": "observed_unchanged" if state == "read_only_reference_observed" else "unavailable",
                "read_access_only": state == "read_only_reference_observed",
                "protected_root_acl_required": False,
                "execution_available": False, "protected_storage_available": False,
                "project_save_allowed": False, "authorship": "unverified"}

    def close(self):
        if self._closed:
            return "closed"
        self._closed = True
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.Close()
        return "closed"


class WindowsProtectedRootCharacterization:
    execution_available = False

    @classmethod
    def capture_for_characterization(cls, disposable_scope, selected_path, purpose, *,
                                     characterization=False, disposable_opt_in=False):
        return cls._capture(disposable_scope, selected_path, purpose,
                            characterization, disposable_opt_in, provision=False)

    @classmethod
    def provision_journal_for_characterization(cls, disposable_scope, *,
                                             characterization=False, disposable_opt_in=False):
        # No caller-chosen destination and no selected Project/asset creation.
        return cls._capture(disposable_scope, None, "private_journal",
                            characterization, disposable_opt_in, provision=True)

    @classmethod
    def provision_asset_for_characterization(cls, disposable_scope, purpose, *,
                                            characterization=False, disposable_opt_in=False):
        if purpose not in ("temporary_containment", "promoted_assets"):
            _fail("unsupported_asset_purpose")
        return cls._capture(disposable_scope, None, purpose,
                            characterization, disposable_opt_in, provision=True)

    @classmethod
    def provision_retained_for_characterization(cls, disposable_scope, *,
                                                characterization=False, disposable_opt_in=False):
        # A new disposable child only; never adopt or repair an existing user
        # directory, and never move/delete retained evidence automatically.
        return cls._capture(disposable_scope, None, "retained_uncertain",
                            characterization, disposable_opt_in, provision=True)

    @classmethod
    def _capture(cls, scope_value, selected_path, purpose, characterization, opt_in, provision):
        if characterization is not True or opt_in is not True:
            _fail("execution_unavailable")
        scope = _path(scope_value)
        if scope.drive.startswith("\\\\") or purpose not in _NATIVE_PURPOSES:
            _fail("unsupported_path")
        prefix = "journal" if purpose == "private_journal" else purpose
        path = scope / ("promptgraph-protected-" + prefix + "-" + uuid.uuid4().hex) if provision else _path(selected_path)
        if path == scope or not path.is_relative_to(scope):
            _fail("unapproved_root")
        if purpose == "selected_project_json" and path.suffix.lower() != ".json":
            _fail("selected_json_required")
        api = _api()
        user = _current_user(api)
        handles = ExitStack()
        scope_handle = None
        observations = []
        try:
            # Pin the full existing ancestor chain without DELETE sharing.
            parent = scope if provision else path.parent
            for ancestor in reversed((parent, *parent.parents)):
                handle = _open(ancestor, True, api)
                handles.callback(handle.Close)
                if ancestor == scope:
                    scope_handle = handle
                    _filesystem(handle)
                # Every in-scope directory must already be protected owner-only.
                # Pin ancestors above scope, but do not impose this ACL policy there.
                if ancestor.is_relative_to(scope):
                    observations.append((ancestor, True, handle, _identity(handle),
                                         _acl(handle, api, user)))
            if provision:
                # CreateDirectory is exclusive; the protected DACL is supplied at
                # creation. Existing names are never repaired or overwritten.
                api[2].CreateDirectory(str(path), _security_attributes(api, user))
            handle = _open(path, purpose != "selected_project_json", api)
            handles.callback(handle.Close)
            identity = _identity(handle)
            filesystem = _filesystem(handle)
            acl = _acl(handle, api, user)
            observations.append((path, purpose != "selected_project_json", handle, identity, acl))
            observations = tuple(observations)
            _revalidate(observations, api, user)
            return cls(path, purpose, handle, scope_handle, handles, identity, filesystem,
                       api, user, observations, _factory=_FACTORY)
        except BaseException:
            handles.close()
            # If creation succeeded, retain evidence. Never delete on failure.
            raise

    def __init__(self, path, purpose, handle, scope_handle, handles, identity, filesystem, api, user,
                 observations, *, _factory=None):
        if _factory is not _FACTORY:
            _fail("host_storage_required")
        self._path, self._purpose, self._handle, self._handles = path, purpose, handle, handles
        self._scope_handle = scope_handle
        self._identity, self._filesystem, self._api, self._user = identity, filesystem, api, user
        self._observations = observations
        self._closed = False

    def readiness(self):
        state = "closed" if self._closed else "unavailable"
        if not self._closed:
            try:
                _filesystem(self._handle)
                _revalidate(self._observations, self._api, self._user)
                state = "owner_only_acl_observed"
            except Exception:
                state = "unsafe_or_unavailable"
        return {"purpose": self._purpose, "native_observation": state,
                "acl_verified": state == "owner_only_acl_observed",
                "identity": "handle_observed" if state == "owner_only_acl_observed" else "unavailable",
                "filesystem": self._filesystem if state == "owner_only_acl_observed" else "unverified",
                "execution_available": False, "protected_storage_available": False,
                "recovery_execution_allowed": False, "attachment_allowed": False,
                "publication_allowed": False, "project_save_allowed": False,
                "cleanup_allowed": False, "authorship": "unverified",
                "integrity": "not_inspected", "digest_chain": "not_inspected",
                "current_authorization": "absent", "directory_durability": "unsupported",
                "power_loss_guarantee": False, "same_user_process_authentication": False}

    def close(self):
        if not self._closed:
            self._closed = True
            self._handles.close()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()
