"""Offline, original-host-owned protected-storage admission characterization.

This owner combines explicit native root observations with process-local
accounting. A reservation is not an OS quota, writer capability, execution
authorization, durable Journal guarantee, or cross-process lock.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import threading

from core import generation_ownership_journal as journal
from core import generation_multi_request_journal as multi_journal
from core import generation_windows_protected_storage as windows
from core.comfy_output_containment import ContainmentLimits


_FACTORY = object()
_PURPOSES = ("private_journal", "temporary_containment", "retained_uncertain",
             "promoted_assets", "selected_project_json")
_WRITABLE = _PURPOSES[:-1]
_JOURNAL_BYTES = journal.MAX_BYTES
_JOURNAL_REPLACEMENT_LIVE_BYTES = multi_journal.MAX_LIVE_OPERATION_BYTES
_ASSET_BYTES = ContainmentLimits().aggregate_bytes
_MAX_OPERATION_BYTES = journal.MAX_OPERATION_BYTES + _JOURNAL_BYTES
_MAX_INVENTORY_ENTRIES = 256
_MAX_OPERATION_ENTRIES = 400
_MAX_ASSET_ENTRIES = 16
_MAX_JOURNAL_ENTRIES = 300
_MAX_ROOT_FILE_BYTES = _MAX_OPERATION_BYTES
_MAX_PROCESS_ACCOUNTING_SCOPES = 128
_MAX_PROFILE_A_HOST_LIFECYCLES = 1

# Successful captures leave a process-local claim until process exit, even
# after close/invalidation, so uncertain reservations cannot be forgotten by
# constructing another ledger over the same writable roots.
_PROCESS_ACCOUNTING_SCOPE_LOCK = threading.Lock()
_PROCESS_ACCOUNTING_SCOPES = set()
_JOURNAL_REPLACEMENT_ISSUER = object()


def _fail(code):
    raise ValueError(code)


def _validate_profile_a_root_set_shape(purpose_roots):
    """Pure shape gate for the four independently captured writable owners."""
    from core.generation_windows_protected_storage import WindowsProtectedRootCharacterization

    if type(purpose_roots) is not dict or set(purpose_roots) != set(_WRITABLE):
        _fail("profile_a_four_roots_required")
    roots = dict(purpose_roots)
    owners, identities, paths = set(), set(), []
    for purpose in _WRITABLE:
        root = roots[purpose]
        if (type(root) is not WindowsProtectedRootCharacterization
                or root._purpose != purpose or root._closed is not False
                or not isinstance(root._path, Path)):
            _fail("profile_a_root_purpose_mismatch")
        if id(root) in owners:
            _fail("profile_a_root_alias")
        owners.add(id(root))
        identity = root._identity
        if identity is not None and (type(identity) is not tuple or len(identity) != 2
                                     or any(type(value) is not int or value < 0
                                            for value in identity)):
            _fail("profile_a_root_identity_invalid")
        if type(identity) is tuple and identity in identities:
            _fail("profile_a_root_alias")
        if identity is not None:
            identities.add(identity)
        path = root._path
        if any(path == prior or path.is_relative_to(prior) or prior.is_relative_to(path)
               for prior in paths):
            _fail("profile_a_root_overlap")
        paths.append(path)
    return roots


@dataclass(frozen=True)
class CapacityEstimate:
    """Host-supplied upper bound; it is not an observed file measurement."""
    byte_upper_bound: int
    entry_upper_bound: int


@dataclass(frozen=True)
class _JournalReplacementBinding:
    admission_owner: object = field(repr=False, compare=False)
    journal_owner: object = field(repr=False, compare=False)
    root_owner: object = field(repr=False, compare=False)
    writer: object = field(repr=False, compare=False)
    schema: str
    operation_id: str
    filename: str
    previous_revision: int
    previous_digest: str = field(repr=False)
    previous_file_identity: tuple | None = field(repr=False)
    previous_native_row: tuple | None = field(repr=False)
    previous_acknowledgement: object = field(repr=False, compare=False)
    prior_inventory: tuple = field(repr=False)
    _issuer: object = field(repr=False, compare=False)
    journal_lease: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _JournalReplacementCompletion:
    binding: _JournalReplacementBinding = field(repr=False, compare=False)
    acknowledgement: object = field(repr=False, compare=False)
    file_identity: tuple = field(repr=False)
    native_row: tuple = field(repr=False)
    _issuer: object = field(repr=False, compare=False)


def _freeze_inventory(inventory):
    if type(inventory) is not dict or set(inventory) != set(_WRITABLE):
        return None
    frozen = []
    for purpose in _WRITABLE:
        entries = inventory[purpose]
        if type(entries) is not dict:
            return None
        frozen.append((purpose, tuple(sorted(entries.items()))))
    return tuple(frozen)


@dataclass(frozen=True)
class ProtectedStorageCapacityLimits:
    """Policy ceilings; they do not claim that corresponding disk space exists."""
    journal_bytes: int = _JOURNAL_BYTES
    shared_temporary_and_promoted_bytes: int = _ASSET_BYTES
    retained_uncertain_bytes: int = _ASSET_BYTES
    journal_entries: int = _MAX_JOURNAL_ENTRIES
    shared_temporary_and_promoted_entries: int = _MAX_ASSET_ENTRIES
    retained_uncertain_entries: int = _MAX_INVENTORY_ENTRIES

    def validate(self):
        values = (self.journal_bytes, self.shared_temporary_and_promoted_bytes,
                  self.retained_uncertain_bytes, self.journal_entries,
                  self.shared_temporary_and_promoted_entries,
                  self.retained_uncertain_entries)
        maxima = (_JOURNAL_BYTES, _ASSET_BYTES, _ASSET_BYTES,
                  _MAX_JOURNAL_ENTRIES, _MAX_ASSET_ENTRIES, _MAX_INVENTORY_ENTRIES)
        if any(type(value) is not int or not 0 < value <= maximum
               for value, maximum in zip(values, maxima)):
            _fail("invalid_capacity_limits")


class _Opaque:
    def __init__(self, factory):
        if factory is not _FACTORY:
            _fail("host_storage_required")


def _limit_for(purpose, limits, *, entries=False):
    if purpose == "private_journal":
        return limits.journal_entries if entries else limits.journal_bytes
    if purpose in ("temporary_containment", "promoted_assets"):
        return (limits.shared_temporary_and_promoted_entries if entries
                else limits.shared_temporary_and_promoted_bytes)
    if purpose == "retained_uncertain":
        return limits.retained_uncertain_entries if entries else limits.retained_uncertain_bytes
    return 0


def _fits(current, amount, limit):
    # Subtraction form avoids relying on a potentially overflowing addition in
    # ports whose integer representation is bounded.
    return type(amount) is int and amount >= 0 and current <= limit and amount <= limit - current


class _CapacityLedger:
    """Portable accounting kernel. Tokens are exact object identities."""

    def __init__(self, limits, *, owner_identity=None):
        if type(limits) is not ProtectedStorageCapacityLimits:
            _fail("invalid_capacity_limits")
        limits.validate()
        self._limits = limits
        self._owner_identity = owner_identity
        self._lock = threading.RLock()
        self._closed = False
        self._invalid = False
        self._operation_ids = set()
        self._operations = {}
        self._reservations = {}
        self._active_write = None
        self._reserved = {p: [0, 0] for p in _WRITABLE}
        self._observed = {p: [0, 0] for p in _WRITABLE}
        self._uncertain = {p: [0, 0] for p in _WRITABLE}
        self._inventory = None
        self._available_free_bytes = None
        self._journal_files = {}
        self._journal_operation_writers = {}

    def set_initial_inventory(self, inventory, available_free_bytes=None):
        with self._lock:
            if self._inventory is not None or self._closed:
                _fail("storage_owner_unavailable")
            # Existing files have no current operation custody. Count them as
            # retained uncertainty instead of silently adopting them.
            for purpose in _WRITABLE:
                entries = inventory.get(purpose, {})
                total = sum(row[1] for row in entries.values())
                if (len(entries) > _MAX_INVENTORY_ENTRIES
                        or total > _MAX_ROOT_FILE_BYTES
                        or not _fits(0, total, _limit_for(purpose, self._limits))
                        or not _fits(0, len(entries), _limit_for(purpose, self._limits, entries=True))):
                    _fail("retained_inventory_over_capacity")
                self._uncertain[purpose] = [total, len(entries)]
            shared_asset_bytes = sum(self._uncertain[p][0]
                                     for p in ("temporary_containment", "promoted_assets"))
            shared_asset_entries = sum(self._uncertain[p][1]
                                       for p in ("temporary_containment", "promoted_assets"))
            if (shared_asset_bytes > self._limits.shared_temporary_and_promoted_bytes
                    or shared_asset_entries > self._limits.shared_temporary_and_promoted_entries):
                _fail("retained_inventory_over_capacity")
            self._available_free_bytes = self._validate_free_bytes(
                available_free_bytes if available_free_bytes is not None else
                self._limits.journal_bytes + self._limits.shared_temporary_and_promoted_bytes
                + self._limits.retained_uncertain_bytes)
            self._inventory = inventory

    def begin_operation(self, operation_id):
        if type(operation_id) is not str or not 1 <= len(operation_id) <= 128:
            _fail("invalid_operation_identity")
        with self._lock:
            self._require_live()
            if operation_id in self._operation_ids:
                _fail("operation_identity_reused")
            self._operation_ids.add(operation_id)
            operation = _Opaque(_FACTORY)
            self._operations[operation] = {"state": "open", "operation_id": operation_id}
            return operation

    def reserve(self, operation, estimates):
        normalized = self._validate_estimates(estimates)
        with self._lock:
            self._require_live()
            state = self._operations.get(operation)
            if state is None or state["state"] != "open":
                _fail("operation_unavailable")
            projected = {p: self._reserved[p][0] + self._observed[p][0] + self._uncertain[p][0]
                         for p in _WRITABLE}
            projected_entries = {p: self._reserved[p][1] + self._observed[p][1] + self._uncertain[p][1]
                                 for p in _WRITABLE}
            for purpose, (byte_count, entry_count) in normalized.items():
                if not _fits(projected[purpose], byte_count, _limit_for(purpose, self._limits)):
                    _fail("storage_capacity_exceeded")
                if not _fits(projected_entries[purpose], entry_count,
                             _limit_for(purpose, self._limits, entries=True)):
                    _fail("storage_entry_capacity_exceeded")
                projected[purpose] += byte_count
                projected_entries[purpose] += entry_count
            new_reservation_bytes = sum(value[0] for value in normalized.values())
            unsettled_bytes = sum(row[0] for row in self._reserved.values())
            retained_upper_bound = sum(row[0] for row in self._uncertain.values())
            if (unsettled_bytes > self._available_free_bytes
                    or retained_upper_bound > self._available_free_bytes - unsettled_bytes
                    or new_reservation_bytes > self._available_free_bytes
                        - unsettled_bytes - retained_upper_bound):
                _fail("observed_free_capacity_insufficient")
            # The existing staging/promoted contract shares one aggregate cap.
            asset_current = sum(projected[p] for p in ("temporary_containment", "promoted_assets"))
            asset_current_entries = sum(projected_entries[p]
                                        for p in ("temporary_containment", "promoted_assets"))
            if (asset_current > self._limits.shared_temporary_and_promoted_bytes
                    or asset_current_entries > self._limits.shared_temporary_and_promoted_entries):
                _fail("shared_asset_capacity_exceeded")
            token = _Opaque(_FACTORY)
            reservation = {"operation": operation, "estimates": normalized, "state": "reserved"}
            self._reservations[token] = reservation
            state["state"] = "reserved"
            for purpose, estimate in normalized.items():
                self._reserved[purpose][0] += estimate[0]
                self._reserved[purpose][1] += estimate[1]
            return token

    def cancel_before_write(self, operation, reservation):
        with self._lock:
            record = self._reservations.get(reservation)
            if (record is None or record["operation"] is not operation
                    or record["state"] != "reserved"):
                _fail("reservation_not_releasable")
            self._release_reserved(record)
            record["state"] = "cancelled"
            self._operations[record["operation"]]["state"] = "cancelled"

    def admit_write(self, operation, reservation):
        with self._lock:
            self._require_live()
            record = self._reservations.get(reservation)
            if (record is None or record["operation"] is not operation
                    or record["state"] != "reserved"):
                _fail("reservation_unavailable")
            if self._active_write is not None:
                _fail("write_admission_busy")
            write = _Opaque(_FACTORY)
            record["state"] = "writing"
            record["write"] = write
            self._active_write = write
            self._operations[record["operation"]]["state"] = "writing"
            return write

    def admit_journal_replacement(self, operation, binding):
        """Reserve one full TMP plus an empty lock for an exact live Journal tip."""
        with self._lock:
            self._require_live()
            state = self._operations.get(operation)
            if (type(binding) is not _JournalReplacementBinding
                    or binding._issuer is not _JOURNAL_REPLACEMENT_ISSUER
                    or binding.admission_owner is not self._owner_identity
                    or state is None
                    or binding.operation_id != state.get("operation_id")
                    or state["state"] not in ("open", "journal_completed")
                    or binding.filename != binding.operation_id + ".json"
                    or type(binding.previous_revision) is not int
                    or binding.previous_revision < 0
                    or binding.schema not in (journal.SCHEMA, multi_journal.SCHEMA)
                    or binding.root_owner is not binding.admission_owner._roots.get("private_journal")
                    or binding.journal_owner._native is not binding.root_owner
                    or (binding.journal_lease is not None
                        and (binding.journal_owner._active_lease is not binding.journal_lease
                             or binding.journal_owner._revoking))
                    or _freeze_inventory(self._inventory) != binding.prior_inventory):
                _fail("journal_replacement_binding_invalid")
            if self._active_write is not None:
                _fail("write_admission_busy")
            if (type(binding.previous_digest) is not str
                    or len(binding.previous_digest) != 64
                    or any(char not in "0123456789abcdef" for char in binding.previous_digest)):
                _fail("journal_replacement_binding_invalid")

            prior_row = self._inventory["private_journal"].get(binding.filename)
            prior_record = self._journal_files.get(binding.filename)
            writer_record = self._journal_operation_writers.get(binding.operation_id)
            if binding.previous_revision == 0:
                if (binding.previous_digest != "0" * 64
                        or binding.previous_file_identity is not None
                        or binding.previous_native_row is not None
                        or binding.previous_acknowledgement is not None
                        or prior_row is not None or prior_record is not None
                        or writer_record is not None):
                    _fail("journal_replacement_revision_conflict")
            else:
                expected_previous = (prior_record is not None
                    and prior_record["operation"] is operation
                    and prior_record["writer"] is binding.writer
                    and prior_record["schema"] == binding.schema
                    and prior_record["revision"] == binding.previous_revision
                    and prior_record["digest"] == binding.previous_digest
                    and prior_record["file_identity"] == binding.previous_file_identity
                    and prior_record["native_row"] == binding.previous_native_row
                    and prior_record["acknowledgement"] is binding.previous_acknowledgement
                    and writer_record is not None
                    and writer_record["operation"] is operation
                    and writer_record["writer"] is binding.writer
                    and writer_record["schema"] == binding.schema)
                if (not expected_previous or prior_row != binding.previous_native_row
                        or type(binding.previous_native_row) is not tuple
                        or len(binding.previous_native_row) != 3
                        or type(binding.previous_native_row[1]) is not int
                        or prior_row[1] != binding.previous_native_row[1]):
                    _fail("journal_replacement_revision_conflict")
            if (prior_row is None) != (binding.previous_revision == 0):
                _fail("journal_replacement_revision_conflict")

            inventory = self._inventory["private_journal"]
            old_size = prior_row[1] if prior_row is not None else 0
            current_bytes = sum(row[1] for row in inventory.values())
            current_entries = len(inventory)
            other_reserved_bytes = self._reserved["private_journal"][0]
            other_reserved_entries = self._reserved["private_journal"][1]
            # The old JSON is already in the observed/retained inventory. Only
            # the new maximum-size TMP consumes additional bytes. The lock is
            # an entry but is created empty, so it consumes zero reserved bytes.
            if (old_size > _JOURNAL_BYTES
                    or old_size + _JOURNAL_BYTES > _JOURNAL_REPLACEMENT_LIVE_BYTES
                    or current_bytes + _JOURNAL_BYTES > _JOURNAL_REPLACEMENT_LIVE_BYTES
                    or current_bytes - old_size + _JOURNAL_BYTES + other_reserved_bytes
                        > self._limits.journal_bytes
                    or current_entries + 2 + other_reserved_entries
                        > self._limits.journal_entries):
                _fail("journal_replacement_capacity_exceeded")
            outstanding_reserved = sum(row[0] for row in self._reserved.values())
            retained_upper_bound = sum(row[0] for row in self._uncertain.values())
            available = self._available_free_bytes
            if (outstanding_reserved > available
                    or retained_upper_bound > available - outstanding_reserved
                    or _JOURNAL_BYTES > available - outstanding_reserved - retained_upper_bound):
                _fail("observed_free_capacity_insufficient")

            reservation = _Opaque(_FACTORY)
            write = _Opaque(_FACTORY)
            record = {"operation": operation,
                      "estimates": {"private_journal": (_JOURNAL_BYTES, 2)},
                      "state": "writing", "write": write,
                      "kind": "journal_replacement", "journal_binding": binding}
            self._reservations[reservation] = record
            self._reserved["private_journal"][0] += _JOURNAL_BYTES
            self._reserved["private_journal"][1] += 2
            self._active_write = write
            state["state"] = "writing"
            return write

    def complete_journal_replacement(self, operation, write, inventory,
                                     available_free_bytes, completion):
        observed_free = self._validate_free_bytes(available_free_bytes)
        with self._lock:
            self._require_live()
            record = self._find_active_write(operation, write)
            if record.get("kind") != "journal_replacement":
                self._fail_active_journal_replacement(record, "journal_replacement_commit_invalid")
            binding = record["journal_binding"]
            if (type(completion) is not _JournalReplacementCompletion
                    or completion._issuer is not _JOURNAL_REPLACEMENT_ISSUER
                    or completion.binding is not binding
                    or binding.admission_owner is not self._owner_identity
                    or (binding.journal_lease is not None
                        and (binding.journal_owner._active_lease is not binding.journal_lease
                             or binding.journal_owner._revoking))
                    or _freeze_inventory(self._inventory) != binding.prior_inventory
                    or type(inventory) is not dict
                    or set(inventory) != set(_WRITABLE)):
                self._fail_active_journal_replacement(record, "journal_replacement_inventory_conflict")

            before = self._inventory
            filename = binding.filename
            expected = {purpose: dict(before[purpose]) for purpose in _WRITABLE}
            old_row = expected["private_journal"].get(filename)
            if binding.previous_revision == 0:
                if old_row is not None:
                    self._fail_active_journal_replacement(record, "journal_replacement_revision_conflict")
            elif old_row != binding.previous_native_row:
                self._fail_active_journal_replacement(record, "journal_replacement_revision_conflict")

            new_row = inventory.get("private_journal", {}).get(filename)
            if (type(new_row) is not tuple or len(new_row) != 3
                    or type(new_row[0]) is not tuple or len(new_row[0]) != 2
                    or any(type(value) is not int or value < 0 for value in new_row[0])
                    or new_row != completion.native_row
                    or type(new_row[1]) is not int or not 0 < new_row[1] <= _JOURNAL_BYTES
                    or type(new_row[2]) is not tuple
                    or type(completion.file_identity) is not tuple
                    or len(completion.file_identity) != 2
                    or any(type(value) is not int or value < 0 for value in completion.file_identity)
                    or (old_row is not None and new_row[0] == old_row[0])
                    or (old_row is not None and new_row[2] != old_row[2])):
                self._fail_active_journal_replacement(record, "journal_replacement_identity_conflict")
            expected["private_journal"][filename] = new_row
            if inventory != expected:
                self._fail_active_journal_replacement(record, "journal_replacement_inventory_conflict")
            if any(row[0] == new_row[0]
                   for purpose, entries in inventory.items()
                   for name, row in entries.items()
                   if purpose != "private_journal" or name != filename):
                self._fail_active_journal_replacement(record, "journal_replacement_identity_conflict")

            ack = completion.acknowledgement
            writer = binding.writer
            next_revision = binding.previous_revision + 1
            if type(ack) is journal.ReopenedJournal and binding.schema == journal.SCHEMA:
                ack_revision = ack.revision
                ack_digest = ack.digest
                ack_identity = ack.file_identity
                ack_operation_id = ack.operation.operation_id
                writer_operation_id = writer.operation.operation_id
                ack_is_live_tip = True
            elif (type(ack) is multi_journal.JournalAcknowledgement
                  and binding.schema == multi_journal.SCHEMA):
                ack_revision = ack.revision
                ack_digest = ack.digest
                ack_identity = ack.file_identity
                ack_operation_id = ack.operation_id
                writer_operation_id = writer.operation.operation_id
                ack_is_live_tip = writer._tip is ack
            else:
                self._fail_active_journal_replacement(record, "journal_replacement_ack_conflict")
            if (not ack_is_live_tip or ack_operation_id != binding.operation_id
                    or writer_operation_id != binding.operation_id
                    or ack_revision != next_revision
                    or ack_digest != writer._digest
                    or ack_identity != completion.file_identity
                    or writer._revision != next_revision
                    or writer._file_identity != completion.file_identity):
                self._fail_active_journal_replacement(record, "journal_replacement_ack_conflict")

            new_total = sum(row[1] for row in inventory["private_journal"].values())
            if new_total > self._limits.journal_bytes:
                self._fail_active_journal_replacement(record, "journal_replacement_capacity_exceeded")
            if old_row is not None:
                if (self._observed["private_journal"][0] < old_row[1]
                        or self._observed["private_journal"][1] < 1):
                    self._fail_active_journal_replacement(record, "journal_replacement_accounting_conflict")
                self._observed["private_journal"][0] -= old_row[1]
                self._observed["private_journal"][1] -= 1
            self._release_reserved(record)
            self._observed["private_journal"][0] += new_row[1]
            self._observed["private_journal"][1] += 1
            record["state"] = "completed"
            self._operations[operation]["state"] = "journal_completed"
            self._active_write = None
            self._inventory = inventory
            self._available_free_bytes = observed_free
            self._journal_files[filename] = {
                "operation": operation, "writer": writer, "schema": binding.schema,
                "revision": next_revision, "digest": ack_digest,
                "file_identity": completion.file_identity, "native_row": new_row,
                "acknowledgement": ack,
            }
            self._journal_operation_writers[binding.operation_id] = {
                "operation": operation, "writer": writer, "schema": binding.schema,
            }
            return self._summary_locked()

    def _fail_active_journal_replacement(self, record, code):
        self._retain_locked(record)
        self._invalid = True
        _fail(code)

    def complete_write(self, operation, write, inventory, available_free_bytes=None):
        observed_free = (self._validate_free_bytes(available_free_bytes)
                         if available_free_bytes is not None else None)
        with self._lock:
            self._require_live()
            record = self._find_active_write(operation, write)
            if record.get("kind") == "journal_replacement":
                self._fail_active_journal_replacement(record, "journal_replacement_commit_required")
            delta = self._inventory_delta(self._inventory, inventory)
            if delta is None:
                self._retain_locked(record)
                self._invalid = True
                _fail("storage_inventory_changed")
            if not any(byte_count or entry_count for byte_count, entry_count in delta.values()):
                # Once a write token is admitted, unchanged inventory cannot
                # prove a create-only write completed. Keep the full estimate
                # as uncertain rather than releasing capacity on absence of
                # evidence.
                self._retain_locked(record)
                self._invalid = True
                _fail("no_new_storage_observed")
            for purpose, (byte_count, entry_count) in delta.items():
                reserved_bytes, reserved_entries = record["estimates"].get(purpose, (0, 0))
                if byte_count > reserved_bytes or entry_count > reserved_entries:
                    self._retain_locked(record)
                    self._invalid = True
                    _fail("observed_usage_exceeded_reservation")
            self._release_reserved(record)
            for purpose, (byte_count, entry_count) in delta.items():
                self._observed[purpose][0] += byte_count
                self._observed[purpose][1] += entry_count
            record["state"] = "completed"
            self._operations[record["operation"]]["state"] = "completed"
            self._active_write = None
            self._inventory = inventory
            if observed_free is not None:
                self._available_free_bytes = observed_free
            return self._summary_locked()

    def retain_uncertain(self, operation, write):
        with self._lock:
            record = self._find_active_write(operation, write)
            self._retain_locked(record)
            self._invalid = True

    def cancel_write_before_create(self, operation, write):
        """Release a token only while its owner can prove CREATE_NEW was not called."""
        with self._lock:
            self._require_live()
            record = self._find_active_write(operation, write)
            if record.get("kind") == "journal_replacement":
                # The generic API has no Journal-writer observation proving
                # CREATE_NEW was not attempted. Conservatively retain it.
                _fail("journal_replacement_precreate_proof_required")
            self._release_reserved(record)
            record["state"] = "cancelled"
            self._operations[record["operation"]]["state"] = "cancelled"
            self._active_write = None

    def retain_completed_write_as_uncertain(self, operation, write, observed_delta):
        """Keep a verified write's full upper bound if its joint owner publish fails."""
        with self._lock:
            record = next((item for item in self._reservations.values()
                           if item.get("write") is write and item["state"] == "completed"), None)
            if (record is None or record["operation"] is not operation
                    or self._active_write is not None or type(observed_delta) is not dict
                    or set(observed_delta) != set(_WRITABLE)):
                _fail("write_admission_unavailable")
            for purpose in _WRITABLE:
                delta = observed_delta[purpose]
                if (type(delta) is not tuple or len(delta) != 2
                        or any(type(value) is not int or value < 0 for value in delta)
                        or self._observed[purpose][0] < delta[0]
                        or self._observed[purpose][1] < delta[1]):
                    _fail("write_admission_unavailable")
            for purpose in _WRITABLE:
                delta = observed_delta[purpose]
                self._observed[purpose][0] -= delta[0]
                self._observed[purpose][1] -= delta[1]
                estimate = record["estimates"].get(purpose, (0, 0))
                self._uncertain[purpose][0] += estimate[0]
                self._uncertain[purpose][1] += estimate[1]
            record["state"] = "uncertain"
            self._operations[record["operation"]]["state"] = "uncertain"
            self._invalid = True

    def retain_completed_journal_replacement_as_uncertain(self, operation, write):
        """Reopen capacity accounting if the Journal ACK publish fails after commit.

        The previous Journal JSON was already counted before this replacement.
        Restore that prior observed accounting, then retain the entire admitted
        replacement upper bound. The native file remains untouched and the
        ledger stays invalid, so this is accounting compensation only; it does
        not claim that the previous bytes were restored on disk.
        """
        with self._lock:
            record = next((item for item in self._reservations.values()
                           if item.get("write") is write and item["state"] == "completed"), None)
            binding = record.get("journal_binding") if record is not None else None
            operation_state = self._operations.get(operation)
            if (record is None or record["operation"] is not operation
                    or record.get("kind") != "journal_replacement"
                    or self._active_write is not None
                    or type(binding) is not _JournalReplacementBinding
                    or binding._issuer is not _JOURNAL_REPLACEMENT_ISSUER
                    or operation_state is None
                    or binding.operation_id != operation_state.get("operation_id")
                    or binding.admission_owner is not self._owner_identity
                    or operation_state["state"] != "journal_completed"):
                _fail("journal_replacement_uncertain_unavailable")

            prior_inventory = binding.prior_inventory
            current_inventory = _freeze_inventory(self._inventory)
            if prior_inventory is None or current_inventory is None:
                _fail("journal_replacement_uncertain_unavailable")
            prior = {purpose: dict(entries) for purpose, entries in prior_inventory}
            current = {purpose: dict(entries) for purpose, entries in current_inventory}
            filename = binding.filename
            prior_row = prior["private_journal"].get(filename)
            current_row = current["private_journal"].get(filename)
            committed = self._journal_files.get(filename)
            writer_record = self._journal_operation_writers.get(binding.operation_id)
            if (prior_row != binding.previous_native_row
                    or (binding.previous_revision == 0) != (prior_row is None)
                    or any(prior[purpose] != current[purpose]
                           for purpose in _WRITABLE if purpose != "private_journal")
                    or {name: row for name, row in prior["private_journal"].items()
                        if name != filename}
                       != {name: row for name, row in current["private_journal"].items()
                           if name != filename}
                    or type(current_row) is not tuple or len(current_row) != 3
                    or committed is None
                    or committed["operation"] is not operation
                    or committed["writer"] is not binding.writer
                    or committed["schema"] != binding.schema
                    or committed["revision"] != binding.previous_revision + 1
                    or committed["native_row"] != current_row
                    or writer_record is None
                    or writer_record["operation"] is not operation
                    or writer_record["writer"] is not binding.writer
                    or writer_record["schema"] != binding.schema
                    or type(current_row[1]) is not int or current_row[1] <= 0
                    or (prior_row is not None
                        and (type(prior_row) is not tuple or len(prior_row) != 3
                             or type(prior_row[1]) is not int or prior_row[1] <= 0))
                    or record.get("estimates", {}).get("private_journal")
                        != (_JOURNAL_BYTES, 2)):
                _fail("journal_replacement_uncertain_unavailable")

            observed_bytes, observed_entries = self._observed["private_journal"]
            current_size = current_row[1]
            prior_size = prior_row[1] if prior_row is not None else 0
            prior_entries = 1 if prior_row is not None else 0
            if observed_bytes < current_size or observed_entries < 1:
                _fail("journal_replacement_uncertain_unavailable")
            estimate = record["estimates"]["private_journal"]
            self._observed["private_journal"][0] = observed_bytes - current_size + prior_size
            self._observed["private_journal"][1] = observed_entries - 1 + prior_entries
            self._uncertain["private_journal"][0] += estimate[0]
            self._uncertain["private_journal"][1] += estimate[1]
            record["state"] = "retained_uncertain"
            operation_state["state"] = "retained_uncertain"
            self._invalid = True

    def observe_inventory(self, inventory, available_free_bytes=None):
        observed_free = (self._validate_free_bytes(available_free_bytes)
                         if available_free_bytes is not None else None)
        with self._lock:
            self._require_live()
            if inventory != self._inventory:
                self._invalidate_locked()
                _fail("storage_inventory_changed")
            if observed_free is not None:
                self._available_free_bytes = observed_free
            return self._summary_locked()

    def close(self):
        with self._lock:
            if self._closed:
                return
            # Close is not evidence that an in-flight or reserved write did
            # not happen. Keep every unsettled upper bound conservatively.
            for record in self._reservations.values():
                if record["state"] in ("reserved", "writing"):
                    self._retain_locked(record)
            self._closed = True

    def readiness(self):
        with self._lock:
            return self._summary_locked()

    def _validate_estimates(self, estimates):
        if type(estimates) is not dict or not estimates or not set(estimates) <= set(_WRITABLE):
            _fail("invalid_capacity_estimate")
        normalized = {}
        total_bytes = total_entries = 0
        for purpose, estimate in estimates.items():
            if type(estimate) is not CapacityEstimate:
                _fail("invalid_capacity_estimate")
            byte_count, entry_count = estimate.byte_upper_bound, estimate.entry_upper_bound
            if (type(byte_count) is not int or type(entry_count) is not int
                    or not 0 < byte_count <= _MAX_OPERATION_BYTES
                    or not 0 < entry_count <= _MAX_OPERATION_ENTRIES):
                _fail("invalid_capacity_estimate")
            # Bound before addition, even though Python integers do not wrap.
            if total_bytes > _MAX_OPERATION_BYTES - byte_count:
                _fail("operation_capacity_exceeded")
            if total_entries > _MAX_OPERATION_ENTRIES - entry_count:
                _fail("operation_entry_capacity_exceeded")
            total_bytes += byte_count
            total_entries += entry_count
            normalized[purpose] = (byte_count, entry_count)
        return normalized

    @staticmethod
    def _validate_free_bytes(value):
        if type(value) is not int or not 0 <= value <= 0x7FFFFFFFFFFFFFFF:
            _fail("invalid_free_capacity_observation")
        return value

    def _require_live(self):
        if self._closed or self._invalid or self._inventory is None:
            _fail("storage_owner_unavailable")

    def _find_active_write(self, operation, write):
        record = next((item for item in self._reservations.values()
                       if item.get("write") is write and item["state"] == "writing"), None)
        if (record is None or record["operation"] is not operation
                or self._active_write is not write):
            _fail("write_admission_unavailable")
        return record

    def _release_reserved(self, record):
        for purpose, estimate in record["estimates"].items():
            self._reserved[purpose][0] -= estimate[0]
            self._reserved[purpose][1] -= estimate[1]

    def _retain_locked(self, record):
        if record["state"] not in ("reserved", "writing"):
            return
        self._release_reserved(record)
        for purpose, estimate in record["estimates"].items():
            self._uncertain[purpose][0] += estimate[0]
            self._uncertain[purpose][1] += estimate[1]
        record["state"] = "retained_uncertain"
        self._operations[record["operation"]]["state"] = "retained_uncertain"
        if self._active_write is record.get("write"):
            self._active_write = None

    @staticmethod
    def _inventory_delta(before, after):
        if type(before) is not dict or type(after) is not dict or set(before) != set(_WRITABLE) or set(after) != set(_WRITABLE):
            return None
        delta = {p: [0, 0] for p in _WRITABLE}
        for purpose in _WRITABLE:
            old, new = before[purpose], after[purpose]
            if type(old) is not dict or type(new) is not dict:
                return None
            for name, row in old.items():
                if name not in new or new[name] != row:
                    return None
            additions = set(new) - set(old)
            if len(new) > _MAX_INVENTORY_ENTRIES:
                return None
            for name in additions:
                row = new[name]
                if (type(name) is not str or type(row) is not tuple or len(row) != 3
                        or type(row[1]) is not int or row[1] < 0):
                    return None
                delta[purpose][0] += row[1]
                delta[purpose][1] += 1
        return {p: tuple(value) for p, value in delta.items()}

    def _invalidate_locked(self):
        for record in self._reservations.values():
            if record["state"] in ("reserved", "writing"):
                self._retain_locked(record)
        self._invalid = True

    def _summary_locked(self):
        rows = []
        shared_asset_used = sum(self._reserved[p][0] + self._observed[p][0] + self._uncertain[p][0]
                                for p in ("temporary_containment", "promoted_assets"))
        shared_asset_entries = sum(self._reserved[p][1] + self._observed[p][1] + self._uncertain[p][1]
                                   for p in ("temporary_containment", "promoted_assets"))
        shared_asset_remaining = max(0, self._limits.shared_temporary_and_promoted_bytes - shared_asset_used)
        shared_entry_remaining = max(0, self._limits.shared_temporary_and_promoted_entries - shared_asset_entries)
        for purpose in _WRITABLE:
            reserved, observed, uncertain = (self._reserved[purpose], self._observed[purpose],
                                             self._uncertain[purpose])
            limit = _limit_for(purpose, self._limits)
            entry_limit = _limit_for(purpose, self._limits, entries=True)
            rows.append({"purpose": purpose,
                         "reserved_bytes": reserved[0], "reserved_entries": reserved[1],
                         "observed_used_bytes": observed[0], "observed_used_entries": observed[1],
                         "retained_uncertain_bytes": uncertain[0],
                         "retained_uncertain_entries": uncertain[1],
                         "policy_byte_capacity": limit, "policy_entry_capacity": entry_limit,
                         "remaining_policy_bytes": (shared_asset_remaining if purpose in
                             ("temporary_containment", "promoted_assets") else
                             max(0, limit - reserved[0] - observed[0] - uncertain[0])),
                         "remaining_policy_entries": (shared_entry_remaining if purpose in
                             ("temporary_containment", "promoted_assets") else
                             max(0, entry_limit - reserved[1] - observed[1] - uncertain[1]))})
        return {"status": "unavailable" if self._closed or self._invalid else "characterization_only",
                "execution_available": False, "protected_storage_available": False,
                "promotion_available": False, "candidate_publication_allowed": False,
                "authorship": "unverified", "disk_space_guaranteed": False,
                "observed_free_bytes": self._available_free_bytes,
                "writer_integrated": False, "cross_process_quota": False,
                "roots": rows}


class WindowsProtectedStorageAdmissionCharacterization:
    """Exact native-root composition plus bounded in-process capacity ledger."""
    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False

    @classmethod
    def capture_for_characterization(cls, approved_scope, purpose_roots, *,
                                     characterization=False, disposable_opt_in=False,
                                     limits=ProtectedStorageCapacityLimits()):
        return cls._capture_for_characterization(
            approved_scope, purpose_roots, expected_purposes=_PURPOSES,
            characterization=characterization, disposable_opt_in=disposable_opt_in,
            limits=limits, profile_a=False,
        )

    @classmethod
    def capture_profile_a_root_set_for_characterization(
            cls, approved_scope, purpose_roots, *,
            characterization=False, disposable_opt_in=False,
            limits=ProtectedStorageCapacityLimits()):
        """Capture the four writable Profile A roots under the shared 17A ledger.

        The independently selected Project JSON is bound later by the
        original-host lifecycle and is intentionally not a capacity root.
        """
        return cls._capture_for_characterization(
            approved_scope, purpose_roots, expected_purposes=_WRITABLE,
            characterization=characterization, disposable_opt_in=disposable_opt_in,
            limits=limits, profile_a=True,
        )

    @classmethod
    def _capture_for_characterization(cls, approved_scope, purpose_roots, *,
                                      expected_purposes, characterization,
                                      disposable_opt_in, limits, profile_a):
        if characterization is not True or disposable_opt_in is not True:
            _fail("execution_unavailable")
        if type(limits) is not ProtectedStorageCapacityLimits:
            _fail("invalid_capacity_limits")
        limits.validate()
        scope = windows._path(approved_scope)
        if profile_a:
            roots = _validate_profile_a_root_set_shape(purpose_roots)
        else:
            if type(purpose_roots) is not dict or set(purpose_roots) != set(expected_purposes):
                _fail("explicit_purpose_roots_required")
            roots = dict(purpose_roots)
        identities = []
        paths = []
        scope_identity = None
        user_sid = None
        for purpose in expected_purposes:
            root = roots[purpose]
            if type(root) is not windows.WindowsProtectedRootCharacterization:
                _fail("native_root_owner_required")
            if root._closed or root._purpose != purpose:
                _fail("native_root_purpose_mismatch")
            view = root.readiness()
            if view.get("acl_verified") is not True or root._filesystem != "local_ntfs_observed":
                _fail("native_root_unavailable")
            path = root._path
            is_directory = purpose != "selected_project_json"
            endpoint = [row for row in root._observations
                        if row[0] == path and row[1] is is_directory]
            if (len(endpoint) != 1 or endpoint[0][2] is not root._handle
                    or endpoint[0][3] != root._identity):
                _fail("native_root_identity_mismatch")
            if path == scope or not path.is_relative_to(scope):
                _fail("unapproved_root")
            if purpose == "selected_project_json" and path.suffix.lower() != ".json":
                _fail("selected_json_required")
            if purpose != "selected_project_json" and not is_directory:
                _fail("writable_root_required")
            if root._user is None:
                _fail("native_root_unavailable")
            sid = root._api[3].ConvertSidToStringSid(root._user)
            if user_sid is None:
                user_sid = sid
            elif sid != user_sid:
                _fail("native_owner_mismatch")
            found_scope = [row for row in root._observations if row[0] == scope and row[1]]
            if len(found_scope) != 1 or found_scope[0][2] is not root._scope_handle:
                _fail("approved_scope_identity_missing")
            if scope_identity is None:
                scope_identity = found_scope[0][3]
            elif scope_identity != found_scope[0][3]:
                _fail("approved_scope_identity_mismatch")
            identities.append(root._identity)
            paths.append(path)
        if len(set(identities)) != len(expected_purposes):
            _fail("purpose_alias")
        for index, path in enumerate(paths):
            if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
                   for other in paths[index + 1:]):
                _fail("purpose_overlap")
        # The scope marker adds atomic exclusion across processes to the
        # process-local accounting registry. An existing marker is never
        # inspected or adopted, so a crashed/ambiguous writer cannot be stolen.
        accounting_key = scope_identity
        with _PROCESS_ACCOUNTING_SCOPE_LOCK:
            if accounting_key in _PROCESS_ACCOUNTING_SCOPES:
                _fail("storage_accounting_scope_already_captured")
            if len(_PROCESS_ACCOUNTING_SCOPES) >= _MAX_PROCESS_ACCOUNTING_SCOPES:
                _fail("storage_accounting_scope_limit_exceeded")

        lease = windows.WindowsProtectedScopeWriterLease._acquire_for_characterization(
            scope, scope_identity, roots[expected_purposes[0]]._api,
            roots[expected_purposes[0]]._user,
        )
        registered = False
        try:
            with _PROCESS_ACCOUNTING_SCOPE_LOCK:
                if accounting_key in _PROCESS_ACCOUNTING_SCOPES:
                    _fail("storage_accounting_scope_already_captured")
                _PROCESS_ACCOUNTING_SCOPES.add(accounting_key)
                registered = True
            owner = cls(scope, scope_identity, roots, limits, lease,
                        profile_a=profile_a, _factory=_FACTORY)
            inventory = owner._scan()
            free_bytes = owner._free_bytes()
            owner._ledger.set_initial_inventory(inventory, free_bytes)
            # Revalidate after initial inventory; capture is not an ACL repair
            # or directory creation operation.
            owner._check_roots()
            if lease.readiness().get("status") != "held":
                _fail("scope_writer_lease_changed")
            return owner
        except BaseException:
            # No owner escaped and no write admission was possible, so a
            # failed read-only capture may relinquish its provisional claim.
            if registered:
                with _PROCESS_ACCOUNTING_SCOPE_LOCK:
                    _PROCESS_ACCOUNTING_SCOPES.discard(accounting_key)
            lease.release_settled_for_characterization()
            raise

    def __init__(self, scope, scope_identity, roots, limits, scope_lease, *,
                 profile_a=False, _factory=None):
        if _factory is not _FACTORY:
            _fail("host_storage_required")
        self._scope, self._scope_identity = scope, scope_identity
        self._roots, self._limits = roots, limits
        self._scope_lease = scope_lease
        self._profile_a_root_set = profile_a is True
        self._ledger = _CapacityLedger(limits, owner_identity=self)
        self._lock = threading.RLock()
        # A refresh owns this token only as a serialization marker. Native
        # filesystem observation runs after the mutex is released.
        self._refresh_lock = threading.Lock()
        self._refresh_active = False
        self._refresh_done = None
        self._closed = False
        self._invalid = False
        # Retain associated lifecycles strongly so a retired runtime cannot
        # make a late Worker uncertainty invisible to lease-release checks.
        self._host_lifecycle_refs = []
        self._asset_writer_integrated = False
        self._promotion_writer_integrated = False
        self._journal_writer_integrated = False

    def begin_operation_for_characterization(self, operation_id):
        self._refresh()
        with self._lock:
            self._require_live()
            return self._ledger.begin_operation(operation_id)

    def reserve_for_characterization(self, operation, estimates):
        self._refresh()
        with self._lock:
            self._require_live()
            return self._ledger.reserve(operation, estimates)

    def cancel_before_write_for_characterization(self, operation, reservation):
        # This token is still in the ledger's reserved state, so cancellation
        # is an in-memory pre-write release and does not depend on a fresh
        # filesystem inventory. In particular, another operation may already
        # own the single active write slot; that must not strand this unused
        # reservation merely because _refresh() refuses to scan during a write.
        with self._lock:
            self._require_live()
            return self._ledger.cancel_before_write(operation, reservation)

    def admit_write_for_characterization(self, operation, reservation):
        # Serialize the final pre-write inventory with admission publication.
        # Once the ledger marks a write active, other refreshes refuse to scan
        # its intentionally changing file inventory until exact completion.
        refresh_token = self._claim_refresh_slot()
        try:
            self._refresh_observation()
            with self._lock:
                self._require_live()
                return self._ledger.admit_write(operation, reservation)
        finally:
            self._release_refresh_slot(refresh_token)

    def admit_journal_replacement_for_characterization(
            self, operation, journal_owner, *, _journal_lease=None):
        """Preflight one protected Journal replacement before any CREATE_NEW.

        The optional lease is supplied only by the owner's integrated append.
        Direct C2B-17E-A callers get a temporary lease for the observation; it
        does not alter the already established writer APIs.
        """
        from core import generation_protected_journal as protected_journal

        if type(journal_owner) is not protected_journal.WindowsProtectedJournalCharacterization:
            _fail("journal_replacement_binding_invalid")
        owns_lease = _journal_lease is None
        if owns_lease:
            lease, _, _ = journal_owner._begin_lifecycle_lease()
        else:
            lease = _journal_lease
            journal_owner._assert_lifecycle_lease(lease)
        refresh_token = self._claim_refresh_slot()
        try:
            self._refresh_observation()
            with self._lock:
                self._require_live()
                with self._ledger._lock:
                    operation_state = self._ledger._operations.get(operation)
                    operation_id = (operation_state or {}).get("operation_id")
            if operation_id is None:
                _fail("journal_replacement_binding_invalid")
            journal_owner._assert_lifecycle_lease(lease)
            with journal_owner._lock:
                journal_owner._assert_lifecycle_lease_locked(lease)
                root = self._roots.get("private_journal")
                if (root is None or journal_owner._native is not root
                        or not journal_owner._writable or journal_owner._uncertain
                        or root._closed or root._purpose != "private_journal"
                        or root._identity != self._roots["private_journal"]._identity
                        or journal_owner._approved.path != str(root._path)
                        or journal_owner._approved.identity != root._identity):
                    _fail("journal_replacement_root_mismatch")
                active = ((journal_owner._writer, journal.SCHEMA),
                          (journal_owner._multi_request_writer, multi_journal.SCHEMA))
                selected = [(writer, schema) for writer, schema in active if writer is not None]
                if len(selected) != 1:
                    _fail("journal_replacement_writer_unavailable")
                writer, schema = selected[0]

            # Root/ACL checks and previous-tip reopen are native observations;
            # they deliberately run without Journal, admission, ledger, or
            # refresh mutexes held. Close can revoke the exact lease meanwhile.
            journal_owner._check()
            scope_rows = [row for row in root._observations
                          if row[0] == self._scope and row[1]]
            if (len(scope_rows) != 1 or scope_rows[0][2] is not root._scope_handle
                    or scope_rows[0][3] != self._scope_identity):
                _fail("journal_replacement_root_mismatch")
            expected_type = (protected_journal._ProtectedWriter if schema == journal.SCHEMA
                             else protected_journal._ProtectedMultiRequestWriter)
            if (type(writer) is not expected_type
                    or writer._uncertain or getattr(writer, "_closed", False)
                    or (schema == multi_journal.SCHEMA and writer._busy.locked())
                    or writer.root._owner is not journal_owner
                    or writer.root.path != journal_owner._approved.path
                    or writer.root.identity != journal_owner._approved.identity
                    or type(writer.operation) is not journal.OperationObservation
                    or writer.operation.operation_id != operation_id
                    or writer.filename != writer.operation.operation_id + ".json"
                    or type(writer._revision) is not int
                    or (schema == journal.SCHEMA and not 0 <= writer._revision < 8)
                    or (schema == multi_journal.SCHEMA
                        and not 0 <= writer._revision < multi_journal.MAX_REVISIONS)):
                _fail("journal_replacement_writer_unavailable")
            operation_id = writer.operation.operation_id
            previous_revision = writer._revision
            previous_digest = writer._digest
            previous_file_identity = writer._file_identity
            previous_acknowledgement = None
            reopened_previous = None
            if previous_revision == 0:
                if (previous_digest != "0" * 64 or previous_file_identity is not None
                        or (schema == multi_journal.SCHEMA and writer._tip is not None)):
                    _fail("journal_replacement_revision_conflict")
            else:
                if schema == journal.SCHEMA:
                    reopened_previous = journal_owner._observe_for_lifecycle_lease(
                        lease, lambda: journal.reopen_journal(
                            writer.root, writer.filename, expected_revision=previous_revision,
                            expected_digest=previous_digest))
                else:
                    reopened_previous = journal_owner._observe_for_lifecycle_lease(
                        lease, lambda: multi_journal.reopen_multi_request_journal(
                            writer.root, writer.filename, expected_revision=previous_revision,
                            expected_digest=previous_digest))
                if (reopened_previous.revision != previous_revision
                        or reopened_previous.digest != previous_digest
                        or reopened_previous.file_identity != previous_file_identity
                        or reopened_previous.operation != writer.operation):
                    _fail("journal_replacement_revision_conflict")

            with journal_owner._lock:
                journal_owner._assert_lifecycle_lease_locked(lease)
                with self._lock:
                    self._require_live()
                    with self._ledger._lock:
                        current_state = self._ledger._operations.get(operation)
                        inventory = self._ledger._inventory
                        if (current_state is None or current_state.get("operation_id") != operation_id
                                or inventory is None):
                            _fail("journal_replacement_binding_invalid")
                        filename = operation_id + ".json"
                        prior_inventory = _freeze_inventory(inventory)
                        prior_row = inventory["private_journal"].get(filename)
                        names = inventory["private_journal"]
                        if (operation_id + ".lock" in names
                                or any(name.startswith(operation_id + ".") and name.endswith(".tmp")
                                       for name in names)):
                            _fail("journal_replacement_evidence_conflict")
                        if ((previous_revision == 0 and prior_row is not None)
                                or (previous_revision > 0 and prior_row is None)):
                            _fail("journal_replacement_revision_conflict")
                        prior_record = self._ledger._journal_files.get(filename)
                        if previous_revision > 0 and (prior_record is None
                                or prior_record["operation"] is not operation
                                or prior_record["writer"] is not writer
                                or prior_record["schema"] != schema
                                or prior_record["revision"] != previous_revision
                                or prior_record["digest"] != previous_digest
                                or prior_record["file_identity"] != previous_file_identity
                                or prior_record["native_row"] != prior_row):
                            _fail("journal_replacement_revision_conflict")
                        if previous_revision > 0:
                            previous_acknowledgement = prior_record["acknowledgement"]
                            if schema == journal.SCHEMA:
                                if reopened_previous != previous_acknowledgement:
                                    _fail("journal_replacement_revision_conflict")
                            elif (writer._tip is not previous_acknowledgement
                                  or previous_acknowledgement.revision != previous_revision
                                  or previous_acknowledgement.digest != previous_digest
                                  or previous_acknowledgement.file_identity != previous_file_identity):
                                _fail("journal_replacement_revision_conflict")
                        binding = _JournalReplacementBinding(
                            self, journal_owner, root, writer, schema, operation_id, filename,
                            previous_revision, previous_digest, previous_file_identity,
                            prior_row, previous_acknowledgement, prior_inventory,
                            _JOURNAL_REPLACEMENT_ISSUER,
                            lease if not owns_lease else None)
                        return self._ledger.admit_journal_replacement(operation, binding)
        finally:
            self._release_refresh_slot(refresh_token)
            if owns_lease:
                journal_owner._release_lifecycle_lease(lease)

    def complete_journal_replacement_for_characterization(
            self, operation, write_admission, journal_owner, acknowledgement, *,
            _journal_lease=None):
        """Commit only a verified replacement returned by the bound live writer."""
        from core import generation_protected_journal as protected_journal

        bound_attempt = False
        owns_lease = False
        lease = _journal_lease
        try:
            if type(journal_owner) is not protected_journal.WindowsProtectedJournalCharacterization:
                _fail("journal_replacement_binding_invalid")
            with self._lock:
                self._require_live()
                with self._ledger._lock:
                    record = self._ledger._find_active_write(operation, write_admission)
                    binding = record.get("journal_binding")
                    if (record.get("kind") != "journal_replacement"
                            or type(binding) is not _JournalReplacementBinding
                            or binding.admission_owner is not self
                            or binding.journal_owner is not journal_owner):
                        _fail("journal_replacement_binding_invalid")
                    bound_attempt = True
            if binding.journal_lease is not _journal_lease:
                _fail("journal_replacement_binding_invalid")
            if lease is None:
                lease, _, _ = journal_owner._begin_lifecycle_lease(binding.schema)
                owns_lease = True
            else:
                journal_owner._assert_lifecycle_lease(lease)

            with journal_owner._lock:
                journal_owner._assert_lifecycle_lease_locked(lease)
                if (journal_owner._uncertain or journal_owner._native is not binding.root_owner
                        or binding.root_owner is not self._roots.get("private_journal")):
                    _fail("journal_replacement_writer_unavailable")
                writer = binding.writer
                if (writer._uncertain or getattr(writer, "_closed", False)
                        or writer.operation.operation_id != binding.operation_id
                        or writer._revision != binding.previous_revision + 1):
                    _fail("journal_replacement_ack_conflict")

            # All reopen, native identity, and inventory observations happen
            # outside Journal/admission/ledger locks. Close can publish
            # revocation during any of these operations.
            journal_owner._check()
            if binding.schema == journal.SCHEMA:
                if (type(acknowledgement) is not journal.ReopenedJournal
                        or acknowledgement is None):
                    _fail("journal_replacement_ack_conflict")
                verified = journal_owner._observe_for_lifecycle_lease(
                    lease, lambda: journal.reopen_journal(
                        writer.root, binding.filename,
                        expected_revision=acknowledgement.revision,
                        expected_digest=acknowledgement.digest))
                if (verified != acknowledgement or acknowledgement.operation != writer.operation):
                    _fail("journal_replacement_ack_conflict")
            else:
                if (type(acknowledgement) is not multi_journal.JournalAcknowledgement
                        or writer._tip is not acknowledgement):
                    _fail("journal_replacement_ack_conflict")
                verified = journal_owner._observe_for_lifecycle_lease(
                    lease, lambda: multi_journal.reopen_multi_request_journal(
                        writer.root, binding.filename,
                        expected_revision=acknowledgement.revision,
                        expected_digest=acknowledgement.digest))
                if (verified.revision != acknowledgement.revision
                        or verified.digest != acknowledgement.digest
                        or verified.file_identity != acknowledgement.file_identity
                        or verified.operation != writer.operation):
                    _fail("journal_replacement_ack_conflict")

            journal_owner._assert_lifecycle_lease(lease)
            target = binding.root_owner._path / binding.filename
            file_identity = journal._file_identity(journal._ordinary(target, directory=False))
            if (file_identity != acknowledgement.file_identity
                    or writer._file_identity != file_identity
                    or writer._digest != acknowledgement.digest):
                _fail("journal_replacement_ack_conflict")
            inventory = self._scan()
            free_bytes = self._free_bytes()
            native_row = inventory["private_journal"].get(binding.filename)
            with journal_owner._lock:
                known_acl = journal_owner._file_acls.get(native_row[0]) if native_row is not None else None
            if (native_row is None or known_acl != native_row[2]):
                _fail("journal_replacement_identity_conflict")

            journal_owner._assert_lifecycle_lease(lease)
            with journal_owner._lock:
                journal_owner._assert_lifecycle_lease_locked(lease)
                with self._lock:
                    self._require_live()
                    with self._ledger._lock:
                        record = self._ledger._find_active_write(operation, write_admission)
                        if record.get("journal_binding") is not binding:
                            _fail("journal_replacement_binding_invalid")
                        completion = _JournalReplacementCompletion(
                            binding, acknowledgement, file_identity, native_row,
                            _JOURNAL_REPLACEMENT_ISSUER)
                        try:
                            result = self._ledger.complete_journal_replacement(
                                operation, write_admission, inventory, free_bytes, completion)
                            if binding.journal_lease is not None:
                                journal_owner._mark_lifecycle_lease_committed_locked(
                                    binding.journal_lease, acknowledgement)
                            self._journal_writer_integrated = True
                            return result
                        except BaseException:
                            # Keep competing admission fenced until any ledger
                            # commit that lacks its exact ACK marker has been
                            # compensated into retained uncertainty.
                            self._invalid = True
                            if record.get("state") == "completed":
                                self._ledger.retain_completed_journal_replacement_as_uncertain(
                                    operation, write_admission)
                            raise
        except BaseException as error:
            if bound_attempt:
                with self._lock:
                    try:
                        self._ledger.retain_uncertain(operation, write_admission)
                    except ValueError:
                        pass
                    self._invalid = True
            if (type(error) is ValueError
                    and (str(error).startswith("journal_replacement_")
                         or str(error) == "write_admission_unavailable")):
                raise
            _fail("journal_replacement_observation_unavailable")
        finally:
            if owns_lease:
                journal_owner._release_lifecycle_lease(lease)

    def retain_journal_replacement_uncertain_for_characterization(self, operation, write_admission):
        """Retain the full replacement upper bound after any uncertain writer outcome."""
        with self._lock:
            with self._ledger._lock:
                record = next((item for item in self._ledger._reservations.values()
                               if item.get("write") is write_admission), None)
                if (record is None or record["operation"] is not operation
                        or record.get("kind") != "journal_replacement"):
                    _fail("journal_replacement_binding_invalid")
                if record["state"] == "retained_uncertain":
                    self._invalid = True
                    return self._ledger._summary_locked()
                if record["state"] == "completed":
                    self._ledger.retain_completed_journal_replacement_as_uncertain(
                        operation, write_admission)
                    self._invalid = True
                    return self._ledger._summary_locked()
                if record["state"] != "writing":
                    _fail("journal_replacement_uncertain_unavailable")
                self._ledger.retain_uncertain(operation, write_admission)
                self._invalid = True
                return self._ledger._summary_locked()

    def assert_write_admission_for_characterization(self, operation, write_admission):
        """Check a live exact write token without rescanning native roots."""
        with self._lock:
            self._require_live()
            with self._ledger._lock:
                self._ledger._require_live()
                self._ledger._find_active_write(operation, write_admission)
                return True

    def cancel_write_before_create_for_characterization(self, operation, write_admission):
        """Release an admitted batch only when its caller has not entered CREATE_NEW."""
        with self._lock:
            self._require_live()
            return self._ledger.cancel_write_before_create(operation, write_admission)

    def retain_completed_write_uncertain_for_characterization(
            self, operation, write_admission, observed_delta):
        with self._lock:
            return self._ledger.retain_completed_write_as_uncertain(
                operation, write_admission, observed_delta)

    def complete_write_for_characterization(self, operation, write_admission):
        try:
            inventory = self._scan()
            free_bytes = self._free_bytes()
        except Exception:
            with self._lock:
                try:
                    self._ledger.retain_uncertain(operation, write_admission)
                except ValueError:
                    # A concurrent close already moved this exact reservation
                    # to retained-uncertain accounting.
                    pass
                self._invalid = True
            _fail("protected_storage_observation_unavailable")
        with self._lock:
            self._require_live()
            result = self._ledger.complete_write(operation, write_admission, inventory, free_bytes)
            return result

    def complete_asset_write_for_characterization(
            self, operation, write_admission, asset_owner, image, *,
            stream_attempt=None, stream_observation=None, stream_freshness=None):
        """Complete only the exact one-file delta from the issuing asset owner.

        Native inventory and image-byte verification run without owner locks.
        Final accounting uses the lock order protected-assets owner ->
        admission owner and performs only bounded in-memory checks.
        """
        from core import generation_windows_protected_assets as assets

        if (type(asset_owner) is not assets.WindowsProtectedAssetsCharacterization
                or type(image) is not assets.ProtectedImageObservation
                or image.purpose not in ("temporary_containment", "promoted_assets")
                or self._roots.get(image.purpose) is not asset_owner._roots.get(image.purpose)
                or any(self._roots.get(purpose) is not asset_owner._roots.get(purpose)
                       for purpose in ("temporary_containment", "promoted_assets"))):
            _fail("protected_asset_owner_mismatch")
        if ((stream_attempt is None) != (stream_observation is None)
                or (stream_attempt is None) != (stream_freshness is None)):
            _fail("protected_stream_commit_invalid")
        if stream_attempt is not None:
            if (type(stream_attempt) is not tuple or len(stream_attempt) != 2
                    or type(stream_observation) is not assets.VerifiedProtectedImageObservation
                    or stream_attempt != (stream_observation.request_id,
                                          stream_observation.descriptor_identity)
                    or stream_observation.image is not image
                    or not callable(stream_freshness)):
                _fail("protected_stream_commit_invalid")
            with asset_owner._lock:
                pending = asset_owner._stream_pending_images.get(stream_attempt)
                binding = asset_owner._stream_bindings.get(stream_attempt[0])
                if (pending is None or pending[0] is not stream_observation
                        or pending[1] is not stream_freshness
                        or asset_owner._stream_envelope is None
                        or binding is None or len(binding) != 2):
                    _fail("protected_stream_commit_invalid")
                prepared, remote = binding
                if (not assets.is_owner_prepared_frozen_request(prepared)
                        or remote.execution_succeeded is not True
                        or stream_observation.job_id != remote.job_id
                        or stream_observation.claim_id != remote.claim_id
                        or stream_observation.manifest_identity != remote.manifest_identity
                        or stream_observation.request_id != prepared.request_id
                        or stream_observation.request_index != prepared.request_index
                        or stream_observation.workflow_identity != prepared.workflow_identity
                        or stream_observation.prompt_id != remote.prompt_id
                        or stream_observation.remote_receipt_identity != remote.identity
                        or stream_observation.descriptor_identity not in {
                            item.identity for item in remote.images}):
                    _fail("protected_stream_commit_invalid")

        try:
            with asset_owner._lock:
                key = (image.purpose, image.storage_identity)
                if (asset_owner._images.get(key) is not image
                        or asset_owner._closed or asset_owner._revoking
                        or asset_owner._invalid or asset_owner._uncertain):
                    _fail("protected_asset_observation_mismatch")
                extension = asset_owner._files[key][0].suffix[1:]
            # The writer's existing inspection method keeps its lock while it
            # rereads bytes. Use the same native observer outside the lock so
            # image verification cannot block close or callbacks.
            if asset_owner._observe(image.storage_identity, image.purpose, extension) != image:
                _fail("protected_asset_observation_mismatch")
            inventory = self._scan()
            free_bytes = self._free_bytes()
            if asset_owner._observe(image.storage_identity, image.purpose, extension) != image:
                _fail("protected_asset_observation_mismatch")
            if stream_freshness is not None:
                try:
                    fresh = stream_freshness()
                except Exception:
                    _fail("host_freshness_lost")
                if fresh is not True:
                    _fail("host_freshness_lost")
        except BaseException as error:
            self._retain_asset_write(operation, write_admission)
            if type(error) is ValueError and str(error) == "host_freshness_lost":
                raise
            _fail("protected_asset_observation_unavailable")

        try:
            # No native I/O occurs while these locks are held. This pair is the
            # commit boundary against close/invalidation on either owner.
            with asset_owner._lock:
                with self._lock:
                    self._require_live()
                    key = (image.purpose, image.storage_identity)
                    file_record = asset_owner._files.get(key)
                    if (asset_owner._closed or asset_owner._revoking
                            or asset_owner._invalid or asset_owner._uncertain
                            or asset_owner._images.get(key) is not image
                            or file_record is None
                            or file_record[0].name != image.storage_identity
                            or file_record[0].parent != asset_owner._roots[image.purpose]._path):
                        _fail("protected_asset_observation_mismatch")
                    if stream_attempt is not None:
                        if (stream_attempt not in asset_owner._stream_attempts
                                or stream_attempt in asset_owner._stream_images
                                or asset_owner._stream_busy is not True
                                or asset_owner._capacity_busy is not True):
                            _fail("protected_stream_commit_invalid")
                    delta = self._ledger._inventory_delta(self._ledger._inventory, inventory)
                    additions = ({purpose: set(inventory[purpose]) - set(self._ledger._inventory[purpose])
                                  for purpose in _WRITABLE}
                                 if type(inventory) is dict and type(self._ledger._inventory) is dict
                                 else None)
                    expected_additions = {purpose: set() for purpose in _WRITABLE}
                    expected_additions[image.purpose] = {image.storage_identity}
                    row = inventory.get(image.purpose, {}).get(image.storage_identity)
                    if (delta is None or additions != expected_additions
                            or delta[image.purpose] != (image.byte_count, 1)
                            or any(delta[purpose] != (0, 0) for purpose in _WRITABLE
                                   if purpose != image.purpose)
                            or row != (file_record[2], image.byte_count, file_record[3][0])):
                        self._ledger.retain_uncertain(operation, write_admission)
                        self._invalid = True
                        _fail("protected_asset_inventory_mismatch")
                    if stream_attempt is not None:
                        # The exact stream observation and its storage accounting
                        # become visible under the same two-owner commit locks.
                        # Roll it back if ledger completion refuses, retaining
                        # the native file itself as uncertain evidence.
                        asset_owner._stream_images[stream_attempt] = stream_observation
                        asset_owner._stream_pending_images.pop(stream_attempt, None)
                    try:
                        result = self._ledger.complete_write(
                            operation, write_admission, inventory, free_bytes)
                    except BaseException:
                        if stream_attempt is not None:
                            asset_owner._stream_images.pop(stream_attempt, None)
                            asset_owner._stream_pending_images.pop(stream_attempt, None)
                        raise
                    self._asset_writer_integrated = True
                    return result
        except BaseException:
            if stream_attempt is not None:
                with asset_owner._lock:
                    pending = asset_owner._stream_pending_images.get(stream_attempt)
                    if pending is not None and pending[0] is stream_observation:
                        asset_owner._stream_pending_images.pop(stream_attempt, None)
            self._retain_asset_write(operation, write_admission)
            raise

    def complete_protected_promotion_batch_for_characterization(
            self, operation, write_admission, asset_owner, promotion_owner,
            acceptance_owner, accepted, receipt, capacity_lease, *, final_revalidate):
        """Atomically account and publish one exact all-image promotion batch.

        Native image verification and the final host callback run without
        owner locks. The final in-memory commit follows protected-assets ->
        acceptance -> promotion -> admission -> ledger lock order.
        """
        from core import generation_windows_protected_assets as assets
        from core import generation_windows_protected_promotion as promotion

        if (type(asset_owner) is not assets.WindowsProtectedAssetsCharacterization
                or type(promotion_owner) is not promotion.ProtectedDurablePromotionCharacterization
                or type(acceptance_owner) is not promotion.ProtectedOutputAcceptanceCharacterization
                or type(accepted) is not promotion.AcceptedProtectedOutputBatch
                or type(receipt) is not promotion.VerifiedProtectedPromotionReceipt
                or not callable(final_revalidate)
                or any(self._roots.get(purpose) is not asset_owner._roots.get(purpose)
                       for purpose in ("temporary_containment", "promoted_assets"))):
            _fail("protected_promotion_binding_invalid")
        if (promotion_owner._protected_owner is not asset_owner
                or promotion_owner._acceptance_owner is not acceptance_owner
                or promotion_owner._accepted is not accepted
                or receipt._promotion_owner is not promotion_owner
                or receipt._protected_owner is not asset_owner
                or receipt._acceptance_owner is not acceptance_owner
                or receipt._accepted is not accepted
                or receipt.accepted_identity != accepted.identity
                or receipt.batch_identity != accepted._batch_receipt.identity):
            _fail("protected_promotion_binding_invalid")

        prepared, remote = accepted._prepared, accepted._remote
        batch = accepted._batch_receipt
        descriptors, sources, rows = tuple(remote.images), tuple(batch.observations), tuple(receipt.images)
        descriptor_ids = tuple(item.identity for item in descriptors)
        if (not descriptors or len(descriptors) != len(sources) or len(rows) != len(descriptors)
                or tuple(item.descriptor_identity for item in sources) != descriptor_ids
                or tuple(row.descriptor_identity for row in rows) != descriptor_ids
                or any(row.source_observation is not source for row, source in zip(rows, sources))
                or any(source.image.purpose != "temporary_containment" for source in sources)
                or any(row.promoted_image.purpose != "promoted_assets" for row in rows)):
            _fail("protected_promotion_incomplete")

        total_bytes = 0
        for source in sources:
            size = source.image.byte_count
            if (type(size) is not int or size <= 0
                    or size > min(asset_owner._limits.image_bytes, asset_owner._limits.request_bytes)
                    or total_bytes > self._limits.shared_temporary_and_promoted_bytes - size):
                _fail("storage_capacity_exceeded")
            total_bytes += size
        expected_estimate = {"promoted_assets": (total_bytes, len(rows))}
        with self._lock:
            self._require_live()
            with self._ledger._lock:
                record = self._ledger._find_active_write(operation, write_admission)
                if record["estimates"] != expected_estimate:
                    _fail("protected_promotion_capacity_mismatch")
                baseline = {purpose: dict(entries)
                            for purpose, entries in self._ledger._inventory.items()}

        expected_keys = set()
        file_records = {}
        source_records = {}
        with asset_owner._lock:
            if (asset_owner._closed or asset_owner._revoking or asset_owner._invalid
                    or asset_owner._uncertain or not asset_owner._writable
                    or not asset_owner._capacity_busy or asset_owner._capacity_lease is not capacity_lease
                    or asset_owner._capacity_thread != threading.get_ident()
                    or not asset_owner._promotion_busy or asset_owner._promotion_owner is not promotion_owner
                    or asset_owner._promotion_thread != threading.get_ident()):
                _fail("protected_promotion_invalidated")
            for descriptor, source, row in zip(descriptors, sources, rows):
                if (asset_owner._stream_images.get((prepared.request_id, descriptor.identity)) is not source
                        or asset_owner._images.get(("temporary_containment", source.image.storage_identity))
                        is not source.image):
                    _fail("protected_promotion_source_mismatch")
                source_key = ("temporary_containment", source.image.storage_identity)
                destination = row.promoted_image
                destination_key = ("promoted_assets", destination.storage_identity)
                source_record = asset_owner._files.get(source_key)
                destination_record = asset_owner._files.get(destination_key)
                if (source_record is None or destination_record is None
                        or asset_owner._images.get(destination_key) is not destination
                        or destination.storage_identity in expected_keys):
                    _fail("protected_promotion_destination_mismatch")
                expected_keys.add(destination.storage_identity)
                source_records[source_key] = source_record
                file_records[destination_key] = destination_record

        # Re-read every promoted image through the existing native verifier.
        # This runs outside lifecycle locks while the exact capacity lease
        # keeps protected close waiting and excludes another writer.
        for row in rows:
            image = row.promoted_image
            key = ("promoted_assets", image.storage_identity)
            record = file_records[key]
            extension = record[0].suffix[1:]
            if (record[0].parent != asset_owner._roots["promoted_assets"]._path
                    or extension not in assets.SUPPORTED_EXTENSIONS
                    or asset_owner._observe(image.storage_identity, image.purpose, extension) != image
                    or image.byte_count != row.source_observation.image.byte_count
                    or image.content_sha256 != row.source_observation.image.content_sha256
                    or image.image_format != row.source_observation.image.image_format
                    or (image.width, image.height) !=
                       (row.source_observation.image.width, row.source_observation.image.height)):
                _fail("protected_promotion_destination_mismatch")

        inventory = self._scan()
        free_bytes = self._free_bytes()
        delta = self._ledger._inventory_delta(baseline, inventory)
        additions = ({purpose: set(inventory[purpose]) - set(baseline[purpose])
                      for purpose in _WRITABLE}
                     if delta is not None else None)
        expected_additions = {purpose: set() for purpose in _WRITABLE}
        expected_additions["promoted_assets"] = expected_keys
        if (delta is None or additions != expected_additions
                or delta["promoted_assets"] != (total_bytes, len(rows))
                or any(delta[purpose] != (0, 0) for purpose in _WRITABLE
                       if purpose != "promoted_assets")):
            _fail("protected_promotion_inventory_mismatch")
        for row in rows:
            image = row.promoted_image
            key = ("promoted_assets", image.storage_identity)
            record = file_records[key]
            if inventory["promoted_assets"].get(image.storage_identity) != (
                    record[2], image.byte_count, record[3][0]):
                _fail("protected_promotion_inventory_mismatch")

        # This callback revalidates the original source custody and host
        # binding after native verification, before the joint in-memory commit.
        final_revalidate()

        request_key = (prepared.request_id, remote.identity)
        with asset_owner._lock:
            if (asset_owner._closed or asset_owner._revoking or asset_owner._invalid
                    or asset_owner._uncertain or asset_owner._capacity_lease is not capacity_lease
                    or not asset_owner._capacity_busy or asset_owner._capacity_thread != threading.get_ident()
                    or not asset_owner._promotion_busy or asset_owner._promotion_owner is not promotion_owner
                    or asset_owner._promotion_thread != threading.get_ident()
                    or request_key not in asset_owner._stream_promotion_attempts
                    or request_key in asset_owner._stream_promotions
                    or asset_owner._stream_batch_acceptances.get(request_key) is not accepted):
                _fail("protected_promotion_invalidated")
            with acceptance_owner._lock:
                if (acceptance_owner._closed or acceptance_owner._revoking
                        or acceptance_owner._invalid or acceptance_owner._uncertain
                        or acceptance_owner._busy or acceptance_owner._receipt is not accepted
                        or accepted._protected_owner is not asset_owner
                        or accepted._batch_receipt is not batch):
                    _fail("protected_promotion_invalidated")
                with promotion_owner._lock:
                    if (promotion_owner._closed or promotion_owner._revoking
                            or promotion_owner._uncertain or not promotion_owner._busy
                            or not promotion_owner._attempted or promotion_owner._receipt is not None
                            or promotion_owner._pending_receipt is not receipt):
                        _fail("protected_promotion_invalidated")
                    with self._lock:
                        self._require_live()
                        if (any(asset_owner._files.get(key) is not record
                                for key, record in file_records.items())
                                or any(asset_owner._files.get(key) is not record
                                       for key, record in source_records.items())
                                or any(asset_owner._images.get(("promoted_assets", row.promoted_image.storage_identity))
                                       is not row.promoted_image for row in rows)
                                or any(asset_owner._stream_images.get((prepared.request_id, descriptor.identity))
                                       is not source for descriptor, source in zip(descriptors, sources))):
                            _fail("protected_promotion_invalidated")
                        ledger_completed = False
                        try:
                            result = self._ledger.complete_write(
                                operation, write_admission, inventory, free_bytes)
                            ledger_completed = True
                            promotion_owner._receipt = receipt
                            asset_owner._stream_promotions[request_key] = receipt
                            promotion_owner._pending_receipt = None
                        except BaseException:
                            asset_owner._stream_promotions.pop(request_key, None)
                            promotion_owner._receipt = None
                            promotion_owner._pending_receipt = receipt
                            if not ledger_completed:
                                with self._ledger._lock:
                                    ledger_completed = any(
                                        item.get("write") is write_admission
                                        and item["operation"] is operation
                                        and item["state"] == "completed"
                                        for item in self._ledger._reservations.values())
                            if ledger_completed:
                                try:
                                    self._ledger.retain_completed_write_as_uncertain(
                                        operation, write_admission, delta)
                                    self._invalid = True
                                except BaseException:
                                    # Preserve the verified inventory and any
                                    # already-invalid ledger; never claim a
                                    # public promotion receipt after this path.
                                    self._invalid = True
                            raise
                        self._asset_writer_integrated = True
                        self._promotion_writer_integrated = True
                        return result

    def _retain_asset_write(self, operation, write_admission):
        with self._lock:
            try:
                self._ledger.retain_uncertain(operation, write_admission)
            except ValueError:
                # Close/invalidation may already have moved this exact live
                # token into retained-uncertain capacity.
                pass
            self._invalid = True

    def retain_uncertain_for_characterization(self, operation, write_admission):
        with self._lock:
            self._ledger.retain_uncertain(operation, write_admission)
            self._invalid = True

    def readiness(self):
        try:
            self._refresh()
        except ValueError:
            pass
        lease_status = (self._scope_lease.readiness().get("status")
                        if self._scope_lease is not None else "unavailable")
        with self._lock:
            base = self._ledger.readiness()
            base["writer_integrated"] = self._asset_writer_integrated
            base["promotion_writer_integrated"] = self._promotion_writer_integrated
            base["journal_writer_integrated"] = self._journal_writer_integrated
            base.update({"filesystem": "local_ntfs_observed" if not self._invalid and not self._closed
                         else "unverified",
                         "native_root_identity": "observed_unchanged" if not self._invalid and not self._closed
                         else "unsafe_or_unavailable",
                         "approved_scope_identity": "observed_unchanged" if not self._invalid and not self._closed
                         else "unsafe_or_unavailable",
                         "directory_durability": "unsupported", "power_loss_guarantee": False,
                         "current_authorization": "absent", "recovery_execution_allowed": False,
                         "project_save_allowed": False, "cleanup_allowed": False,
                         "root_set_contract": ("profile_a_four_writable_roots"
                             if self._profile_a_root_set else "legacy_five_purpose_roots"),
                         "scope_writer_lease": lease_status,
                         "scope_writer_lease_cross_process": True,
                         "project_reference": "bound_separately" if self._profile_a_root_set else "legacy_selected_purpose"})
            return base

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._ledger.close()
            self._closed = True
        self.release_scope_writer_lease_if_settled_for_characterization()

    def _scope_lease_retention_reason(self):
        with self._ledger._lock:
            states = {record["state"] for record in self._ledger._operations.values()}
            # Initial inventory has no operation record to inspect, but its
            # bytes and entries are still retained-uncertain evidence. Keep
            # the cross-process scope lease across close/restart in that case.
            uncertain_inventory = any(
                byte_count or entry_count
                for byte_count, entry_count in self._ledger._uncertain.values()
            )
            uncertain = (uncertain_inventory or self._ledger._active_write is not None
                         or bool(states & {"reserved", "writing", "retained_uncertain"}))
        if uncertain or self._invalid:
            return "uncertain"
        active_host = False
        with self._lock:
            references = tuple(self._host_lifecycle_refs)
        for lifecycle in references:
            with lifecycle._lock:
                state = lifecycle._state
                integration = lifecycle._worker_storage_integration
            if state != "closed":
                active_host = True
            if integration is not None:
                with integration._lock:
                    if integration._uncertain_leases:
                        return "uncertain"
                    if integration._state != "closed" or integration._active is not None:
                        active_host = True
        return "active_host" if active_host else "settled"

    def _bind_profile_a_lifecycle_for_characterization(
            self, lifecycle, project_reference):
        """Publish the host binding and its lease-retention reference atomically.

        The lifecycle callback is an in-memory state update only. Keep the
        owner lock across that update and association publication so close()
        either wins before binding or observes the successfully bound lifecycle.
        This prevents a clean close from releasing or stranding the lease in a
        gap between those two publications.
        """
        with self._lock:
            if (not self._profile_a_root_set or self._closed or self._invalid
                    or lifecycle is None):
                _fail("profile_a_storage_unavailable")
            references = tuple(self._host_lifecycle_refs)
            already_registered = any(previous is lifecycle for previous in references)
        if already_registered:
            with self._lock:
                if (self._closed or self._invalid
                        or tuple(self._host_lifecycle_refs) != references):
                    _fail("profile_a_storage_unavailable")
                return lifecycle.observe_profile_a_storage_binding_for_characterization(
                    self, project_reference,
                )

        retained = []
        unsettled = False
        for previous in references:
            with previous._lock:
                state = previous._state
                integration = previous._worker_storage_integration
            integration_active = False
            integration_uncertain = False
            if integration is not None:
                with integration._lock:
                    integration_active = (integration._state != "closed"
                                          or integration._active is not None)
                    integration_uncertain = bool(integration._uncertain_leases)
            if state != "closed" or integration_active or integration_uncertain:
                retained.append(previous)
                unsettled = True

        with self._lock:
            if (self._closed or self._invalid or not self._profile_a_root_set
                    or tuple(self._host_lifecycle_refs) != references):
                _fail("profile_a_storage_unavailable")
            if unsettled:
                self._host_lifecycle_refs = retained
                _fail("profile_a_storage_lifecycle_unsettled")
            if len(retained) >= _MAX_PROFILE_A_HOST_LIFECYCLES:
                _fail("profile_a_storage_lifecycle_limit_exceeded")
            next_references = [*retained, lifecycle]
            status = lifecycle.observe_profile_a_storage_binding_for_characterization(
                self, project_reference,
            )
            if status == "matched_reference_only":
                self._host_lifecycle_refs = next_references
            return status

    def release_scope_writer_lease_if_settled_for_characterization(self):
        if not self._closed:
            return "owner_open"
        if self._scope_lease is None:
            return "unavailable"
        retention = self._scope_lease_retention_reason()
        if retention == "uncertain":
            return self._scope_lease.retain_uncertain_for_characterization()
        if retention == "active_host":
            return "retained_for_active_host"
        return self._scope_lease.release_settled_for_characterization()

    def _claim_refresh_slot(self):
        """Serialize root observations without holding a mutex during I/O."""
        while True:
            with self._refresh_lock:
                if not self._refresh_active:
                    token = threading.Event()
                    self._refresh_active = True
                    self._refresh_done = token
                    return token
                token = self._refresh_done
            token.wait()

    def _release_refresh_slot(self, token):
        with self._refresh_lock:
            if self._refresh_done is not token:
                return
            self._refresh_active = False
            self._refresh_done = None
        token.set()

    def _refresh_observation(self):
        try:
            with self._lock:
                self._require_live()
                with self._ledger._lock:
                    if self._ledger._active_write is not None:
                        _fail("storage_write_in_progress")
            # Native root/file enumeration and disk-space observation happen
            # with no admission, ledger, or refresh mutex held.
            self._check_roots()
            inventory = self._scan()
            free_bytes = self._free_bytes()
        except ValueError as error:
            if str(error) == "storage_write_in_progress":
                raise
            with self._lock:
                self._invalidate()
            _fail("protected_storage_observation_unavailable")
        except Exception:
            with self._lock:
                self._invalidate()
            _fail("protected_storage_observation_unavailable")
        with self._lock:
            self._require_live()
            try:
                self._ledger.observe_inventory(inventory, free_bytes)
            except ValueError:
                self._invalidate()
                raise

    def _refresh(self):
        token = self._claim_refresh_slot()
        try:
            self._refresh_observation()
        finally:
            self._release_refresh_slot(token)

    def _check_roots(self):
        if self._closed or self._invalid:
            _fail("storage_owner_unavailable")
        for purpose, root in self._roots.items():
            view = root.readiness()
            if (root._closed or root._purpose != purpose or view.get("acl_verified") is not True
                    or root._filesystem != "local_ntfs_observed"):
                _fail("native_root_changed")
            is_directory = purpose != "selected_project_json"
            endpoint = [row for row in root._observations
                        if row[0] == root._path and row[1] is is_directory]
            if (len(endpoint) != 1 or endpoint[0][2] is not root._handle
                    or endpoint[0][3] != root._identity):
                _fail("native_root_identity_changed")
            rows = [row for row in root._observations if row[0] == self._scope and row[1]]
            if (len(rows) != 1 or rows[0][2] is not root._scope_handle
                    or rows[0][3] != self._scope_identity):
                _fail("approved_scope_identity_changed")
        if (self._scope_lease is None
                or self._scope_lease.readiness().get("status") != "held"):
            _fail("scope_writer_lease_unavailable")

    def _scan(self):
        self._check_roots()
        inventory = {purpose: {} for purpose in _WRITABLE}
        for purpose in _WRITABLE:
            root = self._roots[purpose]
            api = root._api
            _, _, files, _, _, _ = api
            try:
                with os.scandir(root._path) as entries:
                    selected = list(entries)
            except OSError:
                _fail("root_inventory_unavailable")
            if len(selected) > _MAX_INVENTORY_ENTRIES:
                _fail("root_inventory_limit_exceeded")
            for entry in selected:
                path = Path(entry.path)
                try:
                    if entry.is_dir(follow_symlinks=False) or entry.is_symlink():
                        _fail("unsupported_root_entry")
                    handle = windows._open(path, False, api)
                    try:
                        identity = windows._identity(handle)
                        acl = windows._acl(handle, api, root._user)
                        native_size = files.GetFileSize(handle)
                        if type(native_size) is not int or not 0 <= native_size <= _MAX_ROOT_FILE_BYTES:
                            _fail("root_file_size_unsupported")
                        if identity != windows._ordinary(path, directory=False):
                            _fail("root_file_identity_changed")
                        inventory[purpose][entry.name] = (identity, native_size, acl)
                    finally:
                        handle.Close()
                except (OSError, ValueError):
                    _fail("root_inventory_unsafe")
        self._check_roots()
        return inventory

    def _free_bytes(self):
        try:
            value = shutil.disk_usage(self._scope).free
        except OSError:
            _fail("disk_capacity_observation_unavailable")
        return _CapacityLedger._validate_free_bytes(value)

    def _require_live(self):
        if self._closed or self._invalid:
            _fail("storage_owner_unavailable")

    def _invalidate(self):
        self._ledger.close()
        self._invalid = True
