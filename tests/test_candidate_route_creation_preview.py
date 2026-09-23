import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.candidate_route_creation_preview import build_candidate_route_creation_preview


class CandidateRouteCreationPreviewTests(unittest.TestCase):
    def test_counts_skips_preserves_order_and_reserves_labels_beyond_example_limit(self):
        lines = [SimpleNamespace(id=name, current_index=index) for index, name in enumerate(("first", "empty", "second"))]
        project = SimpleNamespace(prompt_lines=lines)
        candidates = {
            "first": [
                {"path": "missing.png"},
                {"path": "duplicate.png"},
                {"path": "one\\valid.png", "created_at": "today"},
                {"path": "two.png"},
                {"path": "three.png"},
                {"path": "four.png"},
                {"path": "five.png"},
            ],
            "empty": [],
            "second": ["second.png"],
        }
        before = copy.deepcopy(candidates)
        warnings = ["scope warning"]
        route_resolution = {"route_id": "route-a"}
        calls = []

        def resolve(path):
            calls.append(("resolve", path))
            return f"asset/{path}" if path else ""

        def exists(path):
            calls.append(("exists", path))
            return path != "asset/missing.png"

        def duplicate(_project, line_id, path):
            calls.append(("duplicate", line_id, path))
            return path == "duplicate.png"

        def label(_project, line, reserved):
            value = f"Candidates {len(reserved) + 1}"
            reserved.add(value)
            calls.append(("label", line.id, value))
            return value

        preview = build_candidate_route_creation_preview(
            project,
            "selected_lines",
            {"target_lines": lines, "warnings": warnings, "route_resolution": route_resolution},
            1,
            active_candidates_for_line=lambda line: candidates[line.id],
            resolve_path=resolve,
            path_exists=exists,
            duplicate_exists=duplicate,
            route_label=label,
            line_base_label=lambda line: f"Line {line.id}",
        )

        self.assertEqual(candidates, before)
        self.assertEqual(
            {key: preview[key] for key in (
                "scope", "target_line_count", "candidate_line_count", "route_count",
                "add_line_count", "skip_count", "missing_count", "duplicate_count", "no_candidate_count",
            )},
            {
                "scope": "selected_lines", "target_line_count": 3, "candidate_line_count": 2,
                "route_count": 2, "add_line_count": 6, "skip_count": 3,
                "missing_count": 1, "duplicate_count": 1, "no_candidate_count": 1,
            },
        )
        self.assertIs(preview["warnings"], warnings)
        self.assertIs(preview["route_resolution"], route_resolution)
        self.assertEqual(preview["examples"], [{
            "line_id": "first", "display_id": "Line first", "line_index": 0,
            "route_label": "Candidates 1", "candidate_count": 5,
            "candidate_paths": ["one/valid.png", "two.png", "three.png", "four.png"],
        }])
        self.assertIn(("label", "second", "Candidates 2"), calls)
        self.assertIn(("exists", "asset/missing.png"), calls)
        self.assertIn(("resolve", "one/valid.png"), calls)

    def test_empty_path_still_resolves_before_missing_check(self):
        line = SimpleNamespace(id="one")
        calls = []
        result = build_candidate_route_creation_preview(
            SimpleNamespace(prompt_lines=[line]), "all_lines",
            {"target_lines": [line], "warnings": []},
            active_candidates_for_line=lambda _: [{"path": ""}],
            resolve_path=lambda path: calls.append(path) or "",
            path_exists=lambda _: self.fail("empty path must skip existence check"),
            duplicate_exists=lambda *_: self.fail("empty path must skip duplicate check"),
            route_label=lambda *_: self.fail("empty path must skip label allocation"),
            line_base_label=lambda _: "unused",
        )
        self.assertEqual(calls, [""])
        self.assertEqual(result["missing_count"], 1)
        self.assertEqual(result["examples"], [])

    def test_app_wrapper_passes_scope_resolution_and_runtime_callbacks(self):
        source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        node = next(
            item for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == "preview_candidate_route_creation"
        )
        wrapper = compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec")
        resolution = {"target_lines": [], "warnings": ["warning"]}
        marker = object()
        received = {}

        def build(*args, **kwargs):
            received["args"] = args
            received["kwargs"] = kwargs
            return marker

        namespace = {
            "_candidate_route_target_lines": lambda *args: resolution,
            "build_candidate_route_creation_preview": build,
        }
        callback_names = {
            "active_candidates_for_line": "_line_active_generated_candidates",
            "resolve_path": "_runtime_asset_path",
            "path_exists": "profiled_path_exists",
            "duplicate_exists": "_candidate_route_duplicate_exists",
            "route_label": "_candidate_route_label",
            "line_base_label": "_candidate_route_line_base_label",
        }
        for name in callback_names.values():
            namespace[name] = object()
        exec(wrapper, namespace)
        project = object()
        self.assertIs(namespace["preview_candidate_route_creation"](project, "focused_line", ["x"], 3), marker)
        self.assertEqual(received["args"], (project, "focused_line", resolution, 3))
        for keyword, name in callback_names.items():
            self.assertIs(received["kwargs"][keyword], namespace[name])


if __name__ == "__main__":
    unittest.main()
