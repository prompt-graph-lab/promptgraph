"""Read-only Save As destination snapshots and overwrite freshness checks."""

import copy
import hashlib
import os


def normalize_project_save_as_path(path) -> str:
    """Resolve the exact final path used by Advanced Save As."""

    try:
        path_value = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    if not isinstance(path_value, str) or not path_value.strip():
        return ""
    clean_path = path_value.strip()
    if "\x00" in clean_path:
        return ""
    try:
        return os.path.abspath(os.path.expanduser(clean_path))
    except (OSError, TypeError, ValueError):
        return ""


def inspect_project_save_as_destination(path) -> dict:
    """Return a fail-closed snapshot for one normalized Save As target."""

    normalized_path = normalize_project_save_as_path(path)
    if not normalized_path:
        raise ValueError("Project JSONの保存先が正しくありません。")
    parent_dir = os.path.dirname(normalized_path)
    if not parent_dir or not os.path.isdir(parent_dir):
        raise ValueError(
            "Project JSONの保存先フォルダが見つかりません。"
        )

    snapshot = {
        "normalized_path": normalized_path,
        "occupied": False,
        "kind": "missing",
        "size": None,
        "mtime_ns": None,
        "device": None,
        "inode": None,
        "sha256": "",
    }
    if not os.path.lexists(normalized_path):
        return snapshot
    snapshot["occupied"] = True
    if os.path.islink(normalized_path):
        snapshot["kind"] = "unsupported"
        return snapshot
    if os.path.isdir(normalized_path):
        snapshot["kind"] = "directory"
        return snapshot
    if not os.path.isfile(normalized_path):
        snapshot["kind"] = "unsupported"
        return snapshot

    before_stat = os.stat(normalized_path, follow_symlinks=False)
    digest = hashlib.sha256()
    with open(normalized_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after_stat = os.stat(normalized_path, follow_symlinks=False)
    before_signature = (
        before_stat.st_size,
        before_stat.st_mtime_ns,
        before_stat.st_dev,
        before_stat.st_ino,
    )
    after_signature = (
        after_stat.st_size,
        after_stat.st_mtime_ns,
        after_stat.st_dev,
        after_stat.st_ino,
    )
    if before_signature != after_signature:
        raise OSError(
            "上書き対象が確認中に変更されました。保存先を再確認してください。"
        )
    snapshot.update(
        {
            "kind": "file",
            "size": after_stat.st_size,
            "mtime_ns": after_stat.st_mtime_ns,
            "device": after_stat.st_dev,
            "inode": after_stat.st_ino,
            "sha256": digest.hexdigest(),
        }
    )
    return snapshot


def build_project_save_as_pending_overwrite(
    target_snapshot: dict,
    source_project_path,
    source_project,
) -> dict:
    """Bind an overwrite snapshot to its source Project context."""

    return {
        "target_path": str(target_snapshot.get("normalized_path") or ""),
        "target_snapshot": copy.deepcopy(target_snapshot),
        "source_project_path": normalize_project_save_as_path(
            source_project_path
        ),
        "source_project_object_id": id(source_project),
    }


def project_save_as_confirmation_is_fresh(
    pending,
    current_target_path,
    current_source_project_path,
    current_source_project,
) -> tuple[bool, dict]:
    """Rebuild and compare the overwrite target immediately before save."""

    if not isinstance(pending, dict):
        return False, {}
    pending_snapshot = pending.get("target_snapshot")
    if not isinstance(pending_snapshot, dict):
        return False, {}
    normalized_target = normalize_project_save_as_path(current_target_path)
    normalized_source = normalize_project_save_as_path(
        current_source_project_path
    )
    if not normalized_target:
        return False, {}
    if os.path.normcase(str(pending.get("target_path") or "")) != os.path.normcase(
        normalized_target
    ):
        return False, {}
    if os.path.normcase(
        str(pending.get("source_project_path") or "")
    ) != os.path.normcase(normalized_source):
        return False, {}
    if pending.get("source_project_object_id") != id(current_source_project):
        return False, {}
    try:
        current_snapshot = inspect_project_save_as_destination(
            normalized_target
        )
    except (OSError, TypeError, ValueError):
        return False, {}
    if current_snapshot != pending_snapshot:
        return False, current_snapshot
    return current_snapshot.get("kind") == "file", current_snapshot
