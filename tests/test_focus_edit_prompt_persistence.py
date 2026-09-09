import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.io import load_project_from_json, save_project_to_json
from core.project import Project, PromptLine


PROMPT = "smoke, blue sky, verified"
TOKEN = "luna_persistence_smoke"


def _project():
    project = Project()
    line = PromptLine(
        id="line-1",
        original_file_name="manual",
        original_index=0,
        current_index=0,
        original_text=PROMPT,
        current_text=PROMPT,
        tokens=["smoke", "blue sky", "verified"],
    )
    project.prompt_lines = [line]
    project.line_map = {line.id: line}
    return project


class FocusEditPromptPersistenceTests(unittest.TestCase):
    def test_focus_edit_save_round_trips_prompt_after_graph_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = _project()
            project_path = root / "project.json"
            save_project_to_json(project, project_path)

            app_path = Path(__file__).resolve().parents[1] / "app.py"
            app = AppTest.from_file(str(app_path), default_timeout=30).run(
                timeout=30
            )
            app.session_state["project"] = project
            app.session_state["current_project_path"] = str(project_path)
            app.session_state["startup_project_auto_open_attempted"] = True
            app.session_state["gallery_main_mode_enabled"] = False
            app.session_state["focus_text_line-1"] = "smoke, blue sky"
            app.run(timeout=30)

            next(
                button
                for button in app.button
                if button.key == "focus_btn_line-1"
            ).click().run(timeout=30)

            prompt_widget = next(
                text_area
                for text_area in app.text_area
                if text_area.key == "focus_text_line-1"
            )
            self.assertEqual(prompt_widget.value, PROMPT)

            prompt_widget.set_value(f"{PROMPT}, {TOKEN}").run(timeout=30)
            next(
                button
                for button in app.button
                if button.label and "Save Changes" in button.label
            ).click().run(timeout=30)
            expected_prompt = f"{PROMPT}, {TOKEN}"
            self.assertEqual(
                app.session_state["project"].prompt_lines[0].current_text,
                expected_prompt,
            )
            self.assertEqual(
                load_project_from_json(project_path).prompt_lines[0].current_text,
                PROMPT,
            )
            next(
                button
                for button in app.button
                if button.key == "quick_save_project"
            ).click().run(timeout=30)

            reopened = load_project_from_json(project_path)
            reopened_line = reopened.prompt_lines[0]
            self.assertEqual(reopened_line.current_text, expected_prompt)
            self.assertIn(TOKEN, reopened_line.tokens)


if __name__ == "__main__":
    unittest.main()
