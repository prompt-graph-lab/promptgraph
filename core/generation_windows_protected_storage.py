"""Opt-in disposable Windows ACL observations. Never production readiness.

Only a new private-journal child may be provisioned. Existing purpose paths are
inspected read-only. Handles deny delete sharing until explicit close; no cleanup.
"""
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import sys
import uuid

from core.generation_protected_storage import _path, _ordinary, _fail, PURPOSES


_FACTORY = object()
_FILE_ID_INFO = 18
_PERSISTENT_ACLS = 0x8


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("identifier", ctypes.c_ubyte * 16)]


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
    def _capture(cls, scope_value, selected_path, purpose, characterization, opt_in, provision):
        if characterization is not True or opt_in is not True:
            _fail("execution_unavailable")
        scope = _path(scope_value)
        if scope.drive.startswith("\\\\") or purpose not in PURPOSES:
            _fail("unsupported_path")
        path = scope / ("promptgraph-protected-journal-" + uuid.uuid4().hex) if provision else _path(selected_path)
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
