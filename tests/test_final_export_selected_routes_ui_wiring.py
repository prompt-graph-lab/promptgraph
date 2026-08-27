import ast
from pathlib import Path
import unittest


class FinalExportSelectedRoutesUiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_final_export_scope_and_selected_route_state_are_wired(self):
        self.assertIn('["all_lines", "current_route", "selected_route", "selected_routes"]', self.app_source)
        self.assertIn('selected_route_ids = st.session_state.get("gallery_selected_route_ids", [])', self.app_source)
        self.assertIn("selected_route_ids=selected_route_ids", self.app_source)
        self.assertIn("resolve_selected_route_export_lines", self.app_source)
        self.assertIn("GALLERY_SCOPE_DISPLAY_LABELS_JA", self.app_source)
        terminology_source = (
            Path(__file__).resolve().parents[1] / "core" / "ui_terminology.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"selected_routes": "選択中の複数シーン"', terminology_source)

    def test_selected_routes_hides_single_route_selector(self):
        start = self.app_source.index("def render_gallery_final_image_export")
        end = self.app_source.index("def _gallery_route_line_count", start)
        export_source = self.app_source[start:end]
        selector_start = export_source.index('if export_scope == "selected_route":')
        selector_end = export_source.index("col_a, col_b, col_c", selector_start)
        selector_source = export_source[selector_start:selector_end]
        self.assertIn("gallery_final_export_selected_route_id", selector_source)
        self.assertNotIn("selected_routes", selector_source)

    def test_selected_routes_use_fresh_preview_signature_before_export(self):
        start = self.app_source.index("def render_gallery_final_image_export")
        end = self.app_source.index("def _gallery_route_line_count", start)
        export_source = self.app_source[start:end]
        self.assertIn("def _final_export_preview_signature", self.app_source)
        self.assertIn("gallery_final_export_selected_routes_preview_signature", export_source)
        self.assertIn("gallery_final_export_selected_routes_preview_button", export_source)
        self.assertIn("not selected_routes_preview_current", export_source)
        self.assertIn("selected_route_handles=target_resolution[\"resolved_route_handles\"]", export_source)
        self.assertIn("selected_route_labels=target_resolution[\"resolved_route_labels\"]", export_source)
        self.assertIn("route_summaries=target_resolution[\"route_summaries\"]", export_source)

    def test_existing_operation_panels_do_not_use_selected_routes_state(self):
        operation_start = self.app_source.index("def render_gallery_operations_launcher")
        operation_end = self.app_source.index("\ndef render_prompt_import_export_panel", operation_start)
        operation_source = self.app_source[operation_start:operation_end]
        self.assertNotIn("gallery_selected_route_ids", operation_source)
        self.assertIn('key="_gallery_generation_scope_widget"', self.app_source)
        self.assertIn('"gallery_generation_scope"', self.app_source)
        self.assertIn('key="gallery_final_export_scope"', self.app_source)

    def test_size_destination_metrics_table_and_warnings_are_wired(self):
        start = self.app_source.index("def render_gallery_final_image_export")
        end = self.app_source.index("def _gallery_route_line_count", start)
        export_source = self.app_source[start:end]
        for expected in (
            "Exportable images",
            "Skipped illustrations",
            "Source total size / 出力前合計容量",
            "Destination free",
            "Planned overwrite",
            "Destination profile",
            '"size": (',
            "PNGメタデータ削除が有効な場合",
            'capacity_status == "insufficient"',
            'capacity_status == "unknown"',
            'destination_kind") == "final_root"',
            "既存画像",
            "manifest",
        ):
            self.assertIn(expected, export_source)

    def test_capacity_is_informational_and_does_not_disable_export(self):
        start = self.app_source.index(
            'if st.button(\n            "最終画像を書き出す"'
        )
        end = self.app_source.index("summary = export_final_images(", start)
        button_source = self.app_source[start:end]
        self.assertNotIn("capacity_status", button_source)
        self.assertNotIn("disk_free_bytes", button_source)
        self.assertIn('preview["exportable_count"] == 0', button_source)
        self.assertIn("not selected_routes_preview_current", button_source)

    def test_existing_widget_keys_and_scope_options_are_unchanged(self):
        expected_keys = (
            "gallery_final_export_use_timestamp",
            "final_image_export_timestamp",
            "gallery_final_export_scope",
            "gallery_final_export_selected_route_id",
            "gallery_final_export_base_filename",
            "gallery_final_export_start_index",
            "gallery_final_export_digits",
            "gallery_final_export_strip_metadata",
            "gallery_final_export_selected_routes_preview_button",
            "gallery_final_export_button",
        )
        for key in expected_keys:
            self.assertIn(f'"{key}"', self.app_source)
        self.assertIn(
            '["all_lines", "current_route", "selected_route", "selected_routes"]',
            self.app_source,
        )

    def test_final_export_renderer_has_one_owner(self):
        tree = ast.parse(self.app_source)
        render_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_gallery_final_image_export"
        ]
        self.assertEqual(
            len(render_calls),
            1,
        )


if __name__ == "__main__":
    unittest.main()
