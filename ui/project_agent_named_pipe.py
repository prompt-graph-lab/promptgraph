"""Protected Windows named-pipe pairing for PromptGraph session routes.

This module owns only the local transport and delegates pairing and mailbox
operations to the existing process-local session registry. It never imports
Streamlit, Project, capture, or the app-side request bridge.
"""

from dataclasses import dataclass, field
import ctypes
import ctypes.wintypes as wintypes
import functools
import hashlib
import json
import math
import os
import secrets
import struct
import tempfile
import threading
import time

from ui.project_agent_session_registry import (
    PAIRING_BOOTSTRAP_CONTRACT,
    DEFAULT_PAIRING_LIFETIME_SECONDS,
    ProjectAgentPairedRoute,
    ProjectAgentSessionRegistration,
    ProjectAgentSessionRegistry,
    get_process_project_agent_session_registry,
)


LOCAL_PIPE_CONTRACT = "promptgraph.local-named-pipe.v1"
LAUNCHER_RENDEZVOUS_CONTRACT = "promptgraph.mcp-launcher-rendezvous.v1"
_PIPE_PREFIX = "\\\\.\\pipe\\PromptGraph-"
_DESCRIPTOR_PREFIX = "promptgraph-pairing-"
_LAUNCHER_RENDEZVOUS_PREFIX = "promptgraph-mcp-rendezvous-"
_MAX_DESCRIPTOR_BYTES = 64 * 1024
_MAX_LAUNCHER_RENDEZVOUS_BYTES = 64 * 1024
_MAX_REQUEST_FRAME_BYTES = 16 * 1024 * 1024
_MAX_PIPE_INSTANCES_PER_ROUTE = 1
_MAX_ACTIVE_ROUTES = 32
_PIPE_BUFFER_BYTES = 64 * 1024
_PAIRING_CONNECT_TIMEOUT_SECONDS = 10.0
_PAIRING_RESPONSE_CLOSE_TIMEOUT_SECONDS = 2.0
_PIPE_PARTIAL_FRAME_TIMEOUT_SECONDS = 30.0
_ORPHAN_DRAIN_TIMEOUT_SECONDS = 130.0
_ORPHAN_POLL_SECONDS = 0.05


class LocalPipeError(Exception):
    """A bounded transport failure that never includes OS error text."""

    __slots__ = ("reason",)

    def __init__(self, reason):
        if type(reason) is not str or not reason.isascii() or not reason:
            reason = "transport_error"
        self.reason = reason
        super().__init__(reason)

    def __repr__(self):
        return f"LocalPipeError({self.reason!r})"


@dataclass(frozen=True, repr=False)
class PairingDescriptorFile:
    """Opaque path handle for the protected, delete-on-close descriptor file."""

    path: str = field(repr=False)
    route_id: str = field(repr=False)
    expires_in_seconds: float

    def __repr__(self):
        return "PairingDescriptorFile(<protected local descriptor>)"


@dataclass(frozen=True, repr=False)
class PairingDescriptorDelivery:
    """Bounded result of preparing one route's protected descriptor."""

    status: str
    descriptor_file: PairingDescriptorFile | None = field(default=None, repr=False)

    def __repr__(self):
        return f"PairingDescriptorDelivery(status={self.status!r})"


@dataclass(frozen=True, repr=False)
class LauncherRendezvousOperation:
    """Bounded session-owned launcher rendezvous result."""

    status: str
    expires_in_seconds: float | None = None

    def __repr__(self):
        return f"LauncherRendezvousOperation(status={self.status!r})"


@dataclass(frozen=True, repr=False)
class LocalLauncherRendezvous:
    """Validated local launcher target; protected paths are redacted."""

    status: str
    descriptor_file_path: str = field(default="", repr=False)
    server_pid: int = 0
    process_incarnation: str = field(default="", repr=False)

    def __repr__(self):
        return f"LocalLauncherRendezvous(status={self.status!r})"


@dataclass(frozen=True, repr=False)
class LocalPairingDescriptor:
    """Validated descriptor loaded from the protected one-use local file."""

    contract_version: str
    bootstrap_contract_version: str
    pipe_name: str
    server_pid: int
    process_incarnation: str
    route_id: str
    capability: str = field(repr=False)
    expires_in_seconds: float

    def __repr__(self):
        return "LocalPairingDescriptor(<protected>)"


@dataclass(frozen=True, repr=False)
class PipeConnectionResult:
    """Bounded result from the Windows pipe client connection attempt."""

    status: str
    client: object = field(default=None, repr=False)

    def __repr__(self):
        return f"PipeConnectionResult(status={self.status!r})"


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BYTE)]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TokenGroupsHead(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", _SidAndAttributes * 1)]


class _WindowsApi:
    """Small wrapper over documented Win32 APIs used by this transport."""

    def __init__(self):
        if os.name != "nt":
            raise LocalPipeError("unsupported_platform")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._declare_functions()

    def _declare_functions(self):
        k = self.kernel32
        a = self.advapi32
        handle = wintypes.HANDLE
        dword = wintypes.DWORD
        lpvoid = wintypes.LPVOID

        k.GetCurrentProcess.restype = handle
        k.GetCurrentProcess.argtypes = []
        k.GetCurrentProcessId.restype = dword
        k.GetCurrentProcessId.argtypes = []
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [handle]
        k.LocalFree.restype = handle
        k.LocalFree.argtypes = [handle]
        k.GetDriveTypeW.restype = dword
        k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]

        k.CreateFileW.restype = handle
        k.CreateFileW.argtypes = [
            wintypes.LPCWSTR, dword, dword, ctypes.POINTER(_SecurityAttributes),
            dword, dword, handle,
        ]
        k.CreateNamedPipeW.restype = handle
        k.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR, dword, dword, dword, dword, dword, dword,
            ctypes.POINTER(_SecurityAttributes),
        ]
        k.ConnectNamedPipe.restype = wintypes.BOOL
        k.ConnectNamedPipe.argtypes = [handle, lpvoid]
        k.DisconnectNamedPipe.restype = wintypes.BOOL
        k.DisconnectNamedPipe.argtypes = [handle]
        k.ReadFile.restype = wintypes.BOOL
        k.ReadFile.argtypes = [handle, lpvoid, dword, ctypes.POINTER(dword), lpvoid]
        k.WriteFile.restype = wintypes.BOOL
        k.WriteFile.argtypes = [handle, lpvoid, dword, ctypes.POINTER(dword), lpvoid]
        k.FlushFileBuffers.restype = wintypes.BOOL
        k.FlushFileBuffers.argtypes = [handle]
        k.PeekNamedPipe.restype = wintypes.BOOL
        k.PeekNamedPipe.argtypes = [
            handle, lpvoid, dword, ctypes.POINTER(dword), ctypes.POINTER(dword),
            ctypes.POINTER(dword),
        ]
        k.GetNamedPipeServerProcessId.restype = wintypes.BOOL
        k.GetNamedPipeServerProcessId.argtypes = [handle, ctypes.POINTER(dword)]
        k.GetNamedPipeClientProcessId.restype = wintypes.BOOL
        k.GetNamedPipeClientProcessId.argtypes = [handle, ctypes.POINTER(dword)]
        k.GetNamedPipeInfo.restype = wintypes.BOOL
        k.GetNamedPipeInfo.argtypes = [
            handle, ctypes.POINTER(dword), ctypes.POINTER(dword),
            ctypes.POINTER(dword), ctypes.POINTER(dword),
        ]
        k.WaitNamedPipeW.restype = wintypes.BOOL
        k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, dword]
        k.GetFileSizeEx.restype = wintypes.BOOL
        k.GetFileSizeEx.argtypes = [handle, ctypes.POINTER(ctypes.c_longlong)]
        k.SetFilePointerEx.restype = wintypes.BOOL
        k.SetFilePointerEx.argtypes = [
            handle, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), dword,
        ]
        k.SetEndOfFile.restype = wintypes.BOOL
        k.SetEndOfFile.argtypes = [handle]
        k.SetFileInformationByHandle.restype = wintypes.BOOL
        k.SetFileInformationByHandle.argtypes = [handle, ctypes.c_int, lpvoid, dword]
        k.OpenProcess.restype = handle
        k.OpenProcess.argtypes = [dword, wintypes.BOOL, dword]
        k.WaitForSingleObject.restype = dword
        k.WaitForSingleObject.argtypes = [handle, dword]

        a.OpenProcessToken.restype = wintypes.BOOL
        a.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
        a.GetTokenInformation.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = [
            handle, dword, lpvoid, dword, ctypes.POINTER(dword),
        ]
        a.ConvertSidToStringSidW.restype = wintypes.BOOL
        a.ConvertSidToStringSidW.argtypes = [lpvoid, ctypes.POINTER(wintypes.LPWSTR)]
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, dword, ctypes.POINTER(lpvoid), ctypes.POINTER(dword),
        ]

    def close_handle(self, handle):
        if handle and handle != _invalid_handle_value():
            self.kernel32.CloseHandle(handle)

    def process_id(self):
        return int(self.kernel32.GetCurrentProcessId())

    def process_is_alive(self, process_id):
        if type(process_id) is not int or process_id <= 0:
            return False
        handle = self.kernel32.OpenProcess(0x00100000, False, process_id)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            if error in (87, 1168):  # INVALID_PARAMETER / NOT_FOUND
                return False
            return None
        try:
            result = self.kernel32.WaitForSingleObject(handle, 0)
            if result == 0:
                return False
            if result == 0x00000102:  # WAIT_TIMEOUT
                return True
            return None
        finally:
            self.close_handle(handle)

    def current_logon_sid(self):
        token = wintypes.HANDLE()
        if not self.advapi32.OpenProcessToken(
            self.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token),
        ):
            raise LocalPipeError("security_unavailable")
        try:
            required = wintypes.DWORD()
            self.advapi32.GetTokenInformation(token, 2, None, 0, ctypes.byref(required))
            if not required.value or required.value > 1024 * 1024:
                raise LocalPipeError("security_unavailable")
            buffer = ctypes.create_string_buffer(required.value)
            if not self.advapi32.GetTokenInformation(
                token, 2, buffer, required.value, ctypes.byref(required),
            ):
                raise LocalPipeError("security_unavailable")

            count = wintypes.DWORD.from_buffer_copy(buffer.raw[:ctypes.sizeof(wintypes.DWORD)]).value
            if count > 4096:
                raise LocalPipeError("security_unavailable")
            offset = _TokenGroupsHead.Groups.offset
            stride = ctypes.sizeof(_SidAndAttributes)
            for index in range(count):
                start = offset + index * stride
                item = _SidAndAttributes.from_buffer_copy(buffer.raw[start:start + stride])
                if item.Attributes & 0xC0000000 != 0xC0000000:
                    continue
                sid_text = wintypes.LPWSTR()
                if not self.advapi32.ConvertSidToStringSidW(
                    item.Sid, ctypes.byref(sid_text),
                ):
                    raise LocalPipeError("security_unavailable")
                try:
                    value = sid_text.value
                    if type(value) is not str or not value.startswith("S-"):
                        raise LocalPipeError("security_unavailable")
                    return value
                finally:
                    self.kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HANDLE))
            raise LocalPipeError("security_unavailable")
        finally:
            self.close_handle(token)

    def security_descriptor(self):
        logon_sid = self.current_logon_sid()
        sddl = f"D:P(A;;GA;;;{logon_sid})(A;;GA;;;SY)"
        descriptor = wintypes.LPVOID()
        size = wintypes.DWORD()
        if not self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), ctypes.byref(size),
        ):
            raise LocalPipeError("security_unavailable")
        return descriptor

    @staticmethod
    def security_attributes(descriptor):
        return _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes), descriptor, False,
        )

    def create_pipe(self, pipe_name, security_descriptor):
        open_mode = 0x00000003 | 0x00080000  # DUPLEX | FIRST_PIPE_INSTANCE
        pipe_mode = 0x00000000 | 0x00000000 | 0x00000000 | 0x00000008
        security = self.security_attributes(security_descriptor)
        handle = self.kernel32.CreateNamedPipeW(
            pipe_name,
            open_mode,
            pipe_mode,
            _MAX_PIPE_INSTANCES_PER_ROUTE,
            _PIPE_BUFFER_BYTES,
            _PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(security),
        )
        if not handle or handle == _invalid_handle_value():
            raise LocalPipeError("pipe_unavailable")
        return handle

    def open_pipe_client(self, pipe_name, timeout_ms=10_000):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            handle = self.kernel32.CreateFileW(
                pipe_name,
                0x00000001 | 0x00000002 | 0x00100000,  # READ_DATA | WRITE_DATA | SYNCHRONIZE
                0,
                None,
                3,  # OPEN_EXISTING
                0,
                None,
            )
            if handle and handle != _invalid_handle_value():
                return handle
            error = ctypes.get_last_error()
            if error != 231 or time.monotonic() >= deadline:  # ERROR_PIPE_BUSY
                raise LocalPipeError("pipe_unavailable")
            remaining_ms = max(1, min(100, int((deadline - time.monotonic()) * 1000)))
            if not self.kernel32.WaitNamedPipeW(pipe_name, remaining_ms):
                if time.monotonic() >= deadline:
                    raise LocalPipeError("pipe_unavailable")

    def pipe_server_pid(self, handle):
        value = wintypes.DWORD()
        if not self.kernel32.GetNamedPipeServerProcessId(handle, ctypes.byref(value)):
            raise LocalPipeError("pipe_unavailable")
        return int(value.value)

    def pipe_client_pid(self, handle):
        value = wintypes.DWORD()
        if not self.kernel32.GetNamedPipeClientProcessId(handle, ctypes.byref(value)):
            raise LocalPipeError("pipe_unavailable")
        return int(value.value)

    def write_all(self, handle, data):
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + _PIPE_BUFFER_BYTES]
            buffer = ctypes.create_string_buffer(chunk)
            written = wintypes.DWORD()
            if not self.kernel32.WriteFile(
                handle, buffer, len(chunk), ctypes.byref(written), None,
            ) or not written.value:
                raise LocalPipeError("pipe_disconnected")
            offset += int(written.value)

    def read_file_chunk(self, handle, count):
        if count <= 0:
            return b""
        buffer = ctypes.create_string_buffer(count)
        read = wintypes.DWORD()
        if not self.kernel32.ReadFile(
            handle, buffer, count, ctypes.byref(read), None,
        ):
            raise LocalPipeError("pipe_disconnected")
        return buffer.raw[:read.value]

    def peek_available(self, handle):
        available = wintypes.DWORD()
        if not self.kernel32.PeekNamedPipe(
            handle, None, 0, None, ctypes.byref(available), None,
        ):
            raise LocalPipeError("pipe_disconnected")
        return int(available.value)

    def create_descriptor_file(self, payload):
        temp_dir = tempfile.gettempdir()
        if type(temp_dir) is not str or not os.path.isabs(temp_dir):
            raise LocalPipeError("descriptor_unavailable")
        drive, _ = os.path.splitdrive(temp_dir)
        root = (drive + os.sep) if drive else temp_dir
        if self.kernel32.GetDriveTypeW(root) in (0, 1, 4):  # UNKNOWN, NO_ROOT_DIR, REMOTE
            raise LocalPipeError("descriptor_unavailable")

        raw = _encode_json(payload)
        if len(raw) > _MAX_DESCRIPTOR_BYTES:
            raise LocalPipeError("descriptor_unavailable")
        security = self.security_attributes(self._security_descriptor)
        for _ in range(5):
            filename = f"{_DESCRIPTOR_PREFIX}{secrets.token_hex(24)}.json"
            path = os.path.join(temp_dir, filename)
            handle = self.kernel32.CreateFileW(
                path,
                0x80000000 | 0x40000000 | 0x00010000,  # READ | WRITE | DELETE
                0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ | WRITE | DELETE
                ctypes.byref(security),
                1,  # CREATE_NEW
                0x00000100 | 0x04000000,  # TEMPORARY | DELETE_ON_CLOSE
                None,
            )
            if not handle or handle == _invalid_handle_value():
                if ctypes.get_last_error() in (80, 183):  # FILE_EXISTS / ALREADY_EXISTS
                    continue
                raise LocalPipeError("descriptor_unavailable")
            try:
                self.write_all(handle, raw)
                if not self.kernel32.FlushFileBuffers(handle):
                    raise LocalPipeError("descriptor_unavailable")
                return path, handle
            except Exception:
                self.close_handle(handle)
                raise
        raise LocalPipeError("descriptor_unavailable")

    def launcher_rendezvous_path(self):
        temp_dir = tempfile.gettempdir()
        if type(temp_dir) is not str or not os.path.isabs(temp_dir):
            raise LocalPipeError("rendezvous_unavailable")
        drive, _ = os.path.splitdrive(temp_dir)
        root = (drive + os.sep) if drive else temp_dir
        if self.kernel32.GetDriveTypeW(root) in (0, 1, 4):  # UNKNOWN, NO_ROOT_DIR, REMOTE
            raise LocalPipeError("rendezvous_unavailable")
        logon_sid = self.current_logon_sid()
        sid_hash = hashlib.sha256(logon_sid.encode("ascii")).hexdigest()[:24]
        return os.path.join(
            temp_dir,
            f"{_LAUNCHER_RENDEZVOUS_PREFIX}{sid_hash}.json",
        )

    def create_launcher_rendezvous_file(self, payload):
        path = self.launcher_rendezvous_path()
        raw = _encode_json(payload)
        if len(raw) > _MAX_LAUNCHER_RENDEZVOUS_BYTES:
            raise LocalPipeError("rendezvous_unavailable")
        security = self.security_attributes(self._security_descriptor)
        handle = self.kernel32.CreateFileW(
            path,
            0x40000000 | 0x00010000,  # GENERIC_WRITE | DELETE
            0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ | WRITE | DELETE
            ctypes.byref(security),
            1,  # CREATE_NEW
            0x00000100 | 0x04000000,  # TEMPORARY | DELETE_ON_CLOSE
            None,
        )
        if not handle or handle == _invalid_handle_value():
            error = ctypes.get_last_error()
            if error in (80, 183):  # FILE_EXISTS / ALREADY_EXISTS
                raise LocalPipeError("rendezvous_owned")
            raise LocalPipeError("rendezvous_unavailable")
        try:
            self._write_launcher_rendezvous_file(handle, raw)
            return path, handle
        except Exception:
            self.close_handle(handle)
            raise

    def write_launcher_rendezvous_file(self, handle, payload):
        raw = _encode_json(payload)
        if len(raw) > _MAX_LAUNCHER_RENDEZVOUS_BYTES:
            raise LocalPipeError("rendezvous_unavailable")
        self._write_launcher_rendezvous_file(handle, raw)

    def _write_launcher_rendezvous_file(self, handle, raw):
        if not self.kernel32.SetFilePointerEx(handle, 0, None, 0):
            raise LocalPipeError("rendezvous_unavailable")
        if not self.kernel32.SetEndOfFile(handle):
            raise LocalPipeError("rendezvous_unavailable")
        self.write_all(handle, raw)
        if not self.kernel32.FlushFileBuffers(handle):
            raise LocalPipeError("rendezvous_unavailable")

    def read_launcher_rendezvous_file(self, path):
        if type(path) is not str or not path or len(path) > 32767:
            raise LocalPipeError("invalid_rendezvous")
        handle = self.kernel32.CreateFileW(
            path,
            0x80000000,  # GENERIC_READ
            0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ | WRITE | DELETE
            None,
            3,  # OPEN_EXISTING
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        if not handle or handle == _invalid_handle_value():
            error = ctypes.get_last_error()
            if error == 2:  # FILE_NOT_FOUND
                raise LocalPipeError("rendezvous_unavailable")
            raise LocalPipeError("rendezvous_owned")
        try:
            size = ctypes.c_longlong()
            if not self.kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
                raise LocalPipeError("invalid_rendezvous")
            if size.value <= 0 or size.value > _MAX_LAUNCHER_RENDEZVOUS_BYTES:
                raise LocalPipeError("invalid_rendezvous")
            chunks = []
            remaining = int(size.value)
            while remaining:
                part = self.read_file_chunk(handle, min(remaining, _PIPE_BUFFER_BYTES))
                if not part:
                    raise LocalPipeError("invalid_rendezvous")
                chunks.append(part)
                remaining -= len(part)
            return b"".join(chunks)
        finally:
            self.close_handle(handle)

    def remove_launcher_rendezvous_file(self, path):
        if type(path) is not str or not path or len(path) > 32767:
            raise LocalPipeError("invalid_rendezvous")
        handle = self.kernel32.CreateFileW(
            path,
            0x00010000,  # DELETE
            0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ | WRITE | DELETE
            None,
            3,  # OPEN_EXISTING
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        if not handle or handle == _invalid_handle_value():
            error = ctypes.get_last_error()
            if error == 2:
                return False
            raise LocalPipeError("rendezvous_cleanup_failed")
        try:
            self.mark_file_for_deletion(handle)
            return True
        finally:
            self.close_handle(handle)

    def mark_file_for_deletion(self, handle):
        disposition = _FileDispositionInfo(True)
        if not self.kernel32.SetFileInformationByHandle(
            handle,
            4,  # FileDispositionInfo
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            raise LocalPipeError("rendezvous_cleanup_failed")

    def read_descriptor_file(self, path):
        if type(path) is not str or not path or len(path) > 32767:
            raise LocalPipeError("invalid_descriptor")
        handle = self.kernel32.CreateFileW(
            path,
            0x80000000,  # GENERIC_READ
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,  # OPEN_EXISTING
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        if not handle or handle == _invalid_handle_value():
            raise LocalPipeError("descriptor_unavailable")
        try:
            size = ctypes.c_longlong()
            if not self.kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
                raise LocalPipeError("invalid_descriptor")
            if size.value <= 0 or size.value > _MAX_DESCRIPTOR_BYTES:
                raise LocalPipeError("invalid_descriptor")
            chunks = []
            remaining = int(size.value)
            while remaining:
                part = self.read_file_chunk(handle, min(remaining, _PIPE_BUFFER_BYTES))
                if not part:
                    raise LocalPipeError("invalid_descriptor")
                chunks.append(part)
                remaining -= len(part)
            return b"".join(chunks)
        finally:
            self.close_handle(handle)

    def create_security_descriptor_for_broker(self):
        self._security_descriptor = self.security_descriptor()
        return self._security_descriptor

    def close_security_descriptor(self, descriptor):
        if descriptor:
            self.kernel32.LocalFree(ctypes.cast(descriptor, wintypes.HANDLE))


@functools.lru_cache(maxsize=1)
def _win32():
    return _WindowsApi()


def _invalid_handle_value():
    return ctypes.c_void_p(-1).value


def _reject_json_constant(_value):
    raise ValueError("invalid JSON number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _decode_json_object(raw):
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        raise LocalPipeError("invalid_request") from None
    if type(value) is not dict:
        raise LocalPipeError("invalid_request")
    return value


def _encode_json(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
    except Exception:
        raise LocalPipeError("invalid_result") from None


def _valid_secret_field(value):
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and value.isascii()
    )


def _descriptor_payload_valid(value):
    expected = {
        "contract_version",
        "bootstrap_contract_version",
        "pipe_name",
        "server_pid",
        "process_incarnation",
        "route_id",
        "capability",
        "expires_in_seconds",
    }
    if type(value) is not dict or set(value) != expected:
        return False
    if value["contract_version"] != LOCAL_PIPE_CONTRACT:
        return False
    if value["bootstrap_contract_version"] != PAIRING_BOOTSTRAP_CONTRACT:
        return False
    pipe_name = value["pipe_name"]
    if (
        type(pipe_name) is not str
        or not pipe_name.startswith(_PIPE_PREFIX)
        or len(pipe_name) > 240
        or not pipe_name.isascii()
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in pipe_name[len(_PIPE_PREFIX):])
    ):
        return False
    if type(value["server_pid"]) is not int or value["server_pid"] <= 0:
        return False
    if not _valid_secret_field(value["process_incarnation"]):
        return False
    if not _valid_secret_field(value["route_id"]):
        return False
    if not _valid_secret_field(value["capability"]):
        return False
    lifetime = value["expires_in_seconds"]
    if (
        type(lifetime) not in (int, float)
        or not math.isfinite(lifetime)
        or lifetime <= 0
        or lifetime > 300
    ):
        return False
    return True


def _launcher_rendezvous_payload_valid(value):
    expected = {
        "contract_version",
        "status",
        "server_pid",
        "process_incarnation",
        "descriptor_path",
        "expires_at",
    }
    if type(value) is not dict or set(value) != expected:
        return False
    if value["contract_version"] != LAUNCHER_RENDEZVOUS_CONTRACT:
        return False
    status = value["status"]
    if type(status) is not str or status not in {
        "preparing", "ready", "claimed", "expired", "disarmed", "released",
        "unavailable",
    }:
        return False
    if type(value["server_pid"]) is not int or value["server_pid"] <= 0:
        return False
    if not _valid_secret_field(value["process_incarnation"]):
        return False
    descriptor_path = value["descriptor_path"]
    if status == "ready":
        if (type(descriptor_path) is not str
                or not descriptor_path
                or len(descriptor_path) > 32767
                or not os.path.isabs(descriptor_path)):
            return False
    elif descriptor_path != "":
        return False
    expires_at = value["expires_at"]
    if status in ("preparing", "ready"):
        return (
            type(expires_at) in (int, float)
            and math.isfinite(expires_at)
            and expires_at > 0
        )
    return expires_at is None


def _launcher_rendezvous_payload(
    *, status, server_pid, process_incarnation, descriptor_path="", expires_at=None,
):
    return {
        "contract_version": LAUNCHER_RENDEZVOUS_CONTRACT,
        "status": status,
        "server_pid": server_pid,
        "process_incarnation": process_incarnation,
        "descriptor_path": descriptor_path,
        "expires_at": expires_at,
    }


def _remove_stale_launcher_rendezvous(api, path, payload):
    """Remove only terminal, expired, or dead-process rendezvous records."""

    if not _launcher_rendezvous_payload_valid(payload):
        return False
    if payload["status"] in ("preparing", "ready"):
        expired = payload["expires_at"] <= time.monotonic()
        alive = api.process_is_alive(payload["server_pid"])
        stale = alive is False or (payload["status"] == "ready" and expired)
    else:
        alive = api.process_is_alive(payload["server_pid"])
        stale = alive is False or payload["status"] in (
            "expired", "disarmed", "released", "unavailable",
        )
    if not stale:
        return False
    api.remove_launcher_rendezvous_file(path)
    return True


def read_local_launcher_rendezvous():
    """Read the one per-logon armed target without exposing its path in repr."""

    try:
        api = _win32()
        path = api.launcher_rendezvous_path()
        raw = api.read_launcher_rendezvous_file(path)
        payload = _decode_json_object(raw)
    except LocalPipeError as error:
        return LocalLauncherRendezvous(error.reason)
    except Exception:
        return LocalLauncherRendezvous("rendezvous_unavailable")

    if not _launcher_rendezvous_payload_valid(payload):
        return LocalLauncherRendezvous("invalid_rendezvous")
    status = payload["status"]
    if status in ("expired", "disarmed", "released", "unavailable"):
        try:
            api.remove_launcher_rendezvous_file(path)
        except LocalPipeError:
            pass
        return LocalLauncherRendezvous(status)
    if status == "claimed":
        if api.process_is_alive(payload["server_pid"]) is False:
            try:
                api.remove_launcher_rendezvous_file(path)
            except LocalPipeError:
                pass
            return LocalLauncherRendezvous("stale_rendezvous")
        return LocalLauncherRendezvous("already_owned")
    if status == "preparing":
        alive = api.process_is_alive(payload["server_pid"])
        if alive is False:
            try:
                api.remove_launcher_rendezvous_file(path)
            except LocalPipeError:
                pass
            return LocalLauncherRendezvous("stale_rendezvous")
        if alive is not True or payload["expires_at"] <= time.monotonic():
            return LocalLauncherRendezvous("rendezvous_not_ready")
        return LocalLauncherRendezvous("rendezvous_not_ready")

    if payload["expires_at"] <= time.monotonic():
        try:
            api.remove_launcher_rendezvous_file(path)
        except LocalPipeError:
            pass
        return LocalLauncherRendezvous("expired_rendezvous")
    alive = api.process_is_alive(payload["server_pid"])
    if alive is False:
        try:
            api.remove_launcher_rendezvous_file(path)
        except LocalPipeError:
            pass
        return LocalLauncherRendezvous("stale_rendezvous")
    if alive is not True:
        return LocalLauncherRendezvous("rendezvous_unavailable")
    return LocalLauncherRendezvous(
        "ready",
        descriptor_file_path=payload["descriptor_path"],
        server_pid=payload["server_pid"],
        process_incarnation=payload["process_incarnation"],
    )


def read_local_pairing_descriptor(path):
    """Read and validate one protected local descriptor file."""

    api = _win32()
    raw = api.read_descriptor_file(path)
    descriptor = _decode_json_object(raw)
    if not _descriptor_payload_valid(descriptor):
        raise LocalPipeError("invalid_descriptor")
    return LocalPairingDescriptor(**descriptor)


@dataclass
class _PairingLease:
    route_id: str
    process_incarnation: str
    pipe_name: str
    endpoint: object = field(repr=False)
    descriptor_path: str = field(repr=False)
    descriptor_handle: object = field(repr=False)
    expires_at: float
    expiry_timer: object = field(default=None, repr=False)
    claimed: bool = False
    stuck_in_flight: bool = False


@dataclass
class _LauncherRendezvousLease:
    route_id: str
    path: str = field(repr=False)
    file_handle: object = field(repr=False)
    expires_at: float
    status: str = "preparing"


class _PipeEndpoint:
    """One-instance endpoint bound to a single session route offer."""

    def __init__(self, broker, lease):
        self._broker = broker
        self._lease = lease
        self._api = broker._api
        handle = self._api.create_pipe(
            lease.pipe_name, broker._security_descriptor,
        )
        try:
            self._stop_event = threading.Event()
            self._connected = threading.Event()
            self._orphan_cleanup_started = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                name="PromptGraphLocalPipeRoute",
                daemon=True,
            )
            self._handle = handle
        except Exception:
            self._api.close_handle(handle)
            raise

    @property
    def native_handle(self):
        return self._handle

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread.ident is None:
            self._api.close_handle(self._handle)
            self._handle = None
        elif not self._connected.is_set():
            self._wake_connect()

    def _wake_connect(self):
        try:
            handle = self._api.open_pipe_client(self._lease.pipe_name, timeout_ms=100)
        except LocalPipeError:
            return
        self._api.close_handle(handle)

    def _run(self):
        paired_route = None
        outcome = "closed"
        served = None
        try:
            while not self._stop_event.is_set():
                connected = self._connect_once()
                if not connected:
                    if self._stop_event.is_set():
                        break
                    continue
                self._connected.set()
                if self._stop_event.is_set():
                    self._disconnect_pipe()
                    break
                claim = self._read_claim()
                if claim is None:
                    self._disconnect_pipe()
                    self._connected.clear()
                    continue
                if claim[0] != "paired":
                    self._write_response({"status": claim[0]})
                    self._wait_for_claimant_close()
                    self._disconnect_pipe()
                    self._connected.clear()
                    continue

                paired_route = claim[1]
                self._broker._mark_claimed(self._lease)
                self._write_response({"status": "paired"})
                served = self._serve_paired_route(paired_route)
                if type(served) is tuple and served[0] == "released":
                    outcome = "released"
                else:
                    outcome = self._drain_and_release(paired_route, served)
                paired_route = None
                break
        except Exception:
            outcome = "transport_error"
        finally:
            if paired_route is not None:
                outcome = self._drain_and_release(paired_route, served)
            self._api.close_handle(self._handle)
            self._handle = None
            self._broker._endpoint_finished(self._lease, outcome)

    def _connect_once(self):
        result = self._api.kernel32.ConnectNamedPipe(self._handle, None)
        if result:
            return True
        error = ctypes.get_last_error()
        if error == 535:  # ERROR_PIPE_CONNECTED
            return True
        if error in (232, 233):  # client left before acceptance
            self._api.kernel32.DisconnectNamedPipe(self._handle)
            return False
        raise LocalPipeError("pipe_unavailable")

    def _read_claim(self):
        try:
            request = _decode_json_object(self._read_frame(_PAIRING_CONNECT_TIMEOUT_SECONDS))
        except LocalPipeError as error:
            if error.reason not in ("pipe_timeout", "pipe_disconnected"):
                return ("invalid_request", None)
            return None
        required = {
            "contract_version", "operation", "process_incarnation", "route_id",
            "capability",
        }
        if (
            set(request) != required
            or request.get("contract_version") != LOCAL_PIPE_CONTRACT
            or request.get("operation") != "claim"
            or not _valid_secret_field(request.get("process_incarnation"))
            or not _valid_secret_field(request.get("route_id"))
            or not _valid_secret_field(request.get("capability"))
        ):
            return ("invalid_pairing", None)
        if request["route_id"] != self._lease.route_id:
            return ("invalid_pairing", None)
        if request["process_incarnation"] != self._lease.process_incarnation:
            return ("invalid_pairing", None)
        operation = self._broker._registry.claim_pairing(
            request["process_incarnation"],
            request["route_id"],
            request["capability"],
        )
        if operation.status == "paired" and type(operation.paired_route) is ProjectAgentPairedRoute:
            return ("paired", operation.paired_route)
        return (operation.status, None)

    def _wait_for_claimant_close(self):
        """Keep a bounded rejection reply readable before disconnecting the pipe."""

        deadline = time.monotonic() + _PAIRING_RESPONSE_CLOSE_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not self._stop_event.is_set():
            try:
                self._api.peek_available(self._handle)
            except LocalPipeError:
                return
            self._stop_event.wait(min(0.01, deadline - time.monotonic()))

    def _serve_paired_route(self, paired_route):
        outstanding_epoch = None
        while not self._stop_event.is_set():
            try:
                request = _decode_json_object(
                    self._read_frame(
                        _PIPE_PARTIAL_FRAME_TIMEOUT_SECONDS,
                        allow_idle=True,
                    )
                )
            except LocalPipeError as error:
                if error.reason not in ("pipe_timeout", "pipe_disconnected"):
                    self._try_write_response({"status": "invalid_request"})
                return "disconnected", outstanding_epoch

            response, release_status, submitted_epoch = self._dispatch_route_operation(
                paired_route, request,
            )
            if submitted_epoch is not None:
                outstanding_epoch = submitted_epoch
            try:
                self._write_response(response)
            except LocalPipeError:
                return "disconnected", outstanding_epoch
            if release_status == "released":
                return "released", None
        return "disconnected", outstanding_epoch

    @staticmethod
    def _dispatch_route_operation(paired_route, request):
        if type(request) is not dict or type(request.get("operation")) is not str:
            return {"status": "invalid_request"}, None, None
        operation = request["operation"]
        if operation == "current_target_epoch":
            if set(request) != {"operation"}:
                return {"status": "invalid_request"}, None, None
            epoch = paired_route.current_target_epoch
            if type(epoch) is not str or not epoch:
                return {"status": "session_unavailable"}, None, None
            return {"status": "ok", "target_epoch": epoch}, None, None
        if operation == "submit":
            if set(request) != {"operation", "target_epoch", "request"}:
                return {"status": "invalid_request"}, None, None
            epoch = request["target_epoch"]
            if not _valid_secret_field(epoch) or type(request["request"]) is not dict:
                return {"status": "invalid_request"}, None, None
            outcome = paired_route.submit(epoch, request["request"])
            accepted_epoch = epoch if outcome.status == "accepted" else None
            return {"status": outcome.status}, None, accepted_epoch
        if operation == "consume_reply":
            if set(request) != {"operation", "target_epoch"}:
                return {"status": "invalid_request"}, None, None
            epoch = request["target_epoch"]
            if not _valid_secret_field(epoch):
                return {"status": "invalid_request"}, None, None
            outcome = paired_route.consume_reply(epoch)
            response = {"status": outcome.status}
            if outcome.status == "completed":
                if type(outcome.reply) is not dict:
                    return {"status": "internal_error"}, None, None
                response["reply"] = outcome.reply
            return response, None, None
        if operation == "release":
            if set(request) != {"operation"}:
                return {"status": "invalid_request"}, None, None
            result = paired_route.release()
            return {"status": result.status}, result.status, None
        return {"status": "invalid_request"}, None, None

    def _drain_and_release(self, paired_route, serve_outcome=None):
        self._orphan_cleanup_started.set()
        outstanding_epoch = None
        if type(serve_outcome) is tuple and len(serve_outcome) == 2:
            outstanding_epoch = serve_outcome[1]
        if outstanding_epoch is None:
            release = paired_route.release()
            if release.status in ("released", "already_released"):
                return "released"
            if release.status == "session_unavailable":
                return "session_unavailable"
            # A route must not be released unless any accepted request is known
            # to be idle. If no accepted epoch was tracked, fail closed.
            return "stuck_in_flight"

        deadline = time.monotonic() + _ORPHAN_DRAIN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                paired_route.consume_reply(outstanding_epoch)
                release = paired_route.release()
            except Exception:
                return "session_unavailable"
            if release.status in ("released", "already_released"):
                return "released"
            if release.status == "session_unavailable":
                return "session_unavailable"
            time.sleep(_ORPHAN_POLL_SECONDS)
        return "stuck_in_flight"

    def _read_frame(self, timeout_seconds, *, allow_idle=False):
        if allow_idle:
            # A paired client may remain connected without sending requests.
            # Wait indefinitely for a frame to begin, then bound completion of
            # its header and body so a partial frame cannot pin the endpoint.
            prefix = self._read_exact(
                4,
                None,
                timeout_after_first_byte=timeout_seconds,
            )
            deadline = time.monotonic() + timeout_seconds
        else:
            deadline = time.monotonic() + timeout_seconds
            prefix = self._read_exact(4, deadline)
        size = struct.unpack(">I", prefix)[0]
        if size <= 0 or size > _MAX_REQUEST_FRAME_BYTES:
            raise LocalPipeError("invalid_frame")
        return self._read_exact(size, deadline)

    def _read_exact(self, size, deadline, *, timeout_after_first_byte=None):
        parts = []
        remaining = size
        while remaining:
            available = self._api.peek_available(self._handle)
            if available <= 0:
                if self._stop_event.is_set():
                    raise LocalPipeError("pipe_disconnected")
                if deadline is None:
                    self._stop_event.wait(0.05)
                    continue
                time_left = deadline - time.monotonic()
                if time_left <= 0:
                    raise LocalPipeError("pipe_timeout")
                self._stop_event.wait(min(0.05, time_left))
                continue
            if deadline is not None and time.monotonic() >= deadline:
                raise LocalPipeError("pipe_timeout")
            chunk_size = min(remaining, available, _PIPE_BUFFER_BYTES)
            chunk = self._api.read_file_chunk(self._handle, chunk_size)
            if not chunk:
                raise LocalPipeError("pipe_disconnected")
            if deadline is None and timeout_after_first_byte is not None:
                deadline = time.monotonic() + timeout_after_first_byte
            parts.append(chunk)
            remaining -= len(chunk)
            if time.monotonic() >= deadline and remaining:
                raise LocalPipeError("pipe_timeout")
        return b"".join(parts)

    def _write_response(self, response):
        raw = _encode_json(response)
        if len(raw) > 0xFFFFFFFF:
            raw = b'{"status":"response_too_large"}'
        self._api.write_all(self._handle, struct.pack(">I", len(raw)) + raw)

    def _try_write_response(self, response):
        try:
            self._write_response(response)
        except Exception:
            return

    def _disconnect_pipe(self):
        if self._handle:
            self._api.kernel32.DisconnectNamedPipe(self._handle)
        self._connected.clear()


class WindowsNamedPipeBroker:
    """App-process coordinator for isolated one-instance session endpoints."""

    def __init__(self, registry=None):
        self._api = _win32()
        if registry is None:
            registry = get_process_project_agent_session_registry()
        if type(registry) is not ProjectAgentSessionRegistry:
            raise LocalPipeError("invalid_registry")
        self._registry = registry
        self._process_incarnation = registry.process_incarnation
        self._server_pid = self._api.process_id()
        self._security_descriptor = self._api.create_security_descriptor_for_broker()
        self._lock = threading.RLock()
        self._leases = {}
        self._launcher_rendezvous = None
        self._launcher_statuses = {}
        self._closed = False

    @property
    def process_incarnation(self):
        return self._process_incarnation

    @property
    def server_pid(self):
        return self._server_pid

    def prepare_pairing_descriptor(self, registration):
        """Arm one exact route and return only its protected descriptor path."""

        if (
            type(registration) is not ProjectAgentSessionRegistration
            or registration._registry is not self._registry
            or not _valid_secret_field(registration.route_id)
        ):
            return PairingDescriptorDelivery("invalid_registration")
        route_id = registration.route_id
        with self._lock:
            if self._closed:
                return PairingDescriptorDelivery("broker_unavailable")
            if route_id in self._leases:
                return PairingDescriptorDelivery("offer_pending")
            if len(self._leases) >= _MAX_ACTIVE_ROUTES:
                return PairingDescriptorDelivery("broker_busy")

            pipe_name = _PIPE_PREFIX + self._process_incarnation + "-" + secrets.token_urlsafe(16)
            lease = _PairingLease(
                route_id=route_id,
                process_incarnation=self._process_incarnation,
                pipe_name=pipe_name,
                endpoint=None,
                descriptor_path="",
                descriptor_handle=None,
                expires_at=0.0,
            )
            endpoint = None
            pairing_armed = False
            try:
                endpoint = _PipeEndpoint(self, lease)
                lease.endpoint = endpoint
                self._leases[route_id] = lease
                endpoint.start()
                armed = registration.arm_pairing()
                if armed.status != "armed" or armed.bootstrap is None:
                    self._leases.pop(route_id, None)
                    endpoint.stop()
                    return PairingDescriptorDelivery(armed.status)
                pairing_armed = True
                bootstrap = armed.bootstrap
                payload = {
                    "contract_version": LOCAL_PIPE_CONTRACT,
                    "bootstrap_contract_version": bootstrap.contract_version,
                    "pipe_name": pipe_name,
                    "server_pid": self._server_pid,
                    "process_incarnation": bootstrap.process_incarnation,
                    "route_id": bootstrap.route_id,
                    "capability": bootstrap.capability,
                    "expires_in_seconds": bootstrap.expires_in_seconds,
                }
                path, file_handle = self._api.create_descriptor_file(payload)
                lease.descriptor_path = path
                lease.descriptor_handle = file_handle
                lease.expires_at = time.monotonic() + bootstrap.expires_in_seconds
                timer = threading.Timer(
                    bootstrap.expires_in_seconds,
                    self._expire_lease,
                    args=(lease,),
                )
                timer.daemon = True
                lease.expiry_timer = timer
                timer.start()
                return PairingDescriptorDelivery(
                    "armed",
                    PairingDescriptorFile(
                        path=path,
                        route_id=route_id,
                        expires_in_seconds=bootstrap.expires_in_seconds,
                    ),
                )
            except Exception as error:
                self._leases.pop(route_id, None)
                if endpoint is not None:
                    endpoint.stop()
                self._close_descriptor_handle(lease)
                if pairing_armed:
                    registration.disarm_pairing_offer()
                if isinstance(error, LocalPipeError):
                    return PairingDescriptorDelivery(error.reason)
                return PairingDescriptorDelivery("descriptor_unavailable")

    def arm_launcher_rendezvous(self, registration):
        """Arm one explicit session and publish only its protected descriptor path."""

        if (
            type(registration) is not ProjectAgentSessionRegistration
            or registration._registry is not self._registry
            or not _valid_secret_field(registration.route_id)
        ):
            return LauncherRendezvousOperation("invalid_registration")
        route_id = registration.route_id
        with self._lock:
            if self._closed:
                return LauncherRendezvousOperation("broker_unavailable")
            current = self._launcher_rendezvous
            if current is not None:
                if (current.status in ("preparing", "ready")
                        and current.expires_at <= time.monotonic()):
                    self._expire_launcher_rendezvous_locked(current)
                    current = self._launcher_rendezvous
            if current is not None:
                if current.route_id != route_id:
                    return LauncherRendezvousOperation("already_owned")
                return LauncherRendezvousOperation(
                    "already_armed" if current.status in ("preparing", "ready")
                    else "already_paired",
                    expires_in_seconds=max(0.0, current.expires_at - time.monotonic())
                    if current.expires_at else None,
                )

            expires_at = time.monotonic() + DEFAULT_PAIRING_LIFETIME_SECONDS
            pending_payload = _launcher_rendezvous_payload(
                status="preparing",
                server_pid=self._server_pid,
                process_incarnation=self._process_incarnation,
                expires_at=expires_at,
            )
            try:
                path, file_handle = self._create_launcher_rendezvous_file(
                    pending_payload
                )
            except Exception as error:
                reason = error.reason if isinstance(error, LocalPipeError) else None
                return LauncherRendezvousOperation(
                    "already_owned" if reason == "rendezvous_owned"
                    else "rendezvous_unavailable"
                )

            rendezvous = _LauncherRendezvousLease(
                route_id=route_id,
                path=path,
                file_handle=file_handle,
                expires_at=expires_at,
                status="preparing",
            )
            self._launcher_rendezvous = rendezvous
            self._launcher_statuses[route_id] = "preparing"

            delivery = self.prepare_pairing_descriptor(registration)
            if delivery.status != "armed" or delivery.descriptor_file is None:
                self._launcher_rendezvous = None
                self._launcher_statuses[route_id] = delivery.status
                self._api.close_handle(rendezvous.file_handle)
                rendezvous.file_handle = None
                self._launcher_statuses.pop(route_id, None)
                return LauncherRendezvousOperation(delivery.status)

            pipe_lease = self._leases.get(route_id)
            if pipe_lease is None:
                self._launcher_rendezvous = None
                self._launcher_statuses[route_id] = "unavailable"
                self._api.close_handle(rendezvous.file_handle)
                rendezvous.file_handle = None
                registration.disarm_pairing_offer()
                self._launcher_rendezvous = None
                return LauncherRendezvousOperation("rendezvous_unavailable")

            rendezvous.expires_at = pipe_lease.expires_at
            try:
                self._write_launcher_rendezvous_state(
                    rendezvous,
                    "ready",
                    descriptor_file_path=delivery.descriptor_file.path,
                    expires_at=pipe_lease.expires_at,
                )
            except Exception:
                self._launcher_statuses[route_id] = "unavailable"
                self._launcher_rendezvous = None
                self._api.close_handle(rendezvous.file_handle)
                rendezvous.file_handle = None
                self.close_session_route(route_id)
                registration.disarm_pairing_offer()
                return LauncherRendezvousOperation("rendezvous_unavailable")

            rendezvous.status = "ready"
            self._launcher_statuses[route_id] = "ready"
            return LauncherRendezvousOperation(
                "ready",
                expires_in_seconds=max(0.0, pipe_lease.expires_at - time.monotonic()),
            )

    def launcher_rendezvous_status(self, registration):
        if (
            type(registration) is not ProjectAgentSessionRegistration
            or registration._registry is not self._registry
        ):
            return "unavailable"
        with self._lock:
            lease = self._launcher_rendezvous
            if (lease is not None and lease.route_id == registration.route_id
                    and lease.status in ("preparing", "ready")
                    and lease.expires_at <= time.monotonic()):
                self._expire_launcher_rendezvous_locked(lease)
                lease = self._launcher_rendezvous
            if lease is not None and lease.route_id == registration.route_id:
                return lease.status
            return self._launcher_statuses.get(registration.route_id, "unavailable")

    def disarm_launcher_rendezvous(self, registration):
        """Disarm only the calling session's own launcher target and route."""

        if (
            type(registration) is not ProjectAgentSessionRegistration
            or registration._registry is not self._registry
        ):
            return LauncherRendezvousOperation("session_unavailable")
        route_id = registration.route_id
        with self._lock:
            rendezvous = self._launcher_rendezvous
            if rendezvous is None or rendezvous.route_id != route_id:
                status = self._launcher_statuses.get(route_id, "unavailable")
                return LauncherRendezvousOperation(status)
            write_failed = False
            try:
                self._write_launcher_rendezvous_state(
                    rendezvous,
                    "disarmed",
                    descriptor_file_path="",
                    expires_at=None,
                )
            except Exception:
                write_failed = True
            rendezvous.status = "disarmed"
            self._launcher_statuses[route_id] = "disarmed"
            has_pipe_lease = route_id in self._leases

        pairing = registration.disarm_pairing_offer()
        if has_pipe_lease:
            self.close_session_route(route_id)
        else:
            self._finish_launcher_rendezvous(route_id, "disarmed")
        if write_failed or pairing.status not in ("disarmed", "already_paired", "not_armed"):
            return LauncherRendezvousOperation("unavailable")
        return LauncherRendezvousOperation("disarmed")

    def forget_launcher_rendezvous(self, registration):
        """Drop terminal per-session status after its session is cleaned up."""

        if (
            type(registration) is not ProjectAgentSessionRegistration
            or registration._registry is not self._registry
        ):
            return False
        with self._lock:
            lease = self._launcher_rendezvous
            if lease is not None and lease.route_id == registration.route_id:
                return False
            self._launcher_statuses.pop(registration.route_id, None)
            return True

    def _create_launcher_rendezvous_file(self, initial_payload):
        try:
            return self._api.create_launcher_rendezvous_file(initial_payload)
        except LocalPipeError as error:
            if error.reason != "rendezvous_owned":
                raise
        except Exception:
            raise LocalPipeError("rendezvous_unavailable") from None
        path = self._api.launcher_rendezvous_path()
        try:
            payload = _decode_json_object(
                self._api.read_launcher_rendezvous_file(path)
            )
        except Exception:
            raise LocalPipeError("rendezvous_owned") from None
        if not _remove_stale_launcher_rendezvous(self._api, path, payload):
            raise LocalPipeError("rendezvous_owned")
        return self._api.create_launcher_rendezvous_file(initial_payload)

    def _write_launcher_rendezvous_state(
        self,
        rendezvous,
        status,
        *,
        descriptor_file_path="",
        expires_at=None,
    ):
        if rendezvous.file_handle is None:
            return
        payload = _launcher_rendezvous_payload(
            status=status,
            server_pid=self._server_pid,
            process_incarnation=self._process_incarnation,
            descriptor_path=descriptor_file_path,
            expires_at=expires_at,
        )
        self._api.write_launcher_rendezvous_file(rendezvous.file_handle, payload)

    def _finish_launcher_rendezvous(self, route_id, status):
        with self._lock:
            rendezvous = self._launcher_rendezvous
            if rendezvous is None or rendezvous.route_id != route_id:
                self._launcher_statuses[route_id] = status
                return
            try:
                self._write_launcher_rendezvous_state(
                    rendezvous,
                    status,
                    descriptor_file_path="",
                    expires_at=None,
                )
            except Exception:
                status = "unavailable"
            rendezvous.status = status
            self._launcher_statuses[route_id] = status
            if rendezvous.file_handle is not None:
                self._api.close_handle(rendezvous.file_handle)
                rendezvous.file_handle = None
            self._launcher_rendezvous = None

    def _expire_launcher_rendezvous_locked(self, rendezvous):
        route_id = rendezvous.route_id
        lease = self._leases.get(route_id)
        if lease is not None and not lease.claimed:
            self._leases.pop(route_id, None)
            if lease.expiry_timer is not None:
                lease.expiry_timer.cancel()
                lease.expiry_timer = None
            self._close_descriptor_handle(lease)
            lease.endpoint.stop()
        self._finish_launcher_rendezvous(route_id, "expired")

    def close_session_route(self, route_id):
        """Stop transport for one session without altering another route."""

        if not _valid_secret_field(route_id):
            return False
        with self._lock:
            lease = self._leases.pop(route_id, None)
            if lease is not None:
                if lease.expiry_timer is not None:
                    lease.expiry_timer.cancel()
                self._close_descriptor_handle(lease)
            rendezvous = self._launcher_rendezvous
            if rendezvous is not None and rendezvous.route_id == route_id:
                terminal = rendezvous.status
                if terminal not in ("disarmed", "expired"):
                    terminal = "unavailable"
                self._finish_launcher_rendezvous(route_id, terminal)
        if lease is not None:
            lease.endpoint.stop()
        return lease is not None

    def close(self):
        """Close all route endpoints and descriptor handles owned by this broker."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            leases = list(self._leases.values())
            self._leases.clear()
            for lease in leases:
                if lease.expiry_timer is not None:
                    lease.expiry_timer.cancel()
                self._close_descriptor_handle(lease)
            rendezvous = self._launcher_rendezvous
            if rendezvous is not None:
                self._finish_launcher_rendezvous(
                    rendezvous.route_id,
                    "unavailable" if rendezvous.status != "disarmed" else "disarmed",
                )
        for lease in leases:
            lease.endpoint.stop()
        self._api.close_security_descriptor(self._security_descriptor)
        self._security_descriptor = None

    def _mark_claimed(self, lease):
        with self._lock:
            if self._leases.get(lease.route_id) is not lease:
                raise LocalPipeError("session_unavailable")
            lease.claimed = True
            if lease.expiry_timer is not None:
                lease.expiry_timer.cancel()
                lease.expiry_timer = None
            self._close_descriptor_handle(lease)
            rendezvous = self._launcher_rendezvous
            if rendezvous is not None and rendezvous.route_id == lease.route_id:
                rendezvous.status = "claimed"
                rendezvous.expires_at = 0.0
                self._launcher_statuses[lease.route_id] = "claimed"
                try:
                    self._write_launcher_rendezvous_state(
                        rendezvous,
                        "claimed",
                        descriptor_file_path="",
                        expires_at=None,
                    )
                except Exception:
                    # The file lock remains held; the paired route itself is
                    # already authenticated and does not depend on status IO.
                    pass

    def _expire_lease(self, lease):
        with self._lock:
            if self._leases.get(lease.route_id) is not lease or lease.claimed:
                return
            self._leases.pop(lease.route_id, None)
            self._close_descriptor_handle(lease)
            rendezvous = self._launcher_rendezvous
            if rendezvous is not None and rendezvous.route_id == lease.route_id:
                self._finish_launcher_rendezvous(lease.route_id, "expired")
        lease.endpoint.stop()

    def _endpoint_finished(self, lease, outcome):
        with self._lock:
            if self._leases.get(lease.route_id) is not lease:
                return
            if outcome == "stuck_in_flight":
                lease.stuck_in_flight = True
                return
            self._leases.pop(lease.route_id, None)
            if lease.expiry_timer is not None:
                lease.expiry_timer.cancel()
                lease.expiry_timer = None
            self._close_descriptor_handle(lease)
            if (self._launcher_rendezvous is not None
                    and self._launcher_rendezvous.route_id == lease.route_id):
                status = "released" if outcome == "released" else "unavailable"
                self._finish_launcher_rendezvous(lease.route_id, status)

    def _close_descriptor_handle(self, lease):
        if lease.descriptor_handle:
            self._api.close_handle(lease.descriptor_handle)
            lease.descriptor_handle = None

    def __repr__(self):
        return "WindowsNamedPipeBroker(<local session routes>)"


class LocalNamedPipeClient:
    """Narrow client for the authenticated paired-route wire operations."""

    __slots__ = ("_api", "_handle", "_closed")

    def __init__(self, api, handle):
        self._api = api
        self._handle = handle
        self._closed = False

    def __repr__(self):
        return "LocalNamedPipeClient(<authenticated>)"

    @classmethod
    def connect_from_descriptor_file(cls, path):
        try:
            descriptor = read_local_pairing_descriptor(path)
            return cls.connect(descriptor)
        except LocalPipeError as error:
            return PipeConnectionResult(error.reason)
        except Exception:
            return PipeConnectionResult("transport_error")

    @classmethod
    def connect(cls, descriptor):
        if (
            type(descriptor) is not LocalPairingDescriptor
            or not _descriptor_payload_valid(descriptor.__dict__)
        ):
            return PipeConnectionResult("invalid_descriptor")
        try:
            api = _win32()
            handle = api.open_pipe_client(descriptor.pipe_name)
            server_pid = api.pipe_server_pid(handle)
            if server_pid != descriptor.server_pid:
                api.close_handle(handle)
                return PipeConnectionResult("wrong_endpoint")
            client = cls(api, handle)
            claim = client._exchange({
                "contract_version": descriptor.contract_version,
                "operation": "claim",
                "process_incarnation": descriptor.process_incarnation,
                "route_id": descriptor.route_id,
                "capability": descriptor.capability,
            })
            if claim.get("status") != "paired":
                client.close()
                return PipeConnectionResult(
                    claim.get("status") if _valid_status(claim.get("status")) else "invalid_pairing"
                )
            return PipeConnectionResult("paired", client)
        except LocalPipeError as error:
            return PipeConnectionResult(error.reason)
        except Exception:
            return PipeConnectionResult("transport_error")

    def current_target_epoch(self):
        return self._exchange({"operation": "current_target_epoch"})

    def submit(self, target_epoch, request):
        return self._exchange({
            "operation": "submit",
            "target_epoch": target_epoch,
            "request": request,
        })

    def consume_reply(self, target_epoch):
        return self._exchange({
            "operation": "consume_reply",
            "target_epoch": target_epoch,
        })

    def release(self):
        result = self._exchange({"operation": "release"})
        if result.get("status") == "released":
            self.close()
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._api.close_handle(self._handle)
        self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()

    def _exchange(self, payload):
        if self._closed or not self._handle:
            raise LocalPipeError("pipe_disconnected")
        raw = _encode_json(payload)
        if len(raw) > _MAX_REQUEST_FRAME_BYTES:
            raise LocalPipeError("invalid_request")
        try:
            self._api.write_all(self._handle, struct.pack(">I", len(raw)) + raw)
            response = _decode_json_object(_read_client_frame(self._api, self._handle))
            return response
        except Exception as error:
            self.close()
            if isinstance(error, LocalPipeError):
                raise
            raise LocalPipeError("transport_error") from None


def _valid_status(value):
    return (
        type(value) is str
        and 0 < len(value) <= 64
        and value.isascii()
        and all(character.isalnum() or character == "_" for character in value)
    )


def _read_client_frame(api, handle):
    prefix = _read_client_exact(api, handle, 4)
    size = struct.unpack(">I", prefix)[0]
    if size <= 0:
        raise LocalPipeError("invalid_response")
    return _read_client_exact(api, handle, size)


def _read_client_exact(api, handle, size):
    parts = []
    remaining = size
    while remaining:
        chunk = api.read_file_chunk(handle, min(remaining, _PIPE_BUFFER_BYTES))
        if not chunk:
            raise LocalPipeError("pipe_disconnected")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


_PROCESS_BROKER_LOCK = threading.Lock()
_PROCESS_BROKER = None


def get_process_project_agent_named_pipe_broker():
    """Return the process-local broker; it has no active-session fallback."""

    global _PROCESS_BROKER
    with _PROCESS_BROKER_LOCK:
        if _PROCESS_BROKER is None or _PROCESS_BROKER._closed:
            _PROCESS_BROKER = WindowsNamedPipeBroker(
                get_process_project_agent_session_registry(),
            )
        return _PROCESS_BROKER
