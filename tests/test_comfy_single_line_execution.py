"""Characterize single-submission ComfyUI progress and output collection."""

import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ui import comfy_single_line_execution


class SingleLineComfyExecutionTests(unittest.TestCase):
    def test_widgets_precede_submission_and_done_paths_keep_event_order(self):
        events = []

        class Progress:
            def progress(self, value):
                events.append(("progress", value))

        class Status:
            def markdown(self, value):
                events.append(("status", value))

        def make_progress(value):
            events.append(("create_progress", value))
            return Progress()

        def make_status():
            events.append(("create_status",))
            return Status()

        first_done = {"type": "done", "value": 1.0, "text": "Completed", "paths": ["first"]}
        second_done = {"type": "done", "paths": ["first", "second"]}

        def status_source():
            events.append(("submit",))
            return iter([
                {"type": "status", "value": 0.25, "text": "Queued"},
                first_done,
                second_done,
            ])

        def output_paths(status, *, output_dir):
            events.append(("resolve", status, output_dir))
            return status["paths"]

        fake_st = SimpleNamespace(progress=make_progress, empty=make_status)
        with patch.object(comfy_single_line_execution, "st", fake_st):
            paths = comfy_single_line_execution.collect_single_line_comfy_outputs(
                status_source, "output", output_paths
            )

        self.assertEqual(paths, ["first", "first", "second"])
        self.assertEqual(events, [
            ("create_progress", 0.0),
            ("create_status",),
            ("submit",),
            ("progress", 0.25),
            ("status", "**Status:** Queued"),
            ("progress", 1.0),
            ("status", "**Status:** Completed"),
            ("resolve", first_done, "output"),
            ("resolve", second_done, "output"),
        ])

    def test_submission_and_path_errors_propagate(self):
        fake_st = SimpleNamespace(
            progress=lambda _value: SimpleNamespace(progress=lambda _value: None),
            empty=lambda: SimpleNamespace(markdown=lambda _value: None),
        )

        def fail_submission():
            raise RuntimeError("submission failed")

        def fail_paths(_status, *, output_dir):
            raise ValueError(output_dir)

        with patch.object(comfy_single_line_execution, "st", fake_st):
            with self.assertRaisesRegex(RuntimeError, "submission failed"):
                comfy_single_line_execution.collect_single_line_comfy_outputs(
                    fail_submission, "output", fail_paths
                )
            with self.assertRaisesRegex(ValueError, "output"):
                comfy_single_line_execution.collect_single_line_comfy_outputs(
                    lambda: iter([{"type": "done"}]), "output", fail_paths
                )

    def test_legacy_single_line_caller_keeps_candidate_and_save_order(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        function = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "render_single_line_comfy_execution"
        )

        class Rerun(BaseException):
            pass

        class State(dict):
            def __getattr__(self, name):
                return self[name]

        events = []
        line = SimpleNamespace(id="line-1", current_text="prompt")
        project = SimpleNamespace()
        state = State(
            edition="PRO",
            settings={"comfyui_workflow_path": "configured.json", "comfyui_url": "settings:8188"},
        )
        fake_st = SimpleNamespace(
            session_state=state,
            markdown=lambda *_args: None,
            caption=lambda *_args: None,
            write=lambda *_args: None,
            code=lambda *_args, **_kwargs: None,
            text_area=lambda *_args, **_kwargs: None,
            button=lambda *_args, **_kwargs: True,
            warning=lambda message: events.append(("warning", message)),
            progress=lambda value: events.append(("progress", value)) or SimpleNamespace(progress=lambda value: events.append(("progress", value))),
            empty=lambda: SimpleNamespace(markdown=lambda value: events.append(("status", value))),
            success=lambda message: events.append(("success", message)),
            rerun=lambda: (_ for _ in ()).throw(Rerun()),
        )

        def generate(_workflow, comfy_url, output_dir, prefix):
            events.append(("submit", comfy_url, output_dir, prefix))
            return iter([{"type": "done", "path": "first"}, {"type": "done", "path": "second"}])

        def make_record(path, record_line, source, index):
            events.append(("record", path, record_line, source, index))
            return {"path": path, "source": source, "run_index": index}

        namespace = {
            "st": fake_st,
            "os": os,
            "resolve_effective_comfy_workflow_path": lambda _path: (__file__, "configured"),
            "_workflow_text_from_line_metadata": lambda *_args: ("", "", None),
            "build_single_line_workflow": lambda *_args, **_kwargs: ({"workflow": True}, "binding warning"),
            "_project_generation_output_dir": lambda _project: "output",
            "collect_single_line_comfy_outputs": comfy_single_line_execution.collect_single_line_comfy_outputs,
            "generate_image_with_progress": generate,
            "_status_output_paths": lambda status, *, output_dir: [status["path"]],
            "_make_generated_candidate_record": make_record,
            "_append_line_generated_candidates": lambda record_line, records: events.append(("append", record_line, records)),
            "save_current_project_if_possible": lambda reason: events.append(("save", reason)),
        }
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)

        with patch.object(comfy_single_line_execution, "st", fake_st):
            with self.assertRaises(Rerun):
                namespace["render_single_line_comfy_execution"](project, line)

        self.assertEqual(line.generated_image_path, "second")
        self.assertEqual(line.selected_candidate_path, "second")
        self.assertIn(("submit", "settings:8188", "output", "single_line-1"), events)
        self.assertEqual(
            [event[1:] for event in events if event[0] == "record"],
            [("first", line, "single_generate", 1), ("second", line, "single_generate", 2)],
        )
        append_index = next(index for index, event in enumerate(events) if event[0] == "append")
        save_index = next(index for index, event in enumerate(events) if event[0] == "save")
        self.assertLess(append_index, save_index)
        self.assertEqual(events[save_index], ("save", "single-line candidate generated"))


if __name__ == "__main__":
    unittest.main()
