"""Characterize effective shared workflow precedence and its lazy boundary."""

import ast
import itertools
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.comfy_workflow_path_resolution import resolve_effective_workflow_path


class EffectiveWorkflowPathTests(unittest.TestCase):
    def test_precedence_and_exact_operation_order(self):
        for force, project, preset in itertools.product((False, True), repeat=3):
            with self.subTest(force=force, project=project, preset=preset):
                events = []

                def resolve(value):
                    events.append(("resolve", value))
                    return "project.json"

                def exists(value):
                    events.append(("exists", value))
                    return {"project.json": project, "preset.json": preset}[value]

                actual = resolve_effective_workflow_path(
                    "configured.json", "preset.json", force,
                    resolve_project_path=resolve, path_exists=exists,
                )
                expected_events = [("exists", "preset.json")] if force else []
                if force and preset:
                    expected = ("preset.json", "preset")
                else:
                    expected_events += [("resolve", "configured.json"), ("exists", "project.json")]
                    if project:
                        expected = ("project.json", "project")
                    else:
                        expected_events.append(("exists", "preset.json"))
                        expected = ("preset.json", "preset") if preset else ("project.json", "fallback")
                self.assertEqual(actual, expected)
                self.assertEqual(events, expected_events)

    def test_empty_paths_are_not_probed_and_fallback_value_is_preserved(self):
        for path in ("", None):
            exists = Mock(side_effect=AssertionError("unexpected probe"))
            resolve = Mock(return_value=path)
            result = resolve_effective_workflow_path(
                "", "", True, resolve_project_path=resolve, path_exists=exists,
            )
            self.assertIs(result[0], path)
            self.assertEqual(result[1], "fallback")
            resolve.assert_called_once_with("")
            exists.assert_not_called()

    def test_missing_forced_preset_is_checked_again(self):
        exists = Mock(side_effect=[False, False, True])
        result = resolve_effective_workflow_path(
            "configured", "preset", True,
            resolve_project_path=lambda _: "project", path_exists=exists,
        )
        self.assertEqual(result, ("preset", "preset"))
        self.assertEqual([call.args[0] for call in exists.call_args_list], ["preset", "project", "preset"])

    def test_forced_preset_bypasses_resolution_errors(self):
        resolve = Mock(side_effect=ValueError("bad path"))
        self.assertEqual(resolve_effective_workflow_path(
            "configured", "preset", True,
            resolve_project_path=resolve, path_exists=lambda _: True,
        ), ("preset", "preset"))
        resolve.assert_not_called()

    def test_callback_errors_propagate_unchanged(self):
        error = OSError("cannot resolve")
        for resolve, exists in (
            (Mock(side_effect=error), Mock()),
            (Mock(return_value="project"), Mock(side_effect=error)),
        ):
            with self.assertRaises(OSError) as raised:
                resolve_effective_workflow_path(
                    "configured", "preset", False,
                    resolve_project_path=resolve, path_exists=exists,
                )
            self.assertIs(raised.exception, error)


class AppWorkflowPathAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        names = {"resolve_effective_comfy_workflow_path", "resolve_comfy_workflow_path", "resolve_comfy_workflow_preset_path"}
        cls.code = compile(ast.Module(body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ], type_ignores=[]), "app.py", "exec")

    def load(self, state):
        class State(dict):
            def __getattr__(self, name):
                return self[name]

        namespace = {
            "st": SimpleNamespace(session_state=State(state)),
            "os": os, "WORKFLOW_PRESET_DIR": os.path.abspath("workflows"),
            "resolve_effective_workflow_path": resolve_effective_workflow_path,
        }
        exec(self.code, namespace)
        return namespace

    def test_configuration_defaults_and_explicit_falsey_override(self):
        for explicit, session, settings, expected in (
            (None, "session.json", {"comfyui_workflow_path": "stored.json"}, "session.json"),
            (None, "", {"comfyui_workflow_path": "stored.json"}, "stored.json"),
            (None, "", {}, "workflow_api.json"),
            ("", "session.json", {}, ""),
            (False, "session.json", {}, False),
            ("explicit.json", "session.json", {}, "explicit.json"),
        ):
            with self.subTest(explicit=explicit, session=session, settings=settings):
                namespace = self.load({"settings": settings, "comfy_workflow_path": session})
                delegate = Mock(return_value=("resolved", "fallback"))
                namespace["resolve_effective_workflow_path"] = delegate
                self.assertEqual(namespace["resolve_effective_comfy_workflow_path"](explicit), ("resolved", "fallback"))
                self.assertEqual(delegate.call_args.args, (expected, "", False))

    def test_session_preset_and_force_override_settings_even_when_falsey(self):
        namespace = self.load({
            "settings": {"comfyui_workflow_preset": "stored.json", "force_shared_comfy_workflow": True},
            "comfy_workflow_preset": "", "force_shared_comfy_workflow": False,
        })
        delegate = Mock()
        namespace["resolve_effective_workflow_path"] = delegate
        namespace["resolve_effective_comfy_workflow_path"]()
        self.assertEqual(delegate.call_args.args, ("workflow_api.json", "", False))

    def test_relative_project_path_and_preset_normalization(self):
        namespace = self.load({"settings": {}, "current_project_path": os.path.abspath("project/project.json")})
        self.assertEqual(namespace["resolve_comfy_workflow_path"]("workflow.json"), os.path.abspath("project/workflow.json"))
        self.assertEqual(namespace["resolve_comfy_workflow_preset_path"](" ../preset.JSON "), os.path.abspath("workflows/preset.JSON"))
        self.assertEqual(namespace["resolve_comfy_workflow_preset_path"]("preset.txt"), "")


if __name__ == "__main__":
    unittest.main()
