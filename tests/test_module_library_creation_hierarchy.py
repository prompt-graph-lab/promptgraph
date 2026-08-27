import ast
import copy
import unittest
from pathlib import Path

from core.operations import (
    apply_create_module_replace,
    apply_replace_with_module,
    create_library_module,
    preview_create_module_replace,
    preview_replace_with_module,
)
from core.project import Project, PromptLine


class ModuleLibraryCreationHierarchyTests(unittest.TestCase):
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

    def _function_source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def _call_owners(self, callee):
        owners = []
        for function_name, function_node in self.functions.items():
            for node in ast.walk(function_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == callee
                ):
                    owners.append(function_name)
        return owners

    def test_renderers_keep_one_authoring_owner(self):
        self.assertEqual(
            self._call_owners("render_create_module_from_scratch_section"),
            ["render_module_attribute_authoring_workspace"],
        )
        self.assertEqual(
            self._call_owners("render_animadex_browser_section"),
            ["render_create_module_from_scratch_section"],
        )
        self.assertEqual(
            self._call_owners("render_global_module_manager_section"),
            ["render_create_module_from_scratch_section"],
        )

        workspace = self._function_source(
            "render_module_attribute_authoring_workspace"
        )
        self.assertEqual(
            workspace.count("render_create_module_from_scratch_section(project)"),
            1,
        )
        for excluded_owner in (
            "render_module_attribute_apply_workspace",
            "render_module_attribute_apply_sidebar_section",
        ):
            self.assertNotIn(
                "render_create_module_from_scratch_section",
                self._function_source(excluded_owner),
            )

    def test_heading_hierarchy_and_render_order_are_explicit(self):
        source = self._function_source(
            "render_create_module_from_scratch_section"
        )
        expected_once = (
            'st.expander("Module Library / Creation"',
            "### Global Module Library / グローバルModule",
            "Global Module Library Search / グローバルModule検索",
            "#### Project → Global / Project Moduleをグローバル保存",
            "#### Global → Project / Global ModuleをProjectへ読み込み",
            "#### Manage Global Modules / Global Moduleの編集・管理",
            "### Project Module Creation / Project Module作成",
            "#### Blank Project Module / 空のProject Moduleを作成",
            "#### Create Module from Prompt Content / Prompt内容からModuleを作成",
            "### Replace with Existing Module / 保存済みModuleで置換",
        )
        for heading in expected_once:
            self.assertEqual(source.count(heading), 1, heading)

        ordered_markers = (
            "### Global Module Library",
            "Global Module Library Search / グローバルModule検索",
            "Search matches:",
            "render_animadex_browser_section(",
            "#### Project → Global",
            "#### Global → Project",
            "#### Manage Global Modules",
            "render_global_module_manager_section(",
            "### Project Module Creation",
            "#### Blank Project Module",
            'key="blank_module_name"',
            "#### Create Module from Prompt Content",
            'key="create_module_name"',
            "Preview Module Creation",
            "Apply Module Creation",
            "### Replace with Existing Module",
            'key="replace_with_module_targets"',
            "Preview Replace With Module",
            "Apply Replace With Module",
        )
        positions = [source.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))

    def test_existing_widget_keys_remain_unique(self):
        source = self._function_source(
            "render_create_module_from_scratch_section"
        )
        exact_keys = (
            "global_module_save_name",
            "global_module_save_overwrite",
            "global_module_save_btn",
            "global_module_load_name",
            "global_module_load_overwrite",
            "global_module_load_btn",
            "global_module_library_search_clear",
            "blank_module_name",
            "blank_module_type",
            "blank_module_body",
            "blank_module_create_btn",
            "create_module_name",
            "create_module_body",
            "create_module_type",
            "create_module_targets",
            "create_module_preview_btn",
            "create_module_apply_btn",
            "replace_with_module_targets",
            "replace_with_module_name",
            "replace_with_module_preview_btn",
            "replace_with_module_apply_btn",
        )
        for key in exact_keys:
            self.assertEqual(source.count(f'key="{key}"'), 1, key)
        self.assertEqual(source.count("global_module_save_category_"), 1)

    def test_transfer_and_blank_creation_semantics_are_unchanged(self):
        source = self._function_source(
            "render_create_module_from_scratch_section"
        )
        project_to_global = source.split(
            "#### Project → Global", maxsplit=1
        )[1].split("#### Global → Project", maxsplit=1)[0]
        self.assertIn(
            "save_and_cache_global_module_library(",
            project_to_global,
        )
        self.assertNotIn("push_history()", project_to_global)
        self.assertNotIn("build_graph(", project_to_global)

        global_to_project = source.split(
            "#### Global → Project", maxsplit=1
        )[1].split("#### Manage Global Modules", maxsplit=1)[0]
        for expected in (
            "push_history()",
            "build_graph(",
            "restore_focus_after_graph_update(",
            "sync_text_areas()",
        ):
            self.assertIn(expected, global_to_project)

        blank_creation = source.split(
            "#### Blank Project Module", maxsplit=1
        )[1].split("#### Create Module from Prompt Content", maxsplit=1)[0]
        self.assertIn("create_library_module(", blank_creation)
        self.assertIn("push_history()", blank_creation)
        for forbidden in (
            "apply_create_module_replace(",
            "apply_replace_with_module(",
            "line.current_text",
        ):
            self.assertNotIn(forbidden, blank_creation)

    def test_create_and_replace_sections_keep_separate_preview_contracts(self):
        source = self._function_source(
            "render_create_module_from_scratch_section"
        )
        create_section, replace_section = source.split(
            "### Replace with Existing Module", maxsplit=1
        )
        create_section = create_section.split(
            "#### Create Module from Prompt Content", maxsplit=1
        )[1]

        for expected in (
            "preview_signature",
            "preview_current",
            "Preview is out of date. Run preview again.",
            "preview_create_module_replace(",
            "apply_create_module_replace(",
            "push_history()",
            "restore_focus_after_graph_update(",
            "sync_text_areas()",
        ):
            self.assertIn(expected, create_section)
        self.assertNotIn("return", create_section)

        for expected in (
            "replace_signature",
            "replace_preview_current",
            "Replace preview is out of date. Run preview again.",
            "preview_replace_with_module(",
            "apply_replace_with_module(",
            "target != replacement_module",
            "push_history()",
            "restore_focus_after_graph_update(",
            "sync_text_areas()",
        ):
            self.assertIn(expected, replace_section)

        self.assertLess(
            source.index("apply_create_module_replace("),
            source.index("### Replace with Existing Module"),
        )

    def test_guards_and_empty_states_remain_before_or_inside_operations(self):
        source = self._function_source(
            "render_create_module_from_scratch_section"
        )
        first_heading = source.index("### Global Module Library")
        self.assertLess(source.index("if not project:"), first_heading)
        self.assertLess(source.index("if is_free():"), first_heading)
        for empty_state in (
            "Create a saved project module before saving to the global library.",
            "No global modules saved yet.",
            "No global modules to edit yet.",
            "No replacement targets detected.",
        ):
            owner = (
                self._function_source("render_global_module_manager_section")
                if empty_state == "No global modules to edit yet."
                else source
            )
            self.assertIn(empty_state, owner)

    def test_global_manager_keeps_metadata_preserving_operations(self):
        manager = self._function_source("render_global_module_manager_section")
        for expected in (
            "update_module_entry_preserving_metadata(",
            "copy_outfit_module_to_character_attribute_group(",
            "save_and_cache_global_module_library(",
        ):
            self.assertIn(expected, manager)

    def test_blank_and_targetless_creation_do_not_rewrite_prompt(self):
        line = PromptLine(
            id="line-1",
            original_file_name="fixture.txt",
            original_index=0,
            current_index=0,
            original_text="red dress, smile",
            current_text="red dress, smile",
            tokens=["red dress", "smile"],
        )
        project = Project(prompt_lines=[line])
        prompt_before = copy.deepcopy(project.prompt_lines)

        self.assertTrue(
            create_library_module(project, "blank pose", "", "generic")
        )
        self.assertEqual(project.prompt_lines, prompt_before)

        prompt_content_before = (
            project.prompt_lines[0].current_text,
            list(project.prompt_lines[0].tokens),
            project.prompt_lines[0].edited,
        )
        preview = preview_create_module_replace(
            project,
            "outfit",
            "red dress",
        )
        self.assertEqual(preview["affected_line_count"], 0)
        apply_create_module_replace(
            project,
            "outfit",
            "red dress",
        )
        self.assertEqual(
            (
                project.prompt_lines[0].current_text,
                project.prompt_lines[0].tokens,
                project.prompt_lines[0].edited,
            ),
            prompt_content_before,
        )
        self.assertIn("outfit", project.module_library)

    def test_create_and_existing_replace_engines_keep_distinct_semantics(self):
        create_project = Project(
            prompt_lines=[
                PromptLine(
                    id="line-1",
                    original_file_name="fixture.txt",
                    original_index=0,
                    current_index=0,
                    original_text="red dress, smile",
                    current_text="red dress, smile",
                    tokens=["red dress", "smile"],
                )
            ]
        )
        create_preview = preview_create_module_replace(
            create_project,
            "outfit",
            "red dress",
            token_targets=["red dress"],
        )
        self.assertEqual(create_preview["affected_line_count"], 1)
        apply_create_module_replace(
            create_project,
            "outfit",
            "red dress",
            token_targets=["red dress"],
        )
        self.assertIn("outfit", create_project.module_library)
        self.assertEqual(
            create_project.prompt_lines[0].current_text,
            "<mod:outfit>, smile",
        )

        replace_project = Project(
            prompt_lines=[
                PromptLine(
                    id="line-2",
                    original_file_name="fixture.txt",
                    original_index=0,
                    current_index=0,
                    original_text="red dress, smile",
                    current_text="red dress, smile",
                    tokens=["red dress", "smile"],
                )
            ],
            module_library={
                "existing outfit": {
                    "body": "blue dress",
                    "type": "generic",
                }
            },
        )
        module_count_before = len(replace_project.module_library)
        replace_preview = preview_replace_with_module(
            replace_project,
            "existing outfit",
            token_targets=["red dress"],
        )
        self.assertEqual(replace_preview["affected_line_count"], 1)
        apply_replace_with_module(
            replace_project,
            "existing outfit",
            token_targets=["red dress"],
        )
        self.assertEqual(len(replace_project.module_library), module_count_before)
        self.assertEqual(
            replace_project.prompt_lines[0].current_text,
            "<mod:existing outfit>, smile",
        )


if __name__ == "__main__":
    unittest.main()
