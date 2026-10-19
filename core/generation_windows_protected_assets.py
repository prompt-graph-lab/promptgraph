"""Disposable native staging and promoted-asset observations.

This adapter deliberately does not implement ContainedOutputStore or
DurableGenerationAssets. Their correlation/publication contracts stay separate.
No retries, overwrite, cleanup, transport or production call sites.
"""
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
import re
import threading
import uuid

from core import generation_windows_protected_storage as w
from core.comfy_output_containment import (
    AcceptedProtectedOutputBatch, ContainedOutputStore, ContainmentLimits,
    ProtectedOutputAcceptanceCharacterization, SUPPORTED_EXTENSIONS, CHUNK_BYTES,
    DownloadStream, ImageDownloadLookup, _validate_binding,
)
from core.comfy_prompt_request import is_owner_prepared_frozen_request
from core.comfy_remote_output_receipts import MAX_REMOTE_IMAGES

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


@dataclass(frozen=True)
class VerifiedProtectedImageObservation:
    """Exact remote-to-native byte observation; never publication authority."""
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    request_id: str = field(repr=False)
    request_index: int
    workflow_identity: str = field(repr=False)
    prompt_id: str = field(repr=False)
    remote_receipt_identity: str = field(repr=False)
    descriptor_identity: str = field(repr=False)
    image: ProtectedImageObservation = field(repr=False)


@dataclass(frozen=True)
class VerifiedProtectedImageBatchReceipt:
    """Owner-held all-images observation; never local-output or publication authority."""
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    request_id: str = field(repr=False)
    request_index: int
    workflow_identity: str = field(repr=False)
    prompt_id: str = field(repr=False)
    remote_receipt_identity: str = field(repr=False)
    identity: str
    observations: tuple[VerifiedProtectedImageObservation, ...] = field(repr=False)


class WindowsProtectedAssetsCharacterization:
    execution_available = False
    protected_storage_available = False

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
        # Names are unique only inside one purpose root; never key by filename alone.
        self._files, self._images = {}, {}
        self._used_bytes = 0
        self._closed = self._uncertain = False
        self._invalid = False
        self._revoking = False
        self._revoking_event = threading.Event()
        self._close_complete = threading.Event()
        self._close_complete.set()
        self._lock = threading.RLock()
        self._stream_envelope = None
        self._stream_bindings, self._stream_attempts, self._stream_images = {}, set(), {}
        self._stream_pending_images = {}
        self._stream_batch_attempts, self._stream_batches = set(), {}
        self._stream_batch_freshness = {}
        self._stream_batch_acceptance_attempts, self._stream_batch_acceptances = set(), {}
        self._stream_promotion_attempts, self._stream_promotions = set(), {}
        self._stream_request_bytes = {}
        self._stream_busy = False
        self._stream_batch_busy = False
        self._promotion_busy = False
        self._promotion_owner = self._promotion_thread = None
        self._capacity_busy = False
        self._capacity_lease = self._capacity_thread = None
        self._capacity_idle = threading.Event()
        self._capacity_idle.set()
        self._unobserved_files = []
        # Only the existing pure image verifier is shared; local-output receipt
        # custody remains with ContainedOutputStore.
        self._verifier = object.__new__(ContainedOutputStore)
        self._verifier._limits = limits

    def _check(self):
        with self._lock:
            if self._closed:
                w._fail("closed_observation")
            if self._revoking:
                w._fail("closing_observation")
            if self._invalid:
                w._fail("invalidated_observation")
            files = tuple(self._files.values())
            roots = tuple(self._roots.items())
        try:
            for _, root in roots:
                if not root.readiness()["acl_verified"]:
                    w._fail("protected_root_unavailable")
            for path, handle, identity, acl in files:
                root = next(r for _, r in roots if path.parent == r._path)
                w._revalidate(((path, False, handle, identity, acl[0]),), root._api, root._user)
                if _file_acl(handle, root) != acl:
                    w._fail("native_observation_changed")
        except BaseException:
            with self._lock:
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
            self._check()
            try:
                _, chunk = f.ReadFile(handle, min(CHUNK_BYTES, size - count))
            finally:
                self._check()
            if not chunk:
                w._fail("incomplete_image")
            chunks.append(chunk)
            count += len(chunk)
        if f.GetFileSize(handle) != size:
            w._fail("content_changed")
        return b"".join(chunks)

    def _observe(self, name, purpose, extension):
        self._check()
        key = (purpose, name)
        data = self._bytes(self._files[key])
        image_format, width, height = self._verifier._verify(io.BytesIO(data), extension)
        self._check()
        return ProtectedImageObservation(name, purpose, hashlib.sha256(data).hexdigest(),
                                         len(data), image_format, width, height)

    def create_image_for_characterization(self, purpose, data, *, extension="png",
                                          _promotion_owner=None, _admission_lease=None,
                                          _admission_context=None):
        # The admitted path owns a capacity lease which makes close wait for
        # its terminal accounting. Keep the native handle lifecycle lock short:
        # CREATE_NEW and immediate handle retention must be atomic with close,
        # but metadata reads, fault hooks and file I/O must not prevent close
        # from publishing revocation while this writer is suspended.
        if _admission_lease is not None:
            return self._create_admitted_image_for_characterization(
                purpose, data, extension, _admission_lease,
                promotion_owner=_promotion_owner, admission_context=_admission_context)
        with self._lock:
            promotion_write = (self._promotion_busy and self._promotion_owner is _promotion_owner
                               and self._promotion_thread == threading.get_ident())
            admitted_write = (self._capacity_busy and self._capacity_lease is _admission_lease
                              and self._capacity_thread == threading.get_ident()
                              and _admission_lease is not None)
            if (self._stream_busy or self._stream_batch_busy
                    or self._promotion_busy and not promotion_write
                    or _promotion_owner is not None and not promotion_write
                    or self._capacity_busy and not admitted_write
                    or _admission_lease is not None and not admitted_write):
                w._fail("storage_busy")
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            if purpose not in _PURPOSES or extension not in SUPPORTED_EXTENSIONS:
                w._fail("unsupported_asset_purpose_or_format")
            if (type(data) is not bytes or not 0 < len(data) <= min(self._limits.image_bytes, self._limits.request_bytes)
                    or self._used_bytes + len(data) > self._limits.aggregate_bytes
                    or len(self._files) + len(self._unobserved_files) >= self._limits.images):
                w._fail("storage_capacity")
            self._check()
            root = self._roots[purpose]
            # Reject unknown existing evidence without deleting or adopting it.
            inventory = {(stored_purpose, path.name)
                         for stored_purpose, _, path in self._inventory()}
            if inventory != set(self._files):
                self._uncertain = True
                w._fail("unexpected_existing_file")
            name = uuid.uuid4().hex + "." + extension
            key = (purpose, name)
            path = root._path / name
            _, c, f, _, _, _ = root._api
            handle = None
            try:
                if key in self._files and self._files[key][0] != path:
                    w._fail("exclusive_file_unavailable")
                handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                    c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(root._api, root._user),
                    c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
                # Retain the native handle immediately after CREATE_NEW. If
                # identity or ACL capture fails, the file remains accounted
                # evidence and cannot be silently replaced on a later attempt.
                self._unobserved_files.append((path, handle))
                self._used_bytes += len(data)  # reserve failed writes too; no retry
                # Capture BEFORE any callbacks/write. Keep the original handle until close.
                record = path, handle, w._identity(handle), _file_acl(handle, root)
                self._files[key] = record
                self._unobserved_files.remove((path, handle))
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
                self._images[key] = image
                return image
            except BaseException:
                self._uncertain = True
                # An unobserved file is intentionally retained with its handle
                # until owner close. No cleanup or retry is attempted.
                raise  # Retain incomplete/uncertain evidence; never remove it.

    def _create_admitted_image_for_characterization(
            self, purpose, data, extension, lease, *, promotion_owner=None,
            admission_context=None):
        if promotion_owner is not None or admission_context is not None:
            from core import generation_storage_admission as admission
            from core import generation_windows_protected_promotion as promotion

            if (promotion_owner is not None
                    and type(promotion_owner) is not promotion.ProtectedDurablePromotionCharacterization):
                w._fail("protected_promotion_binding_invalid")
            if admission_context is not None:
                if (type(admission_context) is not tuple or len(admission_context) != 3
                        or type(admission_context[0]) is not
                           admission.WindowsProtectedStorageAdmissionCharacterization):
                    w._fail("protected_promotion_capacity_mismatch")
        def assert_batch_leases():
            # Keep the established asset -> promotion -> admission order. The
            # checks are in-memory only and never enclose a native file call.
            if promotion_owner is not None:
                with promotion_owner._lock:
                    if (promotion_owner._closed or promotion_owner._revoking
                            or promotion_owner._uncertain or not promotion_owner._busy):
                        w._fail("protected_promotion_invalidated")
            if admission_context is not None:
                admission_owner, operation, write_admission = admission_context
                admission_owner.assert_write_admission_for_characterization(
                    operation, write_admission)

        with self._lock:
            admitted_write = (self._capacity_busy and self._capacity_lease is lease
                              and self._capacity_thread == threading.get_ident())
            promotion_write = (self._promotion_busy and self._promotion_owner is promotion_owner
                               and self._promotion_thread == threading.get_ident()
                               and promotion_owner is not None)
            if (not admitted_write or self._stream_busy or self._stream_batch_busy
                    or self._promotion_busy and not promotion_write
                    or promotion_owner is not None and not promotion_write):
                w._fail("storage_busy")
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            if purpose not in _PURPOSES or extension not in SUPPORTED_EXTENSIONS:
                w._fail("unsupported_asset_purpose_or_format")
            if (type(data) is not bytes or not 0 < len(data) <= min(self._limits.image_bytes, self._limits.request_bytes)
                    or self._used_bytes + len(data) > self._limits.aggregate_bytes
                    or len(self._files) + len(self._unobserved_files) >= self._limits.images):
                w._fail("storage_capacity")
            root = self._roots[purpose]

        # Root ACL/identity checks and directory inventory can touch the
        # filesystem. The capacity lease excludes other writes; keep those
        # observations outside the lifecycle lock so close can revoke promptly.
        self._check()
        assert_batch_leases()
        inventory = {(stored_purpose, path.name)
                     for stored_purpose, _, path in self._inventory()}
        assert_batch_leases()
        with self._lock:
            if inventory != set(self._files):
                self._uncertain = True
                w._fail("unexpected_existing_file")
            admitted_write = (self._capacity_busy and self._capacity_lease is lease
                              and self._capacity_thread == threading.get_ident())
            if (not admitted_write or self._revoking or self._closed
                    or self._invalid or self._uncertain):
                w._fail("storage_owner_unavailable")
            if (self._used_bytes + len(data) > self._limits.aggregate_bytes
                    or len(self._files) + len(self._unobserved_files) >= self._limits.images):
                w._fail("storage_capacity")
            name = uuid.uuid4().hex + "." + extension
            key = (purpose, name)
            path = root._path / name
            _, c, f, _, _, _ = root._api
            assert_batch_leases()
            handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(root._api, root._user),
                c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
            try:
                # close() cannot pass this lock until the newly created native
                # handle is visible in retained evidence.
                self._unobserved_files.append((path, handle))
                self._used_bytes += len(data)
            except BaseException:
                try:
                    handle.Close()
                except BaseException:
                    self._invalid = self._uncertain = True
                raise

        try:
            # These native reads can be slow. The retained unobserved handle
            # keeps the file owned while close waits on _capacity_idle.
            record = path, handle, w._identity(handle), _file_acl(handle, root)
            assert_batch_leases()
            with self._lock:
                self._files[key] = record
                self._unobserved_files.remove((path, handle))
            self._check()
            assert_batch_leases()
            self._fault("after_file_create")
            self._check()
            assert_batch_leases()
            for offset in range(0, len(data), CHUNK_BYTES):
                chunk = data[offset:offset + CHUNK_BYTES]
                self._check()
                assert_batch_leases()
                try:
                    _, written = f.WriteFile(handle, chunk)
                finally:
                    self._check()
                    assert_batch_leases()
                if written != len(chunk):
                    w._fail("incomplete_write")
                self._fault("after_file_write")
                self._check()
            f.FlushFileBuffers(handle)
            self._check()
            assert_batch_leases()
            self._fault("after_file_sync")
            self._check()
            image = self._observe(name, purpose, extension)
            if image.content_sha256 != hashlib.sha256(data).hexdigest():
                w._fail("content_changed")
            # Native identity/ACL/byte verification is complete before this
            # short publication lock. close() can revoke during verification;
            # the in-memory check below then refuses publication and retains
            # the file as uncertain evidence.
            self._check()
            with self._lock:
                if (self._closed or self._revoking or self._invalid or self._uncertain
                        or self._files.get(key) is not record):
                    w._fail("closing_observation" if self._revoking else "storage_owner_unavailable")
                self._images[key] = image
            return image
        except BaseException:
            with self._lock:
                self._uncertain = True
            # The native file and handle remain recorded for owner close; no
            # cleanup, overwrite or retry is attempted.
            raise

    def _begin_promotion_capacity_lease_for_characterization(self, promotion_owner):
        """Pin a complete admitted promotion batch against asset close/writers."""
        lease = object()
        with self._lock:
            if (self._closed or self._revoking or self._invalid or self._uncertain
                    or not self._writable):
                w._fail("storage_owner_unavailable")
            if (not self._promotion_busy or self._promotion_owner is not promotion_owner
                    or self._promotion_thread != threading.get_ident()
                    or self._capacity_busy or self._stream_busy or self._stream_batch_busy):
                w._fail("storage_busy")
            self._capacity_busy = True
            self._capacity_lease = lease
            self._capacity_thread = threading.get_ident()
            self._capacity_idle.clear()
        return lease

    def _finish_promotion_capacity_lease_for_characterization(self, promotion_owner, lease):
        with self._lock:
            if (self._capacity_busy and self._capacity_lease is lease
                    and self._capacity_thread == threading.get_ident()
                    and self._promotion_owner is promotion_owner):
                self._capacity_busy = False
                self._capacity_lease = self._capacity_thread = None
                self._promotion_busy = False
                self._promotion_owner = self._promotion_thread = None
                self._capacity_idle.set()

    def create_image_with_admission_for_characterization(
            self, admission_owner, operation_id, purpose, data, *, extension="png",
            characterization=False, disposable_opt_in=False):
        """Create one image only after its exact protected-root capacity is reserved.

        This offline seam uses this owner's existing CREATE_NEW writer. Its
        opaque capacity lease prevents a concurrent unaccounted writer from
        changing the inventory while admission is being reconciled.
        """
        from core import generation_storage_admission as admission

        if characterization is not True or disposable_opt_in is not True:
            w._fail("execution_unavailable")
        if type(admission_owner) is not admission.WindowsProtectedStorageAdmissionCharacterization:
            w._fail("storage_admission_owner_required")
        if (purpose not in _PURPOSES or extension not in SUPPORTED_EXTENSIONS
                or type(data) is not bytes
                or not 0 < len(data) <= min(self._limits.image_bytes, self._limits.request_bytes)):
            w._fail("invalid_asset_write_request")
        # The admission ledger must scan the actual root owners used by this
        # image writer; matching paths or freshly captured equivalents do not
        # establish shared accounting custody.
        if any(admission_owner._roots.get(name) is not self._roots.get(name)
               for name in _PURPOSES):
            w._fail("storage_root_owner_mismatch")

        lease = object()
        with self._lock:
            if self._closed:
                w._fail("closed_observation")
            if self._revoking:
                w._fail("closing_observation")
            if self._invalid:
                w._fail("invalidated_observation")
            if (self._stream_busy or self._stream_batch_busy or self._promotion_busy
                    or self._capacity_busy):
                w._fail("storage_busy")
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            self._capacity_busy = True
            self._capacity_lease = lease
            self._capacity_thread = threading.get_ident()
            self._capacity_idle.clear()

        operation = reservation = write_admission = None
        writer_started = False
        try:
            # Native root, identity and ACL observations can block. Publish a
            # revocable capacity lease first, then perform them outside the
            # Asset Owner lifecycle lock so close can signal revocation.
            self._check()
            with self._lock:
                if (self._capacity_lease is not lease or self._revoking or self._closed
                        or self._invalid or self._uncertain):
                    w._fail("storage_owner_unavailable")
            operation = admission_owner.begin_operation_for_characterization(operation_id)
            reservation = admission_owner.reserve_for_characterization(operation, {
                purpose: admission.CapacityEstimate(len(data), 1)})
            with self._lock:
                if (self._capacity_lease is not lease or self._revoking or self._closed
                        or self._invalid or self._uncertain):
                    w._fail("storage_owner_unavailable")
            write_admission = admission_owner.admit_write_for_characterization(
                operation, reservation)
            with self._lock:
                if (self._capacity_lease is not lease or self._revoking or self._closed
                        or self._invalid or self._uncertain):
                    w._fail("storage_owner_unavailable")
            writer_started = True
            image = self.create_image_for_characterization(
                purpose, data, extension=extension, _admission_lease=lease)
            if (type(image) is not ProtectedImageObservation or image.purpose != purpose
                    or image.byte_count != len(data)
                    or image.content_sha256 != hashlib.sha256(data).hexdigest()):
                w._fail("protected_asset_observation_mismatch")
            admission_owner.complete_asset_write_for_characterization(
                operation, write_admission, self, image)
            return image
        except BaseException:
            if write_admission is not None:
                try:
                    admission_owner.retain_uncertain_for_characterization(
                        operation, write_admission)
                except ValueError:
                    # A concurrent admission close may already have retained
                    # this exact live upper bound.
                    pass
            elif reservation is not None:
                try:
                    admission_owner.cancel_before_write_for_characterization(operation, reservation)
                except ValueError:
                    # Closing/invalidation conservatively retains the reservation.
                    pass
            if writer_started:
                with self._lock:
                    self._uncertain = True
            raise
        finally:
            with self._lock:
                if self._capacity_lease is lease:
                    self._capacity_busy = False
                    self._capacity_lease = self._capacity_thread = None
                    self._capacity_idle.set()

    def stage_remote_image_for_characterization(self, envelope, prepared, remote, descriptor, *,
                                               stream_provider, host_freshness):
        """One explicit offline stream into protected staging, with no receipts.

        The trusted original host supplies freshness, not a remote/job flag.
        External callbacks run outside the reservation lock. Every callback is
        surrounded by native checks; remote operations also by freshness checks.
        No other file creation is permitted during this owner's stream attempt.
        """
        return self._stage_remote_image_for_characterization(
            envelope, prepared, remote, descriptor, stream_provider=stream_provider,
            host_freshness=host_freshness)

    def stage_remote_image_with_admission_for_characterization(
            self, envelope, prepared, remote, descriptor, *, admission_owner,
            operation_id, stream_provider, host_freshness,
            characterization=False, disposable_opt_in=False):
        """Reserve bounded storage before the existing protected stream writer.

        This remains a disposable characterization seam. The original stream
        writer, exact host binding and native file custody stay authoritative.
        """
        from core import generation_storage_admission as admission

        if characterization is not True or disposable_opt_in is not True:
            w._fail("execution_unavailable")
        if type(admission_owner) is not admission.WindowsProtectedStorageAdmissionCharacterization:
            w._fail("storage_admission_owner_required")
        if any(admission_owner._roots.get(purpose) is not self._roots.get(purpose)
               for purpose in _PURPOSES):
            w._fail("storage_root_owner_mismatch")
        return self._stage_remote_image_for_characterization(
            envelope, prepared, remote, descriptor, stream_provider=stream_provider,
            host_freshness=host_freshness, admission_owner=admission_owner,
            operation_id=operation_id)

    def _stage_remote_image_for_characterization(
            self, envelope, prepared, remote, descriptor, *, stream_provider,
            host_freshness, admission_owner=None, operation_id=None):
        try:
            if not is_owner_prepared_frozen_request(prepared):
                raise ValueError()
            _validate_binding(envelope, prepared, remote)
            if (remote.execution_succeeded is not True
                    or not any(item is descriptor for item in remote.images)
                    or descriptor.image_format not in SUPPORTED_EXTENSIONS
                    or not callable(stream_provider) or not callable(host_freshness)):
                raise ValueError()
        except Exception:
            w._fail("remote_correlation_mismatch")
        fresh = lambda: host_freshness(envelope, remote)
        attempt = (prepared.request_id, descriptor.identity)
        admitted = admission_owner is not None
        capacity_lease = object() if admitted else None
        operation = reservation = write_admission = None
        published_image_key = None
        observed = None
        stream_freshness = None
        with self._lock:
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            if self._closed:
                w._fail("closed_observation")
            if self._revoking:
                w._fail("closing_observation")
            if self._invalid:
                w._fail("invalidated_observation")
            if self._stream_envelope is not None and self._stream_envelope is not envelope:
                w._fail("storage_owner_mismatch")
            previous = self._stream_bindings.get(prepared.request_id)
            if previous is not None and (previous[0] is not prepared or previous[1] is not remote):
                w._fail("remote_binding_conflict")
            if attempt in self._stream_attempts:
                w._fail("already_attempted")
            if (self._stream_busy or self._stream_batch_busy or self._promotion_busy
                    or self._capacity_busy):
                w._fail("storage_busy")
            if (len(self._stream_bindings) >= 100 and previous is None
                    or len(self._files) + len(self._unobserved_files) >= self._limits.images):
                w._fail("storage_capacity")
            self._stream_envelope = envelope
            self._stream_bindings[prepared.request_id] = (prepared, remote)
            self._stream_attempts.add(attempt)  # before freshness/provider/fault/reentry
            self._stream_busy = True
            if admitted:
                if self._capacity_busy:
                    self._stream_busy = False
                    w._fail("storage_busy")
                self._capacity_busy = True
                self._capacity_lease = capacity_lease
                self._capacity_thread = threading.get_ident()
                self._capacity_idle.clear()

        def check_capacity_admission():
            if write_admission is not None:
                admission_owner.assert_write_admission_for_characterization(
                    operation, write_admission)

        stream = None
        try:
            self._stream_fresh(fresh)
            self._check()
            if {(purpose, path.name) for purpose, _, path in self._inventory()} != set(self._files):
                with self._lock:
                    self._uncertain = True
                w._fail("unexpected_existing_file")
            if admitted:
                from core import generation_storage_admission as admission

                upper_bound = min(self._limits.image_bytes, self._limits.request_bytes,
                                  self._limits.aggregate_bytes)
                request_bytes = self._stream_request_bytes.get(prepared.request_id, 0)
                # Reserve the whole policy maximum, never a remote Content-Length.
                # Refuse before admission when this descriptor cannot fit that
                # conservative upper bound within current per-request/store limits.
                if (request_bytes + upper_bound > self._limits.request_bytes
                        or self._used_bytes + upper_bound > self._limits.aggregate_bytes
                        or len(self._files) + len(self._unobserved_files) >= self._limits.images):
                    w._fail("storage_capacity")
                operation = admission_owner.begin_operation_for_characterization(operation_id)
                reservation = admission_owner.reserve_for_characterization(operation, {
                    "temporary_containment": admission.CapacityEstimate(upper_bound, 1)})
                write_admission = admission_owner.admit_write_for_characterization(
                    operation, reservation)
                check_capacity_admission()
                with self._lock:
                    if (self._capacity_lease is not capacity_lease or self._revoking
                            or self._closed or self._invalid or self._uncertain):
                        w._fail("storage_owner_unavailable")

            root = self._roots["temporary_containment"]
            name = uuid.uuid4().hex + "." + descriptor.image_format
            key, path = ("temporary_containment", name), root._path / name
            _, c, f, _, _, _ = root._api
            # Allocation and earliest handle retention share the lifecycle lock
            # with close(). Once CreateFile succeeds, shutdown must see this
            # handle even if it wins before metadata capture or stream callbacks.
            self._stream_fresh(fresh)
            check_capacity_admission()
            self._check()
            with self._lock:
                if (self._closed or self._revoking or self._invalid or self._uncertain
                        or admitted and self._capacity_lease is not capacity_lease):
                    w._fail("storage_owner_unavailable")
                handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                    c.FILE_SHARE_READ | c.FILE_SHARE_WRITE, w._security_attributes(root._api, root._user),
                    c.CREATE_NEW, c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
                try:
                    # Even failed initial metadata capture retains the file and handle.
                    self._unobserved_files.append((path, handle))
                except BaseException:
                    try:
                        handle.Close()
                    except BaseException:
                        self._invalid = self._uncertain = True
                    raise
            try:
                record = path, handle, w._identity(handle), _file_acl(handle, root)
                self._check()
                with self._lock:
                    if (self._closed or self._revoking or self._invalid or self._uncertain
                            or admitted and self._capacity_lease is not capacity_lease):
                        w._fail("storage_owner_unavailable")
                    self._files[key] = record
                    self._unobserved_files.remove((path, handle))
            except BaseException:
                with self._lock:
                    self._invalid = self._uncertain = True
                raise
            self._stream_callback(self._fault, "after_file_create")
            check_capacity_admission()
            lookup = ImageDownloadLookup(prepared.prompt_url.removesuffix("/prompt"),
                descriptor.filename, descriptor.subfolder, descriptor.bucket, descriptor.identity)
            # Assign before the post-provider checks so stale/drift still closes it.
            self._stream_fresh(fresh)
            try:
                try:
                    stream = stream_provider(lookup)
                except Exception:
                    raise ValueError("download_interrupted") from None
            finally:
                self._stream_fresh(fresh)
                check_capacity_admission()
            if (type(stream) is not DownloadStream or type(stream.content_length) is not int
                    or not callable(stream.read) or not callable(stream.close)):
                w._fail("download_contract_invalid")
            length = stream.content_length
            request_bytes = self._stream_request_bytes.get(prepared.request_id, 0)
            if (not 0 < length <= self._limits.image_bytes
                    or request_bytes + length > self._limits.request_bytes
                    or self._used_bytes + length > self._limits.aggregate_bytes):
                w._fail("download_size_limit")
            # Reserve the entire declared body before writes, including partial
            # native writes that raise without reporting their actual byte count.
            self._used_bytes += length
            self._stream_request_bytes[prepared.request_id] = request_bytes + length
            count, digest = 0, hashlib.sha256()
            while True:
                limit = min(CHUNK_BYTES, length - count + 1)
                chunk = self._stream_remote(
                    fresh, stream.read, limit,
                    admission_check=check_capacity_admission if admitted else None)
                if type(chunk) is not bytes or len(chunk) > limit:
                    w._fail("download_contract_invalid")
                if not chunk:
                    if count != length:
                        w._fail("short_download")
                    break
                if count + len(chunk) > length:
                    w._fail("extra_download")
                self._check()
                check_capacity_admission()
                try:
                    _, written = f.WriteFile(handle, chunk)
                finally:
                    self._check()
                    check_capacity_admission()
                if written != len(chunk):
                    w._fail("incomplete_write")
                count += len(chunk)
                digest.update(chunk)
                self._stream_callback(self._fault, "after_file_write")
            closing, stream = stream, None
            self._stream_close(closing, fresh,
                               admission_check=check_capacity_admission if admitted else None)
            self._check()
            check_capacity_admission()
            try:
                f.FlushFileBuffers(handle)
            finally:
                self._check()
                check_capacity_admission()
            self._stream_callback(self._fault, "after_file_sync")
            check_capacity_admission()
            image = self._observe(name, "temporary_containment", descriptor.image_format)
            if image.byte_count != count or image.content_sha256 != digest.hexdigest():
                w._fail("content_changed")
            self._stream_fresh(fresh)
            check_capacity_admission()
            observed = VerifiedProtectedImageObservation(remote.job_id, remote.claim_id,
                remote.manifest_identity, remote.request_id, remote.request_index,
                remote.workflow_identity, remote.prompt_id, remote.identity, descriptor.identity, image)
            if admitted:
                stream_freshness = lambda: self._stream_fresh(fresh) is None
            # The image record is available to the admission owner's exact
            # native-byte verifier. The stream observation itself is published
            # only at the same two-owner ledger commit boundary.
            self._check()
            with self._lock:
                if (self._closed or self._revoking or self._invalid or self._uncertain
                        or admitted and self._capacity_lease is not capacity_lease):
                    w._fail("storage_owner_unavailable")
                self._images[key] = image
                if admitted:
                    self._stream_pending_images[attempt] = (observed, stream_freshness)
                published_image_key = key
            if admitted:
                admission_owner.complete_asset_write_for_characterization(
                    operation, write_admission, self, image,
                    stream_attempt=attempt, stream_observation=observed,
                    stream_freshness=stream_freshness)
            else:
                with self._lock:
                    if self._closed or self._revoking or self._invalid or self._uncertain:
                        w._fail("storage_owner_unavailable")
                    self._stream_images[attempt] = observed
            return observed
        except BaseException:
            if admitted:
                if write_admission is not None:
                    try:
                        admission_owner.retain_uncertain_for_characterization(
                            operation, write_admission)
                    except ValueError:
                        # The admission owner's close may already have retained
                        # this exact active upper bound.
                        pass
                    with self._lock:
                        self._uncertain = True
                elif reservation is not None:
                    try:
                        admission_owner.cancel_before_write_for_characterization(
                            operation, reservation)
                    except ValueError:
                        # A close/invalidation may have retained the unused
                        # reservation before this exact cancellation.
                        pass
                if published_image_key is not None:
                    with self._lock:
                        self._stream_pending_images.pop(attempt, None)
                        if attempt not in self._stream_images:
                            self._images.pop(published_image_key, None)
            else:
                with self._lock:
                    self._uncertain = True
            raise  # No deletion, overwrite, retry or receipt/publication event.
        finally:
            try:
                if type(stream) is DownloadStream and callable(stream.close):
                    # Always close acquired streams, including stale/unsafe ones.
                    # A failed pre-check must not suppress resource closure.
                    self._stream_close(stream, fresh)
            finally:
                with self._lock:
                    self._stream_busy = False
                    if admitted and self._capacity_lease is capacity_lease:
                        self._capacity_busy = False
                        self._capacity_lease = self._capacity_thread = None
                        self._capacity_idle.set()

    def _stream_callback(self, callback, *args):
        self._check()
        try:
            return callback(*args)
        finally:
            self._check()

    def _stream_fresh(self, callback):
        self._check()
        try:
            try:
                current = callback()
            except Exception:
                raise ValueError("host_freshness_lost") from None
        finally:
            self._check()
        if current is not True:
            w._fail("host_freshness_lost")

    def _stream_remote(self, fresh, callback, *args, admission_check=None):
        self._stream_fresh(fresh)
        if admission_check is not None:
            admission_check()
        try:
            try:
                return callback(*args)
            except Exception:
                raise ValueError("download_interrupted") from None
        finally:
            self._stream_fresh(fresh)
            if admission_check is not None:
                admission_check()

    def _stream_close(self, stream, fresh, *, admission_check=None):
        try:
            try:
                self._stream_fresh(fresh)
            finally:
                try:
                    stream.close()
                except Exception:
                    raise ValueError("download_close_failed") from None
        finally:
            self._stream_fresh(fresh)
            if admission_check is not None:
                admission_check()

    def commit_verified_remote_image_batch_for_characterization(
            self, envelope, prepared, remote, observations, *, host_freshness):
        """Commit one immutable all-descriptor receipt after final host/native checks.

        This is a private characterization receipt, not a LocalOutputReceipt.
        It is one-shot per exact host-prepared request and successful remote
        receipt. Any incomplete or uncertain first attempt retains evidence and
        makes this owner inspect-only; no image or batch is retried or cleaned.
        """
        try:
            if (not is_owner_prepared_frozen_request(prepared)
                    or type(observations) is not tuple
                    or len(observations) > MAX_REMOTE_IMAGES
                    or not callable(host_freshness)):
                raise ValueError()
            _validate_binding(envelope, prepared, remote)
            if remote.execution_succeeded is not True:
                raise ValueError()
        except Exception:
            w._fail("remote_correlation_mismatch")

        key = (prepared.request_id, remote.identity)
        with self._lock:
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            self._check()
            if self._stream_envelope is not envelope:
                w._fail("storage_owner_mismatch")
            binding = self._stream_bindings.get(prepared.request_id)
            if binding is None:
                w._fail("unknown_submission")
            if binding[0] is not prepared or binding[1] is not remote:
                w._fail("remote_binding_conflict")
            if key in self._stream_batch_attempts:
                # A repeat after a successful commit must not poison the original
                # receipt; a concurrent repeat likewise cannot disturb its owner.
                w._fail("already_attempted")
            if (self._stream_busy or self._stream_batch_busy or self._promotion_busy
                    or self._capacity_busy):
                w._fail("storage_busy")
            self._stream_batch_attempts.add(key)
            self._stream_batch_busy = True

        fresh = lambda: host_freshness(envelope, remote)
        try:
            descriptors = tuple(remote.images)
            expected_ids = tuple(item.identity for item in descriptors)
            expected_id_set = set(expected_ids)
            if (not descriptors or len(descriptors) > MAX_REMOTE_IMAGES
                    or len(set(expected_ids)) != len(expected_ids)
                    or len(observations) != len(descriptors)):
                w._fail("batch_observation_incomplete")
            supplied = {}
            for observation in observations:
                if type(observation) is not VerifiedProtectedImageObservation:
                    w._fail("batch_observation_invalid")
                descriptor_id = observation.descriptor_identity
                if descriptor_id in supplied or descriptor_id not in expected_id_set:
                    w._fail("batch_observation_ambiguous")
                supplied[descriptor_id] = observation

            canonical = tuple(supplied[descriptor_id] for descriptor_id in expected_ids)
            for descriptor, observation in zip(descriptors, canonical):
                expected_attempt = (prepared.request_id, descriptor.identity)
                with self._lock:
                    if (observation is not self._stream_images.get(expected_attempt)
                            or observation.job_id != remote.job_id
                            or observation.claim_id != remote.claim_id
                            or observation.manifest_identity != remote.manifest_identity
                            or observation.request_id != prepared.request_id
                            or observation.request_index != prepared.request_index
                            or observation.workflow_identity != prepared.workflow_identity
                            or observation.prompt_id != remote.prompt_id
                            or observation.remote_receipt_identity != remote.identity):
                        w._fail("batch_observation_substitution")

            # The host callback stays outside the owner lock. The native lock is
            # reacquired for byte/ACL checks, then freshness is observed again
            # outside the lock before the guarded receipt publication.
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                for observation in canonical:
                    self.inspect_verified_remote_image_for_characterization(observation)
                self._check()

            # Native rereads and Pillow decoding may take long enough for the
            # original Project/session custody to change. Keep this callback
            # outside the owner lock, then serialize the final owner check and
            # publication against close and other storage operations.
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                if key in self._stream_batches:
                    w._fail("already_attempted")
                payload = [
                    "promptgraph.protected-image-batch.v1", remote.job_id, remote.claim_id,
                    remote.manifest_identity, prepared.request_id, prepared.request_index,
                    prepared.workflow_identity, remote.prompt_id, remote.identity,
                    [[item.descriptor_identity, item.image.storage_identity, item.image.purpose,
                      item.image.content_sha256, item.image.byte_count, item.image.image_format,
                      item.image.width, item.image.height] for item in canonical],
                ]
                identity = hashlib.sha256(json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                receipt = VerifiedProtectedImageBatchReceipt(
                    remote.job_id, remote.claim_id, remote.manifest_identity,
                    prepared.request_id, prepared.request_index, prepared.workflow_identity,
                    remote.prompt_id, remote.identity, identity, canonical)
                self._stream_batches[key] = receipt
                self._stream_batch_freshness[key] = host_freshness
                return receipt
        except BaseException:
            with self._lock:
                self._uncertain = True
            raise
        finally:
            with self._lock:
                self._stream_batch_busy = False

    def inspect_verified_remote_image_batch_for_characterization(self, receipt):
        """Recheck exact owner custody and all current native bytes for a batch."""
        with self._lock:
            if (type(receipt) is not VerifiedProtectedImageBatchReceipt
                    or self._stream_batches.get((receipt.request_id, receipt.remote_receipt_identity))
                    is not receipt):
                w._fail("batch_owner_mismatch")
            if self._uncertain:
                w._fail("inspect_only_or_uncertain")
            self._check()
            for observation in receipt.observations:
                self.inspect_verified_remote_image_for_characterization(observation)
            return receipt

    def _accept_batch_for_containment_for_characterization(
            self, envelope, prepared, remote, batch_receipt, *, host_freshness,
            acceptance_owner, accepted):
        """Atomically accept one exact batch through this issuing native owner.

        The containment acceptance owner never treats a batch receipt as a
        legacy local receipt. It supplies the separate immutable result, which
        is published only while this original owner still verifies the native
        batch and exact original host-freshness callback.
        """
        try:
            if (type(acceptance_owner) is not ProtectedOutputAcceptanceCharacterization
                    or type(accepted) is not AcceptedProtectedOutputBatch
                    or not is_owner_prepared_frozen_request(prepared)):
                raise ValueError()
            _validate_binding(envelope, prepared, remote)
            if remote.execution_succeeded is not True:
                raise ValueError()
            if (accepted._protected_owner is not self or accepted._envelope is not envelope
                    or accepted._prepared is not prepared or accepted._remote is not remote
                    or accepted._batch_receipt is not batch_receipt
                    or accepted._host_freshness is not host_freshness):
                raise ValueError()
        except Exception:
            w._fail("protected_acceptance_binding_invalid")

        key = (prepared.request_id, remote.identity)
        with self._lock:
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            self._check()
            if self._stream_envelope is not envelope:
                w._fail("storage_owner_mismatch")
            binding = self._stream_bindings.get(prepared.request_id)
            if binding is None:
                w._fail("unknown_submission")
            if binding[0] is not prepared or binding[1] is not remote:
                w._fail("remote_binding_conflict")
            if self._stream_batches.get(key) is not batch_receipt:
                w._fail("batch_owner_mismatch")
            if self._stream_batch_freshness.get(key) is not host_freshness:
                w._fail("host_freshness_owner_mismatch")
            if key in self._stream_batch_acceptance_attempts:
                w._fail("acceptance_already_attempted")
            self._stream_batch_acceptance_attempts.add(key)

        fresh = lambda: host_freshness(envelope, remote)
        try:
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                self.inspect_verified_remote_image_batch_for_characterization(batch_receipt)
                self._check()

            # Native reread/decode can be slow; check the exact original host
            # callback again before the final lock-serialized acceptance.
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                if self._stream_batches.get(key) is not batch_receipt:
                    w._fail("batch_owner_mismatch")
                if key in self._stream_batch_acceptances:
                    w._fail("acceptance_already_attempted")
                # Publish both owners' records as one close/invalidation
                # boundary. The lock order is protected owner -> acceptance
                # owner; the acceptance owner uses an RLock so its validating
                # commit helper can be called while this lock remains held.
                with acceptance_owner._lock:
                    acceptance_owner._commit_from_protected_owner(accepted)
                    self._stream_batch_acceptances[key] = accepted
                return accepted
        except BaseException:
            with self._lock:
                self._uncertain = True
            raise

    def _inspect_accepted_batch_for_containment_for_characterization(
            self, envelope, prepared, remote, batch_receipt, *, host_freshness,
            acceptance_owner, accepted, freshness_check=None):
        """Revalidate an accepted view against current original-owner evidence."""
        if freshness_check is None:
            freshness_check = host_freshness
        if not callable(freshness_check):
            w._fail("protected_acceptance_binding_invalid")
        try:
            if (type(acceptance_owner) is not ProtectedOutputAcceptanceCharacterization
                    or type(accepted) is not AcceptedProtectedOutputBatch
                    or not is_owner_prepared_frozen_request(prepared)):
                raise ValueError()
            _validate_binding(envelope, prepared, remote)
            if remote.execution_succeeded is not True:
                raise ValueError()
            if (accepted._protected_owner is not self or accepted._envelope is not envelope
                    or accepted._prepared is not prepared or accepted._remote is not remote
                    or accepted._batch_receipt is not batch_receipt
                    or accepted._host_freshness is not host_freshness):
                raise ValueError()
        except Exception:
            w._fail("protected_acceptance_binding_invalid")

        key = (prepared.request_id, remote.identity)
        with self._lock:
            binding = self._stream_bindings.get(prepared.request_id)
            if (self._stream_envelope is not envelope
                    or binding is None or binding[0] is not prepared or binding[1] is not remote
                    or self._stream_batches.get(key) is not batch_receipt
                    or self._stream_batch_freshness.get(key) is not host_freshness
                    or self._stream_batch_acceptances.get(key) is not accepted):
                w._fail("protected_acceptance_owner_mismatch")
            self._check()

        fresh = lambda: freshness_check(envelope, remote)
        try:
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                self.inspect_verified_remote_image_batch_for_characterization(batch_receipt)
                self._check()
            self._stream_fresh(fresh)
            with self._lock:
                self._check()
                if self._stream_batch_acceptances.get(key) is not accepted:
                    w._fail("protected_acceptance_owner_mismatch")
                return accepted
        except BaseException:
            with self._lock:
                self._uncertain = True
            raise

    def inspect_verified_remote_image_for_characterization(self, observation):
        with self._lock:
            if (type(observation) is not VerifiedProtectedImageObservation
                    or self._stream_images.get((observation.request_id, observation.descriptor_identity))
                    is not observation):
                w._fail("image_owner_mismatch")
            if self._uncertain:
                w._fail("inspect_only_or_uncertain")
            self.inspect_image_for_characterization(observation.image)
            return observation

    def inspect_image_for_characterization(self, image):
        with self._lock:
            key = ((image.purpose, image.storage_identity)
                   if type(image) is ProtectedImageObservation else None)
            if (type(image) is not ProtectedImageObservation
                    or self._images.get(key) is not image):
                w._fail("image_owner_mismatch")
            try:
                extension = self._files[key][0].suffix[1:]
                if self._observe(image.storage_identity, image.purpose, extension) != image:
                    w._fail("content_changed")
                return image
            except BaseException:
                self._uncertain = True
                raise

    def _claim_protected_promotion_for_characterization(
            self, promotion_owner, acceptance_owner, accepted, key):
        """Pin the one original-owner promotion attempt before callbacks or I/O."""
        # Root/file observations touch native handles and must not hold the
        # lifecycle lock. The exact owner state is rechecked at the claim below.
        self._check()
        with self._lock:
            if self._closed:
                w._fail("closed_observation")
            if self._revoking:
                w._fail("closing_observation")
            if not self._writable or self._uncertain:
                w._fail("inspect_only_or_uncertain")
            with acceptance_owner._lock:
                if (acceptance_owner._protected_owner is not self
                        or acceptance_owner._receipt is not accepted
                        or acceptance_owner._closed or acceptance_owner._invalid
                        or acceptance_owner._uncertain or acceptance_owner._busy
                        or accepted._protected_owner is not self
                        or self._stream_batch_acceptances.get(key) is not accepted):
                    w._fail("protected_acceptance_owner_mismatch")
                if key in self._stream_promotion_attempts:
                    w._fail("promotion_already_attempted")
                self._stream_promotion_attempts.add(key)
                # Consume this batch's one attempt before checking capacity or
                # doing any copy. A transient failure cannot trigger a retry.
                if (self._promotion_busy or self._stream_busy or self._stream_batch_busy
                        or self._capacity_busy):
                    w._fail("storage_busy")
                self._promotion_busy = True
                self._promotion_owner = promotion_owner
                self._promotion_thread = threading.get_ident()

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
            if self._writable or self._uncertain:
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
            key = (purpose, path.name)
            if key not in self._files:
                handle = w._open(path, False, root._api)
                try:
                    self._files[key] = path, handle, w._identity(handle), _file_acl(handle, root)
                except BaseException:
                    handle.Close()
                    raise
            size = root._api[2].GetFileSize(self._files[key][1])
            total += size
            # Fresh inspection never recreates a writable budget. Still retain
            # the observed size even if decode/limits reject this inventory.
            self._used_bytes = max(self._used_bytes, total)
            if not 0 < size <= min(self._limits.image_bytes, self._limits.request_bytes):
                w._fail("image_byte_limit")
            if total > self._limits.aggregate_bytes:
                w._fail("storage_capacity")
        total = 0
        for purpose, root, path in paths:
            image = self._observe(path.name, purpose, path.suffix[1:])
            total += image.byte_count
            if total > self._limits.aggregate_bytes:
                w._fail("storage_capacity")
            images.append(image)
        self._check()
        # Publish only a complete successful inventory owned by this fresh capture.
        self._images = {(image.purpose, image.storage_identity): image for image in images}
        return tuple(images)

    def readiness(self):
        with self._lock:
            view = next(iter(self._roots.values())).readiness().copy()
            try:
                self._check()
                for image in self._images.values():
                    self.inspect_image_for_characterization(image)
                state = ("retained_uncertain" if self._uncertain else
                         "write_in_progress" if self._capacity_busy else "observed")
            except Exception:
                state = "closed" if self._closed else "unsafe_or_unavailable"
            view.update(purpose="protected_assets", asset_observation=state,
                        integrity="verified_bytes" if state == "observed" and self._images else "not_verified",
                        image_count=len(self._images), retained_file_count=len(self._files) + len(self._unobserved_files),
                        verified_batch_count=len(self._stream_batches),
                        accepted_batch_count=len(self._stream_batch_acceptances),
                        protected_promotion_count=len(self._stream_promotions),
                        retained_byte_reservation=self._used_bytes,
                        retry_allowed=False, fresh_reopen="inspect_only", cross_file_transaction=False)
            if state in ("closed", "unsafe_or_unavailable"):
                view.update(acl_verified=False, identity="unavailable", native_observation=state)
            return view

    def close(self):
        with self._lock:
            if self._closed:
                return
            if (self._capacity_busy
                    and self._capacity_thread == threading.get_ident()):
                # Refuse writer-thread reentry before consulting any other
                # owner, so a callback cannot wait on a lifecycle it owns.
                w._fail("storage_busy")
            promotion_owners = tuple({
                receipt._promotion_owner
                for receipt in self._stream_promotions.values()
            })
            # This is intentionally before _revoking or any wait. A callback
            # cannot close the protected owner while holding its own dispatch
            # lease; refuse reentry without changing lifecycle state.
            for owner in promotion_owners:
                owner._ensure_executor_event_revocation_allowed()
                owner._ensure_candidate_publication_revocation_allowed()
                owner._ensure_project_save_revocation_allowed()
            if self._revoking:
                wait_for_close = True
                wait_for_capacity = None
            else:
                wait_for_close = False
                self._revoking = True
                self._revoking_event.set()
                self._close_complete.clear()
                wait_for_capacity = self._capacity_idle if self._capacity_busy else None
        if wait_for_close:
            self._close_complete.wait()
            return
        try:
            if wait_for_capacity is not None:
                wait_for_capacity.wait()
            # Revoke event leases without holding native-owner locks. An event
            # already committed at the separate boundary completes first;
            # otherwise close prevents a later outputs_ready dispatch.
            for owner in promotion_owners:
                owner._revoke_executor_event_for_characterization()
                owner._revoke_candidate_publication_for_characterization()
                owner._revoke_project_save_for_characterization()
            with self._lock:
                self._closed = True
                failed = False
                for handle in ([r[1] for r in self._files.values()]
                               + [r[1] for r in self._unobserved_files]):
                    try:
                        handle.Close()
                    except BaseException:
                        failed = True
                for root in self._roots.values():
                    try:
                        root.close()
                    except BaseException:
                        failed = True
                if failed:
                    self._invalid = self._uncertain = True
                    w._fail("native_close_failed")
        finally:
            with self._lock:
                self._revoking = False
                self._revoking_event.clear()
            self._close_complete.set()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()
