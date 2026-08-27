from pathlib import Path
import unittest


class GalleryOperationsWorkflowGroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        launcher_start = cls.app_source.index("def render_gallery_operations_launcher")
        launcher_end = cls.app_source.index(
            "\ndef render_gallery_active_operation_panel",
            launcher_start,
        )
        cls.launcher_source = cls.app_source[launcher_start:launcher_end]
        panel_start = launcher_end
        panel_end = cls.app_source.index(
            "\ndef render_prompt_import_export_panel",
            panel_start,
        )
        cls.active_panel_source = cls.app_source[panel_start:panel_end]

    def test_workflow_groups_follow_production_order(self):
        route_group = self.launcher_source.index(
            'st.markdown("#### シーンのプロンプト・構造編集")'
        )
        phase_1 = self.launcher_source.index(
            "##### 1. Prompt／構造を編集",
            route_group,
        )
        route_buttons = self.launcher_source.index(
            "_render_gallery_operation_buttons(",
            phase_1,
        )
        route_active_panel = self.launcher_source.index(
            '_render_gallery_active_operation_for_workflow(project, "route")',
            route_buttons,
        )
        phase_2 = self.launcher_source.index(
            "##### 2. Scene Generation / シーンを一括生成",
            route_active_panel,
        )
        generation = self.launcher_source.index(
            '"gallery_generation"',
            phase_2,
        )
        generation_panel = self.launcher_source.index(
            '_render_gallery_active_operation_for_workflow(project, "generation")',
            generation,
        )
        phase_3 = self.launcher_source.index(
            "##### 3. Candidateを本編へ反映",
            generation_panel,
        )
        adoption = self.launcher_source.index(
            '"batch_candidate_adoption"',
            phase_3,
        )
        adoption_panel = self.launcher_source.index(
            '_render_gallery_active_operation_for_workflow(project, "adoption")',
            adoption,
        )
        divider = self.launcher_source.index("st.divider()", adoption_panel)
        line_group = self.launcher_source.index(
            'st.markdown("#### イラスト／Workbenchベースの作成・拡張")',
            divider,
        )
        promotion = self.launcher_source.index(
            "render_gallery_batch_variant_promotion(",
            line_group,
        )
        candidate_route = self.launcher_source.index(
            '"candidate_route_creation"',
            promotion,
        )

        self.assertEqual(
            [
                route_group,
                phase_1,
                route_buttons,
                route_active_panel,
                phase_2,
                generation,
                generation_panel,
                phase_3,
                adoption,
                adoption_panel,
                divider,
                line_group,
                promotion,
                candidate_route,
            ],
            sorted(
                [
                    route_group,
                    phase_1,
                    route_buttons,
                    route_active_panel,
                    phase_2,
                    generation,
                    generation_panel,
                    phase_3,
                    adoption,
                    adoption_panel,
                    divider,
                    line_group,
                    promotion,
                    candidate_route,
                ]
            ),
        )

    def test_major_operation_renderers_are_not_duplicated(self):
        for call in (
            "render_gallery_batch_variant_promotion(",
            '_render_gallery_active_operation_for_workflow(project, "route")',
            '_render_gallery_active_operation_for_workflow(project, "generation")',
            '_render_gallery_active_operation_for_workflow(project, "adoption")',
            '_render_gallery_active_operation_for_workflow(project, "line")',
        ):
            self.assertEqual(1, self.launcher_source.count(call))

        for call in (
            "render_module_swap_section(project)",
            "render_gallery_attribute_group_swap_section(project)",
            "render_candidate_route_creation_section(project)",
            "render_gallery_global_generation_controls(",
            "render_gallery_batch_candidate_adoption(",
        ):
            self.assertEqual(1, self.active_panel_source.count(call))

        self.assertNotIn("render_gallery_global_generation_controls(", self.launcher_source)
        self.assertNotIn("render_gallery_batch_candidate_adoption(", self.launcher_source)
        self.assertIn("embedded=True", self.active_panel_source)

        for action_key in (
            "module_swap",
            "attribute_group_swap",
            "candidate_route_creation",
        ):
            self.assertEqual(
                1,
                self.launcher_source.count(f'"{action_key}",'),
            )

    def test_route_and_line_launchers_open_in_their_own_workflow_group(self):
        group_start = self.app_source.index("def _gallery_operation_workflow_group")
        group_end = self.app_source.index(
            "\ndef _render_gallery_operation_buttons",
            group_start,
        )
        group_source = self.app_source[group_start:group_end]

        for action_key in (
            "module_swap",
            "attribute_group_swap",
            "batch_edit",
            "lightweight_fork",
        ):
            self.assertIn(f'"{action_key}"', group_source)
        for action_key in (
            "candidate_route_creation",
            "prompt_revert",
            "module_candidates",
        ):
            self.assertIn(f'"{action_key}"', group_source)
        self.assertIn('action_key == "gallery_generation"', group_source)
        self.assertIn('return "generation"', group_source)
        self.assertIn('action_key == "batch_candidate_adoption"', group_source)
        self.assertIn('return "adoption"', group_source)

        self.assertEqual(
            4,
            self.launcher_source.count("_render_gallery_active_operation_for_workflow("),
        )
        self.assertIn(
            '_render_gallery_active_operation_for_workflow(project, "route")',
            self.launcher_source,
        )
        self.assertIn(
            '_render_gallery_active_operation_for_workflow(project, "generation")',
            self.launcher_source,
        )
        self.assertIn(
            '_render_gallery_active_operation_for_workflow(project, "adoption")',
            self.launcher_source,
        )
        self.assertIn(
            '_render_gallery_active_operation_for_workflow(project, "line")',
            self.launcher_source,
        )

    def test_action_button_order_and_workflow_ownership_are_unchanged(self):
        route_actions = self.launcher_source.split(
            "##### 1. Prompt／構造を編集",
            maxsplit=1,
        )[1].split(
            '_render_gallery_active_operation_for_workflow(project, "route")',
            maxsplit=1,
        )[0]
        line_actions = self.launcher_source.split(
            'st.markdown("#### イラスト／Workbenchベースの作成・拡張")',
            maxsplit=1,
        )[1].split(
            '_render_gallery_active_operation_for_workflow(project, "line")',
            maxsplit=1,
        )[0]

        route_positions = [
            route_actions.index(f'"{action_key}"')
            for action_key in (
                "module_swap",
                "attribute_group_swap",
                "batch_edit",
                "lightweight_fork",
            )
        ]
        line_positions = [
            line_actions.index(f'"{action_key}"')
            for action_key in (
                "candidate_route_creation",
                "prompt_revert",
                "module_candidates",
            )
        ]
        self.assertEqual(route_positions, sorted(route_positions))
        self.assertEqual(line_positions, sorted(line_positions))

    def test_candidate_and_variant_expansion_difference_is_explicit(self):
        self.assertIn(
            "Batch Promote Variantsはシーン区切りを作らず通常のGalleryイラストを追加します。",
            self.launcher_source,
        )
        self.assertIn(
            "候補から別案シーンを作成はシーン区切り付きの別案シーンを追加します。",
            self.launcher_source,
        )
        self.assertIn(
            "シーン区切り付きの同一シーン別案",
            self.app_source,
        )
        self.assertIn(
            "シーン区切りも新規作成しません",
            self.app_source,
        )

    def test_grouping_layer_does_not_call_heavy_builders_or_apply_helpers(self):
        for forbidden in (
            "build_batch_variant_promotion_plan(",
            "preview_route_batch_candidate_adoption(",
            "apply_route_batch_candidate_adoption_preview(",
            "_execute_selected_routes_gallery_generation_plan(",
            "generate_image_with_progress(",
            "push_history(",
            "save_project_to_json(",
            "st.session_state.project =",
        ):
            self.assertNotIn(forbidden, self.launcher_source)

    def test_inactive_generation_and_adoption_bodies_are_not_rendered(self):
        self.assertNotIn("render_gallery_global_generation_controls(", self.launcher_source)
        self.assertNotIn("render_gallery_batch_candidate_adoption(", self.launcher_source)
        for forbidden in (
            "_build_selected_routes_gallery_generation_plan(",
            "preview_route_batch_candidate_adoption(",
            "preview_gallery_candidate_adoption(",
            "generate_image_with_progress(",
            "save_current_project_if_possible(",
            "push_history(",
        ):
            self.assertNotIn(forbidden, self.launcher_source)

    def test_selected_routes_and_gallery_regions_wrap_grouped_operations(self):
        mode_start = self.app_source.index("def render_pro_gallery_mode")
        mode_end = self.app_source.index(
            "def _restore_gallery_route_from_trash",
            mode_start,
        )
        mode_source = self.app_source[mode_start:mode_end]
        import_heading = mode_source.index(
            'st.markdown("### Illustration Import / Source")'
        )
        operations_heading = mode_source.index('st.markdown("### Gallery Operations")')
        selected_routes = mode_source.index(
            "render_gallery_selected_routes_controls(project, selected_route_state)"
        )
        grouped_operations = mode_source.index(
            "render_gallery_operations_launcher(project)"
        )
        gallery_heading = mode_source.rindex('st.markdown("### Gallery")')
        pagination = mode_source.index(
            "render_gallery_pagination_controls(display_lines)",
            gallery_heading,
        )

        self.assertLess(import_heading, operations_heading)
        self.assertLess(operations_heading, selected_routes)
        self.assertLess(selected_routes, grouped_operations)
        self.assertLess(grouped_operations, gallery_heading)
        self.assertLess(gallery_heading, pagination)


if __name__ == "__main__":
    unittest.main()
