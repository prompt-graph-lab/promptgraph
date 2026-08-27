"""Display-only descriptions of the existing Gallery operation scope contracts.

This module is presentation metadata, not an execution capability registry.  Target
resolution, validation, preview signatures, and operation availability remain owned
by each existing renderer and core operation.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Iterator, Mapping


_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "action_key": "module_swap",
        "title": "Module Swap / モジュール差し替え",
        "supported_scope_ids": ("all", "line_group", "route", "selected_routes"),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Illustration Group / イラストグループ",
            "Operation-selected Scenes / この操作で指定したシーン",
            "Selected Scenes / 操作対象シーン",
        ),
        "renderer_scope_labels": ("すべてのイラスト", "Illustration Group", "Scene", "Selected Scenes"),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": False,
        "uses_selected_illustrations": False,
        "uses_current_context": False,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "Scene指定はこの操作内の複数選択、Selected Scenesは上の共有選択です。",
    },
    {
        "action_key": "attribute_group_swap",
        "title": "Attribute Group Swap",
        "supported_scope_ids": (
            "current_route",
            "selected_route",
            "selected_routes",
            "selected_lines",
            "all_lines",
        ),
        "supported_scope_labels": (
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Scenes / 操作対象シーン",
            "Selected Illustrations / 選択中のイラスト",
            "All Illustrations / 全イラスト",
        ),
        "renderer_scope_labels": (
            "Current Scene",
            "Selected Scene",
            "Selected Scenes",
            "Selected Illustrations",
            "All Illustrations",
        ),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "指定シーンと共有の操作対象シーンは別の選択です。",
    },
    {
        "action_key": "batch_edit",
        "title": "Batch Edit / 一括編集",
        "supported_scope_ids": (
            "all",
            "focus",
            "selected",
            "current_route",
            "selected_route",
            "group::*",
        ),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Focused Illustration / フォーカス中のイラスト",
            "Selected Illustrations / 選択中のイラスト",
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Illustration Group / イラストグループ",
        ),
        "renderer_scope_labels": (
            "All lines",
            "Focus line only",
            "Selected lines (N)",
            "Current route",
            "Selected route",
            "Group: <name> (N lines)",
        ),
        "uses_shared_selected_scenes": False,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "Focus・選択・Groupの項目は現在のProject状態に応じて表示されます。",
    },
    {
        "action_key": "lightweight_fork",
        "title": "Derived Project / 派生Project",
        "supported_scope_ids": (
            "all_lines",
            "current_route",
            "selected_route",
            "selected_routes",
            "selected_lines",
        ),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Scenes / 操作対象シーン",
            "Selected Illustrations / 選択中のイラスト",
        ),
        "renderer_scope_labels": (
            "すべてのイラスト",
            "現在のシーン",
            "選択中のシーン",
            "選択中の複数シーン",
            "選択中のイラスト",
        ),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "既存の派生Projectへの追加は指定シーン／操作対象シーンだけを使います。",
    },
    {
        "action_key": "gallery_generation",
        "title": "Scene Generation / シーンを一括生成",
        "supported_scope_ids": (
            "all_lines",
            "current_route",
            "selected_route",
            "selected_routes",
            "selected_lines",
        ),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Scenes / 操作対象シーン",
            "Selected Illustrations / 選択中のイラスト",
        ),
        "renderer_scope_labels": (
            "すべてのイラスト",
            "現在のシーン",
            "選択中のシーン",
            "選択中の複数シーン",
            "選択中のイラスト",
        ),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "生成結果はCandidateとして追加されます。",
    },
    {
        "action_key": "batch_candidate_adoption",
        "title": "Scene Batch Candidate Adoption",
        "supported_scope_ids": (
            "all_lines",
            "selected_lines",
            "current_route",
            "selected_route",
            "selected_routes",
        ),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Selected Illustrations / 選択中のイラスト",
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Scenes / 操作対象シーン",
        ),
        "renderer_scope_labels": (
            "All",
            "Selected Illustrations (N)",
            "Current Scene",
            "Selected Scene",
            "Selected Scenes",
        ),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "Candidate／Variant sourceの選択は対象範囲とは別です。",
    },
    {
        "action_key": "batch_promote_variants",
        "title": "Batch Promote Variants",
        "supported_scope_ids": (
            "current_route",
            "selected_route",
            "selected_routes",
            "selected_lines",
            "all_lines",
        ),
        "supported_scope_labels": (
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Scenes / 操作対象シーン",
            "Selected Illustrations / 選択中のイラスト",
            "All Illustrations / 全イラスト",
        ),
        "renderer_scope_labels": (
            "現在のシーン",
            "シーンを選択",
            "Selected Scenes",
            "選択中のイラスト (N)",
            "すべてのGalleryイラスト",
        ),
        "uses_shared_selected_scenes": True,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "Variantを通常Galleryイラストへ昇格し、シーン区切りは作りません。",
    },
    {
        "action_key": "candidate_route_creation",
        "title": "Candidate-based Scene Creation / 候補から別案シーンを作成",
        "supported_scope_ids": ("focused_line", "selected_lines", "current_route", "all_lines"),
        "supported_scope_labels": (
            "Focused Illustration / フォーカス中のイラスト",
            "Selected Illustrations / 選択中のイラスト",
            "Current Scene / 現在のシーン",
            "All Illustrations / 全イラスト",
        ),
        "renderer_scope_labels": (
            "フォーカス中のイラスト",
            "選択中のイラスト (N)",
            "現在のシーン",
            "すべてのイラスト",
        ),
        "uses_shared_selected_scenes": False,
        "has_single_scene_selector": False,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "Illustration／Candidate contextから別案シーンを作ります。",
    },
    {
        "action_key": "prompt_revert",
        "title": "Prompt Revert",
        "supported_scope_ids": ("all_lines", "current_route", "selected_route", "selected_lines"),
        "supported_scope_labels": (
            "All Illustrations / 全イラスト",
            "Current Scene / 現在のシーン",
            "Selected Scene / 指定シーン",
            "Selected Illustrations / 選択中のイラスト",
        ),
        "renderer_scope_labels": (
            "すべてのイラスト",
            "現在のシーン",
            "選択中のシーン",
            "選択中のイラスト",
        ),
        "uses_shared_selected_scenes": False,
        "has_single_scene_selector": True,
        "uses_selected_illustrations": True,
        "uses_current_context": True,
        "has_user_selectable_scope": True,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "共有の操作対象シーンではなく、この操作自身の対象を使います。",
    },
    {
        "action_key": "module_candidates",
        "title": "Module Candidate Scanner / モジュール候補検索",
        "supported_scope_ids": (),
        "supported_scope_labels": ("Project-wide scan / Project全体を検索",),
        "renderer_scope_labels": (),
        "uses_shared_selected_scenes": False,
        "has_single_scene_selector": False,
        "uses_selected_illustrations": False,
        "uses_current_context": False,
        "has_user_selectable_scope": False,
        "all_illustrations_may_include_outside_scenes": True,
        "note": "ユーザー選択のTarget／Scopeはなく、Project内の有効なPrompt行を検索します。",
    },
)

GALLERY_OPERATION_SCOPE_PRESENTATION: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        entry["action_key"]: MappingProxyType(dict(entry))
        for entry in _ENTRIES
    }
)


def get_gallery_operation_scope_presentation(action_key: str) -> Mapping[str, Any] | None:
    """Return immutable display metadata for one Gallery operation."""

    return GALLERY_OPERATION_SCOPE_PRESENTATION.get(action_key)


def iter_gallery_operation_scope_presentations() -> Iterator[Mapping[str, Any]]:
    """Yield display rows in Gallery workflow order."""

    yield from GALLERY_OPERATION_SCOPE_PRESENTATION.values()
