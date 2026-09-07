"""Characterize the retained single-line ComfyUI execution boundary.

These tests load the relevant app definitions without executing Streamlit's
top-level UI.  They document the preparation contracts that must remain
stable before a future extraction can separate them from source selection,
active-token expansion, and live execution.
"""

import ast
import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _UiElement:
    def __init__(self):
        self.markdowns = []
        self.progress_values = []

    def markdown(self, value):
        self.markdowns.append(value)

    def progress(self, value):
        self.progress_values.append(value)


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _StreamlitStub:
    def __init__(self, session_state):
        self.session_state = session_state
        self.warnings = []
        self.successes = []
        self.errors = []
        self.infos = []
        self.json_values = []
        self.elements = []

    def progress(self, value):
        element = _UiElement()
        element.progress(value)
        self.elements.append(element)
        return element

    def empty(self):
        element = _UiElement()
        self.elements.append(element)
        return element

    def warning(self, value):
        self.warnings.append(value)

    def success(self, value):
        self.successes.append(value)

    def error(self, value):
        self.errors.append(value)

    def info(self, value):
        self.infos.append(value)

    def expander(self, *_args, **_kwargs):
        return _Expander()

    def json(self, value):
        self.json_values.append(value)


class ComfyExecutionPreparationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def _load(self, name, namespace):
        module = ast.Module(body=[self.functions[name]], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace[name]

    def test_focus_generation_keeps_source_fallback_and_copy_contract(self):
        project = SimpleNamespace(module_library={"character": {"body": "blue hair"}})
        line = SimpleNamespace(id="line-1", current_text="original")
        settings = {
            "comfyui_workflow_path": "configured.json",
            "fallback_prompt": "fallback",
            "force_shared_comfy_workflow": False,
        }
        state = _SessionState(
            settings=settings,
            disabled_modules={"disabled"},
            comfy_workflow_path="",
            force_shared_comfy_workflow=False,
        )
        st = SimpleNamespace(session_state=state)
        active_calls = []
        build_calls = []

        def get_active_tokens(value, disabled_modules, fallback_prompt=None, module_library=None):
            active_calls.append((value, disabled_modules, fallback_prompt, module_library))
            return ["expanded", "prompt"]

        def build_line_workflow(workflow_text, injection_line, passed_settings, **kwargs):
            build_calls.append((workflow_text, injection_line, passed_settings, kwargs))
            return {"prepared": True}, "warning from binding"

        namespace = {
            "st": st,
            "os": os,
            "copy": copy,
            "get_active_tokens": get_active_tokens,
            "_workflow_text_from_line_metadata": lambda *_args: ("", "", {"source": "metadata"}),
            "resolve_effective_comfy_workflow_path": None,
            "_build_line_workflow_from_text": build_line_workflow,
        }

        with tempfile.TemporaryDirectory() as directory:
            workflow_path = Path(directory) / "workflow.json"
            workflow_path.write_text('{"node": {"inputs": {}}}', encoding="utf-8")
            namespace["resolve_effective_comfy_workflow_path"] = (
                lambda _path: (str(workflow_path), "project")
            )
            result = self._load("_build_focus_line_generation_workflow", namespace)(project, line)

        self.assertEqual(result, ({"prepared": True}, "warning from binding"))
        self.assertEqual(active_calls, [(line, {"disabled"}, "fallback", project.module_library)])
        self.assertEqual(len(build_calls), 1)
        workflow_text, injection_line, passed_settings, kwargs = build_calls[0]
        self.assertEqual(workflow_text, '{"node": {"inputs": {}}}')
        self.assertIsNot(injection_line, line)
        self.assertEqual(injection_line.current_text, "expanded, prompt")
        self.assertEqual(line.current_text, "original")
        self.assertIs(passed_settings, settings)
        self.assertIs(kwargs["project"], project)
        self.assertEqual(kwargs["disabled_modules"], {"disabled"})
        self.assertEqual(kwargs["image_metadata"], {"source": "metadata"})

    def test_focus_generation_preserves_missing_workflow_error_contract(self):
        project = SimpleNamespace(module_library={})
        line = SimpleNamespace(id="line-1", current_text="original")
        state = _SessionState(
            settings={
                "comfyui_workflow_path": "configured.json",
                "force_shared_comfy_workflow": True,
            },
            disabled_modules=set(),
            comfy_workflow_path="",
            force_shared_comfy_workflow=True,
        )
        namespace = {
            "st": SimpleNamespace(session_state=state),
            "os": os,
            "copy": copy,
            "get_active_tokens": lambda *_args, **_kwargs: self.fail("expansion should not run"),
            "_workflow_text_from_line_metadata": lambda *_args: self.fail("metadata should be bypassed"),
            "resolve_effective_comfy_workflow_path": lambda _path: ("missing.json", "fallback"),
            "_build_line_workflow_from_text": lambda *_args, **_kwargs: self.fail("builder should not run"),
        }

        with self.assertRaisesRegex(FileNotFoundError, r"^Workflow JSON not found at missing\.json$"):
            self._load("_build_focus_line_generation_workflow", namespace)(project, line)

    def test_single_line_preparation_keeps_force_shared_and_active_token_contract(self):
        project = SimpleNamespace(module_library={"module": {"body": "smile"}})
        line = SimpleNamespace(id="line-1", current_text="original")
        settings = {"force_shared_comfy_workflow": True, "fallback_prompt": "fallback"}
        state = _SessionState(disabled_modules={"disabled"})
        active_calls = []
        build_calls = []

        def get_active_tokens(value, disabled_modules, fallback_prompt=None, module_library=None):
            active_calls.append((value, disabled_modules, fallback_prompt, module_library))
            return ["active"]

        def build_line_workflow(workflow_text, injection_line, passed_settings, **kwargs):
            build_calls.append((workflow_text, injection_line, passed_settings, kwargs))
            return {"prepared": True}, ""

        namespace = {
            "st": SimpleNamespace(session_state=state),
            "copy": copy,
            "get_active_tokens": get_active_tokens,
            "_workflow_text_from_line_metadata": lambda *_args: self.fail("force_shared must bypass metadata"),
            "resolve_effective_comfy_workflow_path": None,
            "_build_line_workflow_from_text": build_line_workflow,
        }

        with tempfile.TemporaryDirectory() as directory:
            workflow_path = Path(directory) / "workflow.json"
            workflow_path.write_text('{"node": {"inputs": {}}}', encoding="utf-8")
            namespace["resolve_effective_comfy_workflow_path"] = (
                lambda _path: (str(workflow_path), "project")
            )
            result = self._load("build_single_line_workflow", namespace)(
                "configured.json", line, settings, project=project
            )

        self.assertEqual(result, ({"prepared": True}, ""))
        self.assertEqual(active_calls, [(line, {"disabled"}, "fallback", project.module_library)])
        self.assertEqual(len(build_calls), 1)
        workflow_text, injection_line, passed_settings, kwargs = build_calls[0]
        self.assertEqual(workflow_text, '{"node": {"inputs": {}}}')
        self.assertIsNot(injection_line, line)
        self.assertEqual(injection_line.current_text, "active")
        self.assertEqual(line.current_text, "original")
        self.assertIs(passed_settings, settings)
        self.assertIs(kwargs["project"], project)
        self.assertEqual(kwargs["disabled_modules"], {"disabled"})

    def test_multi_execution_preserves_settings_fallback_and_submission_order(self):
        project = SimpleNamespace()
        line = SimpleNamespace(id="line-1", current_index=2, current_text="prompt", negative_prompt="negative")
        state = _SessionState(
            settings={"comfyui_url": "settings:8188"},
            comfy_url="",
            project=project,
        )
        st = _StreamlitStub(state)
        output_calls = []
        build_calls = []
        generate_calls = []
        execution_logs = []

        def build_workflow():
            build_calls.append(True)
            return {"node": {"inputs": {"text": "prompt"}}}, "binding warning"

        def generate_image_with_progress(workflow, comfy_url, output_dir, prefix):
            generate_calls.append((workflow, comfy_url, output_dir, prefix))
            return iter(())

        namespace = {
            "st": st,
            "os": os,
            "datetime": datetime,
            "timezone": timezone,
            "_project_generation_output_dir": lambda value: output_calls.append(value) or "output",
            "_workflow_submitted_prompt_debug": lambda workflow, value: {"text": workflow["node"]["inputs"]["text"]},
            "generate_image_with_progress": generate_image_with_progress,
            "_status_output_debug": lambda *_args, **_kwargs: {},
            "_status_output_paths": lambda *_args, **_kwargs: [],
            "_make_generated_candidate_record": lambda *_args, **_kwargs: {},
            "get_line_by_id": lambda _project, _line_id: line,
            "_append_line_generated_candidates": lambda *_args, **_kwargs: None,
            "save_current_project_if_possible": lambda *_args, **_kwargs: None,
            "_append_comfy_execution_log": execution_logs.append,
        }

        result = self._load("_run_current_line_comfy_multiple", namespace)(
            project,
            line,
            "2",
            build_workflow,
            "single_line",
        )

        self.assertEqual(result, [])
        self.assertEqual(output_calls, [project])
        self.assertEqual(len(build_calls), 2)
        self.assertEqual(
            generate_calls,
            [
                ({"node": {"inputs": {"text": "prompt"}}}, "settings:8188", "output", "single_line_run1"),
                ({"node": {"inputs": {"text": "prompt"}}}, "settings:8188", "output", "single_line_run2"),
            ],
        )
        self.assertEqual(st.warnings.count("binding warning"), 1)
        self.assertEqual(len(execution_logs), 1)
        self.assertEqual(execution_logs[0]["run_count"], 2)
        self.assertEqual(execution_logs[0]["success_count"], 0)
        self.assertEqual(execution_logs[0]["failure_count"], 2)
        self.assertEqual(execution_logs[0]["generated_paths"], [])


if __name__ == "__main__":
    unittest.main()
