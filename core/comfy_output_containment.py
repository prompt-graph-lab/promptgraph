"""Private C2B-5 local custody. Offline injected streams only; no publication.

Only the host factory allocates a destination, outside Project/Gallery storage.
This owner has no job locks, network default, retry, worker or automatic cleanup.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
import warnings

from PIL import Image, ImageFile

from core.comfy_prompt_request import FrozenPromptRequest, prepare_frozen_prompt_request
from core.comfy_remote_output_receipts import (
    RemoteOutputReceipt, validate_remote_outputs,
    MAX_REMOTE_BYTES, MAX_REMOTE_IMAGES,
)

CHUNK_BYTES = 64 * 1024
SUPPORTED_EXTENSIONS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "bmp": "BMP"}


@dataclass(frozen=True)
class ContainmentLimits:
    image_bytes: int = 32 * 1024 * 1024
    request_bytes: int = 128 * 1024 * 1024
    aggregate_bytes: int = 256 * 1024 * 1024
    images: int = 16
    dimension: int = 8192
    pixels: int = 16 * 1024 * 1024


@dataclass(frozen=True)
class ImageDownloadLookup:
    """Frozen /view lookup, no arbitrary URL or local destination parameter.

    Future transport must build /view on endpoint_origin and refuse redirects
    outside that origin. This PR supplies no transport implementation.
    """
    endpoint_origin: str = field(repr=False)
    filename: str = field(repr=False)
    subfolder: str = field(repr=False)
    bucket: str
    descriptor_identity: str


@dataclass(frozen=True)
class DownloadStream:
    """Fake contract: declared exact length + read(max_bytes) + close()."""
    content_length: int
    read: object = field(repr=False)
    close: object = field(repr=False)


@dataclass(frozen=True)
class VerifiedLocalImage:
    descriptor_identity: str
    content_sha256: str
    image_format: str
    width: int
    height: int
    byte_count: int
    storage_identity: str = field(repr=False)


@dataclass(frozen=True)
class LocalOutputReceipt:
    """Private bounded evidence, never Candidate/persistence authority or paths."""
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    request_id: str = field(repr=False)
    request_index: int
    workflow_identity: str = field(repr=False)
    prompt_id: str = field(repr=False)
    remote_receipt_identity: str
    identity: str
    state: str
    failure_code: str
    images: tuple[VerifiedLocalImage, ...] = field(repr=False)
    downloaded_count: int = 0
    retained_storage_identities: tuple[str, ...] = field(default=(), repr=False)

    @property
    def verified_count(self):
        return len(self.images)


class _ContainmentFailure(Exception):
    pass


def _file_identity(info):
    return info.st_dev, info.st_ino


def _ordinary(path, *, directory):
    """lstat every ancestor: also covers Windows junction/reparse points."""
    path = Path(path)
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise _ContainmentFailure("unsafe_storage")
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            raise _ContainmentFailure("unsafe_storage")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise _ContainmentFailure("unsafe_storage")
    return info


def _validate_binding(envelope, prepared, remote):
    if (type(remote) is not RemoteOutputReceipt or type(remote.execution_succeeded) is not bool
            or type(remote.images) is not tuple or not 1 <= len(remote.images) <= MAX_REMOTE_IMAGES
            or type(remote.encoded_size) is not int or not 0 < remote.encoded_size <= MAX_REMOTE_BYTES
            or type(prepared) is not FrozenPromptRequest
            or type(prepared.request_index) is not int
            or not 0 <= prepared.request_index < len(envelope.manifest.requests)):
        raise _ContainmentFailure("remote_correlation_mismatch")
    if prepared != prepare_frozen_prompt_request(envelope.manifest,
            envelope.manifest.requests[prepared.request_index], client_id=prepared.client_id):
        raise _ContainmentFailure("remote_correlation_mismatch")
    # Revalidate the original history, including its explicit execution status.
    # A replaced summary boolean cannot manufacture missing success evidence.
    # Compare every correlation field and descriptor, not just opaque digests.
    checked = validate_remote_outputs(envelope, prepared, remote.prompt_id,
        remote._validated_history_json)
    if checked != remote:
        raise _ContainmentFailure("remote_correlation_mismatch")


class ContainedOutputStore:
    """Single host-owned store with atomic request receipts and pinned attempts.

    Files survive close/GC/expiry. No path setter or auto-delete exists. Failed
    attempts are remembered, preventing ambiguous retry. Stale complete bytes
    remain in quarantine. Explicit human recovery/retention is a later slice.
    """
    execution_available = False

    @classmethod
    def create_for_characterization(cls, *, characterization=False, limits=ContainmentLimits()):
        if characterization is not True:
            raise ValueError("execution_unavailable")
        defaults = ContainmentLimits()
        if (type(limits) is not ContainmentLimits or any(type(value) is not int or not 0 < value <= getattr(defaults, key)
                for key, value in vars(limits).items())
                or not limits.image_bytes <= limits.request_bytes <= limits.aggregate_bytes):
            raise ValueError("invalid_storage_limits")
        parent = Path(tempfile.gettempdir()).absolute()
        _ordinary(parent, directory=True)
        # mkdtemp allocates exclusively. No TemporaryDirectory finalizer removes
        # evidence on session close; no supplied Project/export path is accepted.
        root = Path(tempfile.mkdtemp(prefix="promptgraph-generation-", dir=parent))
        info = _ordinary(root, directory=True)
        if root.resolve() != root:
            raise ValueError("unsafe_storage")
        return cls(root, _file_identity(info), limits, _factory=_FACTORY)

    def __init__(self, root, root_identity, limits, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("host_storage_required")
        self._root, self._root_identity, self._limits = root, root_identity, limits
        self._records, self._remote, self._storage = {}, {}, {}
        self._envelope = None
        self._used_bytes = 0
        self._busy = False

    def _check_root(self):
        if (_file_identity(_ordinary(self._root, directory=True)) != self._root_identity
                or self._root.resolve() != self._root):
            raise _ContainmentFailure("unsafe_storage")

    def stage_for_characterization(self, envelope, prepared, remote, *, fake_stream_provider):
        """Disk and decode work must run outside all host/job/inbox locks."""
        try:
            _validate_binding(envelope, prepared, remote)
        except Exception:
            raise ValueError("remote_correlation_mismatch") from None
        if self._envelope is not None and self._envelope is not envelope:
            raise ValueError("storage_owner_mismatch")
        self._envelope = envelope
        key = remote.request_id
        previous = self._records.get(key)
        if previous is not None:
            if self._remote[key] != remote:
                raise ValueError("local_receipt_conflict")
            return self.revalidate_for_characterization(previous)  # no second provider call
        if self._busy:
            raise ValueError("storage_busy")
        if len(self._records) >= 100:
            raise ValueError("storage_capacity")
        if not remote.execution_succeeded:
            return self._remember(remote, "quarantined", "execution_success_unproven", (), 0)
        if (len(remote.images) > self._limits.images or not callable(fake_stream_provider)):
            return self._remember(remote, "incomplete", "download_contract_invalid", (), 0)
        self._busy = True
        owned, verified, downloaded, complete_paths = [], [], 0, set()
        directory = None
        request_bytes = 0
        try:
            self._check_root()
            directory = self._root / uuid.uuid4().hex
            directory.mkdir(mode=0o700)  # exclusive, never exist_ok
            directory_identity = _file_identity(_ordinary(directory, directory=True))
            for descriptor in remote.images:
                self._check_directory(directory, directory_identity)
                if descriptor.image_format not in SUPPORTED_EXTENSIONS:
                    raise _ContainmentFailure("unsupported_image_format")
                storage_id = uuid.uuid4().hex
                path = directory / storage_id  # remote names never enter paths
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                fd = os.open(path, flags, 0o600)
                file_id = _file_identity(os.fstat(fd))
                owned.append((path, file_id, 0))
                with os.fdopen(fd, "w+b") as output:
                    self._check_file(path, file_id, directory, directory_identity)
                    lookup = ImageDownloadLookup(prepared.prompt_url.removesuffix("/prompt"),
                        descriptor.filename, descriptor.subfolder, descriptor.bucket, descriptor.identity)
                    stream = None
                    try:
                        stream = fake_stream_provider(lookup)
                        if (type(stream) is not DownloadStream or type(stream.content_length) is not int
                                or not callable(stream.read) or not callable(stream.close)):
                            raise _ContainmentFailure("download_contract_invalid")
                        length = stream.content_length
                        if length <= 0:
                            raise _ContainmentFailure("empty_download")
                        if (length > self._limits.image_bytes or request_bytes + length > self._limits.request_bytes
                                or self._used_bytes + length > self._limits.aggregate_bytes):
                            raise _ContainmentFailure("download_size_limit")
                        count, digest = 0, hashlib.sha256()
                        while True:
                            limit = min(CHUNK_BYTES, length - count + 1)
                            chunk = stream.read(limit)
                            if type(chunk) is not bytes or len(chunk) > limit:
                                raise _ContainmentFailure("download_contract_invalid")
                            if not chunk:
                                if count != length:
                                    raise _ContainmentFailure("short_download")
                                break
                            if count + len(chunk) > length:
                                raise _ContainmentFailure("download_size_limit")
                            output.write(chunk)
                            count += len(chunk)
                            request_bytes += len(chunk)
                            self._used_bytes += len(chunk)
                            owned[-1] = (path, file_id, count)
                            digest.update(chunk)
                        downloaded += 1
                        complete_paths.add(path)
                        self._storage[storage_id] = (path, file_id, directory_identity)
                    except _ContainmentFailure:
                        raise
                    except Exception:
                        raise _ContainmentFailure("download_interrupted") from None
                    finally:
                        if type(stream) is DownloadStream and callable(stream.close):
                            try:
                                stream.close()
                            except Exception:
                                raise _ContainmentFailure("download_interrupted") from None
                    output.flush()
                    os.fsync(output.fileno())
                    self._check_file(path, file_id, directory, directory_identity)
                    image_format, width, height = self._verify(output, descriptor.image_format)
                    # Identity covers the actual decoded file, including any
                    # provider-side modification, not merely streamed chunks.
                    if self._content_hash(output, count) != digest.hexdigest():
                        raise _ContainmentFailure("local_content_conflict")
                    verified.append(VerifiedLocalImage(descriptor.identity, digest.hexdigest(), image_format,
                        width, height, count, storage_id))
            self._check_directory(directory, directory_identity)
            for path, file_id, _ in owned:
                self._check_file(path, file_id, directory, directory_identity)
            # Receipt insertion is the atomic commit; directory/files stay private.
            return self._remember(remote, "verified", "", tuple(verified), downloaded,
                                  tuple(path.name for path, _, _ in owned))
        except Exception as error:
            code = str(error) if type(error) is _ContainmentFailure else "storage_unavailable"
            # Fully downloaded files remain isolated evidence, even when another
            # image fails. Remove only incomplete own files with unchanged identity.
            retained = []
            for path, file_id, count in owned:
                if path in complete_paths:
                    retained.append(path.name)
                    continue
                try:
                    self._check_file(path, file_id, directory, directory_identity)
                    path.unlink()
                    self._used_bytes -= count
                except Exception:
                    retained.append(path.name)
                    self._storage[path.name] = (path, file_id, directory_identity)
                    # uncertain location remains pinned; never follow a link
            return self._remember(remote, "quarantined" if downloaded else "incomplete", code,
                                  tuple(verified), downloaded, tuple(retained))
        finally:
            self._busy = False

    def _check_directory(self, directory, identity):
        self._check_root()
        if directory.parent != self._root or _file_identity(_ordinary(directory, directory=True)) != identity:
            raise _ContainmentFailure("unsafe_storage")

    def _check_file(self, path, identity, directory, directory_identity):
        self._check_directory(directory, directory_identity)
        if path.parent != directory or _file_identity(_ordinary(path, directory=False)) != identity:
            raise _ContainmentFailure("unsafe_storage")

    def _verify(self, output, extension):
        try:
            # Never relax or mutate Pillow's process-global bomb/truncation policy.
            if ImageFile.LOAD_TRUNCATED_IMAGES:
                raise _ContainmentFailure("image_policy_unavailable")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                output.seek(0)
                with Image.open(output, formats=list(set(SUPPORTED_EXTENSIONS.values()))) as image:
                    image_format, (width, height) = image.format, image.size
                    if image_format != SUPPORTED_EXTENSIONS[extension]:
                        raise _ContainmentFailure("image_format_mismatch")
                    if (not 0 < width <= self._limits.dimension or not 0 < height <= self._limits.dimension
                            or width * height > self._limits.pixels):
                        raise _ContainmentFailure("image_dimension_limit")
                    if getattr(image, "n_frames", 1) != 1:
                        raise _ContainmentFailure("unsupported_image_format")
                    image.verify()
                output.seek(0)
                with Image.open(output, formats=[image_format]) as image:
                    image.load()  # verify() alone does not prove successful decode
            return image_format, width, height
        except _ContainmentFailure:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise _ContainmentFailure("image_dimension_limit") from None
        except Exception:
            raise _ContainmentFailure("invalid_image_content") from None

    @staticmethod
    def _content_hash(source, expected_size):
        source.seek(0)
        count, digest = 0, hashlib.sha256()
        while True:
            chunk = source.read(min(CHUNK_BYTES, expected_size - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > expected_size:
                raise _ContainmentFailure("local_content_conflict")
            digest.update(chunk)
        if count != expected_size:
            raise _ContainmentFailure("local_content_conflict")
        return digest.hexdigest()

    def revalidate_for_characterization(self, receipt):
        """Unlocked integrity check only; never re-download or restore custody."""
        if self._records.get(receipt.request_id) is not receipt:
            raise ValueError("local_receipt_conflict")
        if receipt.state != "verified":
            return receipt
        try:
            for image in receipt.images:
                path, identity, directory_identity = self._storage[image.storage_identity]
                self._check_file(path, identity, path.parent, directory_identity)
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
                with os.fdopen(fd, "rb") as source:
                    if _file_identity(os.fstat(source.fileno())) != identity:
                        raise _ContainmentFailure("unsafe_storage")
                    if self._content_hash(source, image.byte_count) != image.content_sha256:
                        raise _ContainmentFailure("local_content_conflict")
                self._check_file(path, identity, path.parent, directory_identity)
        except Exception:
            self._records[receipt.request_id] = replace(receipt, state="quarantined", failure_code="storage_integrity_lost")
            raise ValueError("local_content_conflict") from None
        return receipt

    def _remember(self, remote, state, code, images, downloaded, retained=()):
        identity = hashlib.sha256(json.dumps([remote.identity, state, code,
            [[i.descriptor_identity, i.content_sha256, i.image_format, i.width, i.height,
              i.byte_count, i.storage_identity] for i in images]],
            separators=(",", ":")).encode()).hexdigest()
        receipt = LocalOutputReceipt(remote.job_id, remote.claim_id, remote.manifest_identity,
            remote.request_id, remote.request_index, remote.workflow_identity, remote.prompt_id,
            remote.identity, identity, state, code, images, downloaded, retained)
        self._records[remote.request_id], self._remote[remote.request_id] = receipt, remote
        return receipt

    def quarantine_for_characterization(self, receipt):
        if self._records.get(receipt.request_id) is not receipt:
            raise ValueError("local_receipt_conflict")
        if receipt.state == "verified":
            receipt = replace(receipt, state="quarantined", failure_code="host_custody_invalidated")
            self._records[receipt.request_id] = receipt
        return receipt

    def receipts_for_characterization(self):
        return tuple(self._records.values())


_FACTORY = object()
