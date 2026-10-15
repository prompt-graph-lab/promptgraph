"""Offline promotion observations over the original Windows protected owner.

This contract deliberately remains distinct from PromotedImage and
DurableGenerationAssets. It retains native protected files and owner-held
evidence only; it grants no Candidate, Project, executor or Recovery authority.
"""
from dataclasses import dataclass, field
import hashlib
import io
import json
import re
import threading

from core import generation_windows_protected_storage as w
from core.comfy_output_containment import (
    AcceptedProtectedOutputBatch, ProtectedOutputAcceptanceCharacterization,
    SUPPORTED_EXTENSIONS, _validate_binding,
)
from core.comfy_prompt_request import is_owner_prepared_frozen_request
from core.generation_windows_protected_assets import (
    ProtectedImageObservation, VerifiedProtectedImageObservation,
    VerifiedProtectedImageBatchReceipt, WindowsProtectedAssetsCharacterization,
)

_FACTORY = object()
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")


@dataclass(frozen=True)
class ProtectedPromotedImage:
    """One exact descriptor's staging-to-protected-root byte correspondence."""
    descriptor_identity: str = field(repr=False)
    source_observation: VerifiedProtectedImageObservation = field(repr=False)
    promoted_image: ProtectedImageObservation = field(repr=False)


@dataclass(frozen=True)
class VerifiedProtectedPromotionReceipt:
    """Immutable result held by the issuing promotion owner only."""
    identity: str
    accepted_identity: str = field(repr=False)
    batch_identity: str = field(repr=False)
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    request_id: str = field(repr=False)
    request_index: int
    workflow_identity: str = field(repr=False)
    prompt_id: str = field(repr=False)
    remote_receipt_identity: str = field(repr=False)
    images: tuple[ProtectedPromotedImage, ...] = field(repr=False)
    _promotion_owner: object = field(repr=False, compare=False)
    _protected_owner: object = field(repr=False, compare=False)
    _acceptance_owner: object = field(repr=False, compare=False)
    _accepted: AcceptedProtectedOutputBatch = field(repr=False, compare=False)


class ProtectedDurablePromotionCharacterization:
    """One-shot copy from an accepted batch into its original protected root.

    This is characterization-only. The receipt is not PromotedImage custody,
    is not restart-adoptable and cannot be consumed by Candidate publication.
    """
    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    project_save_allowed = False
    recovery_execution_allowed = False
    authorship = "unverified"

    @classmethod
    def create_for_characterization(
            cls, protected_owner, acceptance_owner, accepted, *,
            characterization=False, disposable_opt_in=False):
        if characterization is not True or disposable_opt_in is not True:
            w._fail("execution_unavailable")
        if (type(protected_owner) is not WindowsProtectedAssetsCharacterization
                or type(acceptance_owner) is not ProtectedOutputAcceptanceCharacterization
                or type(accepted) is not AcceptedProtectedOutputBatch):
            w._fail("protected_promotion_binding_invalid")
        batch = accepted._batch_receipt
        prepared, remote = accepted._prepared, accepted._remote
        try:
            if (accepted._protected_owner is not protected_owner
                    or acceptance_owner._protected_owner is not protected_owner
                    or acceptance_owner._envelope is not accepted._envelope
                    or acceptance_owner._prepared is not prepared
                    or acceptance_owner._remote is not remote
                    or acceptance_owner._batch_receipt is not batch
                    or acceptance_owner._host_freshness is not accepted._host_freshness
                    or type(batch) is not VerifiedProtectedImageBatchReceipt
                    or not is_owner_prepared_frozen_request(prepared)
                    or remote.execution_succeeded is not True):
                raise ValueError()
            _validate_binding(accepted._envelope, prepared, remote)
            key = (prepared.request_id, remote.identity)
            with protected_owner._lock:
                if (protected_owner._closed or protected_owner._invalid or protected_owner._uncertain
                        or not protected_owner._writable):
                    raise ValueError()
                binding = protected_owner._stream_bindings.get(prepared.request_id)
                if (protected_owner._stream_envelope is not accepted._envelope
                        or binding is None or binding[0] is not prepared or binding[1] is not remote
                        or protected_owner._stream_batches.get(key) is not batch
                        or protected_owner._stream_batch_freshness.get(key) is not accepted._host_freshness
                        or protected_owner._stream_batch_acceptances.get(key) is not accepted):
                    raise ValueError()
                with acceptance_owner._lock:
                    if (acceptance_owner._closed or acceptance_owner._invalid
                            or acceptance_owner._uncertain or acceptance_owner._busy
                            or acceptance_owner._receipt is not accepted):
                        raise ValueError()
                    descriptors = tuple(remote.images)
                    observations = batch.observations
                    ids = tuple(item.identity for item in descriptors)
                    if (not descriptors or len(set(ids)) != len(ids)
                            or type(observations) is not tuple or len(observations) != len(descriptors)
                            or accepted.image_count != len(descriptors)
                            or accepted.identity != acceptance_owner._receipt.identity
                            or accepted.batch_identity != batch.identity
                            or tuple(item.descriptor_identity for item in observations) != ids):
                        raise ValueError()
                    for descriptor, observation in zip(descriptors, observations):
                        if (type(observation) is not VerifiedProtectedImageObservation
                                or protected_owner._stream_images.get((prepared.request_id, descriptor.identity))
                                is not observation
                                or observation.job_id != remote.job_id
                                or observation.claim_id != remote.claim_id
                                or observation.manifest_identity != remote.manifest_identity
                                or observation.request_id != prepared.request_id
                                or observation.request_index != prepared.request_index
                                or observation.workflow_identity != prepared.workflow_identity
                                or observation.prompt_id != remote.prompt_id
                                or observation.remote_receipt_identity != remote.identity
                                or type(observation.image) is not ProtectedImageObservation
                                or observation.image.purpose != "temporary_containment"
                                or observation.image.storage_identity not in {
                                    path.name for path, *_ in protected_owner._files.values()
                                    if path.parent == protected_owner._roots["temporary_containment"]._path
                                }):
                            raise ValueError()
        except Exception:
            w._fail("protected_promotion_binding_invalid")
        return cls(protected_owner, acceptance_owner, accepted, _factory=_FACTORY)

    def __init__(self, protected_owner, acceptance_owner, accepted, *, _factory=None):
        if _factory is not _FACTORY:
            w._fail("host_protected_promotion_required")
        self._protected_owner, self._acceptance_owner, self._accepted = (
            protected_owner, acceptance_owner, accepted)
        self._lock = threading.RLock()
        self._attempted = self._busy = self._closed = self._uncertain = False
        self._receipt = None

    def _build_receipt(self, images):
        accepted = self._accepted
        batch, prepared, remote = accepted._batch_receipt, accepted._prepared, accepted._remote
        rows = tuple(images)
        payload = [
            "promptgraph.protected-durable-promotion.v1", accepted.identity, batch.identity,
            remote.job_id, remote.claim_id, remote.manifest_identity, prepared.request_id,
            prepared.request_index, prepared.workflow_identity, remote.prompt_id, remote.identity,
            [[row.descriptor_identity,
              row.source_observation.image.storage_identity,
              row.source_observation.image.content_sha256,
              row.promoted_image.storage_identity, row.promoted_image.content_sha256,
              row.promoted_image.byte_count, row.promoted_image.image_format,
              row.promoted_image.width, row.promoted_image.height] for row in rows],
        ]
        identity = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        return VerifiedProtectedPromotionReceipt(
            identity, accepted.identity, batch.identity, remote.job_id, remote.claim_id,
            remote.manifest_identity, prepared.request_id, prepared.request_index,
            prepared.workflow_identity, remote.prompt_id, remote.identity, rows,
            self, self._protected_owner, self._acceptance_owner, accepted)

    def _read_source_bytes(self, descriptor, observation):
        protected = self._protected_owner
        image = observation.image
        key = (image.purpose, image.storage_identity)
        with protected._lock:
            if (protected._stream_images.get((observation.request_id, descriptor.identity)) is not observation
                    or protected._images.get(key) is not image):
                w._fail("protected_promotion_source_mismatch")
            protected._check()
            record = protected._files.get(key)
            if record is None:
                w._fail("protected_promotion_source_mismatch")
            path = record[0]
            extension = path.suffix[1:]
            if extension not in SUPPORTED_EXTENSIONS or descriptor.image_format != extension:
                w._fail("protected_promotion_source_mismatch")
            if protected._observe(image.storage_identity, image.purpose, extension) != image:
                w._fail("protected_promotion_source_changed")
            data = protected._bytes(record)
            image_format, width, height = protected._verifier._verify(io.BytesIO(data), extension)
            if (len(data) != image.byte_count or hashlib.sha256(data).hexdigest() != image.content_sha256
                    or (image_format, width, height) != (image.image_format, image.width, image.height)):
                w._fail("protected_promotion_source_changed")
            protected._check()
            return data, extension

    def promote_for_characterization(self):
        with self._lock:
            if self._closed:
                w._fail("promotion_closed")
            if self._attempted:
                w._fail("promotion_already_attempted")
            if self._uncertain:
                w._fail("promotion_uncertain")
            self._attempted = self._busy = True

        protected, acceptance, accepted = self._protected_owner, self._acceptance_owner, self._accepted
        prepared, remote = accepted._prepared, accepted._remote
        key = (prepared.request_id, remote.identity)
        claimed = False
        try:
            protected._claim_protected_promotion_for_characterization(self, acceptance, accepted, key)
            claimed = True
            # Acceptance inspection performs exact original-host freshness and
            # complete source native/content verification outside owner locks.
            acceptance.inspect_for_characterization(accepted)
            batch = accepted._batch_receipt
            descriptors = tuple(remote.images)
            sources = tuple(batch.observations)
            if (not descriptors or len(descriptors) != len(sources)
                    or tuple(item.descriptor_identity for item in sources)
                    != tuple(item.identity for item in descriptors)):
                w._fail("protected_promotion_incomplete")
            expected_bytes = sum(item.image.byte_count for item in sources)
            with protected._lock:
                protected._check()
                if (len(protected._files) + len(protected._unobserved_files) + len(sources)
                        > protected._limits.images
                        or protected._used_bytes + expected_bytes > protected._limits.aggregate_bytes
                        or any(item.image.byte_count <= 0
                               or item.image.byte_count > min(protected._limits.image_bytes,
                                                              protected._limits.request_bytes)
                               for item in sources)):
                    w._fail("storage_capacity")

            promoted = []
            for descriptor, source in zip(descriptors, sources):
                if source.image.purpose != "temporary_containment":
                    w._fail("protected_promotion_source_mismatch")
                data, extension = self._read_source_bytes(descriptor, source)
                destination = protected.create_image_for_characterization(
                    "promoted_assets", data, extension=extension, _promotion_owner=self)
                if (destination.purpose != "promoted_assets"
                        or destination.byte_count != source.image.byte_count
                        or destination.content_sha256 != source.image.content_sha256
                        or (destination.image_format, destination.width, destination.height)
                        != (source.image.image_format, source.image.width, source.image.height)):
                    w._fail("protected_promotion_destination_mismatch")
                if protected.inspect_image_for_characterization(destination) is not destination:
                    w._fail("protected_promotion_destination_mismatch")
                promoted.append(ProtectedPromotedImage(descriptor.identity, source, destination))

            # Recheck both sides after the last native destination verification.
            acceptance.inspect_for_characterization(accepted)
            for row in promoted:
                protected.inspect_image_for_characterization(row.promoted_image)
            receipt = self._build_receipt(promoted)
            # Destination verification may be slow. Recheck the exact original
            # host binding after it, immediately before joint publication.
            acceptance.inspect_for_characterization(accepted)

            # Serialize publication against protected close and acceptance
            # close/invalidation. Preserve protected -> acceptance lock order;
            # the host-freshness callback has already completed outside locks.
            with protected._lock:
                protected._check()
                inventory = {(purpose, path.name)
                             for purpose, _, path in protected._inventory()}
                if inventory != set(protected._files):
                    protected._uncertain = True
                    w._fail("unexpected_existing_file")
                if (not protected._promotion_busy or protected._promotion_owner is not self
                        or key not in protected._stream_promotion_attempts
                        or key in protected._stream_promotions
                        or protected._stream_batch_acceptances.get(key) is not accepted):
                    w._fail("protected_promotion_invalidated")
                with acceptance._lock:
                    if (acceptance._closed or acceptance._invalid or acceptance._uncertain
                            or acceptance._busy or acceptance._receipt is not accepted
                            or accepted._protected_owner is not protected
                            or accepted._batch_receipt is not batch):
                        w._fail("protected_promotion_invalidated")
                    with self._lock:
                        if self._closed or self._uncertain or self._receipt is not None:
                            w._fail("protected_promotion_invalidated")
                        protected._stream_promotions[key] = receipt
                        self._receipt = receipt
            return receipt
        except BaseException as error:
            with self._lock:
                self._uncertain = True
            if claimed:
                with protected._lock:
                    protected._uncertain = True
            if isinstance(error, ValueError) and _SAFE_ERROR.fullmatch(str(error)):
                raise
            w._fail("protected_promotion_uncertain")
        finally:
            with self._lock:
                self._busy = False
            if claimed:
                with protected._lock:
                    if protected._promotion_owner is self:
                        protected._promotion_busy = False
                        protected._promotion_owner = protected._promotion_thread = None

    def inspect_for_characterization(self, receipt=None):
        with self._lock:
            if self._closed:
                w._fail("promotion_closed")
            if self._uncertain:
                w._fail("promotion_uncertain")
            current = self._receipt
            if (type(current) is not VerifiedProtectedPromotionReceipt
                    or (receipt is not None and receipt is not current)):
                w._fail("promotion_owner_mismatch")
        protected, acceptance, accepted = self._protected_owner, self._acceptance_owner, self._accepted
        if (current._promotion_owner is not self or current._protected_owner is not protected
                or current._acceptance_owner is not acceptance or current._accepted is not accepted):
            w._fail("promotion_owner_mismatch")
        try:
            acceptance.inspect_for_characterization(accepted)
            for item in current.images:
                protected.inspect_image_for_characterization(item.promoted_image)
            acceptance.inspect_for_characterization(accepted)
            key = (accepted._prepared.request_id, accepted._remote.identity)
            with protected._lock:
                protected._check()
                with acceptance._lock:
                    if (protected._stream_promotions.get(key) is not current
                            or protected._stream_batch_acceptances.get(key) is not accepted
                            or acceptance._closed or acceptance._invalid or acceptance._uncertain
                            or acceptance._receipt is not accepted):
                        w._fail("protected_promotion_invalidated")
                    with self._lock:
                        if self._closed or self._uncertain or self._receipt is not current:
                            w._fail("protected_promotion_invalidated")
                        return current
        except BaseException:
            with self._lock:
                self._uncertain = True
            raise

    def close(self):
        with self._lock:
            self._closed = True

    def readiness(self):
        with self._lock:
            state = ("closed" if self._closed else "uncertain" if self._uncertain
                     else "promoted" if self._receipt else "available")
            return {
                "promotion": state,
                "image_count": len(self._receipt.images) if self._receipt else 0,
                "execution_available": False,
                "protected_storage_available": False,
                "promotion_available": False,
                "candidate_publication_allowed": False,
                "project_save_allowed": False,
                "recovery_execution_allowed": False,
                "human_start_allowed": False,
                "attachment_allowed": False,
                "publication_allowed": False,
                "journal_mutation_allowed": False,
                "cleanup_allowed": False,
                "retry_allowed": False,
                "power_loss_guarantee": False,
                "same_user_process_authentication": False,
                "cross_file_transaction": False,
                "directory_durability": "unsupported",
                "power_loss_durability": "unsupported",
                "authorship": "unverified",
            }
