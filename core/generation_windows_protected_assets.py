"""Disposable native staging/durable image observations; no receipt authority.

This adapter deliberately does not implement ContainedOutputStore or
DurableGenerationAssets. Their correlation/publication contracts stay separate.
No retries, overwrite, cleanup, transport or production call sites.
"""
from dataclasses import dataclass, field
import hashlib
import io
import os
import re
import threading
import uuid

from core import generation_windows_protected_storage as w
from core.comfy_output_containment import (
    ContainedOutputStore, ContainmentLimits, SUPPORTED_EXTENSIONS, CHUNK_BYTES,
)

_FACTORY = object()
_PURPOSES = ("temporary_containment", "promoted_assets")


def _file_acl(handle, root):
    policy = w._acl(handle, root._api, root._user)
    security = root._api[3]
    descriptor = security.GetSecurityInfo(handle, security.SE_FILE_OBJECT,
        security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    # Retain the complete native owner/DACL descriptor, including ACL revision
    # and control bytes. Equal effective owner permissions alone are insufficient.
    return policy, bytes(descriptor)


@dataclass(frozen=True)
class ProtectedImageObservation:
    """Private byte observation, never a local output/publication receipt."""
    storage_identity: str = field(repr=False)
    purpose: str
    content_sha256: str = field(repr=False)
    byte_count: int
    image_format: str
    width: int
    height: int


class WindowsProtectedAssetsCharacterization:
    execution_available = False

    @classmethod
    def provision_for_characterization(cls, disposable_scope, *, characterization=False,
                                      disposable_opt_in=False, limits=ContainmentLimits(),
                                      fault=lambda boundary: None):
        return cls._capture(disposable_scope, None, characterization, disposable_opt_in, limits, fault)

    @classmethod
    def reopen_for_characterization(cls, disposable_scope, purpose_paths, *, characterization=False,
                                   disposable_opt_in=False, limits=ContainmentLimits()):
        # Host paths only. No Journal, receipt or remote metadata is consulted.
        return cls._capture(disposable_scope, purpose_paths, characterization, disposable_opt_in,
                            limits, lambda boundary: None)

    @classmethod
    def _capture(cls, scope, paths, characterization, opt_in, limits, fault):
        if characterization is not True or opt_in is not True:
            w._fail("execution_unavailable")
        defaults = ContainmentLimits()
        if (type(limits) is not ContainmentLimits or any(type(v) is not int or not 0 < v <= getattr(defaults, k)
                for k, v in vars(limits).items())
                or not limits.image_bytes <= limits.request_bytes <= limits.aggregate_bytes):
            w._fail("invalid_storage_limits")
        if paths is not None:
            if type(paths) is not dict or set(paths) != set(_PURPOSES):
                w._fail("explicit_asset_purposes_required")
            approved_scope = w._path(scope)
            selected = [w._path(paths[p]) for p in _PURPOSES]
            if any(p == approved_scope or not p.is_relative_to(approved_scope) for p in selected):
                w._fail("unapproved_root")
            if selected[0].is_relative_to(selected[1]) or selected[1].is_relative_to(selected[0]):
                w._fail("purpose_overlap")
        roots = {}
        try:
            for purpose in _PURPOSES:
                roots[purpose] = (
                    w.WindowsProtectedRootCharacterization.provision_asset_for_characterization(
                        scope, purpose, characterization=True, disposable_opt_in=True)
                    if paths is None else
                    w.WindowsProtectedRootCharacterization.capture_for_characterization(
                        scope, paths[purpose], purpose, characterization=True, disposable_opt_in=True))
            if len({r._identity for r in roots.values()}) != 2:
                w._fail("purpose_alias")
            owner = cls(roots, limits, paths is None, fault, _factory=_FACTORY)
            owner._check()
            return owner
        except BaseException:
            for root in roots.values():
                root.close()
            raise  # Any successfully created evidence remains on disk.

    def __init__(self, roots, limits, writable, fault, *, _factory=None):
        if _factory is not _FACTORY:
            w._fail("host_storage_required")
        self._roots, self._limits, self._writable, self._fault = roots, limits, writable, fault
        self._files, self._images = {}, {}
        self._used_bytes = 0
        self._closed = self._uncertain = False
        self._invalid = False
        self._lock = threading.RLock()
        # Only the existing pure image verifier is shared; no staging receipt exists.
        self._verifier = object.__new__(ContainedOutputStore)
        self._verifier._limits = limits

    def _check(self):
        if self._closed:
            w._fail("closed_observation")
        if self._invalid:
            w._fail("invalidated_observation")
        try:
            for root in self._roots.values():
                if not root.readiness()["acl_verified"]:
                    w._fail("protected_root_unavailable")
            for path, handle, identity, acl in self._files.values():
                root = self._roots[next(p for p, r in self._roots.items() if path.parent == r._path)]
                w._revalidate(((path, False, handle, identity, acl[0]),), root._api, root._user)
                if _file_acl(handle, root) != acl:
                    w._fail("native_observation_changed")
        except BaseException:
            self._invalid = self._uncertain = True
            raise

    def _bytes(self, record):
        path, handle, _, _ = record
        root = next(r for r in self._roots.values() if path.parent == r._path)
        _, c, f, _, _, _ = root._api
        size = f.GetFileSize(handle)
        if not 0 < size <= min(self._limits.image_bytes, self._limits.request_bytes):
            w._fail("image_byte_limit")
        f.SetFilePointer(handle, 0, c.FILE_BEGIN)
        chunks, count = [], 0
        while count < size:
            _, chunk = f.ReadFile(handle, min(CHUNK_BYTES, size - count))
            if not chunk:
                w._fail("incomplete_image")
            chunks.append(chunk)
            count += len(chunk)
        if f.GetFileSize(handle) != size:
            w._fail("content_changed")
        return b"".join(chunks)

    def _observe(self, name, purpose, extension):
        self._check()
        data = self._bytes(self._files[name])
        image_format, width, height = self._verifier._verify(io.BytesIO(data), extension)
        self._check()
        return ProtectedImageObservation(name, purpose, hashlib.sha256(data).hexdigest(),
                                         len(data), image_format, width, height)

    def create_image_for_characterization(self, purpose, data, *, extension="png"):
        with self._lock:
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            if purpose not in _PURPOSES or extension not in SUPPORTED_EXTENSIONS:
                w._fail("unsupported_asset_purpose_or_format")
            if (type(data) is not bytes or not 0 < len(data) <= min(self._limits.image_bytes, self._limits.request_bytes)
                    or self._used_bytes + len(data) > self._limits.aggregate_bytes
                    or len(self._files) >= self._limits.images):
                w._fail("storage_capacity")
            self._check()
            root = self._roots[purpose]
            # Reject unknown existing evidence without deleting or adopting it.
            if set(path.name for _, _, path in self._inventory()) != set(self._files):
                self._uncertain = True
                w._fail("unexpected_existing_file")
            name = uuid.uuid4().hex + "." + extension
            path = root._path / name
            _, c, f, _, _, _ = root._api
            handle = None
            try:
                if name in self._files and self._files[name][0] != path:
                    w._fail("exclusive_file_unavailable")
                handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                    c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(root._api, root._user),
                    c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
                # Capture BEFORE any callbacks/write. Keep the original handle until close.
                record = path, handle, w._identity(handle), _file_acl(handle, root)
                self._files[name] = record
                self._used_bytes += len(data)  # reserve failed writes too; no retry
                self._fault("after_file_create")
                self._check()
                for offset in range(0, len(data), CHUNK_BYTES):
                    chunk = data[offset:offset + CHUNK_BYTES]
                    _, written = f.WriteFile(handle, chunk)
                    if written != len(chunk):
                        w._fail("incomplete_write")
                    self._fault("after_file_write")
                    self._check()
                f.FlushFileBuffers(handle)
                self._fault("after_file_sync")
                image = self._observe(name, purpose, extension)
                if image.content_sha256 != hashlib.sha256(data).hexdigest():
                    w._fail("content_changed")
                self._images[name] = image
                return image
            except BaseException:
                self._uncertain = True
                if handle is not None and name not in self._files:
                    handle.Close()
                raise  # Retain incomplete/uncertain evidence; never remove it.

    def inspect_image_for_characterization(self, image):
        with self._lock:
            if (type(image) is not ProtectedImageObservation
                    or self._images.get(image.storage_identity) is not image):
                w._fail("image_owner_mismatch")
            try:
                extension = self._files[image.storage_identity][0].suffix[1:]
                if self._observe(image.storage_identity, image.purpose, extension) != image:
                    w._fail("content_changed")
                return image
            except BaseException:
                self._uncertain = True
                raise

    def _inventory(self):
        paths = []
        for purpose, root in self._roots.items():
            with os.scandir(root._path) as entries:
                for entry in entries:
                    if len(paths) >= self._limits.images:
                        w._fail("storage_capacity")
                    paths.append((purpose, root, root._path / entry.name))
        return paths

    def inspect_existing_for_characterization(self):
        """Fresh inspect-only snapshot; cannot restore earlier file observations."""
        with self._lock:
            if self._writable:
                w._fail("fresh_inspect_only_owner_required")
            self._check()
            try:
                return self._inspect_existing()
            except BaseException:
                self._uncertain = True
                raise

    def _inspect_existing(self):
        paths = self._inventory()
        total, images = 0, []
        # Observe all child identities/ACLs before decoding any file.
        for purpose, root, path in paths:
            if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|jpeg|webp|bmp)", path.name):
                w._fail("unexpected_existing_file")
            name = purpose + ":" + path.name
            if name not in self._files:
                handle = w._open(path, False, root._api)
                try:
                    self._files[name] = path, handle, w._identity(handle), _file_acl(handle, root)
                except BaseException:
                    handle.Close()
                    raise
            size = root._api[2].GetFileSize(self._files[name][1])
            if not 0 < size <= min(self._limits.image_bytes, self._limits.request_bytes):
                w._fail("image_byte_limit")
            total += size
            if total > self._limits.aggregate_bytes:
                w._fail("storage_capacity")
        total = 0
        for purpose, root, path in paths:
            name = purpose + ":" + path.name
            image = self._observe(name, purpose, path.suffix[1:])
            total += image.byte_count
            if total > self._limits.aggregate_bytes:
                w._fail("storage_capacity")
            images.append(image)
        self._check()
        return tuple(images)

    def readiness(self):
        with self._lock:
            view = next(iter(self._roots.values())).readiness().copy()
            try:
                self._check()
                for image in self._images.values():
                    self.inspect_image_for_characterization(image)
                state = "retained_uncertain" if self._uncertain else "observed"
            except Exception:
                state = "closed" if self._closed else "unsafe_or_unavailable"
            view.update(purpose="protected_assets", asset_observation=state,
                        integrity="verified_bytes" if state == "observed" and self._images else "not_verified",
                        image_count=len(self._images), retained_file_count=len(self._files),
                        retry_allowed=False, fresh_reopen="inspect_only", cross_file_transaction=False)
            if state in ("closed", "unsafe_or_unavailable"):
                view.update(acl_verified=False, identity="unavailable", native_observation=state)
            return view

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                for _, handle, _, _ in self._files.values():
                    handle.Close()
                for root in self._roots.values():
                    root.close()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()
