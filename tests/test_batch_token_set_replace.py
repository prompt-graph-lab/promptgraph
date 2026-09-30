"""Prompt-base N-to-M replacement, shared Preview/Apply and legacy modes."""

import copy

import pytest

from core.batch_preview import _highlight_replace_result_tokens, _highlight_token_matches
from core.operations import (
    _batch_transform_text,
    apply_batch_text_edit,
    is_valid_token_set_replace_target,
    preview_batch_text_edit,
)
from core.parser import parse_prompt
from core.project import Project, PromptLine


def make_line(line_id, text, **kwargs):
    return PromptLine(
        id=line_id, original_file_name=f"{line_id}.png", original_index=0,
        current_index=0, original_text=text, current_text=text,
        tokens=parse_prompt(text), **kwargs,
    )


def transform(text, find, replacement, **kwargs):
    return _batch_transform_text(
        text, "replace", replacement, search_text=find,
        replace_match_mode="token_set", **kwargs,
    )


@pytest.mark.parametrize("source,find,replacement,expected", [
    ("header, white shirt, outdoors, red skirt, pose", "red skirt, white shirt",
     "black dress, white apron", "header, black dress, white apron, outdoors, pose"),
    ("red skirt, outdoors, white shirt", "white shirt, red skirt",
     "black dress, white apron", "black dress, white apron, outdoors"),
    ("header, red skirt, white shirt, red skirt, pose, (white shirt:1.7)",
     "white shirt, red skirt", "black dress, white apron",
     "header, black dress, white apron, pose"),
    ("white shirt, sky", "white shirt", "black dress, white apron",
     "black dress, white apron, sky"),
    ("white shirt, sky, red skirt", "white shirt, red skirt", "black dress",
     "black dress, sky"),
    ("(white shirt:1.7), outdoors, (red skirt:0.8)", "(red skirt:2), white shirt",
     "(white apron:1.2), black dress, (white apron:0.8)",
     "(white apron:1.2), black dress, (white apron:0.8), outdoors"),
    ("(white shirt:1.7), sky", "white shirt", "black dress", "black dress, sky"),
    ("(a, b:1.3), sky, red skirt", "(a, b:2), red skirt", "(c, d:1.1), apron",
     "(c, d:1.1), apron, sky"),
])
def test_token_set_deterministic_replacement(source, find, replacement, expected):
    assert transform(source, find, replacement) == expected
    # Even direct callers that request source weights cannot transfer them.
    assert transform(source, find, replacement, preserve_replace_weights=True) == expected
    assert transform(source, find, replacement, preserve_replace_weights=False) == expected


@pytest.mark.parametrize("source", [
    " white shirt,   outdoors ", "White shirt, red skirt", "white shirt, red skirts",
    "white shirt", "<mod:outfit>, red skirt", "", "red skirt, outdoors",
])
def test_all_exact_bases_required_and_no_match_preserves_original_text(source):
    assert transform(source, "white shirt, red skirt", "black dress") == source


@pytest.mark.parametrize("find,replacement", [
    ("", "x"), ("a", ""), ("   ", "x"), (", ,", "x"), ("a", ", ,"),
    ("a, a", "x"), ("a, (a:1.2)", "x"), ("( :1.2)", "x"),
    ("a", "( :1.2)"), ("<mod:outfit>, a", "x"),
    ("a, </mod:outfit>", "x"), ("a", "x, <mod:outfit>"),
    ("a", "</mod:outfit>, x"),
])
def test_invalid_inputs_fail_closed_in_helper_preview_and_apply(find, replacement):
    source = " a,  red skirt, outdoors "
    assert not is_valid_token_set_replace_target(find, replacement)
    assert transform(source, find, replacement) == source
    project = Project(prompt_lines=[make_line("one", source)])
    original = copy.deepcopy(project)
    preview = preview_batch_text_edit(
        project, "replace", replacement, search_text=find, replace_match_mode="token_set",
    )
    assert preview["affected_line_count"] == 0
    assert preview["examples"] == []
    assert apply_batch_text_edit(
        project, "replace", replacement, search_text=find, replace_match_mode="token_set",
    ) is project
    assert project == original


def test_duplicate_replacement_bases_are_authored_sequence_and_case_is_exact():
    assert is_valid_token_set_replace_target("a, A", "x, (x:1.2)")
    assert transform("a, A", "a, A", "x, (x:1.2)") == "x, (x:1.2)"


@pytest.mark.parametrize("target_ids", [None, ["two"], [], ["one", "three"]])
def test_preview_apply_parity_and_existing_target_filtering(target_ids):
    project = Project(prompt_lines=[
        make_line("one", "white shirt, outdoors, red skirt"),
        make_line("two", "red skirt, (white shirt:1.3), sky"),
        make_line("three", "white shirt, blue skirt"),
        make_line("deleted", "white shirt, red skirt", deleted=True),
        make_line("separator", "white shirt, red skirt", line_type="separator"),
        make_line("workbench", "white shirt, red skirt", line_type="workbench"),
    ])
    before = copy.deepcopy(project)
    kwargs = dict(search_text="white shirt, red skirt", replace_match_mode="token_set",
                  target_line_ids=target_ids)
    preview = preview_batch_text_edit(project, "replace", "black dress, white apron", **kwargs)
    assert project == before  # Preview does not edit or rebuild the Project.
    result = apply_batch_text_edit(project, "replace", "black dress, white apron", **kwargs)
    assert result is project
    reviewed = {item["line_id"]: item["after"] for item in preview["examples"]}
    changed = {line.id: line.current_text for line, old in zip(result.prompt_lines, before.prompt_lines)
               if line.current_text != old.current_text}
    assert changed == reviewed
    assert len(changed) == preview["affected_line_count"]
    assert not {"deleted", "separator", "workbench", "three"} & changed.keys()
    for line in result.prompt_lines:
        if line.id in changed:
            assert line.tokens == parse_prompt(line.current_text)
            assert line.edited


@pytest.mark.parametrize("source,find,replacement,affected,skipped", [
    ("<mod:outfit>, white shirt, red skirt, </mod:outfit>, sky",
     "white shirt, red skirt", "black dress, white apron", 1, 0),
    ("<mod:outfit>white shirt</mod:outfit>, red skirt, sky",
     "white shirt, red skirt", "black dress", 0, 1),
    ("white shirt, red skirt", "white shirt, red skirt",
     "<mod:outfit>black dress</mod:outfit>", 0, 1),
])
def test_existing_module_structure_guard_is_shared_by_preview_and_apply(
    source, find, replacement, affected, skipped,
):
    project = Project(prompt_lines=[make_line("one", source)])
    kwargs = dict(search_text=find, replace_match_mode="token_set")
    preview = preview_batch_text_edit(project, "replace", replacement, **kwargs)
    assert preview["affected_line_count"] == affected
    assert preview["skipped_module_structure_count"] == skipped
    apply_batch_text_edit(project, "replace", replacement, **kwargs)
    expected = preview["examples"][0]["after"] if affected else source
    assert project.prompt_lines[0].current_text == expected


@pytest.mark.parametrize("mode,find,replacement,preserve,expected", [
    ("exact_token", "white shirt", "black dress", True, "(black dress:1.7), white shirtless, red skirt"),
    ("exact_token", "white shirt", "(black dress:1.2)", False, "(black dress:1.2), white shirtless, red skirt"),
    ("contains_token", "shirt", "dress", True, "(dress:1.7), dress, red skirt"),
    ("literal", "white shirt", "black dress, white apron", True,
     "(black dress, white apron:1.7), black dress, white apronless, red skirt"),
    ("exact_token", "white shirt, red skirt", "black dress", True,
     "(white shirt:1.7), white shirtless, red skirt"),
])
def test_legacy_replace_semantics(mode, find, replacement, preserve, expected):
    assert _batch_transform_text(
        "(white shirt:1.7), white shirtless, red skirt", "replace", replacement,
        search_text=find, replace_match_mode=mode, preserve_replace_weights=preserve,
    ) == expected


def test_token_set_source_and_replacement_highlighting_escapes_and_keeps_exact_bases():
    source = "<mod:outfit>, (white shirt:1.3), sky &, red skirt, white shirtless, </mod:outfit>"
    before = _highlight_token_matches(source, "red skirt, white shirt", "token_set")
    assert before.count("background-color:#fff3a3;") == 2
    assert "<span style='background-color:#fff3a3;'>(white shirt:1.3)</span>" in before
    assert "<span style='background-color:#fff3a3;'>red skirt</span>" in before
    assert "sky &amp;" in before
    assert "&lt;mod:outfit&gt;" in before
    after = _highlight_replace_result_tokens(
        "black dress, sky &, (white apron:1.2), white apronless", "black dress, (white apron:1.2)", "token_set",
    )
    assert after.count("background-color:#cfe8ff;") == 2
    assert "white apronless</span>" not in after
    # Existing single-token highlighting keeps multi-token replacements unhighlighted.
    assert _highlight_replace_result_tokens("a,  b &", "a, b") == "a,  b &amp;"
