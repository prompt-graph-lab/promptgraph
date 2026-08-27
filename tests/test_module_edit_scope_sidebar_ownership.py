import ast
import contextlib
import os
import types
import unittest
from pathlib import Path
from unittest import mock


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


class _StreamlitStub:
    def __init__(self, session_state, clicked=()):
        self.session_state = session_state
        self.clicked = set(clicked)
        self.captions = []
        self.infos = []
        self.buttons = []
        self.selected_module = ""
        self.reruns = 0
        self.sidebar = types.SimpleNamespace(expander=self.expander)

    def expander(self, *args, **kwargs):
        return _Context()

    def caption(self, message):
        self.captions.append(message)

    def info(self, message):
        self.infos.append(message)

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs))
        return label in self.clicked

    def selectbox(self, _label, options, **_kwargs):
        return self.selected_module or options[0]

    def markdown(self, _message):
        return None

    def rerun(self):
        self.reruns += 1


class ModuleEditScopeSidebarOwnershipTests(unittest.TestCase):
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

    @classmethod
    def _source(cls, name):
        return ast.get_source_segment(cls.app_source, cls.functions[name])

    @classmethod
    def _load_functions(cls, *names, namespace):
        module = ast.Module(
            body=[cls.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def test_sidebar_analysis_is_the_single_edit_scope_render_owner(self):
        top_level_start = self.app_source.rindex(
            "render_common_undo_sidebar_section()"
        )
        top_level = self.app_source[top_level_start:]
        renderer_call = "render_module_inspector_edit_scope_section()"
        self.assertEqual(top_level.count(renderer_call), 1)
        self.assertLess(
            top_level.index(
                'st.sidebar.subheader("Module / Attribute Analysis")'
            ),
            top_level.index(renderer_call),
        )

        outer = self._source("render_module_inspector_edit_scope_section")
        self.assertIn(
            '"Module Inspector / Active Edit Scope"',
            outer,
        )
        self.assertIn("expanded=False", outer)
        self.assertEqual(
            outer.count("render_active_module_edit_scope_summary()"),
            1,
        )
        self.assertEqual(
            outer.count("render_module_edit_scope_controls(selected_module)"),
            1,
        )

        for owner in (
            "render_module_attribute_apply_workspace",
            "render_module_attribute_apply_sidebar_section",
            "render_module_attribute_authoring_workspace",
        ):
            source = self._source(owner)
            self.assertNotIn(
                "render_module_inspector_edit_scope_section",
                source,
            )
            self.assertNotIn("render_module_edit_scope_controls", source)
            self.assertNotIn(
                "render_active_module_edit_scope_summary",
                source,
            )

    def test_apply_workspace_still_has_exactly_four_children_in_order(self):
        workspace = self._source("render_module_attribute_apply_workspace")
        children = (
            "render_module_toggle_controls(project)",
            "render_insert_saved_module_reference_section(project)",
            "render_module_candidate_selection_section(project)",
            "render_attribute_group_swap_section(project)",
        )
        positions = [workspace.index(child) for child in children]
        self.assertEqual(positions, sorted(positions))
        for child in children:
            self.assertEqual(workspace.count(child), 1)
        self.assertNotIn("render_module_edit_scope", workspace)
        self.assertNotIn("render_module_inspector", workspace)

    def test_no_active_scope_shows_neutral_summary_without_clear_action(self):
        session_state = _SessionState()
        st = _StreamlitStub(session_state)
        namespace = self._load_functions(
            "render_active_module_edit_scope_summary",
            namespace={"st": st},
        )

        namespace["render_active_module_edit_scope_summary"]()

        self.assertEqual(st.captions, ["Active Edit Scope: none"])
        self.assertEqual(st.infos, [])
        self.assertEqual(st.buttons, [])
        self.assertEqual(st.reruns, 0)

    def test_active_summary_uses_scope_not_inspector_selection(self):
        project = object()
        session_state = _SessionState(
            project=project,
            disabled_modules=set(),
            module_edit_scope_name="outfit",
            module_inspector_selected="pose",
        )
        st = _StreamlitStub(session_state)
        st.selected_module = "pose"
        usage_calls = []
        scope_calls = []
        namespace = self._load_functions(
            "clear_module_edit_scope",
            "clear_module_edit_scope_if_missing",
            "render_active_module_edit_scope_summary",
            "render_module_inspector_edit_scope_section",
            namespace={
                "st": st,
                "get_available_modules": lambda _project: ["outfit", "pose"],
                "inspect_modules": lambda _project, _disabled: {
                    "outfit": {"name": "outfit"},
                    "pose": {"name": "pose"},
                },
                "render_module_usage_inspection": (
                    lambda selected, report: usage_calls.append(
                        (selected, report)
                    )
                ),
                "render_module_edit_scope_controls": (
                    lambda selected: scope_calls.append(selected)
                ),
            },
        )

        namespace["render_module_inspector_edit_scope_section"]()

        self.assertEqual(
            st.infos,
            [
                "Active Edit Scope: outfit\n\n"
                "Prompt editing is currently limited to this Module scope."
            ],
        )
        self.assertEqual(usage_calls, [("pose", {"name": "pose"})])
        self.assertEqual(scope_calls, ["pose"])
        self.assertEqual(session_state.module_edit_scope_name, "outfit")
        self.assertEqual(st.reruns, 0)

    def test_invalid_scope_is_cleared_without_replacement_or_project_mutation(self):
        project = object()
        session_state = _SessionState(
            project=project,
            disabled_modules=set(),
            module_edit_scope_name="missing",
            focused_line_id="line-1",
            history=["keep"],
        )
        st = _StreamlitStub(session_state)
        namespace = self._load_functions(
            "clear_module_edit_scope",
            "clear_module_edit_scope_if_missing",
            "render_active_module_edit_scope_summary",
            "render_module_inspector_edit_scope_section",
            namespace={
                "st": st,
                "get_available_modules": lambda _project: ["outfit"],
                "inspect_modules": lambda _project, _disabled: {
                    "outfit": {"name": "outfit"}
                },
                "render_module_usage_inspection": lambda *_args: None,
                "render_module_edit_scope_controls": lambda *_args: None,
            },
        )

        namespace["render_module_inspector_edit_scope_section"]()

        self.assertNotIn("module_edit_scope_name", session_state)
        self.assertEqual(st.captions, ["Active Edit Scope: none"])
        self.assertEqual(st.infos, [])
        self.assertIs(session_state.project, project)
        self.assertEqual(session_state.history, ["keep"])
        self.assertEqual(session_state.focused_line_id, "line-1")

    def test_clear_action_only_clears_scope_and_reruns_once(self):
        project = object()
        session_state = _SessionState(
            project=project,
            module_edit_scope_name="outfit",
            focused_line_id="line-1",
            highlighted_line_id="line-1",
            selected_lines={"line-1": True},
            gallery_selected_line_id="line-1",
            gallery_selected_route_id="route-1",
            disabled_modules={"pose"},
            active_management_workspace="",
            production_mode="overall",
            history=["keep"],
            autosave_feedback="keep",
        )
        st = _StreamlitStub(
            session_state,
            clicked={"Clear Active Edit Scope"},
        )
        namespace = self._load_functions(
            "clear_module_edit_scope",
            "render_active_module_edit_scope_summary",
            namespace={"st": st},
        )
        preserved = {
            key: value
            for key, value in session_state.items()
            if key != "module_edit_scope_name"
        }

        namespace["render_active_module_edit_scope_summary"]()

        self.assertNotIn("module_edit_scope_name", session_state)
        self.assertEqual(st.reruns, 1)
        self.assertEqual(dict(session_state), preserved)
        self.assertIs(session_state.project, project)
        self.assertEqual(
            st.buttons,
            [
                (
                    "Clear Active Edit Scope",
                    {"key": "clear_active_module_edit_scope"},
                )
            ],
        )

    def test_project_scope_reset_is_exact_and_back_preserves_scope(self):
        session_state = _SessionState(
            module_edit_scope_name="outfit",
            module_inspector_selected="pose",
            focused_line_id="line-1",
            active_management_workspace="module_attribute_apply",
        )
        st = _StreamlitStub(session_state)
        namespace = self._load_functions(
            "reset_management_workspace_session_state",
            "reset_module_edit_scope_project_session_state",
            namespace={
                "st": st,
                "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                    "active_management_workspace"
                ),
            },
        )

        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(session_state.module_edit_scope_name, "outfit")
        self.assertEqual(session_state.active_management_workspace, "")

        namespace["reset_module_edit_scope_project_session_state"]()
        self.assertNotIn("module_edit_scope_name", session_state)
        self.assertEqual(session_state.module_inspector_selected, "pose")
        self.assertEqual(session_state.focused_line_id, "line-1")

    def test_successful_project_load_clears_scope_but_missing_file_preserves_it(self):
        old_project = object()
        new_project = types.SimpleNamespace(prompt_lines=[])
        session_state = _SessionState(
            project=old_project,
            module_edit_scope_name="outfit",
            settings={},
        )
        st = _StreamlitStub(session_state)
        st.warning = lambda _message: None
        namespace = {
            "st": st,
            "os": os,
            "profile_block": lambda _label: contextlib.nullcontext(),
            "load_project_from_json": lambda _path: new_project,
            "ensure_original_image_set_route": lambda project: project,
            "build_graph": lambda project: project,
            "reset_lightweight_fork_session_state": lambda: None,
            "reset_gallery_route_action_session_state": lambda: None,
            "reset_gallery_selected_route_session_state": lambda: None,
            "reset_management_workspace_session_state": lambda: None,
            "reset_graph_project_session_state": lambda: None,
            "reset_project_assets_operation_state": lambda: None,
            "reset_module_attribute_authoring_project_session_state": (
                lambda: None
            ),
            "reset_insert_module_reference_project_session_state": lambda: None,
            "reset_module_candidate_project_session_state": lambda: None,
            "reset_attribute_group_swap_project_session_state": lambda: None,
            "_line_candidate_key": lambda line: line,
            "_get_persistent_line_candidates": lambda _line: [],
            "ensure_current_project_folder_layout": lambda _path: True,
            "clear_module_rename_preview": lambda: None,
            "sync_text_areas": lambda: None,
            "remember_project": lambda settings, _path: settings,
            "save_settings": lambda _settings: None,
        }
        self._load_functions(
            "reset_module_edit_scope_project_session_state",
            "load_project_json_into_session",
            namespace=namespace,
        )

        with mock.patch("os.path.exists", return_value=False):
            self.assertFalse(
                namespace["load_project_json_into_session"]("missing.json")
            )
        self.assertIs(session_state.project, old_project)
        self.assertEqual(session_state.module_edit_scope_name, "outfit")

        with mock.patch("os.path.exists", return_value=True):
            self.assertTrue(
                namespace["load_project_json_into_session"]("project-b.json")
            )
        self.assertIs(session_state.project, new_project)
        self.assertNotIn("module_edit_scope_name", session_state)
        self.assertNotIn("module_inspector_selected", session_state)

    def test_project_transition_reset_runs_only_after_inputs_are_loaded(self):
        loader = self._source("load_project_json_into_session")
        load = loader.index("project = load_project_from_json(project_path)")
        reset = loader.index("reset_module_edit_scope_project_session_state()")
        assign = loader.index("st.session_state.project = project")
        self.assertLess(load, reset)
        self.assertLess(reset, assign)
        self.assertNotIn(
            "reset_module_edit_scope_project_session_state()",
            loader[:load],
        )

        new_project = self._source("set_new_workspace_project")
        self.assertEqual(
            new_project.count(
                "reset_module_edit_scope_project_session_state()"
            ),
            1,
        )
        prompt_import = self._source("render_prompt_import_export_panel")
        self.assertEqual(
            prompt_import.count(
                "reset_module_edit_scope_project_session_state()"
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
