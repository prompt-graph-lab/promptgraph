"""Disposable native Windows Journal characterization. No production caller.

Native handles pin the directory chain. Child files are atomically created with
protected owner-only DACLs. Bounded observations do not authenticate same-user
writers or establish power-loss durability. Interrupted evidence is retained.
"""
import os
import threading

from core import generation_ownership_journal as j
from core import generation_multi_request_journal as multi_journal
from core import generation_windows_protected_storage as w


_FACTORY = object()


class _BoundRoot:
    def __init__(self, owner):
        self._owner = owner
        self.key = owner._approved.key
        self.path = owner._approved.path
        self.identity = owner._approved.identity

    def check(self):
        self._owner._check()
        return self._owner._approved.check()


class _ProtectedWriter(j.OfflineJournalWriter):
    def __init__(self, owner, operation, fault):
        self._owner = owner
        super().__init__(_BoundRoot(owner), operation, characterization=True, fault=fault)

    def _create_exclusive_file(self, path, flags):
        # This is deliberately private to the disposable writer. No production
        # caller may supply a path/ACL/backend to the ordinary writer API.
        self.root.check()
        api = self._owner._native._api
        _, c, f, _, _, _ = api
        try:
            handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                c.FILE_SHARE_READ | c.FILE_SHARE_WRITE,
                w._security_attributes(api, self._owner._native._user), c.CREATE_NEW,
                c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
        except api[5].error:
            self._uncertain = True
            raise ValueError("exclusive_file_unavailable") from None
        detached = False
        try:
            acl = w._acl(handle, api, self._owner._native._user)
            identity = w._identity(handle)
            if identity != w._ordinary(path, directory=False):
                raise ValueError("file_identity_changed")
            self._owner._file_acls[identity] = acl
            self._owner._fault("after_file_create")
            self.root.check()
            import msvcrt
            # The CRT owns the detached native handle after this transfer.
            raw_handle = handle.Detach()
            detached = True
            try:
                return msvcrt.open_osfhandle(raw_handle, flags & (os.O_WRONLY | os.O_BINARY))
            except BaseException:
                api[0].CloseHandle(raw_handle)
                raise
        except BaseException:
            if not detached:
                handle.Close()
            self._uncertain = True
            raise

    def _check_file(self, path, identity):
        self.root.check()
        super()._check_file(path, identity)

    def append_for_characterization(self, observation):
        value = super().append_for_characterization(observation)
        self._check_file(self._owner._native._path / self.filename, value.file_identity)
        return value

    def _release_lock(self, path, identity):
        # No crash cleanup or stale-lock takeover, including failed post-ACK
        # checks. An acknowledged live writer may release its own verified lock.
        if self._uncertain:
            return
        self._check_file(path, identity)
        path.unlink()
        self.root.check()


class _ProtectedMultiRequestWriter(multi_journal.MultiRequestJournalWriter):
    """Native protected file creator for the separate multi-request schema."""

    def __init__(self, owner, operation, fault):
        self._owner = owner
        super().__init__(_BoundRoot(owner), operation, characterization=True, fault=fault)

    def _create_exclusive_file(self, path, flags):
        self.root.check()
        api = self._owner._native._api
        _, c, f, _, _, _ = api
        try:
            handle = f.CreateFile(str(path), c.GENERIC_READ | c.GENERIC_WRITE | c.READ_CONTROL,
                c.FILE_SHARE_READ | c.FILE_SHARE_WRITE,
                w._security_attributes(api, self._owner._native._user), c.CREATE_NEW,
                c.FILE_ATTRIBUTE_NORMAL | 0x00200000, None)
        except api[5].error:
            self._uncertain = True
            raise ValueError("exclusive_file_unavailable") from None
        detached = False
        try:
            acl = w._acl(handle, api, self._owner._native._user)
            identity = w._identity(handle)
            if identity != w._ordinary(path, directory=False):
                raise ValueError("file_identity_changed")
            self._owner._file_acls[identity] = acl
            self._owner._fault("after_file_create")
            self.root.check()
            import msvcrt
            raw_handle = handle.Detach()
            detached = True
            try:
                return msvcrt.open_osfhandle(raw_handle, flags & (os.O_WRONLY | os.O_BINARY))
            except BaseException:
                api[0].CloseHandle(raw_handle)
                raise
        except BaseException:
            if not detached:
                handle.Close()
            self._uncertain = True
            raise

    def _check_file(self, path, identity):
        self.root.check()
        super()._check_file(path, identity)

    def _release_lock(self, path, identity):
        self._check_file(path, identity)
        path.unlink()
        self.root.check()


class WindowsProtectedJournalCharacterization:
    execution_available = False

    @classmethod
    def provision_for_characterization(cls, disposable_scope, *, characterization=False,
                                      disposable_opt_in=False, fault=lambda boundary: None):
        native = w.WindowsProtectedRootCharacterization.provision_journal_for_characterization(
            disposable_scope, characterization=characterization, disposable_opt_in=disposable_opt_in)
        return cls._from_native(native, writable=True, fault=fault)

    @classmethod
    def reopen_for_characterization(cls, disposable_scope, selected_journal_directory, *,
                                   characterization=False, disposable_opt_in=False):
        # Independently selected host path; never a path read from Journal data.
        native = w.WindowsProtectedRootCharacterization.capture_for_characterization(
            disposable_scope, selected_journal_directory, "private_journal",
            characterization=characterization, disposable_opt_in=disposable_opt_in)
        return cls._from_native(native, writable=False, fault=lambda boundary: None)

    @classmethod
    def _from_native(cls, native, *, writable, fault):
        try:
            approved = j.ApprovedRoot.capture_for_characterization("private_journal",
                str(native._path), characterization=True)
            if approved.identity != native._identity:
                raise ValueError("root_identity_changed")
            owner = cls(native, approved, writable, fault, _factory=_FACTORY)
            owner._check()
            return owner
        except BaseException:
            native.close()
            raise

    def __init__(self, native, approved, writable, fault, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("host_storage_required")
        self._native, self._approved = native, approved
        self._writable, self._fault = writable, fault
        self._writer = None
        self._multi_request_writer = None
        self._closed = False
        self._uncertain = False
        self._lock = threading.RLock()
        self._file_acls = {}

    def _check(self):
        if self._closed or not self._native.readiness()["acl_verified"]:
            raise ValueError("protected_root_unavailable")
        self._approved.check()
        # Bounded direct children only. Reject unsafe files before reading any
        # contents, including retained lock/temp evidence and unknown entries.
        paths = []
        with os.scandir(self._approved.path) as entries:
            for entry in entries:
                if len(paths) == 64:
                    raise ValueError("journal_inventory_limit")
                paths.append(self._native._path / entry.name)
        observations = []
        try:
            for path in paths:
                handle = w._open(path, False, self._native._api)
                try:
                    identity = w._identity(handle)
                    acl = w._acl(handle, self._native._api, self._native._user)
                except BaseException:
                    handle.Close()
                    raise
                observations.append((path, False, handle, identity, acl))
                identity, acl = observations[-1][3:]
                if identity in self._file_acls and self._file_acls[identity] != acl:
                    raise ValueError("native_observation_changed")
            w._revalidate(observations, self._native._api, self._native._user)
            if not self._native.readiness()["acl_verified"]:
                raise ValueError("protected_root_unavailable")
            self._file_acls.update((item[3], item[4]) for item in observations)
        finally:
            for item in observations:
                item[2].Close()

    def _observe(self, operation):
        self._check()
        try:
            value = operation()
            self._fault("after_operation_before_ack")
        finally:
            # A read error also ends an observable operation. Protection drift
            # cannot be ignored merely because the Journal parse/read failed.
            self._check()
        return value

    def initialize_for_characterization(self, operation):
        with self._lock:
            if (not self._writable or self._writer is not None or self._multi_request_writer is not None
                    or self._uncertain):
                raise ValueError("writer_unavailable")
            self._writer = self._observe(lambda: _ProtectedWriter(self, operation, self._fault))

    def initialize_multi_request_for_characterization(self, operation):
        with self._lock:
            if (not self._writable or self._writer is not None or self._multi_request_writer is not None
                    or self._uncertain):
                raise ValueError("writer_unavailable")
            self._multi_request_writer = self._observe(
                lambda: _ProtectedMultiRequestWriter(self, operation, self._fault))

    def append_for_characterization(self, observation):
        with self._lock:
            if self._writer is None or self._uncertain:
                raise ValueError("writer_unavailable")
            try:
                return self._observe(lambda: self._writer.append_for_characterization(observation))
            except BaseException:
                self._uncertain = True
                self._writer._uncertain = True
                raise

    def append_multi_request_intent_for_characterization(self, expected_tip, request_index):
        with self._lock:
            writer = self._multi_request_writer
            if writer is None or self._uncertain:
                raise ValueError("writer_unavailable")
            try:
                return self._observe(lambda: writer.append_intent_for_characterization(expected_tip, request_index))
            except BaseException:
                self._uncertain = True
                writer._uncertain = True
                raise

    def append_multi_request_outcome_for_characterization(self, expected_tip, outcome, prompt_id=None):
        with self._lock:
            writer = self._multi_request_writer
            if writer is None or self._uncertain:
                raise ValueError("writer_unavailable")
            try:
                return self._observe(lambda: writer.append_submission_outcome_for_characterization(
                    expected_tip, outcome, prompt_id))
            except BaseException:
                self._uncertain = True
                writer._uncertain = True
                raise

    def append_multi_request_settlement_for_characterization(self, expected_tip, settlement):
        with self._lock:
            writer = self._multi_request_writer
            if writer is None or self._uncertain:
                raise ValueError("writer_unavailable")
            try:
                return self._observe(lambda: writer.append_settlement_for_characterization(
                    expected_tip, settlement))
            except BaseException:
                self._uncertain = True
                writer._uncertain = True
                raise

    def reopen_journal_for_characterization(self, filename, **expected_tip):
        with self._lock:
            return self._observe(lambda: j.reopen_journal(_BoundRoot(self), filename, **expected_tip))

    def reopen_multi_request_journal_for_characterization(self, filename, **expected_tip):
        with self._lock:
            return self._observe(lambda: multi_journal.reopen_multi_request_journal(
                _BoundRoot(self), filename, **expected_tip))

    def inspect_inventory_for_characterization(self):
        with self._lock:
            return self._observe(lambda: j.inspect_inventory(_BoundRoot(self)))

    def inspect_human_recovery_for_characterization(self, filename, *, selected_project_root=None,
                                                   selected_relative_path="project.json", **expected_tip):
        # The existing Recovery owner enforces exact ApprovedRoot types. Its
        # private case never escapes this checked operation; return projection.
        from ui.agent_generation_human_recovery import HumanRecoveryReviewOwner
        with self._lock:
            def inspect():
                recovery = HumanRecoveryReviewOwner(self._approved, filename,
                    selected_project_root, selected_relative_path, characterization=True, **expected_tip)
                return recovery.projection_for_characterization()
            return self._observe(inspect)

    def readiness(self):
        with self._lock:
            view = self._native.readiness()
            try:
                self._check()
                state = "uncertain" if self._uncertain else "protected_observation"
            except Exception:
                state = "closed" if self._closed else "unsafe_or_unavailable"
            return {**view, "journal_lifecycle": state, "writer_retry_allowed": False,
                    "trusted_latest_revision": "unavailable", "original_producer": "observation_only",
                    "digest_chain": "separate_inspection_required"}

    def inspect_trust_evidence_for_characterization(self, filename, *,
            selected_project_root=None, selected_relative_path="project.json", asset_roots=(),
            expected_revision=None, expected_digest=None, max_entries=64,
            max_file_bytes=32 * 1024 * 1024):
        """Private native observations composed into diagnostics, never authority."""
        from ui import agent_generation_trust_evidence as evidence
        expected = evidence._expected_tip(expected_revision, expected_digest)
        with self._lock:
            def inspect():
                writer = self._writer
                producer = None
                if writer is not None and not self._uncertain and not writer._uncertain:
                    producer = (writer.operation, writer._revision, writer._digest, writer._file_identity)
                return evidence._inspect(self._approved, filename, selected_project_root,
                    selected_relative_path, asset_roots, max_entries, max_file_bytes,
                    expected, native=True, producer=producer)
            try:
                # Keep the existing before/after ACL and handle checks. A failed
                # post-read check withholds the entire otherwise readable case.
                return self._observe(inspect)
            except (ValueError, OSError):
                view = evidence._empty("closed" if self._closed else "unsafe_or_unavailable", expected)
                view["reasons"].append("protected_observation_unavailable")
                return evidence._bounded(view)

    def close(self):
        with self._lock:
            self._closed = True
            self._native.close()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()
