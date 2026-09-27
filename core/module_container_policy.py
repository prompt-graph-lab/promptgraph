"""Module-vNext container compatibility policy (public P0 reservation).

A Project Module entry may carry the reserved, additive, Project-local field
``reference_assets``: a versioned envelope (integer ``format``; format 1 is the
first reserved representation) whose ordered ``assets`` describe Module-level
visual references stored as files under the reserved Project-local namespace
``refs/modules/``.

Public PromptGraph does not interpret, validate, resolve, read, copy, create or
delete that data. It only guarantees two things:

- inside one Project, the field is preserved like any other unknown extension
  field (normalize, load, save and prompt-field edits keep it); and
- a Module copied into a prompt-only container (the Global Module Library, a
  Derived Project, a Scene Template v1 snapshot) never carries it, because its
  Project-relative paths would not resolve there.

This module is pure: it performs no filesystem access.
"""

import copy
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
