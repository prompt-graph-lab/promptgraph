import ast
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from core.io import (
    get_global_module_library_path,
    load_global_module_library,
    save_global_module_library,
)
from core.module_library_search import filter_global_module_library
from core.operations import (
    get_module_body,
    get_module_category,
    normalize_module_library,
)


class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class GlobalModuleLibraryAuthoritativeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _function_source(self, name):
        return ast.get_source_segment(
            self.app_source,
            self.functions[name],
        )

    def _load_functions(self, *names, namespace):
        loaded = dict(namespace)
        for name in names:
            exec(
                compile(
                    ast.Module(
                        body=[self.functions[name]],
                        type_ignores=[],
                    ),
                    filename="app.py",
                    mode="exec",
                ),
                loaded,
            )
        return loaded

    def _real_io_namespace(self, state):
        return self._load_functions(
            "cache_global_module_library_for_session",
            "save_and_cache_global_module_library",
            "get_session_global_module_library",
            namespace={
                "copy": copy,
                "st": types.SimpleNamespace(session_state=state),
                "get_global_module_library_path": (
                    get_global_module_library_path
                ),
                "load_global_module_library": load_global_module_library,
                "save_global_module_library": save_global_module_library,
            },
        )

    def test_explicit_save_caches_the_persisted_normalized_library(self):
        raw_library = {
            "legacy_character": {
                "body": "alpha, beta",
                "type": "unsupported-type",
                "category": "unsupported-category",
                "core_tokens": [],
                "min_match_tokens": 999,
                "description": "Normalization fixture",
                "notes": "searchable immediately",
            }
        }
        normalized_raw = normalize_module_library(
            copy.deepcopy(raw_library)
        )
        self.assertNotEqual(raw_library, normalized_raw)

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {"global_module_library_dir": temp_dir}
            state = _SessionState(settings=settings)
            namespace = self._real_io_namespace(state)

            def apply_raw_library(authoritative_library):
                authoritative_library.update(copy.deepcopy(raw_library))
                return authoritative_library

            saved_path, cached_library = namespace[
                "save_and_cache_global_module_library"
            ](apply_raw_library)
            persisted_library = load_global_module_library(settings)

            self.assertEqual(
                saved_path,
                get_global_module_library_path(settings),
            )
            self.assertEqual(cached_library, persisted_library)
            self.assertEqual(
                state.global_module_library_session_cache["library"],
                persisted_library,
            )
            self.assertEqual(
                namespace["get_session_global_module_library"](),
                persisted_library,
            )
            self.assertNotEqual(
                persisted_library["legacy_character"],
                raw_library["legacy_character"],
            )

            immediate_search = filter_global_module_library(
                cached_library,
                query="normalization immediately",
            )
            state.pop("global_module_library_session_cache")
            restarted_library = namespace[
                "get_session_global_module_library"
            ]()
            restarted_search = filter_global_module_library(
                restarted_library,
                query="normalization immediately",
            )

            self.assertEqual(immediate_search, restarted_search)
            self.assertEqual(cached_library, restarted_library)
            self.assertEqual(
                get_module_body(cached_library, "legacy_character"),
                get_module_body(restarted_library, "legacy_character"),
            )
            self.assertEqual(
                get_module_category(cached_library, "legacy_character"),
                get_module_category(restarted_library, "legacy_character"),
            )
            self.assertEqual(
                cached_library["legacy_character"]["description"],
                restarted_library["legacy_character"]["description"],
            )

    def test_explicit_save_rebases_on_latest_json_before_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {"global_module_library_dir": temp_dir}
            save_global_module_library(
                {"cached": {"body": "old cached body"}},
                settings,
            )
            state = _SessionState(settings=settings)
            namespace = self._real_io_namespace(state)
            stale_library = namespace[
                "get_session_global_module_library"
            ]()

            concurrent_library = load_global_module_library(settings)
            concurrent_library["concurrent"] = {
                "body": "added by another session",
                "description": "must survive",
                "extension_metadata": {
                    "future_key": "keep",
                    "nested": {"value": 1},
                },
            }
            save_global_module_library(concurrent_library, settings)
            self.assertNotIn("concurrent", stale_library)

            def update_cached_module(authoritative_library):
                authoritative_library["cached"] = {
                    "body": "my update"
                }
                return authoritative_library

            _, cached_after_save = namespace[
                "save_and_cache_global_module_library"
            ](update_cached_module)
            persisted_library = load_global_module_library(settings)

            self.assertIn("concurrent", persisted_library)
            self.assertEqual(
                persisted_library["concurrent"]["description"],
                "must survive",
            )
            self.assertEqual(
                persisted_library["concurrent"]["extension_metadata"],
                {
                    "future_key": "keep",
                    "nested": {"value": 1},
                },
            )
            self.assertEqual(
                get_module_body(persisted_library, "cached"),
                "my update",
            )
            self.assertEqual(cached_after_save, persisted_library)

    def test_failed_save_preserves_cache_project_and_history(self):
        old_library = {"cached": {"body": "keep"}}
        old_cache = {
            "path": "x/global_modules.json",
            "library": old_library,
        }
        project = object()
        history = ["keep-history"]
        state = _SessionState(
            settings={"global_module_library_dir": "x"},
            global_module_library_session_cache=old_cache,
            project=project,
            history=history,
        )
        load_calls = []
        cache_calls = []

        def fail_save(_library, _settings):
            raise OSError("synthetic write failure")

        namespace = self._load_functions(
            "cache_global_module_library_for_session",
            "save_and_cache_global_module_library",
            namespace={
                "copy": copy,
                "st": types.SimpleNamespace(session_state=state),
                "get_global_module_library_path": (
                    lambda _settings: "x/global_modules.json"
                ),
                "load_global_module_library": (
                    lambda _settings: load_calls.append(True)
                    or {"latest": {"body": "latest"}}
                ),
                "save_global_module_library": fail_save,
            },
        )
        original_cache_function = namespace[
            "cache_global_module_library_for_session"
        ]

        def track_cache(library):
            cache_calls.append(copy.deepcopy(library))
            return original_cache_function(library)

        namespace["cache_global_module_library_for_session"] = track_cache

        with self.assertRaisesRegex(OSError, "synthetic write failure"):
            namespace["save_and_cache_global_module_library"](
                lambda library: library
            )

        self.assertEqual(load_calls, [True])
        self.assertEqual(cache_calls, [])
        self.assertIs(
            state.global_module_library_session_cache,
            old_cache,
        )
        self.assertIs(state.project, project)
        self.assertIs(state.history, history)
        self.assertNotIn("global_module_library_notice", state)

    def test_real_partial_write_failure_preserves_disk_cache_and_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {"global_module_library_dir": temp_dir}
            old_library = {
                "cached": {
                    "body": "keep",
                    "extension_metadata": {
                        "future_key": "keep",
                    },
                }
            }
            library_path = Path(
                save_global_module_library(old_library, settings)
            )
            before = library_path.read_bytes()
            cached_library = load_global_module_library(settings)
            old_cache = {
                "path": str(library_path),
                "library": cached_library,
            }
            project = object()
            history = ["keep-history"]
            state = _SessionState(
                settings=settings,
                global_module_library_session_cache=old_cache,
                project=project,
                history=history,
            )
            namespace = self._real_io_namespace(state)

            def partial_failure(_data, handle, **_kwargs):
                handle.write('{"partial":')
                handle.flush()
                raise OSError("synthetic authoritative partial failure")

            def add_module(authoritative_library):
                authoritative_library["must-not-persist"] = {
                    "body": "new"
                }
                return authoritative_library

            with mock.patch(
                "core.io.json.dump",
                side_effect=partial_failure,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "synthetic authoritative partial failure",
                ):
                    namespace["save_and_cache_global_module_library"](
                        add_module
                    )

            self.assertEqual(before, library_path.read_bytes())
            json.loads(library_path.read_text(encoding="utf-8"))
            self.assertEqual(
                cached_library,
                load_global_module_library(settings),
            )
            self.assertNotIn(
                "must-not-persist",
                load_global_module_library(settings),
            )
            self.assertIs(
                state.global_module_library_session_cache,
                old_cache,
            )
            self.assertIs(state.project, project)
            self.assertIs(state.history, history)
            self.assertNotIn("global_module_library_notice", state)
            self.assertEqual(
                [],
                list(library_path.parent.glob(
                    f".{library_path.name}.*.tmp"
                )),
            )

    def test_every_explicit_write_uses_the_authoritative_helper(self):
        helper = self._function_source(
            "save_and_cache_global_module_library"
        )
        self.assertEqual(
            self.app_source.count("save_global_module_library("),
            1,
        )
        self.assertEqual(
            self.app_source.count(
                "cache_global_module_library_for_session("
            ),
            2,
        )
        self.assertEqual(helper.count("load_global_module_library("), 2)
        self.assertEqual(helper.count("save_global_module_library("), 1)
        self.assertLess(
            helper.index("save_global_module_library("),
            helper.rindex("load_global_module_library("),
        )
        self.assertLess(
            helper.rindex("load_global_module_library("),
            helper.index("cache_global_module_library_for_session("),
        )

        animadex = self._function_source(
            "render_animadex_browser_section"
        )
        manager = self._function_source(
            "render_global_module_manager_section"
        )
        creation = self._function_source(
            "render_create_module_from_scratch_section"
        )
        self.assertEqual(
            animadex.count("save_and_cache_global_module_library("),
            1,
        )
        self.assertEqual(
            manager.count("save_and_cache_global_module_library("),
            3,
        )
        self.assertEqual(
            creation.count("save_and_cache_global_module_library("),
            1,
        )
        for owner in (animadex, manager, creation):
            self.assertNotIn("save_global_module_library(", owner)
        self.assertEqual(
            animadex.count(
                "Global Module Libraryを保存できませんでした"
            ),
            1,
        )
        self.assertEqual(
            manager.count(
                "Global Module Libraryを保存できませんでした"
            ),
            3,
        )
        self.assertEqual(
            creation.count(
                "Global Module Libraryを保存できませんでした"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
