"""PromptGraph's repository-owned Streamlit rerun safety default."""

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import streamlit


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".streamlit" / "config.toml"


def _isolated_environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "isolated-user-profile"
    home.mkdir()
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.upper().startswith("STREAMLIT_"):
            environment.pop(name)
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    environment["APPDATA"] = str(home / "AppData" / "Roaming")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_config_probe(tmp_path: Path, script: str, *, overrides=None) -> dict:
    environment = _isolated_environment(tmp_path)
    if overrides:
        environment.update(overrides)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert output_lines, completed.stderr
    return json.loads(output_lines[-1])


def test_repository_streamlit_config_is_narrow_valid_toml_and_in_source_tree():
    assert CONFIG_PATH.is_file()
    assert streamlit.__version__ == "1.60.0"
    assert tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")) == {
        "runner": {"fastReruns": False},
    }

    launcher = (ROOT / "run.bat").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in launcher
    assert ' -m streamlit run app.py' in launcher


def test_pinned_streamlit_runtime_loads_repository_default_without_user_config(tmp_path):
    result = _run_config_probe(
        tmp_path,
        """
import json
import streamlit
from streamlit import config
print(json.dumps({
    "version": streamlit.__version__,
    "fastReruns": config.get_option("runner.fastReruns"),
}))
""",
    )

    assert result == {"version": "1.60.0", "fastReruns": False}


def test_streamlit_cli_environment_override_is_higher_precedence(tmp_path):
    environment = _isolated_environment(tmp_path)
    environment["STREAMLIT_RUNNER_FAST_RERUNS"] = "true"
    completed = subprocess.run(
        [sys.executable, "-m", "streamlit", "config", "show"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert re.search(r"(?m)^fastReruns\s*=\s*true\s*$", completed.stdout)


def test_higher_precedence_cli_override_remains_effective_and_rejects_capture(
    tmp_path,
):
    result = _run_config_probe(
        tmp_path,
        """
import json
from streamlit import config
from streamlit.web.bootstrap import load_config_options
from core.project import Project
from ui.project_capture_safety import begin_project_capture_run, capture_active_project
load_config_options({"runner_fastReruns": True})
session_state = {"project": Project()}
run_token = begin_project_capture_run(session_state)
capture = capture_active_project(session_state, run_token)
print(json.dumps({
    "fastReruns": config.get_option("runner.fastReruns"),
    "capture_ok": capture.ok,
    "reason": capture.reason,
}))
""",
    )

    assert result == {
        "fastReruns": True,
        "capture_ok": False,
        "reason": "overlapping_reruns_enabled",
    }


def test_application_does_not_force_fast_reruns_after_startup():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    matching_setters = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "set_option":
            continue
        if any(
            isinstance(argument, ast.Constant)
            and argument.value == "runner.fastReruns"
            for argument in node.args
        ):
            matching_setters.append(node.lineno)

    assert matching_setters == []
