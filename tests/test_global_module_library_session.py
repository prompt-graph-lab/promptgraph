"""Characterize the authoritative session lifecycle, including legacy failures."""

import ast
import copy
import types
import unittest
from pathlib import Path
from unittest import mock

from ui import global_module_library_session as session


class State(dict):
    def __setattr__(self, key, value):
        self[key] = value


class GlobalModuleLibrarySessionTests(unittest.TestCase):
    def setUp(self):
        self.__dict__.pop("saved", None)
        self.old = {"path": "old", "library": {"old": {"body": "keep"}}}
        self.state = State(settings={"path": "new"},
                           global_module_library_session_cache=self.old)
        self.events = []
        self.authoritative = {"latest": {"nested": []}}
        self.persisted = {"persisted": {"body": "normalized"}}
        self.loads = 0

        def path(settings):
            self.events.append("path")
            return settings.get("path", "default")

        def load(settings):
            self.events.append("load")
            self.loads += 1
            return self.authoritative if self.loads == 1 else self.persisted

        def save(library, settings):
            self.events.append("save")
            self.saved = library
            self.saved_settings = settings
            return "saved-path"

        self.ns = dict(copy=copy, st=types.SimpleNamespace(session_state=self.state),
                       get_global_module_library_path=path,
                       load_global_module_library=load, save_global_module_library=save)
        patcher = mock.patch.dict(session.__dict__, self.ns)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ns = session.__dict__

    def test_app_imports_the_owner_functions_directly(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        nodes = [node for node in ast.parse(source).body if isinstance(node, ast.ImportFrom)
                 and node.module == "ui.global_module_library_session"]
        self.assertEqual(len(nodes), 1)
        namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
        for name in ("get_session_global_module_library", "cache_global_module_library_for_session",
                     "save_and_cache_global_module_library"):
            self.assertIs(namespace[name], getattr(session, name))

    def get(self):
        return self.ns["get_session_global_module_library"]()

    def cache(self, value):
        return self.ns["cache_global_module_library_for_session"](value)

    def save(self, modifier):
        return self.ns["save_and_cache_global_module_library"](modifier)

    def test_miss_hit_path_transition_and_return_to_old_path(self):
        self.assertIs(self.get(), self.authoritative)
        cache = self.state["global_module_library_session_cache"]
        self.assertIs(self.get(), self.authoritative)
        self.assertIs(self.state["global_module_library_session_cache"], cache)
        self.state["settings"] = {"path": "other"}
        self.assertIs(self.get(), self.persisted)
        self.state["settings"] = {"path": "new"}
        self.get()
        self.assertEqual(self.events, ["path", "load", "path", "path", "load", "path", "load"])

    def test_empty_valid_cache_is_reused_invalid_cache_is_replaced(self):
        for value in (None, False, [], {}, {"path": "new", "library": []}):
            with self.subTest(value=value):
                self.state["global_module_library_session_cache"] = value
                self.get()
                self.assertIsNot(self.state["global_module_library_session_cache"], value)
        empty = {}
        self.state["global_module_library_session_cache"] = {"path": "new", "library": empty}
        self.events.clear()
        self.assertIs(self.get(), empty)
        self.assertEqual(self.events, ["path"])

    def test_explicit_cache_identity_and_non_dict_fallback(self):
        for value in ({}, {"a": []}, None, [], False):
            self.assertIsNone(self.cache(value))
            cached = self.state["global_module_library_session_cache"]
            self.assertEqual(set(cached), {"path", "library"})
            self.assertEqual(cached["path"], "new")
            if isinstance(value, dict):
                self.assertIs(cached["library"], value)
            else:
                self.assertEqual(cached["library"], {})

    def test_save_deepcopies_then_uses_replacement_and_reload_identity(self):
        replacement = {}

        def modifier(library):
            self.events.append("modify")
            self.assertIsNot(library, self.authoritative)
            library["latest"]["nested"].append(1)
            return replacement

        result = self.save(modifier)
        self.assertEqual(self.authoritative, {"latest": {"nested": []}})
        self.assertIs(self.saved, replacement)
        self.assertEqual(result[0], "saved-path")
        self.assertIs(result[1], self.persisted)
        self.assertIs(self.state["global_module_library_session_cache"]["library"], self.persisted)
        self.assertEqual(self.events, ["load", "modify", "save", "load", "path"])

    def test_invalid_modifier_and_return_load_before_validation(self):
        for modifier in (None, False, lambda library: None, lambda library: []):
            with self.subTest(modifier=modifier):
                self.events.clear()
                with self.assertRaises(TypeError) as caught:
                    self.save(modifier)
                if callable(modifier):
                    self.assertEqual(str(caught.exception), "Global Module Library update must return a dict.")
                self.assertEqual(self.events, ["load"])
                self.assertIs(self.state["global_module_library_session_cache"], self.old)

    def test_failures_propagate_same_exception_without_cache_replacement(self):
        for stage in ("initial", "modifier", "save", "reload", "path", "deepcopy"):
            with self.subTest(stage=stage):
                self.setUp()
                failure = RuntimeError(stage)

                def fail(*args):
                    raise failure

                modifier = fail if stage == "modifier" else lambda value: value
                if stage == "initial":
                    self.ns["load_global_module_library"] = fail
                elif stage == "reload":
                    self.ns["load_global_module_library"] = mock.Mock(side_effect=[self.authoritative, failure])
                elif stage in ("save", "path"):
                    self.ns[{"save": "save_global_module_library", "path": "get_global_module_library_path"}[stage]] = fail
                elif stage == "deepcopy":
                    self.ns["copy"] = types.SimpleNamespace(deepcopy=fail)
                with self.assertRaises(RuntimeError) as caught:
                    self.save(modifier)
                self.assertIs(caught.exception, failure)
                self.assertIs(self.state["global_module_library_session_cache"], self.old)
                self.assertEqual(self.authoritative, {"latest": {"nested": []}})
                self.assertEqual(hasattr(self, "saved"), stage in ("reload", "path"))

    def test_get_failure_keeps_cache_and_resolves_path_before_load(self):
        failure = OSError("read")
        self.ns["load_global_module_library"] = mock.Mock(side_effect=failure)
        with self.assertRaises(OSError) as caught:
            self.get()
        self.assertIs(caught.exception, failure)
        self.assertIs(self.state["global_module_library_session_cache"], self.old)
        self.assertEqual(self.events, ["path"])

    def test_settings_replacement_during_modifier_preserves_split_path_behavior(self):
        original = self.state["settings"]

        def modifier(value):
            self.state["settings"] = {"path": "changed"}
            return value

        self.save(modifier)
        self.assertIs(self.saved_settings, original)
        self.assertEqual(self.state["global_module_library_session_cache"]["path"], "changed")

    def test_missing_settings_defaults_and_falsey_settings_are_passed_unchanged(self):
        for value in ({}, None, False):
            self.state["settings"] = value
            received = []
            self.ns["get_global_module_library_path"] = lambda settings: received.append(settings) or "new"
            self.ns["load_global_module_library"] = lambda settings: received.append(settings) or {}
            self.state.pop("global_module_library_session_cache", None)
            self.get()
            self.assertIs(received[0], value)
            self.assertIs(received[1], value)
        self.state.pop("settings")
        self.state.pop("global_module_library_session_cache")
        received.clear()
        self.get()
        self.assertEqual(received, [{}, {}])
        self.assertIsNot(received[0], received[1])

    def test_modifier_external_side_effects_are_not_rolled_back(self):
        def modifier(value):
            self.old["library"]["side-effect"] = True
            self.state["notice"] = "changed"
            raise ValueError("stop")

        with self.assertRaisesRegex(ValueError, "stop"):
            self.save(modifier)
        self.assertIs(self.state["global_module_library_session_cache"], self.old)
        self.assertTrue(self.old["library"]["side-effect"])
        self.assertEqual(self.state["notice"], "changed")

    def test_cache_assignment_failure_occurs_after_save_and_reload(self):
        failure = RuntimeError("session assignment")

        class RejectCache(State):
            def __setattr__(self, key, value):
                raise failure

        self.ns["st"] = types.SimpleNamespace(session_state=RejectCache(self.state))
        with self.assertRaises(RuntimeError) as caught:
            self.save(lambda value: value)
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.events, ["load", "save", "load", "path"])
        self.assertIs(self.ns["st"].session_state["global_module_library_session_cache"], self.old)

    def test_non_dict_reload_is_returned_but_cached_as_empty(self):
        self.persisted = None
        _, result = self.save(lambda value: value)
        self.assertIsNone(result)
        self.assertEqual(self.state["global_module_library_session_cache"]["library"], {})


if __name__ == "__main__":
    unittest.main()
