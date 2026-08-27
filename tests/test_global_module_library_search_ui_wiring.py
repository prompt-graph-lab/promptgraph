import ast
import types
import unittest
from pathlib import Path


class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class GlobalModuleLibrarySearchUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _function_source(self, name):
        return ast.get_source_segment(
            self.app_source,
            self.functions[name],
        )

    def _load_functions(self, *names, namespace):
        loaded = dict(namespace)
        for name in names:
            exec(
                compile(
                    ast.Module(
                        body=[self.functions[name]],
                        type_ignores=[],
                    ),
                    filename="app.py",
                    mode="exec",
                ),
                loaded,
            )
        return loaded

    def test_search_widget_and_clear_button_have_one_owner(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        self.assertEqual(
            renderer.count('"global_module_library_search_clear"'),
            1,
        )
        self.assertEqual(
            self.app_source.count(
                "key=GLOBAL_MODULE_LIBRARY_SEARCH_WIDGET_KEY"
            ),
            1,
        )
        self.assertEqual(
            self.app_source.count(
                '"_global_module_library_search_query_widget"'
            ),
            1,
        )
        self.assertEqual(
            self.app_source.count(
                'key="global_module_library_search_clear"'
            ),
            1,
        )

    def test_search_is_directly_under_global_heading_before_operations(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        markers = (
            "### Global Module Library / グローバルModule",
            "Global Module Library Search / グローバルModule検索",
            "Search matches:",
            "render_animadex_browser_section(",
            "#### Project → Global",
            "#### Global → Project",
            "#### Manage Global Modules",
        )
        positions = [renderer.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_global_to_project_and_manager_share_filtered_result(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        global_to_project = renderer.split(
            "#### Global → Project",
            maxsplit=1,
        )[1].split("#### Manage Global Modules", maxsplit=1)[0]
        manager_call = renderer.split(
            "#### Manage Global Modules",
            maxsplit=1,
        )[1].split("### Project Module Creation", maxsplit=1)[0]

        self.assertIn(
            "visible_global_module_names",
            global_to_project,
        )
        self.assertIn(
            "global_module_search_result",
            manager_call,
        )
        self.assertIn(
            "prepare_global_module_search_selection_state(",
            global_to_project,
        )
        self.assertLess(
            global_to_project.index(
                "prepare_global_module_search_selection_state("
            ),
            global_to_project.index(
                'key="global_module_load_name"'
            ),
        )
        self.assertIn(
            'reset_keys=("global_module_load_overwrite",)',
            global_to_project,
        )

    def test_project_to_global_and_animadex_remain_unfiltered(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        project_to_global = renderer.split(
            "#### Project → Global",
            maxsplit=1,
        )[1].split("#### Global → Project", maxsplit=1)[0]
        self.assertIn("project_module_names", project_to_global)
        self.assertNotIn(
            "visible_global_module_names",
            project_to_global,
        )
        self.assertIn(
            "Project → Global selects Project-owned Modules",
            project_to_global,
        )
        self.assertIn(
            "render_animadex_browser_section("
            "project, global_library, global_module_names",
            renderer,
        )
        animadex = self._function_source(
            "render_animadex_browser_section"
        )
        self.assertIn('"animadex_discovery_query"', animadex)
        self.assertNotIn(
            "global_module_library_search_query",
            animadex,
        )

    def test_manager_combines_query_result_with_existing_category_filter(self):
        manager = self._function_source(
            "render_global_module_manager_section"
        )
        self.assertIn(
            'options=["All"] + GLOBAL_MODULE_CATEGORIES',
            manager,
        )
        self.assertIn("search_matched_names", manager)
        self.assertIn(
            "get_module_category(global_library, name) == category_filter",
            manager,
        )
        self.assertIn(
            "Visible after category filter:",
            manager,
        )
        self.assertIn(
            "prepare_global_module_search_selection_state(",
            manager,
        )
        for action in (
            '"Save Global Module"',
            '"Delete Global Module"',
        ):
            action_position = manager.index(action)
            guard_position = manager.index(
                "selected_name not in filtered_module_names",
                action_position,
            )
            save_position = manager.find(
                "save_and_cache_global_module_library(",
                action_position,
            )
            self.assertGreater(save_position, guard_position)

    def test_zero_result_and_empty_library_skip_invalid_selectboxes(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        global_to_project = renderer.split(
            "#### Global → Project",
            maxsplit=1,
        )[1].split("#### Manage Global Modules", maxsplit=1)[0]
        manager = self._function_source(
            "render_global_module_manager_section"
        )
        self.assertIn(
            "Global Module Library is empty.",
            renderer,
        )
        self.assertIn(
            "検索条件に一致するGlobal Moduleはありません。",
            global_to_project,
        )
        self.assertIn(
            "検索条件に一致するGlobal Moduleはありません。",
            manager,
        )
        self.assertLess(
            global_to_project.index(
                "if visible_global_module_names:"
            ),
            global_to_project.index(
                'key="global_module_load_name"'
            ),
        )
        self.assertLess(
            manager.index("if not filtered_module_names:"),
            manager.index('key="global_module_manager_selected"'),
        )

    def test_clear_and_stale_selection_callbacks_only_touch_owned_state(self):
        state = _SessionState(
            global_module_library_search_query="rainbow",
            _global_module_library_search_query_widget="rainbow",
            global_module_load_name="hidden",
            global_module_load_overwrite=True,
            animadex_discovery_query="reimu",
            global_module_manager_category_filter="Character",
            project=object(),
            history=["keep"],
        )
        namespace = self._load_functions(
            "initialize_global_module_library_search_query",
            "sync_global_module_library_search_query",
            "clear_global_module_library_search_query",
            "prepare_global_module_search_selection_state",
            namespace={
                "st": types.SimpleNamespace(session_state=state),
                "GLOBAL_MODULE_LIBRARY_SEARCH_QUERY_KEY": (
                    "global_module_library_search_query"
                ),
                "GLOBAL_MODULE_LIBRARY_SEARCH_WIDGET_KEY": (
                    "_global_module_library_search_query_widget"
                ),
                "normalize_global_module_search_selection": (
                    lambda current, visible: (
                        current
                        if current in list(visible)
                        else (list(visible)[0] if list(visible) else "")
                    )
                ),
            },
        )

        namespace["clear_global_module_library_search_query"]()
        self.assertEqual(
            state.global_module_library_search_query,
            "",
        )
        self.assertEqual(
            state._global_module_library_search_query_widget,
            "",
        )
        self.assertEqual(state.animadex_discovery_query, "reimu")
        self.assertEqual(
            state.global_module_manager_category_filter,
            "Character",
        )
        self.assertEqual(state.history, ["keep"])

        selected = namespace[
            "prepare_global_module_search_selection_state"
        ](
            "global_module_load_name",
            ["visible"],
            reset_keys=("global_module_load_overwrite",),
        )
        self.assertEqual(selected, "visible")
        self.assertEqual(state.global_module_load_name, "visible")
        self.assertNotIn("global_module_load_overwrite", state)
        self.assertEqual(state.history, ["keep"])

    def test_widget_mirror_restores_durable_query_after_hidden_render(self):
        state = _SessionState(
            global_module_library_search_query="rainbow",
        )
        namespace = self._load_functions(
            "initialize_global_module_library_search_query",
            "sync_global_module_library_search_query",
            namespace={
                "st": types.SimpleNamespace(session_state=state),
                "GLOBAL_MODULE_LIBRARY_SEARCH_QUERY_KEY": (
                    "global_module_library_search_query"
                ),
                "GLOBAL_MODULE_LIBRARY_SEARCH_WIDGET_KEY": (
                    "_global_module_library_search_query_widget"
                ),
            },
        )

        self.assertEqual(
            namespace["initialize_global_module_library_search_query"](),
            "rainbow",
        )
        self.assertEqual(
            state._global_module_library_search_query_widget,
            "rainbow",
        )

        state._global_module_library_search_query_widget = "milku"
        namespace["sync_global_module_library_search_query"]()
        self.assertEqual(
            state.global_module_library_search_query,
            "milku",
        )

        state.pop("_global_module_library_search_query_widget")
        self.assertEqual(
            namespace["initialize_global_module_library_search_query"](),
            "milku",
        )
        self.assertEqual(
            state._global_module_library_search_query_widget,
            "milku",
        )

    def test_query_and_cache_survive_workspace_and_project_resets(self):
        for function_name in (
            "reset_management_workspace_session_state",
            "reset_module_attribute_authoring_project_session_state",
        ):
            source = self._function_source(function_name)
            self.assertNotIn(
                "global_module_library_search_query",
                source,
            )
            self.assertNotIn(
                "global_module_library_session_cache",
                source,
            )

        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        self.assertIn(
            "initialize_global_module_library_search_query()",
            renderer,
        )
        self.assertIn(
            "on_change=sync_global_module_library_search_query",
            renderer,
        )

    def test_session_cache_prevents_query_reruns_from_reloading_json(self):
        library = {"module": {"body": "prompt"}}
        state = _SessionState(settings={"global_module_library_dir": "x"})
        load_calls = []
        namespace = self._load_functions(
            "get_session_global_module_library",
            namespace={
                "st": types.SimpleNamespace(session_state=state),
                "get_global_module_library_path": (
                    lambda _settings: "x/global_modules.json"
                ),
                "load_global_module_library": (
                    lambda _settings: load_calls.append(True) or library
                ),
            },
        )

        first = namespace["get_session_global_module_library"]()
        second = namespace["get_session_global_module_library"]()
        self.assertIs(first, library)
        self.assertIs(second, library)
        self.assertEqual(load_calls, [True])

    def test_query_filter_block_has_no_io_or_persistence_calls(self):
        renderer = self._function_source(
            "render_create_module_from_scratch_section"
        )
        query_block = renderer.split(
            "search_cols = st.columns",
            maxsplit=1,
        )[1].split(
            "render_animadex_browser_section(",
            maxsplit=1,
        )[0]
        for forbidden in (
            "load_global_module_library(",
            "save_global_module_library(",
            "open(",
            "os.walk",
            "glob(",
            "import glob",
            "discover_animadex",
            "save_project",
            "hashlib",
            "Image.open",
        ):
            self.assertNotIn(forbidden, query_block)


if __name__ == "__main__":
    unittest.main()
