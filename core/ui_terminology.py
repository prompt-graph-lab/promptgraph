"""Canonical PromptGraph Pro v1 user-facing terminology.

These labels are display aliases only. Internal models, serialized scope values,
session-state keys, and operation identifiers intentionally remain unchanged.
"""

ILLUSTRATION_LABEL = "Illustration"
ILLUSTRATIONS_LABEL = "Illustrations"
SCENE_LABEL = "Scene"
SCENES_LABEL = "Scenes"
GRAPH_EDIT_LABEL = "Graph Edit"
DERIVED_PROJECT_LABEL = "Derived Project"
SEQUENCE_SNAPSHOT_LABEL = "Sequence Snapshot"

GALLERY_SCOPE_DISPLAY_LABELS = {
    "all_lines": "All Illustrations",
    "all_routes": "All Scenes",
    "current_route": "Current Scene",
    "selected_route": "Selected Scene",
    "selected_routes": "Selected Scenes",
    "selected_lines": "Selected Illustrations",
}

GALLERY_SCOPE_DISPLAY_LABELS_JA = {
    "all_lines": "すべてのイラスト",
    "all_routes": "すべてのシーン",
    "current_route": "現在のシーン",
    "selected_route": "選択中のシーン",
    "selected_routes": "選択中の複数シーン",
    "selected_lines": "選択中のイラスト",
}


# These are renderer-only aliases for stable machine-facing values returned by
# core operations. Keep the keys byte-for-byte compatible with the core API.
CORE_MESSAGE_DISPLAY_LABELS = {
    "no selected Routes": "シーンが選択されていません。",
    "no adjacent Route": "隣接するシーンがありません。",
    "already first Route": "このシーンはすでに先頭です。",
    "already last Route": "このシーンはすでに末尾です。",
    "missing Route handle": "シーンを特定できません。",
    "invalid Route separator": "有効なシーン区切りではありません。",
    "unknown Route Action": "このシーン操作は利用できません。",
    "missing Route Action pending dispatch": "シーン操作を開始できません。",
    "unknown Route Action operation": "このシーン操作は利用できません。",
    "ambiguous active Route handle": "シーンを一意に特定できません。",
    "separator already deleted without active Route removal record": "シーンは削除済みですが、復元情報がありません。",
    "malformed source Route": "元シーンの構造が不正です。",
    "Route insertion failed": "シーンを挿入できませんでした。",
    "unsupported Line state": "対応していないイラスト状態です。",
    "Selected Routesがありません。": "シーンが選択されていません。",
    "選択されたRouteに生成対象Lineがありません。": "選択されたシーンに生成対象イラストがありません。",
    "生成前チェックに失敗したLineがあります。": "生成前チェックに失敗したイラストがあります。",
    "source Line id is missing": "対象イラストのIDがありません。",
    "source Line is missing": "対象イラストが見つかりません。",
    "source Line id is ambiguous": "対象イラストのIDが重複しています。",
    "source Line is deleted": "対象イラストは削除済みです。",
    "source Line is not a normal Line": "対象は通常イラストではありません。",
    "invalid source Line": "対象イラストを解決できません。",
    "duplicate or ambiguous Line id": "イラストIDが重複しているか一意に特定できません。",
    "selected Routes have no exportable Lines": "選択中のシーンに書き出せるイラストがありません。",
    "selected Routes have no active normal Lines": "選択中のシーンに有効なイラストがありません。",
    "selected Routes contain ambiguous duplicate Line ids": "選択中のシーンに重複したイラストIDがあります。",
    "selected Routes have no Module Swap target Lines": "選択中のシーンにModule Swap対象のイラストがありません。",
    "selected Routes contain Lines with malformed tokens": "選択中のシーンにtoken状態が不正なイラストがあります。",
    "selected Routes have no Attribute Group Swap target Lines": "選択中のシーンにAttribute Group Swap対象のイラストがありません。",
    "Select a valid Route.": "有効なシーンを選択してください。",
    "Select at least one Route using the Gallery Route checkboxes.": "Galleryでシーンを1つ以上選択してください。",
    "Fork discovery root is unavailable": "派生Projectの検索先を利用できません。",
    "Fork discovery root is not a directory": "派生Projectの検索先がdirectoryではありません。",
    "saved source Project is required for Fork discovery": "派生Projectを検索するには元Projectを保存してください。",
    "Fork source Project does not match": "派生Projectの元Projectが一致しません。",
    "This Fork was created from a different source Project.": "派生Projectの元Projectが一致しません。",
    "The selected Fork is currently open.": "選択した派生Projectは現在開かれています。",
    "selected Project is not a Lightweight Fork": "選択したProjectは対応する派生Projectではありません。",
    "Lightweight Fork commit failed.": "派生Projectの保存に失敗しました。",
    "Selected Routes are already present in this Fork.": "選択中のシーンはすでにこの派生Projectに存在します。",
    "Selected Routes Module Swap has no changes": "Selected Scenes Module Swapで変更されるイラストはありません。",
    "Selected Routes Module Swap preview changed before apply": "Selected Scenes Module Swap PreviewがApply前に変更されました。",
    "Selected Routes Attribute Group Swap has no changes": "Selected Scenes Attribute Group Swapで変更されるイラストはありません。",
    "Selected Routes Attribute Group Swap preview changed before apply": "Selected Scenes Attribute Group Swap PreviewがApply前に変更されました。",
    "Selected Routes Candidate Adoption preview changed before apply": "Selected Scenes Candidate Adoption PreviewがApply前に変更されました。",
    "Selected Routes Candidate Adoption plan changed during apply": "Selected Scenes Candidate Adoptionの計画がApply中に変更されました。",
    "Selected Line id is ambiguous": "選択中のイラストIDを一意に特定できません。",
    "Selected Lines are empty": "イラストが選択されていません。",
    "Current Route anchor is missing or ambiguous": "現在のシーンを一意に特定できません。",
    "Route could not be resolved": "シーンを解決できません。",
    "Route handle is missing or ambiguous": "シーンを一意に特定できません。",
    "Route separator is deleted": "シーン区切りは削除済みです。",
    "Route has no active normal Gallery Lines": "シーンに有効なGalleryイラストがありません。",
    "Selected Route handle is ambiguous": "選択中のシーンを一意に特定できません。",
    "Selected Routes are empty": "シーンが選択されていません。",
    "Selected Routes have no active normal Gallery Lines": "選択中のシーンに有効なGalleryイラストがありません。",
    "Target Line id is ambiguous": "対象イラストIDを一意に特定できません。",
    "No active normal Gallery Lines were resolved": "有効なGalleryイラストを解決できませんでした。",
    "No current line is available to resolve a Route.": "現在のイラストからシーンを解決できません。",
    "Current line is not available in the active Gallery lines.": "現在のイラストは有効なGalleryイラストではありません。",
    "No current Route resolved for the selected line.": "選択中のイラストから現在のシーンを解決できません。",
    "Current Route has no active prompt lines.": "現在のシーンに有効なイラストがありません。",
    "Select at least one Line Group.": "Line Groupを1つ以上選択してください。",
    "Selected Line Group has no active prompt lines.": "選択中のLine Groupに有効なイラストがありません。",
    "No Gallery routes are available in this project.": "このProjectに利用可能なシーンがありません。",
    "Select at least one Route.": "シーンを1つ以上選択してください。",
    "Selected Route has no active prompt lines.": "選択中のシーンに有効なイラストがありません。",
    "Route separator": "Scene separator",
    "deleted line": "deleted Illustration",
    "Workbench line": "Workbench Illustration",
    "Selected Routes Candidate Adoption preview is stale": "Selected Scenes Candidate Adoption Preview is stale.",
    "Selected Routes Attribute Group Swap preview is stale": "Selected Scenes Attribute Group Swap Preview is stale.",
    "Selected Routes Module Swap preview is stale": "Selected Scenes Module Swap Preview is stale.",
}

CORE_MESSAGE_PREFIX_DISPLAY_LABELS = {
    "duplicate Route removal id: ": "重複したシーン削除ID: ",
    "ambiguous active Route handle: ": "識別できないシーンhandle: ",
    "ambiguous selected Route id: ": "識別できない選択シーンID: ",
    "selected Route is not selectable: ": "選択できないシーン: ",
    "ambiguous selected Route line id: ": "識別できない選択イラストID: ",
    "ambiguous selected Line id: ": "識別できない選択イラストID: ",
    "ignored selected Line id: ": "存在しない選択イラストIDを除外: ",
    "ambiguous target Line id: ": "識別できない対象イラストID: ",
    "ignored missing Route id: ": "存在しないシーンIDを除外: ",
    "ignored deleted Route id: ": "削除済みシーンIDを除外: ",
    "ignored duplicate or ambiguous Route id: ": "重複または識別不能なシーンIDを除外: ",
    "duplicate or ambiguous Line id": "重複または識別不能なイラストID",
    "missing selected Route excluded: ": "存在しない選択シーンを除外: ",
    "deleted selected Route excluded: ": "削除済み選択シーンを除外: ",
    "ambiguous selected Route excluded: ": "識別できない選択シーンを除外: ",
    "duplicate selected Route ignored: ": "重複した選択シーンを除外: ",
    "malformed source Line in selected Route: ": "選択シーン内の不正なイラスト: ",
    "Selected Route is missing, deleted, ambiguous, or not an active separator: ": "選択シーンが存在しない、削除済み、重複、または有効な区切りではありません: ",
    "Selected Routes resolution failed: ": "Selected Scenesの解決に失敗しました: ",
    "ignored selected Route Lines with missing ids: ": "IDがない選択シーン内イラストを除外: ",
    "selected Route Line has malformed tokens: ": "選択シーン内イラストのtoken状態が不正です: ",
    "Fork discovery failed: ": "派生Projectの検索に失敗しました: ",
    "Fork manifest ": "派生Project manifest ",
    "Fork root ": "派生Project root ",
    "Fork directory ": "派生Project directory ",
    "Fork candidate ": "派生Project candidate ",
    "Fork Project JSON ": "派生Project JSON ",
    "Fork project.json ": "派生Project project.json ",
    "duplicate resolved Fork directory": "重複した派生Project directory",
    "duplicate Fork directory": "重複した派生Project directory",
    "candidate escapes Fork discovery root": "候補が派生Project検索先の外を指しています",
    "existing Fork ": "既存の派生Project ",
    "duplicate existing Fork Line id: ": "既存の派生Project内で重複したイラストID: ",
    "unsafe existing Fork path: ": "安全でない派生Project path: ",
    "existing Fork could not be loaded: ": "派生Projectを読み込めませんでした: ",
}


def format_core_message_for_display(message) -> str:
    """Translate known core contract strings only at a UI rendering boundary."""

    text = str(message or "")
    exact = CORE_MESSAGE_DISPLAY_LABELS.get(text)
    if exact is not None:
        return exact
    for prefix, display_prefix in CORE_MESSAGE_PREFIX_DISPLAY_LABELS.items():
        if text.startswith(prefix):
            return display_prefix + text[len(prefix):]
    return text
