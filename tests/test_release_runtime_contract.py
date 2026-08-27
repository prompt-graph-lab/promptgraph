import ast
from contextlib import redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core import runtime_environment, runtime_lock


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DIRECT = {
    "matplotlib": "3.11.1",
    "requests": "2.34.2",
    "streamlit": "1.60.0",
    "streamlit-agraph": "0.0.45",
    "websocket-client": "1.9.0",
    "wordcloud": "1.9.6",
}
EXPECTED_LOCK_SHA256 = (
    "EA7628D4C4059FAB5D9ADE168B2A567E68035721B8692B22F3638A69ED769C66"
)


def _effective_requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _requirements(path: Path) -> list[Requirement]:
    return [Requirement(line) for line in _effective_requirement_lines(path)]


def _exact_pin(requirement: Requirement) -> str:
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==":
        return ""
    return specifiers[0].version


def _probe(**overrides) -> runtime_environment.RuntimeProbe:
    values = {
        "operating_system": "Windows",
        "windows_build": 26200,
        "architecture": "AMD64",
        "pointer_bits": 64,
        "python_implementation": "CPython",
        "python_version": "3.14.6",
        "python_version_info": (3, 14, 6),
    }
    values.update(overrides)
    return runtime_environment.RuntimeProbe(**values)


class ReleaseRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.requirements_in = ROOT / "requirements.in"
        self.requirements_lock = ROOT / "requirements.txt"
        self.setup_batch = (ROOT / "setup.bat").read_text(encoding="utf-8")
        self.run_batch = (ROOT / "run.bat").read_text(encoding="utf-8")
        self.app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.app_tree = ast.parse(self.app_source)

    def test_direct_requirements_are_exactly_the_six_validated_pins(self):
        requirements = _requirements(self.requirements_in)
        actual = {
            canonicalize_name(requirement.name): _exact_pin(requirement)
            for requirement in requirements
        }
        self.assertEqual(EXPECTED_DIRECT, actual)
        self.assertEqual(len(actual), len(requirements))
        self.assertEqual(
            list(actual),
            sorted(actual),
            "requirements.in must be deterministically sorted",
        )

    def test_runtime_lock_is_complete_exact_and_normalized(self):
        requirements = _requirements(self.requirements_lock)
        names = [canonicalize_name(requirement.name) for requirement in requirements]
        self.assertEqual(54, len(requirements))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names, sorted(names))
        for requirement in requirements:
            with self.subTest(requirement=str(requirement)):
                self.assertTrue(_exact_pin(requirement))
                self.assertIsNone(requirement.url)
                self.assertFalse(requirement.extras)
        self.assertTrue(set(EXPECTED_DIRECT).issubset(names))
        actual = {
            canonicalize_name(requirement.name): _exact_pin(requirement)
            for requirement in requirements
        }
        for name, version in EXPECTED_DIRECT.items():
            self.assertEqual(version, actual[name])
        self.assertTrue({"numpy", "pandas", "pillow", "pyarrow"}.issubset(names))
        self.assertFalse(
            {"pip", "setuptools", "wheel", "pytest", "pytest-subtests"}
            & set(names)
        )

    def test_runtime_lock_has_release_header_and_expected_hash(self):
        text = self.requirements_lock.read_text(encoding="utf-8")
        self.assertIn("PromptGraph Pro 1.0.0 runtime lock", text)
        self.assertIn("Windows 11 x64", text)
        self.assertIn("CPython 3.14.x", text)
        self.assertIn("Generated from requirements.in", text)
        self.assertIn("docs/supported-environment.md", text)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode(
            "utf-8"
        )
        digest = hashlib.sha256(normalized).hexdigest().upper()
        self.assertEqual(EXPECTED_LOCK_SHA256, digest)

    def test_requirement_files_have_no_url_path_or_editable_entries(self):
        for path in (self.requirements_in, self.requirements_lock):
            for line in _effective_requirement_lines(path):
                with self.subTest(path=path.name, line=line):
                    self.assertNotRegex(line, r"(?i)^-e(?:\s|$)")
                    self.assertNotRegex(line, r"(?i)(?:https?|git\+)://")
                    self.assertNotIn(";", line)
                    self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[^\s]+$")

    def test_setup_batch_owns_environment_installation(self):
        lower = self.setup_batch.lower()
        self.assertIn('cd /d "%~dp0"', lower)
        self.assertIn('.venv\\scripts\\python.exe', lower)
        self.assertIn("py -3.14", lower)
        self.assertIn("pip==26.1.1", lower)
        self.assertIn("--only-binary=:all:", lower)
        self.assertIn("-r requirements.txt", lower)
        self.assertIn("-m pip check", lower)
        self.assertIn(
            "-m core.runtime_lock --requirements requirements.txt --check",
            lower,
        )
        self.assertGreater(
            lower.index("-m core.runtime_lock"),
            lower.index("-m pip check"),
        )
        self.assertIn("-m core.runtime_environment --check", lower)
        self.assertIn("rename or delete .venv manually", lower)
        self.assertIn("does not exactly match", lower)
        self.assertIn("pythondontwritebytecode=1", lower)
        self.assertNotRegex(lower, r"\b(?:rmdir|rd|del)\b")

    def test_run_batch_is_side_effect_free_and_venv_only(self):
        lower = self.run_batch.lower()
        self.assertIn('cd /d "%~dp0"', lower)
        self.assertIn('.venv\\scripts\\python.exe', lower)
        self.assertIn("run setup.bat first", lower)
        self.assertIn("-m core.runtime_environment --check", lower)
        self.assertIn("-m streamlit run app.py", lower)
        self.assertIn("pythondontwritebytecode=1", lower)
        self.assertNotIn("pip", lower)
        self.assertNotRegex(lower, r"(?m)^\s*(?:py|python)(?:\.exe)?\s")

    @unittest.skipUnless(os.name == "nt", "Windows batch behavior")
    def test_run_batch_without_venv_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_path = root / "run.bat"
            batch_path.write_text(self.run_batch, encoding="utf-8")
            before = {path.name for path in root.iterdir()}
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", str(batch_path)],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
                shell=False,
            )
            after = {path.name for path in root.iterdir()}
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("Run setup.bat first", completed.stdout)
        self.assertNotIn("pip", completed.stdout.casefold())
        self.assertEqual(before, after)

    def test_supported_runtime_probe(self):
        environment = runtime_environment.evaluate_runtime_environment(_probe())
        self.assertTrue(environment.supported)
        self.assertTrue(environment.os_supported)
        self.assertTrue(environment.architecture_supported)
        self.assertTrue(environment.python_supported)
        self.assertTrue(environment.implementation_supported)
        self.assertEqual("1.0.0", environment.product_version)
        self.assertEqual(26200, environment.windows_build)

    def test_common_x86_64_architecture_label_is_supported(self):
        environment = runtime_environment.evaluate_runtime_environment(
            _probe(architecture="x86_64")
        )
        self.assertTrue(environment.architecture_supported)
        self.assertTrue(environment.supported)

    def test_unsupported_runtime_dimensions_fail_closed(self):
        probes = {
            "wrong_python_minor": _probe(
                python_version="3.13.12",
                python_version_info=(3, 13, 12),
            ),
            "32_bit": _probe(pointer_bits=32),
            "non_cpython": _probe(python_implementation="PyPy"),
            "non_windows": _probe(operating_system="Linux", windows_build=None),
            "old_windows": _probe(windows_build=19045),
            "unknown_build": _probe(windows_build=None),
        }
        for name, probe in probes.items():
            with self.subTest(name=name):
                self.assertFalse(
                    runtime_environment.evaluate_runtime_environment(probe).supported
                )

    def test_windows_build_parser_is_fail_closed(self):
        self.assertEqual(26200, runtime_environment._parse_windows_build("10.0.26200"))
        self.assertEqual(26200, runtime_environment._parse_windows_build(26200))
        for value in (None, "", "unknown", -1, True, "10.0.invalid"):
            with self.subTest(value=value):
                self.assertIsNone(runtime_environment._parse_windows_build(value))

    def test_runtime_cli_json_and_check_status(self):
        supported = runtime_environment.evaluate_runtime_environment(_probe())
        unsupported = runtime_environment.evaluate_runtime_environment(
            _probe(python_version="3.15.0", python_version_info=(3, 15, 0))
        )
        output = io.StringIO()
        with mock.patch.object(
            runtime_environment,
            "get_runtime_environment",
            return_value=supported,
        ), redirect_stdout(output):
            self.assertEqual(0, runtime_environment.main(["--json", "--check"]))
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["supported"])
        self.assertEqual("PromptGraph Pro", payload["product"])
        self.assertEqual("3.14.6", payload["python_version"])

        with mock.patch.object(
            runtime_environment,
            "get_runtime_environment",
            return_value=unsupported,
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(1, runtime_environment.main(["--check"]))

    def test_runtime_module_import_has_no_process_or_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = Path.cwd()
            os.chdir(temp_dir)
            try:
                before = list(Path(temp_dir).iterdir())
                with mock.patch("subprocess.run") as run:
                    importlib.reload(runtime_environment)
                after = list(Path(temp_dir).iterdir())
            finally:
                os.chdir(previous)
        run.assert_not_called()
        self.assertEqual(before, after)

    def test_exact_runtime_lock_environment_passes(self):
        expected = {"Example_Package": "1.2.3", "second.package": "4.5.6"}
        installed = {"example-package": "1.2.3", "second-package": "4.5.6"}
        result = runtime_lock.evaluate_exact_lock(expected, installed)
        self.assertTrue(result.exact)
        self.assertEqual(2, result.expected_count)
        self.assertEqual(2, result.installed_runtime_count)

    def test_extra_installed_package_fails_exact_runtime_lock(self):
        result = runtime_lock.evaluate_exact_lock(
            {"locked": "1.0"},
            {"locked": "1.0", "extra-package": "2.0", "pip": "26.1.1"},
        )
        self.assertFalse(result.exact)
        self.assertEqual(("extra-package",), result.unexpected)
        self.assertNotIn("pip", result.unexpected)

    def test_package_removed_from_lock_but_still_installed_fails(self):
        prior_lock = {"retained": "1.0", "removed-package": "2.0"}
        current_lock = {"retained": prior_lock["retained"]}
        installed = dict(prior_lock)
        result = runtime_lock.evaluate_exact_lock(current_lock, installed)
        self.assertFalse(result.exact)
        self.assertEqual(("removed-package",), result.unexpected)

    def test_missing_and_version_mismatch_fail_exact_runtime_lock(self):
        result = runtime_lock.evaluate_exact_lock(
            {"missing": "1.0", "wrong-version": "2.0"},
            {"wrong_version": "1.0"},
        )
        self.assertFalse(result.exact)
        self.assertEqual(("missing",), result.missing)
        self.assertEqual(1, len(result.version_mismatches))
        self.assertEqual("wrong-version", result.version_mismatches[0].name)

    def test_lock_parser_fails_closed_on_malformed_duplicate_and_bootstrap(self):
        expected, errors = runtime_lock.parse_exact_lock(
            "valid.name==1.0\nvalid-name==2.0\npip==26.1.1\nnot-pinned\n"
        )
        self.assertEqual({"valid-name": "1.0"}, expected)
        self.assertEqual(3, len(errors))
        result = runtime_lock.evaluate_exact_lock(
            expected,
            {"valid-name": "1.0"},
            lock_errors=errors,
        )
        self.assertFalse(result.exact)

    def test_runtime_lock_cli_is_fail_closed_and_does_not_leak_lock_path(self):
        result = runtime_lock.evaluate_exact_lock(
            {"locked": "1.0"},
            {"locked": "1.0", "extra": "2.0"},
        )
        secret_path = Path.home() / "private" / "requirements.txt"
        output = io.StringIO()
        with mock.patch.object(
            runtime_lock,
            "verify_runtime_lock",
            return_value=result,
        ), redirect_stdout(output):
            self.assertEqual(
                1,
                runtime_lock.main(
                    ["--requirements", str(secret_path), "--json", "--check"]
                ),
            )
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["exact"])
        self.assertEqual(["extra"], payload["unexpected"])
        self.assertNotIn(str(secret_path), output.getvalue())
        self.assertNotIn(Path.home().name, output.getvalue())

    def test_runtime_lock_module_import_has_no_process_or_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = Path.cwd()
            os.chdir(temp_dir)
            try:
                before = list(Path(temp_dir).iterdir())
                with mock.patch("subprocess.run") as run:
                    importlib.reload(runtime_lock)
                after = list(Path(temp_dir).iterdir())
            finally:
                os.chdir(previous)
        run.assert_not_called()
        self.assertEqual(before, after)

    def test_runtime_diagnostic_does_not_duplicate_version_or_leak_paths(self):
        source = (ROOT / "core" / "runtime_environment.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"1.0.0"', source)
        environment = runtime_environment.evaluate_runtime_environment(_probe())
        rendered = runtime_environment._render_human(environment)
        structured = json.dumps(environment.as_dict())
        for output in (rendered, structured):
            self.assertNotIn(str(Path.home()), output)
            self.assertNotIn(Path.home().name, output)

    def test_active_app_has_no_removed_width_keyword(self):
        old_keywords = []
        stretched = []
        for node in ast.walk(self.app_tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "use_container_width":
                    old_keywords.append(node.lineno)
                if (
                    keyword.arg == "width"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "stretch"
                ):
                    stretched.append(node.lineno)
        self.assertEqual([], old_keywords)
        # 63 migrated owners plus 21 pre-existing width="stretch" owners.
        self.assertEqual(84, len(stretched))

    def test_html_component_is_one_contained_compatibility_owner(self):
        component_calls = []
        wrapper_calls = []
        for node in ast.walk(self.app_tree):
            if not isinstance(node, ast.Call):
                continue
            function = ast.unparse(node.func)
            if function == "components.html":
                component_calls.append(node.lineno)
            if function == "_render_component_html":
                wrapper_calls.append(node.lineno)
        self.assertEqual(1, len(component_calls))
        self.assertEqual(2, len(wrapper_calls))
        wrapper = next(
            node
            for node in self.app_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_component_html"
        )
        wrapper_source = ast.get_source_segment(self.app_source, wrapper)
        self.assertIn("components.html", wrapper_source)
        self.assertIn("iframe", wrapper_source)
        self.assertIn("st.html", wrapper_source)
        self.assertIn("1.60.0", wrapper_source)

    def test_no_global_warning_suppression_was_added(self):
        product_python = [ROOT / "app.py", *sorted((ROOT / "core").glob("*.py"))]
        suppressors = []
        for path in product_python:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = ast.unparse(node.func)
                if function == "warnings.filterwarnings":
                    suppressors.append((path.name, node.lineno, function))
                if (
                    function == "warnings.simplefilter"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and str(node.args[0].value).casefold() == "ignore"
                ):
                    suppressors.append((path.name, node.lineno, function))
        self.assertEqual([], suppressors)

    def test_supported_environment_and_release_docs_are_consistent(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        support = (ROOT / "docs" / "supported-environment.md").read_text(
            encoding="utf-8"
        )
        release = (ROOT / "docs" / "release-process.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("docs/supported-environment.md", readme)
        self.assertIn("setup.bat", readme)
        self.assertIn("run.bat", readme)
        self.assertIn("requirements.in", readme)
        self.assertIn("requirements.txt", readme)
        self.assertNotRegex(readme, re.compile(r"run\.bat.*install", re.I))
        for expected in (
            "Windows 11",
            "AMD64 / x86-64",
            "CPython `>=3.14,<3.15`",
            "Microsoft Edge",
            "Google Chrome",
            "POST /prompt",
            "GET /history/<prompt_id>",
            "GET /view",
            "pip==26.1.1",
            EXPECTED_LOCK_SHA256,
        ):
            self.assertIn(expected, support)
        self.assertRegex(support, r"does not contact an endpoint\s+passively")
        self.assertIn("Runtime lock: requirements.txt", release)
        self.assertIn("Runtime lock SHA-256", release)
        self.assertIn("docs/supported-environment.md", release)
        self.assertIn(EXPECTED_LOCK_SHA256, release)
        self.assertNotRegex(
            support + release,
            re.compile(r"v1\.0\.0 (?:has been|is) (?:published|released|tagged)", re.I),
        )


if __name__ == "__main__":
    unittest.main()
