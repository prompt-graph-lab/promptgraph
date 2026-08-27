import ast
import hashlib
import unittest
from pathlib import Path


class GraphEditIllustrationBrowserUIWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.source = cls.app_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _source(self, name):
        return ast.get_source_segment(self.source, self.functions[name])

    def test_graph_edit_has_one_browser_owner_and_old_full_loop_is_removed(self):
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_graph_edit_illustration_browser"
        ]
        self.assertEqual(1, len(calls))
        call_index = self.source.rindex("render_graph_edit_illustration_browser(\n")
        graph_tab_index = self.source.rfind("with tab1:", 0, call_index)
        gallery_tab_index = self.source.find("with tab3:", graph_tab_index)
        self.assertGreater(graph_tab_index, -1)
        self.assertTrue(gallery_tab_index == -1 or call_index < gallery_tab_index)
        self.assertNotIn("for l in display_lines:", self.source)

    def test_existing_authoritative_input_and_graph_node_filter_precede_browser(self):
        call_index = self.source.rindex("render_graph_edit_illustration_browser(\n")
        input_index = self.source.rfind(
            "display_lines = get_visible_prompt_lines(project)",
            0,
            call_index,
        )
        node_filter_index = self.source.find(
            "st.session_state.selected_node_ids",
            input_index,
            call_index,
        )
        filtered_assignment_index = self.source.find(
            "display_lines = [",
            node_filter_index,
            call_index,
        )
        self.assertGreater(input_index, -1)
        self.assertGreater(node_filter_index, input_index)
        self.assertGreater(filtered_assignment_index, node_filter_index)
        self.assertIn("display_lines,", self.source[call_index : call_index + 1000])

    def test_browser_is_display_only_and_does_not_reuse_gallery_state(self):
        browser = self._source("render_graph_edit_illustration_browser")
        self.assertIn(
            "このfilterとpageはIllustration一覧の表示だけを変更します。",
            browser,
        )
        self.assertIn(
            "Graph、PromptCloud、Batch Edit、Module操作は従来どおりProject全体を対象にします。",
            browser,
        )
        self.assertNotIn("project.prompt_lines =", browser)
        self.assertNotIn("gallery_", browser.lower())
        self.assertNotIn("operation_scope", browser)

    def test_controls_and_widget_keys_are_graph_edit_specific(self):
        controls = "\n".join(
            self._source(name)
            for name in (
                "_render_graph_edit_browser_visibility_controls",
                "_render_graph_edit_browser_page_controls",
                "render_graph_edit_illustration_browser",
            )
        )
        for label in (
            '"First"',
            '"Previous"',
            '"Next"',
            '"Last"',
            '"すべて表示"',
            '"すべて閉じる"',
            '"現在のイラストを表示"',
        ):
            self.assertIn(label, controls)
        for key in (
            "graph_edit_browser_first",
            "graph_edit_browser_previous",
            "graph_edit_browser_next",
            "graph_edit_browser_last",
            "graph_edit_browser_footer_previous",
            "graph_edit_browser_footer_next",
            "graph_edit_browser_expand_all",
            "graph_edit_browser_collapse_all",
            "graph_edit_browser_reveal_current",
        ):
            self.assertEqual(1, controls.count(f'key="{key}"'))
        self.assertNotIn('"All"', controls)

    def test_only_page_entries_are_dispatched_to_existing_editor(self):
        dispatcher = self._source("render_graph_edit_illustration_browser_page")
        editor = self._source("render_graph_edit_illustration_editor")
        self.assertIn('plan.get("page_entries")', dispatcher)
        self.assertNotIn("all_entries", dispatcher)
        self.assertNotIn("visible_entries", dispatcher)
        self.assertNotIn("_line_thumbnail_path", dispatcher)
        self.assertEqual(2, editor.count("_line_thumbnail_path(line)"))
        self.assertIn("render_line_list_reorder_controls", editor)

    def test_existing_editor_actions_and_widget_keys_are_preserved(self):
        editor = self._source("render_graph_edit_illustration_editor")
        for key_expression in (
            'f"chk_{line.id}"',
            'f"highlight_btn_{line.id}"',
            'f"focus_btn_{line.id}"',
            'f"text_{line.id}"',
            'f"negative_text_{line.id}"',
            'f"save_{line.id}"',
            'f"dup_{line.id}"',
            'f"del_{line.id}"',
        ):
            self.assertIn(key_expression, editor)
        for operation in (
            "update_line_prompts(",
            "duplicate_line(",
            "delete_line(",
        ):
            self.assertIn(operation, editor)

    def test_full_project_operation_renderers_are_not_inside_page_dispatch(self):
        dispatcher = self._source("render_graph_edit_illustration_browser_page")
        for renderer in (
            "render_line_groups_section",
            "render_batch_edit_section",
            "render_module_preset_section",
            "render_attribute_group_swap_section",
            "render_prompt_cloud",
        ):
            self.assertNotIn(renderer, dispatcher)

    def test_all_browser_navigation_paths_share_unsaved_guard(self):
        visibility = self._source("_render_graph_edit_browser_visibility_controls")
        controls = self._source("_render_graph_edit_browser_page_controls")
        page_setter = self._source("_set_graph_edit_browser_page")
        collapse_setter = self._source(
            "_set_graph_edit_browser_collapsed_group_keys"
        )
        filter_callback = self._source("_on_graph_edit_browser_filter_changed")
        page_size_callback = self._source(
            "_on_graph_edit_browser_page_size_changed"
        )
        page_input_callback = self._source(
            "_on_graph_edit_browser_page_input_changed"
        )
        reveal = self._source("_reveal_graph_edit_browser_current")

        self.assertEqual(
            3,
            visibility.count("_set_graph_edit_browser_collapsed_group_keys"),
        )
        self.assertEqual(6, controls.count("_set_graph_edit_browser_page,"))
        self.assertIn("block_graph_edit_browser_navigation_if_unsaved(", page_setter)
        self.assertIn(
            "block_graph_edit_browser_navigation_if_unsaved(",
            collapse_setter,
        )
        for callback in (
            filter_callback,
            page_size_callback,
            page_input_callback,
            reveal,
        ):
            self.assertIn("block_graph_edit_browser_navigation_if_unsaved(", callback)

        self.assertLess(
            filter_callback.index("block_graph_edit_browser_navigation_if_unsaved("),
            filter_callback.index("GRAPH_EDIT_BROWSER_FILTER_KEY] ="),
        )
        self.assertLess(
            page_size_callback.index("block_graph_edit_browser_navigation_if_unsaved("),
            page_size_callback.index("GRAPH_EDIT_BROWSER_PAGE_SIZE_KEY] ="),
        )

    def test_page_owner_warning_and_discard_are_browser_session_only(self):
        browser = self._source("render_graph_edit_illustration_browser")
        reset = self._source("reset_graph_edit_illustration_browser_state")
        detector = self._source("get_graph_edit_browser_unsaved_line_ids")
        discard = self._source("discard_graph_edit_browser_current_page_drafts")

        self.assertIn("GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY", browser)
        self.assertIn("GRAPH_EDIT_BROWSER_PAGE_LINE_IDS_KEY", reset)
        self.assertIn("graph_edit_browser_discard_current_page_drafts", browser)
        self.assertIn("st.warning(notice)", browser)
        self.assertIn('f"text_{line_id}"', detector)
        self.assertIn('f"negative_text_{line_id}"', detector)
        self.assertNotIn("push_history", detector + discard)
        self.assertNotIn("save_current_project", detector + discard)
        self.assertNotIn("save_settings", detector + discard)
        self.assertNotIn("update_line_prompts", detector + discard)
        self.assertNotIn("autosave", detector + discard)
        self.assertNotIn("project.prompt_lines =", detector + discard)

    def test_visibility_uses_typed_group_keys_for_widget_identity(self):
        visibility = self._source("_render_graph_edit_browser_visibility_controls")
        self.assertIn('summary["group_key"]', visibility)
        self.assertIn('summary.get("group_key")', visibility)
        self.assertNotIn('summary["handle"]', visibility)

        function = self.functions["_graph_edit_browser_group_widget_suffix"]
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {"hashlib": hashlib}
        exec(compile(module, "app.py", "exec"), namespace)
        suffix = namespace["_graph_edit_browser_group_widget_suffix"]
        self.assertNotEqual(
            suffix("scene:outside_scenes"),
            suffix("outside_scenes"),
        )
        self.assertNotEqual(suffix("scene:all"), suffix("all"))


if __name__ == "__main__":
    unittest.main()
