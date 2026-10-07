"""PoC-0 agent boundary: observation, reviewed intent, freshness, clone Apply."""

import copy
import hashlib
import importlib
import json

import pytest

from core import agent_facade as facade
from core import operations
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine


def line(line_id, text="red, blue", **kwargs):
    return PromptLine(id=line_id, original_file_name=f"{line_id}.png", original_index=0,
                      current_index=0, original_text=text, current_text=text,
                      tokens=parse_prompt(text), **kwargs)


def project():
    result = Project(prompt_lines=[
        line("baseline"), line("s1", "First", line_type="separator"), line("one"),
        line("scratch", line_type="workbench"), line("trash", deleted=True),
        line("deleted-scene", "Removed", line_type="separator", deleted=True),
        line("two", "blue, red"), line("s2", "Empty", line_type="separator"),
        line("s3", "Third", line_type="separator"), line("three", "green"),
    ], module_library={"outfit": {"body": "red", "reference_assets": {"unknown": [1, 2]}}},
        attribute_groups={"palette": {"tokens": ["red", "blue"]}},
        project_metadata={"opaque": {"future": ["keep"]}})
    return build_graph(result)


def request(ids=None, **kwargs):
    return {"illustration_ids": ids or ["one"], "find_text": "red", "replace_text": "gold",
            **kwargs}


def json_only(value):
    assert type(value) in (dict, list, str, int, float, bool, type(None))
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            json_only(child)
    if type(value) is list:
        for child in value:
            json_only(child)
    assert json.loads(json.dumps(value, allow_nan=False)) == value


def identities(proj):
    return (id(proj), id(proj.prompt_lines), [id(item) for item in proj.prompt_lines],
            id(proj.module_library), id(proj.attribute_groups), id(proj.nodes), id(proj.line_map),
            {key: id(value) for key, value in proj.line_map.items()})


def resign(plan):
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    plan["plan_id"] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return plan


def test_versioned_capability_discovery_is_fresh_and_json_only():
    first = facade.discover_capabilities()
    json_only(first)
    assert first["contract_version"] == facade.CONTRACT_VERSION
    assert first["capabilities"]["illustration_search"] == {
        "modes": ["exact_token", "contains_token", "literal"],
        "max_results": facade.MAX_ITEMS,
        "query_text_chars": facade.MAX_REQUEST_TEXT,
    }
    assert "illustration_search" in first["capabilities"]["observations"]
    mutations = first["capabilities"]["mutations"]
    by_operation = {item["operation"]: item for item in mutations}
    assert by_operation["batch_replace"]["modes"] == [
        "exact_token", "contains_token", "literal", "token_set"]
    scene_swap = by_operation["scene_module_swap"]
    assert scene_swap["modes"] == ["strict", "loose"]
    assert scene_swap["requires_explicit_scene_id"] is True
    assert scene_swap["requires_explicit_source_module_name"] is True
    assert scene_swap["requires_explicit_target_module_name"] is True
    assert scene_swap["requires_reviewed_preview_before_host_apply"] is True
    first["capabilities"]["mutations"].clear()
    assert len(facade.discover_capabilities()["capabilities"]["mutations"]) == 2


def test_read_only_observations_preserve_gallery_baseline_and_active_scene_semantics():
    proj = project()
    before, identity = copy.deepcopy(proj), identities(proj)
    summary = facade.summarize_project(proj)
    assert summary["illustration_count"] == 4
    assert summary["baseline_illustration_count"] == 1
    assert summary["scene_count"] == 3
    scenes = facade.observe_scenes(proj)
    assert [row["scene_id"] for row in scenes["scenes"]] == ["s1", "s2", "s3"]
    assert [row["illustration_ids"] for row in scenes["scenes"]] == [["one", "two"], [], ["three"]]
    listing = facade.list_illustrations(proj)
    assert [row["illustration_id"] for row in listing["illustrations"]] == ["baseline", "one", "two", "three"]
    assert [row["scene_id"] for row in listing["illustrations"]] == [None, "s1", "s1", "s3"]
    assert [row["illustration_id"] for row in
            facade.list_illustrations(proj, scene_id="s1")["illustrations"]] == ["one", "two"]
    assert facade.list_illustrations(proj, scene_id="s2")["illustrations"] == []
    detail = facade.get_illustration(proj, "baseline")
    assert detail["illustration"]["scene_id"] is None
    for value in (summary, scenes, listing, detail):
        json_only(value)
    detail["illustration"]["tokens"].clear()
    assert proj == before
    assert identities(proj) == identity


def test_read_only_illustration_search_counts_matches_in_list_order_and_scene_scope(monkeypatch):
    proj = project()
    # Make every special row contain the query to characterize the shared
    # active-Illustration filter without relying on their other text.
    for line_id in ("s1", "scratch", "trash", "deleted-scene"):
        next(line for line in proj.prompt_lines if line.id == line_id).current_text = "red"
    before, identity = copy.deepcopy(proj), identities(proj)

    def unexpected_preview(*_args, **_kwargs):
        raise AssertionError("Illustration search must not build a Batch Replace Preview")

    monkeypatch.setattr(operations, "preview_batch_text_edit", unexpected_preview)
    monkeypatch.setattr(facade, "preview_batch_replace", unexpected_preview)

    exact = facade.search_illustrations(proj, "red", limit=2)
    assert exact["ok"] is True
    assert exact["match_mode"] == "exact_token"
    assert exact["total_count"] == 3
    assert exact["truncated"] is True
    assert exact["matches"] == [
        {"illustration_id": "baseline", "scene_id": None, "sequence_index": 0},
        {"illustration_id": "one", "scene_id": "s1", "sequence_index": 1},
    ]

    contains = facade.search_illustrations(proj, "re", match_mode="contains_token")
    assert contains["total_count"] == 4
    assert [row["illustration_id"] for row in contains["matches"]] == [
        "baseline", "one", "two", "three",
    ]

    literal = facade.search_illustrations(
        proj, "red, blue", match_mode="literal", scene_id="s1")
    assert literal["total_count"] == 1
    assert [row["illustration_id"] for row in literal["matches"]] == ["one"]
    empty_scene = facade.search_illustrations(proj, "red", scene_id="s2")
    assert empty_scene["total_count"] == 0 and empty_scene["matches"] == []
    assert all(row["illustration_id"] not in {"scratch", "trash", "s1", "deleted-scene"}
               for row in exact["matches"] + contains["matches"] + literal["matches"])
    for result in (exact, contains, literal, empty_scene):
        json_only(result)
    assert proj == before and identities(proj) == identity


def test_illustration_search_literal_can_find_module_marker_but_token_modes_skip_it():
    proj = build_graph(Project(prompt_lines=[line("module", "<mod:outfit>")],
                               module_library={"outfit": {"body": "red"}},
                               attribute_groups={}))
    exact = facade.search_illustrations(proj, "outfit", match_mode="exact_token")
    contains = facade.search_illustrations(proj, "outfit", match_mode="contains_token")
    literal = facade.search_illustrations(
        proj, "<mod:outfit>", match_mode="literal")
    assert exact["total_count"] == contains["total_count"] == 0
    assert literal["total_count"] == 1
    assert literal["matches"][0]["illustration_id"] == "module"


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"query_text": ""}, "invalid_search_query"),
    ({"query_text": " "}, "invalid_search_query"),
    ({"query_text": "x" * (facade.MAX_REQUEST_TEXT + 1)}, "invalid_search_query"),
    ({"query_text": "red", "match_mode": "token_set"}, "invalid_search_mode"),
    ({"query_text": "red", "limit": 0}, "invalid_limit"),
    ({"query_text": "red", "scene_id": "missing"}, "unknown_scene_id"),
])
def test_illustration_search_rejects_invalid_domain_arguments(kwargs, reason):
    result = facade.search_illustrations(project(), **kwargs)
    assert result["ok"] is False and result["reason"] == reason
    json_only(result)


def test_observation_limits_bound_rows_text_and_tokens():
    proj = Project(prompt_lines=[line("scene", "x" * 5000, line_type="separator")] +
                   [line(f"l{i}", ", ".join(["long" * 100] * 120)) for i in range(110)])
    scene = facade.observe_scenes(proj, limit=1)["scenes"][0]
    assert len(scene["illustration_ids"]) == 100 and scene["illustration_ids_truncated"]
    assert scene["label"]["truncated"]
    listing = facade.list_illustrations(proj, limit=2)
    assert len(listing["illustrations"]) == 2 and listing["truncated"]
    prompt = listing["illustrations"][0]["positive_prompt"]
    assert len(prompt["text"]) == 4000 and prompt["truncated"]
    detail = facade.get_illustration(proj, "l0")["illustration"]
    assert len(detail["tokens"]) == 100 and detail["tokens_truncated"]
    json_only(detail)


def test_orientation_fields_are_bounded_read_only_and_module_values_stay_opaque():
    proj = project()
    proj.module_library["outfit"]["reference_assets"] = OpaqueAssets()
    item = proj.prompt_lines[2]
    item.edited = True
    item.negative_prompt = "blurry"
    item.image_path = "refs/one.png"
    item.generated_image_path = "candidates/new.png"
    item.selected_candidate_path = "candidates/chosen.png"
    item.generated_candidates = [{"path": "a.png"}, {"path": "b.png", "trashed": True},
                                 {"path": ""}, {"future": "opaque"}]
    item.gallery_variants = [{"path": "v.png", "kind": "gallery_variant"},
                             {"path": "old.png", "kind": "gallery_variant", "trashed": True},
                             {"path": "other.png", "kind": "candidate"}]
    proj.prompt_lines[1].separator_color = "#112233"
    before, identity = copy.deepcopy(proj), identities(proj)
    summary = facade.summarize_project(proj)
    assert summary["modules"]["names"][0]["text"] == "outfit"
    assert summary["attribute_groups"]["names"][0]["text"] == "palette"
    assert summary["candidate_count"] == summary["variant_count"] == 1
    scenes = facade.observe_scenes(proj)["scenes"]
    assert [scene["scene_order"] for scene in scenes] == [0, 1, 2]
    assert scenes[0]["color"]["text"] == "#112233"
    detail = facade.get_illustration(proj, "one")["illustration"]
    assert detail["filename"]["text"] == "one.png" and detail["sequence_index"] == 1
    assert detail["scene_label"]["text"] == "First" and detail["edited"]
    assert detail["negative_prompt"]["text"] == "blurry"
    assert detail["image_references"]["selected_candidate_path"]["text"] == "candidates/chosen.png"
    assert detail["candidate_count"] == detail["variant_count"] == 1
    assert "reference_assets" not in json.dumps(summary)
    for result in (summary, detail, scenes):
        json_only(result)
    assert proj == before and identities(proj) == identity


@pytest.mark.parametrize("proj", [None, {}, 0,
                                 Project(prompt_lines=None), Project(prompt_lines=[None])])
def test_missing_and_malformed_project_observations_fail_with_json_diagnostics(proj):
    for result in (facade.summarize_project(proj), facade.observe_scenes(proj),
                   facade.list_illustrations(proj), facade.search_illustrations(proj, "red"),
                   facade.get_illustration(proj, "one")):
        assert not result["ok"] and result["diagnostics"]
        json_only(result)


def test_observation_missing_field_is_structured_and_hostile_project_is_not_inspected():
    proj = project()
    del proj.prompt_lines[2].current_text
    assert facade.list_illustrations(proj)["reason"] == "invalid_project_state"
    assert facade.summarize_project(Hostile())["reason"] == "invalid_project"
    proj = project()
    proj.prompt_lines[1].separator_label = Hostile()
    assert facade.observe_scenes(proj)["reason"] == "invalid_scene_label"


@pytest.mark.parametrize("target", ["missing", "trash", "s1", "scratch"])
def test_illustration_detail_rejects_missing_and_special_targets(target):
    result = facade.get_illustration(project(), target)
    assert not result["ok"] and result["diagnostics"]
    json_only(result)


@pytest.mark.parametrize("limit", [0, 101, True, "5", None])
def test_invalid_observation_limits_fail_clearly(limit):
    assert facade.observe_scenes(project(), limit=limit)["reason"] == "invalid_limit"
    assert facade.list_illustrations(project(), limit=limit)["reason"] == "invalid_limit"


def test_unknown_scene_and_duplicate_project_ids_fail_observations_and_plan():
    proj = project()
    assert facade.list_illustrations(proj, scene_id="missing")["reason"] == "unknown_scene_id"
    proj.prompt_lines.append(line("one", deleted=True))
    for result in (facade.observe_scenes(proj), facade.summarize_project(proj),
                   facade.list_illustrations(proj), facade.get_illustration(proj, "one")):
        assert result["reason"] == "ambiguous_project_id"
    assert facade.preview_batch_replace(proj, request())["reason"] == "ambiguous_project_id"


@pytest.mark.parametrize("change,reason", [
    ({"illustration_ids": []}, "explicit_illustration_ids_required"),
    ({"illustration_ids": "one"}, "explicit_illustration_ids_required"),
    ({"illustration_ids": ["one", " one "]}, "duplicate_requested_id"),
    ({"illustration_ids": ["missing"]}, "unknown_illustration_id"),
    ({"illustration_ids": ["trash"]}, "unsupported_illustration_target"),
    ({"illustration_ids": ["s1"]}, "unsupported_illustration_target"),
    ({"illustration_ids": ["scratch"]}, "unsupported_illustration_target"),
    ({"match_mode": "regex"}, "invalid_replace_options"),
    ({"preserve_weights": 1}, "invalid_replace_options"),
    ({"find_text": ""}, "invalid_replace_text"),
    ({"replace_text": ""}, "invalid_replace_text"),
    ({"find_text": "red, blue"}, "invalid_replace_tokens"),
    ({"match_mode": "contains_token", "replace_text": "a, b"}, "invalid_replace_tokens"),
    ({"match_mode": "token_set", "find_text": "red, (red:2)"}, "invalid_replace_tokens"),
    ({"match_mode": "token_set", "replace_text": "<mod:outfit>, gold"}, "invalid_replace_tokens"),
    ({"selection": "all"}, "invalid_request_shape"),
])
def test_invalid_requests_return_diagnostics_without_mutation(change, reason):
    proj = project()
    before = copy.deepcopy(proj)
    plan = facade.preview_batch_replace(proj, request(**change))
    assert not plan["valid"] and plan["reason"] == reason
    assert facade.apply_batch_replace(proj, plan).updated_project is None
    json_only(plan)
    assert proj == before


@pytest.mark.parametrize("mode,find,replacement,preserve,expected", [
    ("exact_token", "white shirt", "dress", True, "(dress:1.7), white shirtless, red skirt"),
    ("contains_token", "shirt", "dress", True, "(dress:1.7), dress, red skirt"),
    ("literal", "white shirt", "dress, apron", True,
     "(dress, apron:1.7), dress, apronless, red skirt"),
    ("token_set", "red skirt, white shirt", "(dress:1.2), apron, dress", True,
     "(dress:1.2), apron, dress, white shirtless"),
])
def test_replace_modes_use_core_preview_and_apply_semantics(mode, find, replacement, preserve, expected):
    proj = Project(prompt_lines=[line("one", "(white shirt:1.7), white shirtless, red skirt")])
    before, identity = copy.deepcopy(proj), identities(proj)
    value = request(match_mode=mode, find_text=find, replace_text=replacement, preserve_weights=preserve)
    plan = facade.preview_batch_replace(proj, value)
    assert plan["valid"] and plan["affected_count"] == 1
    if mode == "token_set":
        assert plan["request"]["preserve_weights"] is False
    expected_preview = operations.preview_batch_text_edit(
        proj, "replace", replacement, search_text=find, replace_match_mode=mode,
        preserve_replace_weights=preserve, target_line_ids=["one"],
    )
    assert plan["examples"][0]["after"]["text"] == expected_preview["examples"][0]["after"] == expected
    result = facade.apply_batch_replace(proj, json.loads(json.dumps(plan)))
    assert result.agent_result["ok"] and result.updated_project is not proj
    assert result.updated_project.prompt_lines[0].current_text == expected
    assert result.updated_project.prompt_lines[0].tokens == parse_prompt(expected)
    assert proj == before and identities(proj) == identity
    json_only(result.agent_result)


@pytest.mark.parametrize("mode", ["exact_token", "contains_token", "literal", "token_set"])
def test_blank_replace_text_is_rejected_for_every_mode_without_project_mutation(mode):
    proj = project()
    before, identity = copy.deepcopy(proj), identities(proj)
    plan = facade.preview_batch_replace(proj, request(
        match_mode=mode, find_text="red", replace_text="   "))
    assert not plan["valid"] and plan["reason"] == "invalid_replace_text"
    result = facade.apply_batch_replace(proj, plan)
    assert not result.agent_result["ok"] and result.updated_project is None
    assert proj == before and identities(proj) == identity


def test_project_order_normalization_deterministic_plan_and_no_registry():
    proj = project()
    plan = facade.preview_batch_replace(proj, request(["two", "baseline", "one"]))
    assert plan["target_ids"] == ["baseline", "one", "two"]
    assert plan == facade.preview_batch_replace(proj, request(["one", "two", "baseline"]))
    assert len(plan["plan_id"]) == len(plan["source_fingerprint"]) == len(plan["projection_digest"]) == 64
    json_only(plan)
    # A newly loaded facade can Apply a transported envelope without a Preview registry.
    fresh_module = importlib.reload(facade)
    assert fresh_module.apply_batch_replace(proj, json.loads(json.dumps(plan))).agent_result["ok"]


def test_example_bound_and_complete_projection_digest_include_unshown_targets():
    proj = Project(prompt_lines=[line(f"l{i}", "red, " + "z" * 4500) for i in range(8)])
    value = request([item.id for item in proj.prompt_lines])
    plan = facade.preview_batch_replace(proj, value)
    assert len(plan["examples"]) == 5 and plan["examples_truncated"]
    assert plan["target_count"] == plan["affected_count"] == 8
    assert plan["examples"][0]["after"]["truncated"]
    changed = copy.deepcopy(proj)
    changed.prompt_lines[-1].current_text += "!"
    later = facade.preview_batch_replace(changed, value)
    assert later["examples"] == plan["examples"]
    assert later["projection_digest"] != plan["projection_digest"]
    assert later["source_fingerprint"] != plan["source_fingerprint"]
    assert facade.apply_batch_replace(changed, plan).agent_result["reason"] == "stale_plan"
    applied = facade.apply_batch_replace(proj, plan)
    assert applied.agent_result["affected_count"] == 8
    assert all(item.current_text.startswith("gold") for item in applied.updated_project.prompt_lines)


def test_module_guard_is_preserved_and_clone_keeps_domain_metadata_and_aliases():
    proj = project()
    proj.prompt_lines[2] = line("one", "<mod:outfit>red</mod:outfit>, blue")
    build_graph(proj)
    before, identity = copy.deepcopy(proj), identities(proj)
    plan = facade.preview_batch_replace(proj, request(
        ["one", "baseline"], match_mode="token_set", find_text="red, blue", replace_text="gold"))
    assert plan["affected_count"] == 1 and plan["skipped_count"] == 1
    guarded = next(row for row in plan["examples"] if row["illustration_id"] == "one")
    assert guarded["module_structure_guard"] and guarded["skipped"] and not guarded["changed"]
    assert guarded["before"] == guarded["after"]
    result = facade.apply_batch_replace(proj, plan)
    updated = result.updated_project
    assert updated is not None and updated.prompt_lines[2].current_text == proj.prompt_lines[2].current_text
    assert updated.module_library == proj.module_library and updated.module_library is not proj.module_library
    assert updated.attribute_groups == proj.attribute_groups
    assert updated.project_metadata == proj.project_metadata
    assert updated.line_map["baseline"] is updated.prompt_lines[0]
    assert updated.line_map["baseline"] is not proj.prompt_lines[0]
    assert proj == before and identities(proj) == identity


@pytest.mark.parametrize("mutation", [
    lambda p: setattr(p.prompt_lines[2], "current_text", "pink"),
    lambda p: setattr(p.prompt_lines[2], "tokens", ["pink"]),
    lambda p: setattr(p.prompt_lines[2], "line_type", "workbench"),
    lambda p: setattr(p.prompt_lines[2], "deleted", True),
    lambda p: setattr(p.prompt_lines[2], "id", "replacement"),
    lambda p: p.prompt_lines.reverse(),
    lambda p: p.prompt_lines.append(line("one")),
    lambda p: p.prompt_lines.pop(2),
    lambda p: setattr(p, "merge_by_word_only", False),
    lambda p: setattr(p.prompt_lines[0], "current_text", "unselected change"),
])
def test_result_and_resolution_changes_stale_reviewed_plan(mutation):
    proj = project()
    plan = facade.preview_batch_replace(proj, request())
    mutation(proj)
    before, identity = copy.deepcopy(proj), identities(proj)
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["reason"] == "stale_plan"
    assert result.updated_project is None
    assert proj == before and identities(proj) == identity


@pytest.mark.parametrize("field,value", [
    ("request", request(find_text="blue")), ("target_ids", ["two"]),
    ("affected_count", 0), ("examples", []), ("valid", False),
    ("source_fingerprint", "0" * 64), ("projection_digest", "1" * 64),
])
def test_request_and_plan_tampering_fail_closed(field, value):
    proj = project()
    before = copy.deepcopy(proj)
    plan = facade.preview_batch_replace(proj, request())
    plan[field] = value
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["reason"] == "plan_tampered" and result.updated_project is None
    # Rehashing the outer envelope alone cannot turn an edited request into fresh intent.
    result = facade.apply_batch_replace(proj, resign(plan))
    assert not result.agent_result["ok"] and result.updated_project is None
    assert proj == before


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.update(contract_version="future"), "unsupported_plan_contract"),
    (lambda p: p.update(operation="delete"), "unsupported_plan_contract"),
    (lambda p: p.pop("examples"), "invalid_plan_shape"),
    (lambda p: p.update(extra="ignored?"), "invalid_plan_shape"),
    (lambda p: p.update(valid=1), "invalid_reviewed_plan"),
])
def test_malformed_envelope_and_contract_fail_closed(mutation, reason):
    proj = project()
    plan = facade.preview_batch_replace(proj, request())
    mutation(plan)
    resign(plan)
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["reason"] == reason and result.updated_project is None


class Hostile:
    def __str__(self):
        raise AssertionError("must not stringify")

    def __repr__(self):
        raise AssertionError("must not repr")

    def __iter__(self):
        raise AssertionError("must not iterate")

    def __deepcopy__(self, memo):
        raise AssertionError("must not copy")


class HostileDict(dict):
    def items(self):
        raise AssertionError("must not invoke supplied mapping hooks")


class OpaqueAssets(Hostile):
    def __deepcopy__(self, memo):
        # Host-only opaque immutable value: copying preserves it, never inspects it.
        return self


def test_module_library_and_opaque_reference_assets_are_outside_prompt_freshness():
    proj = project()
    plan = facade.preview_batch_replace(proj, request())
    proj.module_library["outfit"]["body"] = "changed library body, unused by Batch Replace"
    opaque = OpaqueAssets()
    proj.module_library["outfit"]["reference_assets"] = opaque
    assert facade.preview_batch_replace(proj, request()) == plan
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["ok"]
    assert result.updated_project.module_library["outfit"]["reference_assets"] is opaque
    assert proj.module_library["outfit"]["reference_assets"] is opaque


def test_hostile_non_json_cyclic_and_unbounded_envelopes_fail_without_hooks():
    proj = project()
    before = copy.deepcopy(proj)
    cycle = []
    cycle.append(cycle)
    for value in (Hostile(), HostileDict(), {"x": Hostile()}, {1: "bad key"}, cycle,
                  {"x": float("nan")}, {"x": "a" * 1000001}, {"x": "\ud800"}):
        preview = facade.preview_batch_replace(proj, value)
        assert not preview["valid"]
        result = facade.apply_batch_replace(proj, value)
        assert not result.agent_result["ok"] and result.updated_project is None
        json_only(preview)
        json_only(result.agent_result)
    assert proj == before


def test_request_and_observation_name_bounds():
    proj = project()
    assert facade.preview_batch_replace(proj, request(
        ["one"] * 1001))["reason"] == "explicit_illustration_ids_required"
    assert facade.preview_batch_replace(proj, request(
        find_text="x" * 10001))["reason"] == "invalid_replace_text"
    proj.module_library = {f"m{i:03}": OpaqueAssets() for i in range(110)}
    proj.attribute_groups = {f"g{i:03}": OpaqueAssets() for i in range(110)}
    summary = facade.summarize_project(proj)
    for key in ("modules", "attribute_groups"):
        assert summary[key]["count"] == 110 and summary[key]["truncated"]
        assert len(summary[key]["names"]) == 100
    json_only(summary)


def test_excessive_nested_envelope_is_bounded_and_json_safe():
    nested = []
    for _ in range(35):
        nested = [nested]
    result = facade.apply_batch_replace(project(), nested)
    assert result.agent_result["reason"] == "json_bounds_exceeded"
    json_only(result.agent_result)


def test_apply_exception_after_clone_mutation_preserves_input(monkeypatch):
    proj = project()
    plan = facade.preview_batch_replace(proj, request())
    before, identity = copy.deepcopy(proj), identities(proj)

    def broken(clone, **kwargs):
        clone.prompt_lines[2].current_text = "partial write"
        clone.module_library.clear()
        raise RuntimeError("host exception details are not agent diagnostics")

    monkeypatch.setattr(operations, "apply_batch_text_edit", broken)
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["reason"] == "apply_failed" and result.updated_project is None
    assert proj == before and identities(proj) == identity


def test_materialization_mismatch_discards_clone(monkeypatch):
    proj = project()
    plan = facade.preview_batch_replace(proj, request())
    before = copy.deepcopy(proj)
    monkeypatch.setattr(operations, "apply_batch_text_edit", lambda clone, **kwargs: clone)
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["reason"] == "apply_materialization_mismatch"
    assert result.updated_project is None and proj == before


def test_no_op_plan_is_visible_but_apply_does_not_clone_or_call_core(monkeypatch):
    proj = project()
    plan = facade.preview_batch_replace(proj, request(find_text="absent"))
    assert plan["valid"] and plan["affected_count"] == plan["skipped_count"] == 0
    assert plan["unchanged_count"] == 1 and not plan["examples"]
    before, identity = copy.deepcopy(proj), identities(proj)

    def unexpected(*args, **kwargs):
        raise AssertionError("zero-change Apply must not clone or call Batch Apply")

    monkeypatch.setattr(facade.copy, "deepcopy", unexpected)
    monkeypatch.setattr(operations, "apply_batch_text_edit", unexpected)
    result = facade.apply_batch_replace(proj, plan)
    assert result.agent_result["applied"] is False
    assert result.agent_result["reason"] == "no_changes"
    assert result.updated_project is None
    assert proj == before and identities(proj) == identity


def scene_module_swap_project(prompts=("red, blue",), *, scene_id="scene"):
    rows = [line(scene_id, "Scene Label", line_type="separator")]
    rows.extend(line(f"swap-{index}", text, negative_prompt="unchanged negative")
                for index, text in enumerate(prompts))
    return build_graph(Project(
        prompt_lines=rows,
        module_library={
            "source": {"body": "red, blue, source-body-secret",
                       "core_tokens": ["red", "blue"],
                       "private_metadata": {"secret": "module-metadata-secret"},
                       "reference_assets": {"private": r"C:\private\reference.png"}},
            "target": {"body": "gold, green", "reference_assets": ["target-reference-secret"]},
        },
        source_directory=r"C:\private\source-directory",
    ))


def scene_module_swap_request(**updates):
    return {"scene_id": "scene", "source_module_name": "source",
            "target_module_name": "target", **updates}


def test_scene_module_swap_preview_reuses_core_planner_and_is_deterministic(monkeypatch):
    proj = scene_module_swap_project(("red, blue", "green, red, blue"))
    before, identity = copy.deepcopy(proj), identities(proj)
    calls = []
    original = facade.module_swap_selected_routes.build_selected_routes_module_swap_plan

    def track(value, route_ids, **kwargs):
        calls.append((route_ids, kwargs))
        return original(value, route_ids, **kwargs)

    monkeypatch.setattr(facade.module_swap_selected_routes,
                        "build_selected_routes_module_swap_plan", track)
    first = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    second = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    assert first == second
    assert calls and all(route_ids == ["scene"] for route_ids, _ in calls)
    assert all(kwargs["project_path"] == "" and kwargs["disabled_modules"] is None
               and kwargs["match_mode"] == "strict" for _, kwargs in calls)
    assert first["valid"] is True
    assert first["operation"] == "scene_module_swap"
    assert first["request"]["match_mode"] == "strict"
    assert first["scene_id"] == "scene"
    assert first["scene_label"]["text"] == "Scene Label"
    assert first["target_ids"] == ["swap-0", "swap-1"]
    assert first["target_count"] == first["changed_count"] == 2
    assert first["no_op_count"] == 0
    assert first["prompt_only"] is True
    assert first["negative_prompt_semantics"] == "unchanged_by_module_swap"
    assert first["review_rows"][0]["before_positive_prompt"]["text"] == "red, blue"
    assert first["review_rows"][0]["after_positive_prompt"]["text"] == "gold, green"
    assert first["review_rows"][0]["token_delta"]["removed_count"] == 2
    assert first["source_fingerprint"] and first["projection_digest"] and first["plan_id"]
    assert first["plan_id"] == facade._digest({key: value for key, value in first.items()
                                               if key != "plan_id"})
    json_only(first)
    assert proj == before and identities(proj) == identity


def test_scene_module_swap_loose_mode_allows_partial_core_match():
    proj = scene_module_swap_project(("red, other",))
    strict = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    loose = facade.preview_scene_module_swap(
        proj, scene_module_swap_request(match_mode="loose"))
    assert strict["valid"] and strict["changed_count"] == 0
    assert loose["valid"] and loose["request"]["match_mode"] == "loose"
    assert loose["changed_count"] == 1
    assert loose["review_rows"][0]["after_positive_prompt"]["text"] == "gold, green, other"


def test_scene_module_swap_rejects_non_explicit_invalid_scene_and_module_inputs():
    proj = scene_module_swap_project()
    cases = [
        ({"source_module_name": "source", "target_module_name": "target"},
         "invalid_request_shape"),
        (scene_module_swap_request(scene_id="missing"), "unknown_scene_id"),
        (scene_module_swap_request(scene_id="swap-0"), "invalid_scene_id"),
        (scene_module_swap_request(source_module_name="missing"), "unknown_source_module"),
        (scene_module_swap_request(target_module_name="missing"), "unknown_target_module"),
        (scene_module_swap_request(target_module_name="source"), "same_module"),
        (scene_module_swap_request(source_module_name=" source"), "invalid_source_module_name"),
        (scene_module_swap_request(match_mode="wide"), "invalid_match_mode"),
    ]
    for value, reason in cases:
        result = facade.preview_scene_module_swap(proj, value)
        assert result["valid"] is False and result["reason"] == reason
        json_only(result)
    deleted = copy.deepcopy(proj)
    deleted.prompt_lines[0].deleted = True
    assert facade.preview_scene_module_swap(
        deleted, scene_module_swap_request())["reason"] == "invalid_scene_id"
    empty = scene_module_swap_project(())
    assert facade.preview_scene_module_swap(
        empty, scene_module_swap_request())["reason"] == "no_scene_targets"


@pytest.mark.parametrize("record,reason", [
    ("not a Module record", "malformed_module"),
    ({"body": ["not", "text"]}, "malformed_module"),
])
def test_scene_module_swap_rejects_malformed_module_records(record, reason):
    proj = scene_module_swap_project()
    proj.module_library["source"] = record
    result = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    assert result["valid"] is False and result["reason"] == reason
    json_only(result)


def test_scene_module_swap_rejects_target_over_limit_without_truncating():
    proj = scene_module_swap_project(tuple("red, blue" for _ in range(facade.MAX_TARGETS + 1)))
    result = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    assert result["valid"] is False and result["reason"] == "target_limit_exceeded"
    assert result["target_ids"] == [] and result["target_count"] == 0
    json_only(result)


def test_scene_module_swap_valid_no_op_is_visible_without_claiming_a_change():
    proj = scene_module_swap_project(("purple, orange",))
    result = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    assert result["valid"] is True
    assert result["changed_count"] == 0 and result["no_op_count"] == 1
    assert result["skipped_count"] == 1
    assert result["review_rows"][0]["no_op"] is True
    json_only(result)


def test_scene_module_swap_identity_tracks_prompts_modules_order_and_image_refs():
    proj = scene_module_swap_project(("red, blue", "red, blue"))
    base = facade.preview_scene_module_swap(proj, scene_module_swap_request())

    changed_prompt = copy.deepcopy(proj)
    changed_prompt.prompt_lines[1].current_text = "red, blue, extra"
    prompt_plan = facade.preview_scene_module_swap(changed_prompt, scene_module_swap_request())
    assert prompt_plan["source_fingerprint"] != base["source_fingerprint"]
    assert prompt_plan["projection_digest"] != base["projection_digest"]

    changed_module = copy.deepcopy(proj)
    changed_module.module_library["target"]["body"] = "silver, violet"
    module_plan = facade.preview_scene_module_swap(changed_module, scene_module_swap_request())
    assert module_plan["source_fingerprint"] != base["source_fingerprint"]

    reordered = copy.deepcopy(proj)
    reordered.prompt_lines[1], reordered.prompt_lines[2] = (
        reordered.prompt_lines[2], reordered.prompt_lines[1])
    order_plan = facade.preview_scene_module_swap(reordered, scene_module_swap_request())
    assert order_plan["source_fingerprint"] != base["source_fingerprint"]
    assert order_plan["projection_digest"] != base["projection_digest"]

    changed_image = copy.deepcopy(proj)
    changed_image.prompt_lines[1].image_path = r"C:\private\changed.png"
    image_plan = facade.preview_scene_module_swap(changed_image, scene_module_swap_request())
    assert image_plan["source_fingerprint"] != base["source_fingerprint"]


def test_scene_module_swap_digest_covers_non_visible_targets_and_bounds_rows_and_text():
    many = scene_module_swap_project(tuple("red, blue" for _ in range(101)))
    all_rows = facade.preview_scene_module_swap(many, scene_module_swap_request())
    changed_last = copy.deepcopy(many)
    changed_last.prompt_lines[-1].current_text = "red, blue, last-only"
    later = facade.preview_scene_module_swap(changed_last, scene_module_swap_request())
    assert len(all_rows["review_rows"]) == facade.MAX_ITEMS
    assert all_rows["review_rows_truncated"] is True
    assert all_rows["review_rows_omitted"] == 1
    assert later["review_rows"] == all_rows["review_rows"]
    assert later["projection_digest"] != all_rows["projection_digest"]

    long = scene_module_swap_project(("red, " + "x" * (facade.MAX_TEXT + 10),))
    long.module_library["target"]["body"] = "gold, " + "y" * (facade.MAX_TEXT + 10)
    bounded = facade.preview_scene_module_swap(long, scene_module_swap_request())
    assert bounded["valid"] is True
    row = bounded["review_rows"][0]
    assert row["before_positive_prompt"]["truncated"]
    assert row["after_positive_prompt"]["truncated"]
    json_only(bounded)


def test_scene_module_swap_never_exposes_module_metadata_paths_or_exception_text(monkeypatch):
    proj = scene_module_swap_project()
    proj.prompt_lines[1].image_path = r"C:\private\original.png"
    proj.prompt_lines[1].generated_image_path = r"C:\private\generated.png"
    proj.prompt_lines[1].selected_candidate_path = r"C:\private\candidate.png"
    result = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    encoded = json.dumps(result, ensure_ascii=False)
    for secret in (
        "source-body-secret", "module-metadata-secret", "reference.png",
        "target-reference-secret", "source-directory", "private\\source-directory",
        "original.png", "generated.png", "candidate.png",
    ):
        assert secret not in encoded

    def fail_with_private_detail(*_args, **_kwargs):
        raise RuntimeError(r"private C:\private\stack\do-not-leak")

    monkeypatch.setattr(facade.module_swap_selected_routes,
                        "build_selected_routes_module_swap_plan", fail_with_private_detail)
    failed = facade.preview_scene_module_swap(proj, scene_module_swap_request())
    assert failed["reason"] == "module_swap_preview_failed"
    assert "private" not in json.dumps(failed)
    assert "RuntimeError" not in json.dumps(failed)


def test_scene_module_swap_hostile_request_values_fail_without_custom_hooks():
    proj = scene_module_swap_project()
    result = facade.preview_scene_module_swap(proj, {
        "scene_id": Hostile(), "source_module_name": "source", "target_module_name": "target",
    })
    assert result["valid"] is False and result["reason"] == "non_json_value"
    json_only(result)
