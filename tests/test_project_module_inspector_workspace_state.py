import ast
import copy
import types
import unittest
from pathlib import Path

from core.operations import (
    MODULE_TYPES,
    get_module_body,
    get_module_core_tokens,
    get_module_min_match_tokens,
    get_module_type,
    get_project_module_library,
    validate_library_module_body,
)
from core.parser import parse_prompt
from core.project import Project


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _RenderStub:
    def __init__(self, session_state, pressed_keys=()):
        self.session_state = session_state
        self.sidebar = self
        self.pressed_keys = set(pressed_keys)
        self.messages = []
        self.rerun_count = 0

    def expander(self, *args, **kwargs):
        return _Context()

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def success(self, message):
        self.messages.append(("success", message))

    def selectbox(self, label, options, key, **kwargs):
        if key not in self.session_state:
            self.session_state[key] = options[0]
        return self.session_state[key]

    def text_area(self, label, key, **kwargs):
        return self.session_state.get(key, "")

    def number_input(self, label, key, **kwargs):
        return self.session_state.get(key, kwargs.get("min_value", 1))

    def button(self, label, key, **kwargs):
        return key in self.pressed_keys

    def rerun(self):
        self.rerun_count += 1


class ProjectModuleInspectorWorkspaceStateTests(unittest.TestCase):
    helper_names = (
        "prepare_project_module_inspector_selection_widget_state",
        "sync_project_module_inspector_selection_widget_state",
        "prepare_project_module_inspector_body_widget_state",
        "sync_project_module_inspector_body_widget_state",
        "prepare_project_module_inspector_core_widget_state",
        "sync_project_module_inspector_core_widget_state",
        "prepare_project_module_inspector_type_widget_state",
        "sync_project_module_inspector_type_widget_state",
        "prepare_project_module_inspector_min_match_widget_state",
        "sync_project_module_inspector_min_match_widget_state",
    )

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_source = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load_functions(self, *names, namespace):
        module = ast.Module(
            body=[
                node for node in self.tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "core.module_token_rules"
            ] + [self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def _helper_namespace(self, session_state):
        st = types.SimpleNamespace(session_state=session_state)
        return self._load_functions(
            *self.helper_names,
            namespace={
                "st": st,
                "parse_prompt": parse_prompt,
                "MODULE_TYPES": MODULE_TYPES,
                "get_module_body": get_module_body,
                "get_module_core_tokens": get_module_core_tokens,
                "get_module_type": get_module_type,
                "get_module_min_match_tokens": get_module_min_match_tokens,
            },
        )

    def _project(self, character_body="black hair"):
        return Project(
            source_directory="fixture",
            module_library={
                "character": {
                    "body": character_body,
                    "type": "character",
                    "core_tokens": [character_body],
                    "min_match_tokens": 1,
                },
                "pose": {
                    "body": "standing, smiling",
                    "type": "generic",
                    "core_tokens": ["standing"],
                    "min_match_tokens": 1,
                },
            },
        )

    def _renderer_namespace(
        self,
        st,
        *,
        calls=None,
        token_capture=None,
    ):
        calls = calls if calls is not None else []
        token_capture = token_capture if token_capture is not None else []

        def render_token_inspector(
            project,
            namespace,
            module_name,
            body_key,
            core_key,
        ):
            token_capture.append(
                {
                    "project": project,
                    "namespace": namespace,
                    "module_name": module_name,
                    "body_key": body_key,
                    "core_key": core_key,
                    "body": st.session_state.get(body_key),
                    "core": st.session_state.get(core_key),
                }
            )

        def push_history():
            calls.append("history")

        def set_module_entry_stub(
            project,
            module_name,
            body,
            module_type,
            core_tokens,
            min_match_tokens,
        ):
            calls.append(
                (
                    "set",
                    module_name,
                    body,
                    module_type,
                    list(core_tokens),
                    min_match_tokens,
                )
            )

        def build_graph_stub(project):
            calls.append("build")
            return project

        def restore_focus_stub(focus):
            calls.append(("restore", focus))

        def sync_text_areas_stub():
            calls.append("sync")

        namespace = {
            "st": st,
            "profiled_render": lambda label: lambda function: function,
            "parse_prompt": parse_prompt,
            "MODULE_TYPES": MODULE_TYPES,
            "get_project_module_library": get_project_module_library,
            "get_module_body": get_module_body,
            "get_module_core_tokens": get_module_core_tokens,
            "get_module_type": get_module_type,
            "get_module_min_match_tokens": get_module_min_match_tokens,
            "validate_library_module_body": validate_library_module_body,
            "is_free": lambda: False,
            "render_module_token_inspector": render_token_inspector,
            "push_history": push_history,
            "set_module_entry": set_module_entry_stub,
            "build_graph": build_graph_stub,
            "restore_focus_after_graph_update": restore_focus_stub,
            "sync_text_areas": sync_text_areas_stub,
        }
        return self._load_functions(
            *self.helper_names,
            "render_project_module_inspector_section",
            namespace=namespace,
        )

    def test_selection_prepare_sync_and_missing_module_normalization(self):
        project = self._project()
        before = copy.deepcopy(project)
        state = _SessionState(project_module_inspector_name="pose")
        namespace = self._helper_namespace(state)

        selected = namespace[
            "prepare_project_module_inspector_selection_widget_state"
        ](["character", "pose"])
        self.assertEqual(selected, "pose")
        self.assertEqual(
            state._project_module_inspector_name_widget,
            "pose",
        )

        state._project_module_inspector_name_widget = "character"
        namespace["sync_project_module_inspector_selection_widget_state"]()
        self.assertEqual(state.project_module_inspector_name, "character")

        state.project_module_inspector_name = "missing"
        selected = namespace[
            "prepare_project_module_inspector_selection_widget_state"
        ](["character", "pose"])
        self.assertEqual(selected, "character")
        self.assertEqual(state.project_module_inspector_name, "character")
        self.assertEqual(
            state._project_module_inspector_name_widget,
            "character",
        )
        self.assertEqual(project, before)

    def test_draft_prepare_and_sync_use_durable_and_temporary_keys(self):
        project = self._project()
        library = get_project_module_library(project)
        state = _SessionState()
        namespace = self._helper_namespace(state)

        body = namespace[
            "prepare_project_module_inspector_body_widget_state"
        ](library, "pose")
        core = namespace[
            "prepare_project_module_inspector_core_widget_state"
        ](library, "pose")
        module_type = namespace[
            "prepare_project_module_inspector_type_widget_state"
        ](library, "pose")
        min_match = namespace[
            "prepare_project_module_inspector_min_match_widget_state"
        ](library, "pose", ["standing", "smiling"])

        self.assertEqual(body, "standing, smiling")
        self.assertEqual(core, "standing")
        self.assertEqual(module_type, "generic")
        self.assertEqual(min_match, 1)
        self.assertEqual(
            state._project_module_inspector_body_widget_pose,
            state.project_module_inspector_body_pose,
        )
        self.assertEqual(
            state._project_module_inspector_core_widget_pose,
            state.project_module_inspector_core_pose,
        )
        self.assertEqual(
            state._project_module_inspector_type_widget_pose,
            state.project_module_inspector_type_pose,
        )
        self.assertEqual(
            state._project_module_inspector_min_match_widget_pose,
            state.project_module_inspector_min_match_pose,
        )

        state._project_module_inspector_body_widget_pose = "walking, waving"
        state._project_module_inspector_core_widget_pose = "walking\nwaving"
        state._project_module_inspector_type_widget_pose = "style"
        state._project_module_inspector_min_match_widget_pose = 2
        namespace["sync_project_module_inspector_body_widget_state"]("pose")
        namespace["sync_project_module_inspector_core_widget_state"]("pose")
        namespace["sync_project_module_inspector_type_widget_state"]("pose")
        namespace[
            "sync_project_module_inspector_min_match_widget_state"
        ]("pose")

        self.assertEqual(
            state.project_module_inspector_body_pose,
            "walking, waving",
        )
        self.assertEqual(
            state.project_module_inspector_core_pose,
            "walking\nwaving",
        )
        self.assertEqual(state.project_module_inspector_type_pose, "style")
        self.assertEqual(state.project_module_inspector_min_match_pose, 2)

    def test_min_match_normalizes_after_body_token_count_changes(self):
        project = self._project()
        library = get_project_module_library(project)
        state = _SessionState(
            project_module_inspector_min_match_pose=8,
        )
        namespace = self._helper_namespace(state)

        normalized = namespace[
            "prepare_project_module_inspector_min_match_widget_state"
        ](library, "pose", ["standing"])

        self.assertEqual(normalized, 1)
        self.assertEqual(state.project_module_inspector_min_match_pose, 1)
        self.assertEqual(
            state._project_module_inspector_min_match_widget_pose,
            1,
        )

        state.project_module_inspector_min_match_pose = "malformed"
        normalized = namespace[
            "prepare_project_module_inspector_min_match_widget_state"
        ](library, "pose", [])
        self.assertEqual(normalized, 1)

    def test_hidden_widget_reconstruction_preserves_unsaved_drafts(self):
        project = self._project()
        get_project_module_library(project)
        before = copy.deepcopy(project)
        state = _SessionState(
            project=project,
            edition="PRO",
            history=[],
            project_module_inspector_name="character",
            project_module_inspector_body_character=(
                "rainbow hair, blue eyes"
            ),
            project_module_inspector_core_character="rainbow hair",
            project_module_inspector_type_character="style",
            project_module_inspector_min_match_character=2,
        )
        st = _RenderStub(state)
        calls = []
        token_capture = []
        namespace = self._renderer_namespace(
            st,
            calls=calls,
            token_capture=token_capture,
        )

        namespace["render_project_module_inspector_section"](project)

        self.assertEqual(
            state._project_module_inspector_name_widget,
            "character",
        )
        self.assertEqual(
            state._project_module_inspector_body_widget_character,
            "rainbow hair, blue eyes",
        )
        self.assertEqual(
            state._project_module_inspector_core_widget_character,
            "rainbow hair",
        )
        self.assertEqual(
            state._project_module_inspector_type_widget_character,
            "style",
        )
        self.assertEqual(
            state._project_module_inspector_min_match_widget_character,
            2,
        )
        self.assertEqual(
            state.project_module_inspector_body_character,
            "rainbow hair, blue eyes",
        )
        self.assertEqual(project, before)
        self.assertEqual(calls, [])
        self.assertEqual(st.rerun_count, 0)
        self.assertEqual(len(token_capture), 1)
        self.assertEqual(
            token_capture[0]["body_key"],
            "project_module_inspector_body_character",
        )
        self.assertEqual(
            token_capture[0]["core_key"],
            "project_module_inspector_core_character",
        )
        self.assertEqual(
            token_capture[0]["body"],
            "rainbow hair, blue eyes",
        )
        self.assertNotIn("autosave_feedback", state)

    def test_module_switch_keeps_independent_unsaved_drafts(self):
        project = self._project()
        library = get_project_module_library(project)
        before = copy.deepcopy(project)
        state = _SessionState(project_module_inspector_name="character")
        namespace = self._helper_namespace(state)

        namespace[
            "prepare_project_module_inspector_body_widget_state"
        ](library, "character")
        state._project_module_inspector_body_widget_character = "rainbow hair"
        namespace["sync_project_module_inspector_body_widget_state"](
            "character"
        )

        state._project_module_inspector_name_widget = "pose"
        namespace["sync_project_module_inspector_selection_widget_state"]()
        namespace[
            "prepare_project_module_inspector_body_widget_state"
        ](library, "pose")
        state._project_module_inspector_body_widget_pose = "walking"
        namespace["sync_project_module_inspector_body_widget_state"]("pose")

        state._project_module_inspector_name_widget = "character"
        namespace["sync_project_module_inspector_selection_widget_state"]()
        namespace[
            "prepare_project_module_inspector_body_widget_state"
        ](library, "character")

        self.assertEqual(
            state._project_module_inspector_body_widget_character,
            "rainbow hair",
        )
        self.assertEqual(
            state.project_module_inspector_body_character,
            "rainbow hair",
        )
        self.assertEqual(
            state.project_module_inspector_body_pose,
            "walking",
        )
        self.assertEqual(project, before)
        self.assertNotIn("history", state)
        self.assertNotIn("autosave_feedback", state)

    def test_successful_project_reset_prevents_same_name_draft_leakage(self):
        project_b = self._project(character_body="white hair")
        state = _SessionState(
            project_module_inspector_name="character",
            _project_module_inspector_name_widget="character",
            project_module_inspector_body_character="rainbow hair",
            project_module_inspector_core_character="rainbow hair",
            project_module_inspector_type_character="style",
            project_module_inspector_min_match_character=2,
            _project_module_inspector_body_widget_character="rainbow hair",
            _project_module_inspector_core_widget_character="rainbow hair",
            _project_module_inspector_type_widget_character="style",
            _project_module_inspector_min_match_widget_character=2,
            project_module_inspector_module_inspector_rows_character={
                "edited_rows": [0]
            },
            project_module_inspector_module_inspector_add_token_character=(
                "old token"
            ),
            project_module_inspector_save_character=False,
            module_attribute_table_name="character",
        )
        st = _RenderStub(state)
        namespace = self._renderer_namespace(st)
        self._load_functions(
            "reset_module_attribute_authoring_project_session_state",
            namespace=namespace,
        )

        namespace[
            "reset_module_attribute_authoring_project_session_state"
        ]()
        for key in (
            "project_module_inspector_name",
            "_project_module_inspector_name_widget",
            "project_module_inspector_body_character",
            "project_module_inspector_core_character",
            "project_module_inspector_type_character",
            "project_module_inspector_min_match_character",
            "_project_module_inspector_body_widget_character",
            "_project_module_inspector_core_widget_character",
            "_project_module_inspector_type_widget_character",
            "_project_module_inspector_min_match_widget_character",
            "project_module_inspector_module_inspector_rows_character",
            "project_module_inspector_module_inspector_add_token_character",
            "project_module_inspector_save_character",
        ):
            self.assertNotIn(key, state)
        self.assertEqual(state.module_attribute_table_name, "character")

        state.project = project_b
        state.edition = "PRO"
        namespace["render_project_module_inspector_section"](project_b)

        self.assertEqual(
            state.project_module_inspector_body_character,
            "white hair",
        )
        self.assertEqual(
            state._project_module_inspector_body_widget_character,
            "white hair",
        )
        self.assertNotIn("rainbow hair", state.values())

    def test_back_and_failed_load_paths_preserve_drafts(self):
        state = _SessionState(
            active_management_workspace="module_attribute_authoring",
            project_module_inspector_name="character",
            project_module_inspector_body_character="rainbow hair",
            _project_module_inspector_body_widget_character="rainbow hair",
        )
        st = types.SimpleNamespace(session_state=state)
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            namespace={
                "st": st,
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                    "active_management_workspace"
                ),
            },
        )

        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(state.active_management_workspace, "")
        self.assertEqual(
            state.project_module_inspector_body_character,
            "rainbow hair",
        )
        self.assertEqual(
            state._project_module_inspector_body_widget_character,
            "rainbow hair",
        )

        loader = self._source("load_project_json_into_session")
        missing_guard = loader.index("if not os.path.exists(project_path):")
        failed_return = loader.index("return False", missing_guard)
        reset = loader.index(
            "reset_module_attribute_authoring_project_session_state()"
        )
        self.assertLess(failed_return, reset)
        self.assertLess(
            loader.index("project = load_project_from_json(project_path)"),
            reset,
        )

    def test_save_contract_runs_once_and_keeps_drafts_and_selection(self):
        project = self._project()
        state = _SessionState(
            project=project,
            edition="PRO",
            focused_line_id="line-1",
            disabled_modules={"pose"},
            module_edit_scope_name="pose",
            global_module_candidate_scan={"stale": True},
            project_module_inspector_name="character",
            project_module_inspector_body_character=(
                "rainbow hair, blue eyes"
            ),
            project_module_inspector_core_character="rainbow hair",
            project_module_inspector_type_character="style",
            project_module_inspector_min_match_character=2,
        )
        st = _RenderStub(
            state,
            pressed_keys={"project_module_inspector_save_character"},
        )
        calls = []
        namespace = self._renderer_namespace(st, calls=calls)

        namespace["render_project_module_inspector_section"](project)

        self.assertEqual(calls.count("history"), 1)
        self.assertEqual(calls.count("build"), 1)
        self.assertEqual(calls.count("sync"), 1)
        set_calls = [call for call in calls if call[0] == "set"]
        self.assertEqual(
            set_calls,
            [
                (
                    "set",
                    "character",
                    "rainbow hair, blue eyes",
                    "style",
                    ["rainbow hair"],
                    2,
                )
            ],
        )
        self.assertEqual(
            [call for call in calls if call[0] == "restore"],
            [("restore", "line-1")],
        )
        ordered_labels = [
            call if isinstance(call, str) else call[0]
            for call in calls
        ]
        self.assertEqual(
            ordered_labels,
            ["history", "set", "build", "restore", "sync"],
        )
        self.assertNotIn("global_module_candidate_scan", state)
        self.assertEqual(state.project_module_inspector_name, "character")
        self.assertEqual(
            state.project_module_inspector_body_character,
            "rainbow hair, blue eyes",
        )
        self.assertEqual(state.module_edit_scope_name, "pose")
        self.assertEqual(state.disabled_modules, {"pose"})
        self.assertEqual(st.rerun_count, 0)
        self.assertIn(
            ("success", "Project module saved."),
            st.messages,
        )

    def test_renderer_ownership_moves_to_authoring_only(self):
        renderer = self._source("render_project_module_inspector_section")
        authoring = self._source(
            "render_module_attribute_authoring_workspace"
        )
        apply_workspace = self._source(
            "render_module_attribute_apply_workspace"
        )
        apply_sidebar = self._source(
            "render_module_attribute_apply_sidebar_section"
        )
        module_table = self._source("render_module_attribute_table_section")

        self.assertIn(
            'with st.expander("Project Module Editor"',
            renderer,
        )
        self.assertNotIn("st.sidebar", renderer)
        self.assertEqual(
            authoring.count(
                "render_project_module_inspector_section(project)"
            ),
            1,
        )
        self.assertNotIn(
            "render_project_module_inspector_section",
            apply_workspace,
        )
        self.assertNotIn(
            "render_project_module_inspector_section",
            apply_sidebar,
        )
        executable_calls = [
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                == "render_project_module_inspector_section"
            )
        ]
        self.assertEqual(len(executable_calls), 1)
        self.assertIn(
            'with st.sidebar.expander("Module Attribute Table"',
            module_table,
        )
        self.assertIn("Read-only view", module_table)
        for forbidden in (
            "set_module_entry",
            "push_history",
            "text_area",
            "number_input",
        ):
            self.assertNotIn(forbidden, module_table)
        self.assertNotIn("module_attribute_table_name", renderer)


if __name__ == "__main__":
    unittest.main()
