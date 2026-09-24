"""Characterization of the read-only Candidate Route preview boundary."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from core import candidate_route_creation_preview as preview


def run_plan(lines, *, example_limit=8, **overrides):
    events = []
    warnings = ['scope warning']
    route_resolution = {'line_ids': ['a']}
    project = NS(prompt_lines=lines)
    resolution = dict(target_lines=lines, warnings=warnings, route_resolution=route_resolution)

    def active(line):
        events.append(('active', line.id))
        return iter(line.candidates)

    def resolve(path):
        events.append(('resolve', path))
        return '' if path == 'unresolved' else 'runtime/' + path

    def exists(path):
        events.append(('exists', path))
        return path != 'runtime/missing'

    def duplicate(project, line_id, path):
        events.append(('duplicate', line_id, path))
        return path == 'duplicate'

    def label(project, line, reserved):
        value = 'Scene' if not reserved else f'Scene {len(reserved) + 1}'
        reserved.add(value)
        events.append(('label', line.id, value))
        return value

    callbacks = dict(active_candidates=active, resolve_asset_path=resolve,
                     path_exists=exists, duplicate_exists=duplicate,
                     build_route_label=label, line_base_label=lambda line: line.id)
    callbacks.update(overrides)
    result = preview.build_candidate_route_creation_preview(
        project, 'selected_lines', resolution, example_limit=example_limit, **callbacks)
    assert result['warnings'] is warnings
    assert result['route_resolution'] is route_resolution
    return result, events


def test_counts_order_path_normalization_and_no_project_mutation():
    lines = [NS(id='empty', candidates=[]),
             NS(id='a', current_index=0, original_index=9,
                candidates=['', 'unresolved', 'missing', 'duplicate', r'images\a.png',
                            {'path': 'b.png', 'seed': 0}]),
             NS(id='b', original_index=7, candidates=['b.png'])]
    before = deepcopy(lines)
    result, events = run_plan(lines)
    assert vars(lines[0]) == vars(before[0])
    assert [vars(line) for line in lines] == [vars(line) for line in before]
    assert {k: result[k] for k in ('scope', 'target_line_count', 'candidate_line_count',
        'route_count', 'add_line_count', 'skip_count', 'missing_count',
        'duplicate_count', 'no_candidate_count')} == dict(
        scope='selected_lines', target_line_count=3, candidate_line_count=2,
        route_count=2, add_line_count=3, skip_count=5, missing_count=3,
        duplicate_count=1, no_candidate_count=1)
    assert result['examples'] == [dict(line_id='a', display_id='a', line_index=0,
        route_label='Scene', candidate_count=2, candidate_paths=['images/a.png', 'b.png']),
        dict(line_id='b', display_id='b', line_index=7, route_label='Scene 2',
             candidate_count=1, candidate_paths=['b.png'])]
    assert events[:10] == [('active', 'empty'), ('active', 'a'), ('resolve', ''),
        ('resolve', 'unresolved'), ('resolve', 'missing'), ('exists', 'runtime/missing'),
        ('resolve', 'duplicate'), ('exists', 'runtime/duplicate'),
        ('duplicate', 'a', 'duplicate'), ('resolve', 'images/a.png')]


@pytest.mark.parametrize('limit, count', [(0, 0), (-1, 0), (1, 1), (8, 2)])
def test_example_limit_does_not_limit_planning_or_label_reservation(limit, count):
    lines = [NS(id='same', candidates=['p'] * 6)] * 2
    result, events = run_plan(lines, example_limit=limit)
    assert result['add_line_count'] == 12  # No new intra-preview deduplication.
    assert result['target_line_count'] == 2
    assert result['route_count'] == 2
    assert len(result['examples']) == count
    assert [e for e in events if e[0] == 'label'] == [
        ('label', 'same', 'Scene'), ('label', 'same', 'Scene 2')]
    if count:
        assert result['examples'][0]['candidate_paths'] == ['p'] * 4
        assert result['examples'][0]['candidate_count'] == 6


def test_metadata_is_still_evaluated_for_every_valid_candidate_with_no_examples(monkeypatch):
    seen = []
    monkeypatch.setattr(preview, '_candidate_metadata_caption', lambda c: seen.append(c))
    record = {'path': 'ok', 'seed': 0}
    result, _ = run_plan([NS(id='a', candidates=['missing', 'duplicate', record])], example_limit=0)
    assert result['examples'] == []
    assert seen == [record]
    assert seen[0] is record


def test_callback_exception_propagates_without_wrapping():
    error = OSError('asset lookup failed')
    def fail(path):
        raise error
    with pytest.raises(OSError) as caught:
        run_plan([NS(id='a', candidates=['ok'])], resolve_asset_path=fail)
    assert caught.value is error


def test_empty_resolution_and_optional_route_resolution():
    warnings = []
    result = preview.build_candidate_route_creation_preview(
        NS(), 'unknown', dict(target_lines=[], warnings=warnings),
        **dict.fromkeys(['active_candidates', 'resolve_asset_path', 'path_exists',
                         'duplicate_exists', 'build_route_label', 'line_base_label']))
    assert result['warnings'] is warnings
    assert result['route_resolution'] is None
    assert result['target_line_count'] == result['skip_count'] == 0
    assert result['examples'] == []
