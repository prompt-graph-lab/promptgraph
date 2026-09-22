# Frozen app.py duplication functions from bf1db72d2cca791d6b195de4eac6e32c725c35c2.
# Executed selectively by the differential tests; no application startup or I/O.

def _sanitize_duplicate_project_dir_name(name: str) -> str:
    clean_name = str(name or "").strip()
    clean_name = clean_name.replace("/", "_").replace("\\", "_")
    for char in '<>:"|?*':
        clean_name = clean_name.replace(char, "_")
    clean_name = clean_name.strip(" .")
    if clean_name in ("", ".", ".."):
        return ""
    return clean_name


def _source_project_directory() -> tuple[str, str]:
    project_path = st.session_state.get("current_project_path", "")
    if not project_path:
        return "", ""
    clean_project_path = os.path.abspath(os.path.expanduser(project_path))
    return clean_project_path, os.path.dirname(clean_project_path)


def _default_duplicate_project_dir_name() -> str:
    source_project_path, source_project_dir = _source_project_directory()
    if not source_project_path or not source_project_dir:
        return "MyProject_copy"

    source_name = os.path.basename(source_project_dir) or "Project"
    parent_dir = os.path.dirname(source_project_dir)
    base_name = f"{source_name}_copy"
    candidate_name = base_name
    suffix = 1
    while os.path.exists(os.path.join(parent_dir, candidate_name)):
        candidate_name = f"{base_name}_{suffix}"
        suffix += 1
    return candidate_name


def _duplicate_project_destination_dir(destination_name: str) -> str:
    _, source_project_dir = _source_project_directory()
    if not source_project_dir:
        return ""
    clean_name = _sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return ""
    return os.path.abspath(os.path.join(os.path.dirname(source_project_dir), clean_name))


def _find_copied_project_json(destination_dir: str, source_project_path: str) -> str:
    preferred_path = os.path.join(destination_dir, os.path.basename(source_project_path))
    if os.path.exists(preferred_path):
        return preferred_path
    json_files = [
        os.path.join(destination_dir, file_name)
        for file_name in os.listdir(destination_dir)
        if file_name.lower().endswith(".json") and os.path.isfile(os.path.join(destination_dir, file_name))
    ]
    return json_files[0] if len(json_files) == 1 else ""


def duplicate_current_project_directory(destination_name: str) -> tuple[bool, str]:
    if not st.session_state.project:
        return False, "先にプロジェクトを読み込むか作成してください。"

    source_project_path, source_project_dir = _source_project_directory()
    if not source_project_path:
        return False, "現在のプロジェクトパスがありません。"
    if not os.path.isfile(source_project_path):
        return False, "元のプロジェクトJSONが見つかりません。"
    if not os.path.isdir(source_project_dir):
        return False, "元のプロジェクトディレクトリが見つかりません。"

    clean_name = _sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return False, "複製先プロジェクト名が必要です。"
    destination_dir = _duplicate_project_destination_dir(clean_name)
    if not destination_dir:
        return False, "複製先ディレクトリを解決できません。"
    if os.path.exists(destination_dir):
        return False, "複製先ディレクトリは既に存在します。"

    try:
        save_project_to_json(st.session_state.project, source_project_path)
        ensure_current_project_folder_layout(source_project_path)
    except Exception as exc:
        return False, f"複製前のプロジェクト保存に失敗しました: {exc}"

    shutil.copytree(
        source_project_dir,
        destination_dir,
        ignore=shutil.ignore_patterns(
            ".promptgraph_cache",
            ".*.tmp",
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".DS_Store",
            "Thumbs.db",
        ),
    )
    destination_project_path = _find_copied_project_json(destination_dir, source_project_path)
    if not destination_project_path:
        return False, "複製先で開くproject JSONが見つかりません。"

    try:
        if not load_project_json_into_session(destination_project_path):
            return False, "複製先project JSONを開けませんでした。"
    except Exception as exc:
        return False, f"複製先project JSONを開けませんでした: {exc}"

    st.session_state.last_saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.autosave_feedback = "project duplicated"
    request_project_directory_discovery_refresh()
    return True, f"プロジェクトディレクトリを複製して開きました: {destination_project_path}"
