"""Module-vNext container compatibility policy (public P0 reservation).

A Project Module entry may carry the reserved, additive, Project-local field
``reference_assets``: a versioned envelope (integer ``format``; format 1 is the
first reserved representation) whose ordered ``assets`` describe Module-level
visual references stored as files under the reserved Project-local namespace
``refs/modules/``.

Public PromptGraph does not interpret, validate, resolve, read, copy, create or
delete that data. It only guarantees three things:

- inside one Project, the field is preserved like any other unknown extension
  field (normalize, load, save and prompt-field edits keep it);
- a Module copied into a prompt-only container (the Global Module Library, a
  Derived Project, a Scene Template v1 snapshot) never carries it, because its
  Project-relative paths would not resolve there; and
- a JSON-only Advanced Save As never moves it to another folder, because no
  Module asset file is copied.

This module never reads, lists or copies a Module asset file. The Save As
gate only normalizes the two Project JSON paths it is given.
"""

import copy
import os
from typing import Any, Dict, Mapping

REFERENCE_ASSETS_FIELD = "reference_assets"
MODULE_ASSET_NAMESPACE = ("refs", "modules")


def module_has_reference_assets(entry: Any) -> bool:
    """Return True when a Module entry carries the reserved top-level field.

    Presence is what matters, whatever the value: the content is opaque to
    public, and an empty or malformed envelope is still Project-local state.
    """
    return isinstance(entry, Mapping) and REFERENCE_ASSETS_FIELD in entry


def module_entry_for_prompt_only_container(entry: Any) -> Any:
    """Return a deep copy of ``entry`` without the reserved top-level field.

    Every other field, including unknown extension metadata and nested values
    that merely look like paths, is kept exactly. The source is never mutated.
    """
    projected = copy.deepcopy(entry)
    if isinstance(projected, dict):
        projected.pop(REFERENCE_ASSETS_FIELD, None)
    return projected


def module_library_for_prompt_only_container(library: Any) -> Dict[str, Any]:
    """Project a Module library for a prompt-only container.

    Names and insertion order are kept; each entry goes through
    :func:`module_entry_for_prompt_only_container`. The source is never mutated.
    """
    if not isinstance(library, Mapping):
        return {}
    return {
        name: module_entry_for_prompt_only_container(entry)
        for name, entry in library.items()
    }


def count_modules_with_reference_assets(library: Any) -> int:
    """Count Module entries that carry the reserved field (content-free)."""
    if not isinstance(library, Mapping):
        return 0
    return sum(1 for entry in library.values() if module_has_reference_assets(entry))


def project_has_module_reference_assets(project: Any) -> bool:
    """Return True when any Project Module carries ``reference_assets``."""
    return count_modules_with_reference_assets(getattr(project, "module_library", None)) > 0


MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE = (
    "このProjectにはModuleのビジュアル参照が含まれています。"
    "Project JSONだけのSave Asでは別フォルダへ移せません。"
    "Project全体をコピーするには「プロジェクトディレクトリを複製して開く」"
    "(Duplicate Project) を使ってください。"
)
MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE = (
    "このProjectにはModuleのビジュアル参照が含まれていますが、"
    "現在のProjectフォルダを特定できないため、Project JSONだけのSave Asはできません。"
    "保存済みProjectから「プロジェクトディレクトリを複製して開く」"
    "(Duplicate Project) を使ってください。"
)


def _project_json_base_directory(path: Any) -> str:
    """Return the comparable folder of a Project JSON path, or "" if unclear."""
    try:
        path_value = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    if not isinstance(path_value, str) or not path_value.strip() or "\x00" in path_value:
        return ""
    try:
        absolute = os.path.abspath(os.path.expanduser(path_value.strip()))
        directory = os.path.dirname(absolute)
        if not directory:
            return ""
        return os.path.normcase(os.path.realpath(directory))
    except (OSError, TypeError, ValueError):
        return ""


def module_reference_assets_json_save_as_block_reason(
    project: Any,
    current_project_path: Any,
    target_project_path: Any,
) -> str:
    """Return a content-free refusal reason, or "" when JSON Save As may proceed.

    Project-relative ``refs/modules/...`` references keep their meaning only
    while the Project JSON stays in the same folder. A Project without
    ``reference_assets`` is never restricted. With it, Save As fails closed
    when the current Project folder is unknown or the target JSON would land
    in another folder. Whole-folder Duplicate Project stays the portable copy.
    """
    if not project_has_module_reference_assets(project):
        return ""
    current_directory = _project_json_base_directory(current_project_path)
    if not current_directory or not os.path.isdir(current_directory):
        return MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE
    target_directory = _project_json_base_directory(target_project_path)
    if not target_directory or target_directory != current_directory:
        return MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE
    return ""
