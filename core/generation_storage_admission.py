"""Offline, original-host-owned protected-storage admission characterization.

This owner combines explicit native root observations with process-local
accounting. A reservation is not an OS quota, writer capability, execution
authorization, durable Journal guarantee, or cross-process lock.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import threading

from core import generation_ownership_journal as journal
from core import generation_windows_protected_storage as windows
from core.comfy_output_containment import ContainmentLimits


_FACTORY = object()
_PURPOSES = ("private_journal", "temporary_containment", "retained_uncertain",
             "promoted_assets", "selected_project_json")
_WRITABLE = _PURPOSES[:-1]
_JOURNAL_BYTES = journal.MAX_BYTES
_ASSET_BYTES = ContainmentLimits().aggregate_bytes
_MAX_OPERATION_BYTES = journal.MAX_OPERATION_BYTES + _JOURNAL_BYTES
_MAX_INVENTORY_ENTRIES = 256
_MAX_OPERATION_ENTRIES = 400
_MAX_ASSET_ENTRIES = 16
_MAX_JOURNAL_ENTRIES = 300
_MAX_ROOT_FILE_BYTES = _MAX_OPERATION_BYTES
_MAX_PROCESS_ACCOUNTING_SCOPES = 128

# Successful captures leave a process-local claim until process exit, even
# after close/invalidation, so uncertain reservations cannot be forgotten by
# constructing another ledger over the same writable roots.
_PROCESS_ACCOUNTING_SCOPE_LOCK = threading.Lock()
_PROCESS_ACCOUNTING_SCOPES = set()


def _fail(code):
    raise ValueError(code)


@dataclass(frozen=True)
class CapacityEstimate:
    """Host-supplied upper bound; it is not an observed file measurement."""
    byte_upper_bound: int
    entry_upper_bound: int


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

    def __init__(self, limits):
        if type(limits) is not ProtectedStorageCapacityLimits:
            _fail("invalid_capacity_limits")
        limits.validate()
        self._limits = limits
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
            self._operations[operation] = {"state": "open"}
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

    def complete_write(self, operation, write, inventory, available_free_bytes=None):
        observed_free = (self._validate_free_bytes(available_free_bytes)
                         if available_free_bytes is not None else None)
        with self._lock:
            self._require_live()
            record = self._find_active_write(operation, write)
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
        if characterization is not True or disposable_opt_in is not True:
            _fail("execution_unavailable")
        if type(limits) is not ProtectedStorageCapacityLimits:
            _fail("invalid_capacity_limits")
        limits.validate()
        scope = windows._path(approved_scope)
        if type(purpose_roots) is not dict or set(purpose_roots) != set(_PURPOSES):
            _fail("explicit_purpose_roots_required")
        roots = dict(purpose_roots)
        identities = []
        paths = []
        scope_identity = None
        user_sid = None
        for purpose in _PURPOSES:
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
        if len(set(identities)) != len(_PURPOSES):
            _fail("purpose_alias")
        for index, path in enumerate(paths):
            if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
                   for other in paths[index + 1:]):
                _fail("purpose_overlap")
        # One process-local ledger owns the approved scope. Keying by the
        # complete scope identity prevents alternate or partially overlapping
        # root sets from creating independent capacity ledgers. The selected
        # Project JSON remains a binding input, not capacity storage.
        accounting_key = scope_identity
        with _PROCESS_ACCOUNTING_SCOPE_LOCK:
            if accounting_key in _PROCESS_ACCOUNTING_SCOPES:
                _fail("storage_accounting_scope_already_captured")
            if len(_PROCESS_ACCOUNTING_SCOPES) >= _MAX_PROCESS_ACCOUNTING_SCOPES:
                _fail("storage_accounting_scope_limit_exceeded")
            _PROCESS_ACCOUNTING_SCOPES.add(accounting_key)
        try:
            owner = cls(scope, scope_identity, roots, limits, _factory=_FACTORY)
            inventory = owner._scan()
            free_bytes = owner._free_bytes()
            owner._ledger.set_initial_inventory(inventory, free_bytes)
            # Revalidate after initial inventory; capture is not an ACL repair
            # or directory creation operation.
            owner._check_roots()
            return owner
        except BaseException:
            # No owner escaped and no write admission was possible, so a
            # failed read-only capture may relinquish its provisional claim.
            with _PROCESS_ACCOUNTING_SCOPE_LOCK:
                _PROCESS_ACCOUNTING_SCOPES.discard(accounting_key)
            raise

    def __init__(self, scope, scope_identity, roots, limits, *, _factory=None):
        if _factory is not _FACTORY:
            _fail("host_storage_required")
        self._scope, self._scope_identity = scope, scope_identity
        self._roots, self._limits = roots, limits
        self._ledger = _CapacityLedger(limits)
        self._lock = threading.RLock()
        self._refresh_lock = threading.RLock()
        self._closed = False
        self._invalid = False
        self._asset_writer_integrated = False

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
        self._refresh()
        with self._lock:
            self._require_live()
            return self._ledger.cancel_before_write(operation, reservation)

    def admit_write_for_characterization(self, operation, reservation):
        # Serialize the final pre-write inventory with admission publication.
        # Once the ledger marks a write active, other refreshes refuse to scan
        # its intentionally changing file inventory until exact completion.
        with self._refresh_lock:
            self._refresh()
            with self._lock:
                self._require_live()
                return self._ledger.admit_write(operation, reservation)

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
            self, operation, write_admission, asset_owner, image):
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
        except BaseException:
            self._retain_asset_write(operation, write_admission)
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
                    result = self._ledger.complete_write(
                        operation, write_admission, inventory, free_bytes)
                    self._asset_writer_integrated = True
                    return result
        except BaseException:
            self._retain_asset_write(operation, write_admission)
            raise

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
        with self._lock:
            base = self._ledger.readiness()
            base["writer_integrated"] = self._asset_writer_integrated
            base.update({"filesystem": "local_ntfs_observed" if not self._invalid and not self._closed
                         else "unverified",
                         "native_root_identity": "observed_unchanged" if not self._invalid and not self._closed
                         else "unsafe_or_unavailable",
                         "approved_scope_identity": "observed_unchanged" if not self._invalid and not self._closed
                         else "unsafe_or_unavailable",
                         "directory_durability": "unsupported", "power_loss_guarantee": False,
                         "current_authorization": "absent", "recovery_execution_allowed": False,
                         "project_save_allowed": False, "cleanup_allowed": False})
            return base

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._ledger.close()
            self._closed = True

    def _refresh(self):
        with self._refresh_lock:
            try:
                with self._lock:
                    self._require_live()
                    with self._ledger._lock:
                        if self._ledger._active_write is not None:
                            _fail("storage_write_in_progress")
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
