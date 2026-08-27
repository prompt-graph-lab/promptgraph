import json
import os
import tempfile
import unittest

from core.gallery_generation import (
    build_selected_routes_generation_plan,
    resolve_gallery_generation_result_target,
)
from core.lightweight_fork_discovery import discover_lightweight_forks_for_source
from core.project import Project, PromptLine
from core.project_discovery import discover_project_root_projects
from core.route_operations import (
    get_route_action_dispatch_updates,
    move_route_block_up,
    remove_route_block,
    resolve_selected_route_export_lines,
    restore_removed_route,
)
from core.ui_terminology import format_core_message_for_display


def _line(line_id, text="prompt", *, line_type=None, **fields):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        **fields,
    )


class CoreReasonContractCompatibilityTests(unittest.TestCase):
    def test_route_move_remove_restore_and_action_reasons_remain_legacy_contracts(self):
        project = Project(
            prompt_lines=[
                _line("route_a", "Route A", line_type="separator"),
                _line("line_a"),
            ]
        )

        self.assertEqual("already first Route", move_route_block_up(project, "route_a")["reason"])
        self.assertEqual("separator not found", remove_route_block(project, "missing")["reason"])
        self.assertEqual("removal record not found", restore_removed_route(project, "missing")["reason"])
        self.assertEqual(
            "missing Route handle",
            get_route_action_dispatch_updates("generation", "")["reason"],
        )

    def test_selected_route_export_and_generation_reasons_remain_legacy_contracts(self):
        project = Project(prompt_lines=[])

        export_resolution = resolve_selected_route_export_lines(project, [])
        generation_plan = build_selected_routes_generation_plan(project, [])
        generation_target = resolve_gallery_generation_result_target(project, "")

        self.assertEqual("no selected Routes", export_resolution["reason"])
        self.assertEqual("Selected Routesがありません。", generation_plan["reason"])
        self.assertEqual("source Line id is missing", generation_target["reason"])
        self.assertEqual(
            "シーンが選択されていません。",
            format_core_message_for_display(export_resolution["reason"]),
        )
        self.assertEqual(
            "対象イラストのIDがありません。",
            format_core_message_for_display(generation_target["reason"]),
        )

    def test_lightweight_fork_discovery_rejection_reason_remains_legacy_contract(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = os.path.join(root, "source.json")
            with open(source_path, "w", encoding="utf-8") as handle:
                json.dump({"prompt_lines": []}, handle)
            fork_dir = os.path.join(root, "forks", "wrong-source")
            os.makedirs(os.path.join(fork_dir, "images"))
            with open(os.path.join(fork_dir, "project.json"), "w", encoding="utf-8") as handle:
                json.dump({"prompt_lines": []}, handle)
            with open(os.path.join(fork_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "manifest_version": 1,
                        "operation": "lightweight_fork_final_sequence",
                        "source_project_path": os.path.join(root, "other.json"),
                    },
                    handle,
                )

            discovery = discover_lightweight_forks_for_source(source_path)

        self.assertEqual("Fork source Project does not match", discovery["rejected"][0]["reason"])
        self.assertEqual(
            "派生Projectの元Projectが一致しません。",
            format_core_message_for_display(discovery["rejected"][0]["reason"]),
        )

    def test_project_root_discovery_reason_remains_legacy_contract(self):
        discovery = discover_project_root_projects("")

        self.assertEqual("Project root path is invalid", discovery["reason"])
        self.assertEqual(
            "Project root path is invalid",
            format_core_message_for_display(discovery["reason"]),
        )


if __name__ == "__main__":
    unittest.main()
