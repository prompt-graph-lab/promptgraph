import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Sidebar:
    def __init__(self, button_clicked=False):
        self.button_clicked = button_clicked
        self.button_calls = []

    def markdown(self, *args, **kwargs):
        return None

    def subheader(self, *args, **kwargs):
        return None

    def button(self, label, **kwargs):
        self.button_calls.append((label, kwargs))
        return self.button_clicked


class GraphSidebarModeSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.app_source = cls.app_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        cls.top_level = ast.Module(
            body=[
                node
                for node in cls.tree.body
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ],
            type_ignores=[],
        )

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _load_functions(self, names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    @staticmethod
    def _direct_named_call_count(nodes, called_name):
        return sum(
            1
            for node in ast.walk(nodes)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == called_name
        )

    def test_common_undo_and_graph_sidebar_have_one_top_level_owner(self):
        self.assertEqual(
            self._direct_named_call_count(
                self.top_level,
                "render_common_undo_sidebar_section",
            ),
            1,
        )
        self.assertEqual(
            self._direct_named_call_count(
                self.top_level,
                "render_graph_sidebar_controls",
            ),
            1,
        )

        for renderer_name in (
            "render_pro_gallery_mode",
            "render_pro_trash_view_mode",
            "render_management_workspace_shell",
        ):
            renderer = self.functions[renderer_name]
            self.assertEqual(
                self._direct_named_call_count(
                    renderer,
                    "render_graph_sidebar_controls",
                ),
                0,
            )

    def test_mode_context_matches_main_routing_and_validates_focus(self):
        session_state = _SessionState()
        st = SimpleNamespace(session_state=session_state)
        namespace = self._load_functions(
            ("get_line_by_id", "get_production_mode_context"),
            {"st": st},
        )
        get_context = namespace["get_production_mode_context"]
        project = SimpleNamespace(
            prompt_lines=[
                SimpleNamespace(id="line-1", deleted=False),
                SimpleNamespace(id="deleted-line", deleted=True),
            ]
        )

        session_state.update(
            gallery_main_mode_enabled=True,
            trash_view_mode_enabled=False,
            focused_line_id=None,
        )
        self.assertEqual(get_context(project)["mode"], "gallery")
        self.assertFalse(get_context(project)["graph_context"])

        session_state.trash_view_mode_enabled = True
        self.assertEqual(get_context(project)["mode"], "trash")
        self.assertFalse(get_context(project)["graph_context"])

        session_state.update(
            gallery_main_mode_enabled=False,
            trash_view_mode_enabled=False,
            focused_line_id=None,
        )
        self.assertEqual(get_context(project)["mode"], "overall")
        self.assertTrue(get_context(project)["graph_context"])

        session_state.update(
            gallery_main_mode_enabled=True,
            focused_line_id="line-1",
        )
        focus_context = get_context(project)
        self.assertEqual(focus_context["mode"], "focus")
        self.assertTrue(focus_context["focus_edit_active"])
        self.assertTrue(focus_context["graph_context"])

        session_state.focused_line_id = "deleted-line"
        self.assertEqual(get_context(project)["mode"], "gallery")
        self.assertFalse(get_context(project)["focus_edit_active"])

    def test_top_level_renders_undo_for_every_production_mode_and_guards_graph(self):
        start = self.app_source.rindex("render_common_undo_sidebar_section()")
        end = self.app_source.index(
            "render_module_attribute_apply_sidebar_section(",
            start,
        )
        orchestration = self.app_source[start:end]
        self.assertEqual(orchestration.count("render_common_undo_sidebar_section()"), 1)
        self.assertEqual(orchestration.count("render_graph_sidebar_controls("), 1)
        self.assertIn(
            'if production_mode_context["graph_context"]:',
            orchestration,
        )
        self.assertLess(
            orchestration.index("render_common_undo_sidebar_section()"),
            orchestration.index('if production_mode_context["graph_context"]:'),
        )

    def test_graph_labels_and_mutations_are_owned_by_graph_renderer(self):
        graph_renderer = self._function_source("render_graph_sidebar_controls")
        common_undo = self._function_source("render_common_undo_sidebar_section")
        for label in (
            "Graph / 表示",
            "グラフ設定",
            "Neighborhood Steps",
            "Merge Identical Prompts",
            "Connect Mode",
            "Path Filter",
        ):
            self.assertIn(label, graph_renderer)
            self.assertNotIn(label, common_undo)

        self.assertIn("build_graph(project)", graph_renderer)
        self.assertIn("sanitize_selected_node_ids(project)", graph_renderer)
        self.assertNotIn("build_graph", common_undo)
        self.assertNotIn("sanitize_selected_node_ids", common_undo)
        self.assertNotIn("save_project", graph_renderer)
        self.assertNotIn("push_history", graph_renderer)

    def test_graph_widget_cleanup_preserves_durable_state(self):
        constants = {
            "GRAPH_NEIGHBORHOOD_STEPS_STATE_KEY": "graph_neighborhood_steps",
            "GRAPH_NEIGHBORHOOD_STEPS_WIDGET_KEY": "_graph_neighborhood_steps_widget",
            "GRAPH_PATH_FILTER_STATE_KEY": "graph_path_filter_enabled",
            "GRAPH_PATH_FILTER_WIDGET_KEY": "_graph_path_filter_widget",
            "GRAPH_CONNECT_MODE_WIDGET_KEY": "_graph_connect_mode_widget",
            "GRAPH_MERGE_WIDGET_KEY": "_graph_merge_by_word_widget",
            "GRAPH_LAYOUT_MODE_STATE_KEY": "graph_layout_mode_value",
            "GRAPH_LAYOUT_MODE_WIDGET_KEY": "_graph_layout_mode_widget",
            "GRAPH_COOCCURRENCE_STATE_KEY": "graph_show_cooccurrence_overlay",
            "GRAPH_COOCCURRENCE_WIDGET_KEY": "_graph_show_cooccurrence_overlay_widget",
        }
        session_state = _SessionState(
            graph_neighborhood_steps=3,
            graph_path_filter_enabled=True,
            connect_mode=True,
            graph_layout_mode_value="均等整列",
            graph_show_cooccurrence_overlay=False,
        )
        namespace = self._load_functions(
            (
                "reset_graph_control_widget_state",
                "prepare_graph_control_widget_state",
            ),
            {
                "st": SimpleNamespace(session_state=session_state),
                **constants,
            },
        )
        project = SimpleNamespace(merge_by_word_only=False)

        namespace["prepare_graph_control_widget_state"](project)
        self.assertEqual(session_state["_graph_neighborhood_steps_widget"], 3)
        self.assertTrue(session_state["_graph_path_filter_widget"])
        self.assertTrue(session_state["_graph_connect_mode_widget"])
        self.assertFalse(session_state["_graph_merge_by_word_widget"])
        self.assertEqual(session_state["_graph_layout_mode_widget"], "均等整列")
        self.assertFalse(session_state["_graph_show_cooccurrence_overlay_widget"])

        namespace["reset_graph_control_widget_state"]()
        self.assertEqual(session_state["graph_neighborhood_steps"], 3)
        self.assertTrue(session_state["graph_path_filter_enabled"])
        self.assertTrue(session_state["connect_mode"])
        self.assertEqual(session_state["graph_layout_mode_value"], "均等整列")
        self.assertFalse(session_state["graph_show_cooccurrence_overlay"])
        self.assertFalse(project.merge_by_word_only)
        self.assertFalse(
            any(key.startswith("_graph_") for key in session_state)
        )

        namespace["prepare_graph_control_widget_state"](project)
        self.assertEqual(session_state["_graph_neighborhood_steps_widget"], 3)
        self.assertTrue(session_state["_graph_path_filter_widget"])
        self.assertTrue(session_state["_graph_connect_mode_widget"])
        self.assertFalse(session_state["_graph_merge_by_word_widget"])

    def test_legacy_widget_values_migrate_to_distinct_durable_keys(self):
        expected_pairs = (
            (
                'GRAPH_NEIGHBORHOOD_STEPS_STATE_KEY = "graph_neighborhood_steps"',
                'st.session_state.get("neighborhood_steps", 5)',
            ),
            (
                'GRAPH_PATH_FILTER_STATE_KEY = "graph_path_filter_enabled"',
                'st.session_state.get("focus_mode", False)',
            ),
            (
                'GRAPH_LAYOUT_MODE_STATE_KEY = "graph_layout_mode_value"',
                '"graph_layout_mode",',
            ),
            (
                'GRAPH_COOCCURRENCE_STATE_KEY = "graph_show_cooccurrence_overlay"',
                'st.session_state.get("show_cooccurrence_overlay", True)',
            ),
        )
        for durable_declaration, legacy_read in expected_pairs:
            self.assertIn(durable_declaration, self.app_source)
            self.assertIn(legacy_read, self.app_source)

    def test_common_undo_preserves_history_focus_restore_and_rerun_contract(self):
        session_state = _SessionState(
            history=["snapshot"],
            focused_line_id="line-1",
        )
        sidebar = _Sidebar(button_clicked=True)
        calls = []
        namespace = self._load_functions(
            ("render_common_undo_sidebar_section",),
            {
                "st": SimpleNamespace(
                    session_state=session_state,
                    sidebar=sidebar,
                    rerun=lambda: calls.append(("rerun", None)),
                ),
                "undo": lambda: calls.append(("undo", None)),
                "restore_focus_after_graph_update": lambda line_id: calls.append(
                    ("restore", line_id)
                ),
            },
        )

        namespace["render_common_undo_sidebar_section"]()
        self.assertEqual(
            calls,
            [
                ("undo", None),
                ("restore", "line-1"),
                ("rerun", None),
            ],
        )
        self.assertEqual(sidebar.button_calls[0][0], "Undo")
        self.assertFalse(sidebar.button_calls[0][1]["disabled"])

        empty_state = _SessionState(history=[], focused_line_id=None)
        empty_sidebar = _Sidebar(button_clicked=False)
        empty_calls = []
        empty_namespace = self._load_functions(
            ("render_common_undo_sidebar_section",),
            {
                "st": SimpleNamespace(
                    session_state=empty_state,
                    sidebar=empty_sidebar,
                    rerun=lambda: empty_calls.append("rerun"),
                ),
                "undo": lambda: empty_calls.append("undo"),
                "restore_focus_after_graph_update": lambda line_id: empty_calls.append(
                    "restore"
                ),
            },
        )
        empty_namespace["render_common_undo_sidebar_section"]()
        self.assertTrue(empty_sidebar.button_calls[0][1]["disabled"])
        self.assertEqual(empty_calls, [])

    def test_keyboard_undo_contract_is_unchanged(self):
        shortcut_renderer = self._function_source("render_shortcut_actions")
        self.assertIn('key="shortcut_undo"', shortcut_renderer)
        self.assertIn("undo()", shortcut_renderer)
        self.assertIn("restore_focus_after_graph_update", shortcut_renderer)
        self.assertIn("st.rerun()", shortcut_renderer)

    def test_project_replacement_resets_only_temporary_graph_widget_keys(self):
        reset_source = self._function_source("reset_graph_control_widget_state")
        for durable_key in (
            "GRAPH_NEIGHBORHOOD_STEPS_STATE_KEY",
            "GRAPH_PATH_FILTER_STATE_KEY",
            "GRAPH_LAYOUT_MODE_STATE_KEY",
            "GRAPH_COOCCURRENCE_STATE_KEY",
            '"connect_mode"',
        ):
            self.assertNotIn(durable_key, reset_source)

        load_source = self._function_source("load_project_json_into_session")
        missing_path_guard = load_source.index("if not os.path.exists(project_path):")
        widget_reset = load_source.index("reset_graph_project_session_state()")
        self.assertLess(missing_path_guard, widget_reset)
        self.assertEqual(load_source.count("reset_graph_project_session_state()"), 1)

        for transition_owner in (
            "set_new_workspace_project",
            "render_prompt_import_export_panel",
        ):
            self.assertIn(
                "reset_graph_project_session_state()",
                self._function_source(transition_owner),
            )

        project_reset_source = self._function_source("reset_graph_project_session_state")
        self.assertIn("reset_graph_control_widget_state()", project_reset_source)
        self.assertIn(
            "reset_graph_edit_illustration_browser_state()",
            project_reset_source,
        )

    def test_graph_widget_keys_are_unique_and_temporary(self):
        widget_keys = (
            "_graph_neighborhood_steps_widget",
            "_graph_path_filter_widget",
            "_graph_connect_mode_widget",
            "_graph_merge_by_word_widget",
            "_graph_layout_mode_widget",
            "_graph_show_cooccurrence_overlay_widget",
        )
        self.assertEqual(len(widget_keys), len(set(widget_keys)))
        for widget_key in widget_keys:
            self.assertEqual(self.app_source.count(f'"{widget_key}"'), 1)

    def test_docs_record_mode_ownership_and_state_preservation(self):
        root = self.app_path.parent
        architecture = (
            root / "docs" / "architecture" / "sidebar-workspace-separation.md"
        ).read_text(encoding="utf-8")
        pro_notes = (root / "docs" / "pro-v1.md").read_text(encoding="utf-8")
        for expected in (
            "Gallery Edit and Trash keep Undo",
            "Overall Edit and Focus Edit",
            "Hiding the widgets therefore does not reset their values",
        ):
            self.assertIn(expected, architecture)
        for expected in (
            "Undo remains available for a loaded Project in Gallery Edit, "
            "Trash, Overall Edit, and Focus Edit",
            "Temporary widget keys are reconstructed from durable session "
            "values or `project.merge_by_word_only`",
        ):
            self.assertIn(expected, pro_notes)


if __name__ == "__main__":
    unittest.main()
