"""C2B-6 durable asset custody; explicit disposable characterization only.

No Project mutation, download, retry, overwrite or automatic cleanup. The host
freezes the approved directory before creating this owner. All I/O is unlocked.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import uuid

from core.comfy_output_containment import (
    ContainedOutputStore, _ordinary, _file_identity, CHUNK_BYTES,
)


@dataclass(frozen=True)
class PromotedImage:
    image: object = field(repr=False)
    path: str = field(repr=False)
    file_identity: tuple = field(repr=False)


class DurableGenerationAssets:
    execution_available = False

    @classmethod
    def create_for_characterization(cls, approved_directory, *, characterization=False):
        if characterization is not True:
            raise ValueError("execution_unavailable")
        parent = Path(approved_directory)
        if not parent.is_absolute() or parent.resolve() != parent:
            raise ValueError("unsafe_destination")
        parent_id = _file_identity(_ordinary(parent, directory=True))
        root = parent / ("promptgraph-generation-assets-" + uuid.uuid4().hex)
        root.mkdir(mode=0o700)
        root_id = _file_identity(_ordinary(root, directory=True))
        owner = cls(parent, parent_id, root, root_id, _factory=_FACTORY)
        owner._check()
        return owner

    def __init__(self, parent, parent_id, root, root_id, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("host_storage_required")
        self._parent, self._parent_id = parent, parent_id
        self._root, self._root_id = root, root_id
        self._attempts, self._retained = {}, []

    def _check(self):
        if (self._parent.resolve() != self._parent or self._root.resolve() != self._root
                or _file_identity(_ordinary(self._parent, directory=True)) != self._parent_id
                or _file_identity(_ordinary(self._root, directory=True)) != self._root_id):
            raise ValueError("unsafe_destination")

    def promote_for_characterization(self, store, envelope, remote, local):
        if (type(store) is not ContainedOutputStore or store._envelope is not envelope
                or store._remote.get(local.request_id) is not remote
                or store._records.get(local.request_id) is not local
                or local.state != "verified" or not remote.execution_succeeded):
            raise ValueError("receipt_owner_mismatch")
        if local.request_id in self._attempts:
            raise ValueError("promotion_already_attempted")
        self._attempts[local.request_id] = "promoting"  # pin even interrupted work
        promoted = []
        try:
            self._check()
            if self._root.is_relative_to(store._root):
                raise ValueError("temporary_destination")
            store.revalidate_for_characterization(local)
            for image in local.images:
                source_path, source_id, directory_id = store._storage[image.storage_identity]
                store._check_file(source_path, source_id, source_path.parent, directory_id)
                extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "BMP": "bmp"}[image.image_format]
                self._check()
                path = self._root / (uuid.uuid4().hex + "." + extension)
                flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                source_fd = os.open(source_path, os.O_RDONLY | flags)
                with os.fdopen(source_fd, "rb") as source:
                    if _file_identity(os.fstat(source.fileno())) != source_id:
                        raise ValueError("source_identity_changed")
                    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | flags, 0o600)
                    identity = _file_identity(os.fstat(fd))
                    self._retained.append((str(path), identity))
                    with os.fdopen(fd, "w+b") as target:
                        count = 0
                        while count < image.byte_count:
                            chunk = source.read(min(CHUNK_BYTES, image.byte_count - count))
                            if not chunk:
                                raise ValueError("source_content_changed")
                            target.write(chunk)
                            count += len(chunk)
                        if source.read(1):
                            raise ValueError("source_content_changed")
                        target.flush()
                        os.fsync(target.fileno())
                        if store._content_hash(target, image.byte_count) != image.content_sha256:
                            raise ValueError("promoted_content_changed")
                promoted.append(PromotedImage(image, str(path), identity))
            store.revalidate_for_characterization(local)
            self.revalidate_for_characterization(tuple(promoted))
            self._attempts[local.request_id] = tuple(promoted)
            return tuple(promoted)
        except Exception:
            self._attempts[local.request_id] = "promotion_failed"
            raise ValueError("promotion_failed") from None

    def revalidate_for_characterization(self, images):
        self._check()
        for promoted in images:
            path = Path(promoted.path)
            if path.parent != self._root:
                raise ValueError("unsafe_destination")
            if _file_identity(_ordinary(path, directory=False)) != promoted.file_identity:
                raise ValueError("promoted_identity_changed")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            with os.fdopen(fd, "rb") as source:
                if (_file_identity(os.fstat(source.fileno())) != promoted.file_identity
                        or ContainedOutputStore._content_hash(source, promoted.image.byte_count)
                           != promoted.image.content_sha256):
                    raise ValueError("promoted_content_changed")
            if _file_identity(_ordinary(path, directory=False)) != promoted.file_identity:
                raise ValueError("promoted_identity_changed")
        self._check()


_FACTORY = object()
