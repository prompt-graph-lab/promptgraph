import copy
import pytest
from core.project import Project, PromptLine
from core.parser import parse_prompt
from core.operations import preview_module_candidates, preview_module_swap, preview_create_module_replace, scan_global_module_candidates
from core.module_candidate_apply import build_module_candidate_apply_plan, apply_reviewed_module_candidates
from core.agent_facade import preview_scene_module_swap

TEXT = '  pose phrase. fictional character name,  scene detail,  '
def project(text=TEXT):
    line = PromptLine(id='line', original_file_name='synthetic.txt', original_index=1, current_index=1, original_text=text, current_text=text, tokens=parse_prompt(text), negative_prompt='keep negative', image_path='keep.png', generated_candidates=[{'id':'keep'}])
    scene = PromptLine(id='scene', original_file_name='synthetic.txt', original_index=0, current_index=0, original_text='Scene', current_text='Scene', tokens=[], line_type='separator', separator_label='Scene')
    return Project(prompt_lines=[scene,line], module_library={'Source':{'body':'fictional character name','core_tokens':['fictional character name']}, 'Target':{'body':'replacement character'}})

def test_candidate_detection_legacy_tokens():
    p=project(); before=copy.deepcopy(p)
    assert preview_module_candidates(p,'Source')['total_candidate_count']==1
    assert scan_global_module_candidates(p, {'Source':p.module_library['Source']})['results'][0]['core_match_line_count']==1
    assert p.prompt_lines[1].tokens==before.prompt_lines[1].tokens

def test_reviewed_candidate_apply():
    p=project(); plan, preview=build_module_candidate_apply_plan(p,'Source',core_tokens=['fictional character name'],min_match_tokens=1)
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']==TEXT.replace('pose phrase. fictional character name','pose phrase, <mod:Source>')
    result=apply_reviewed_module_candidates(p,plan,module_name='Source',core_tokens=['fictional character name'],min_match_tokens=1)
    assert result.applied
    assert result.project.prompt_lines[1].negative_prompt=='keep negative'
    assert result.project.prompt_lines[1].generated_candidates==p.prompt_lines[1].generated_candidates
    assert p.prompt_lines[1].current_text==TEXT

def test_create_bind():
    preview=preview_create_module_replace(project(),'Created','fictional character name',token_targets=['fictional character name'])
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']==TEXT.replace('pose phrase. fictional character name','pose phrase, <mod:Created>')

@pytest.mark.parametrize('mode',['strict','loose'])
def test_body_swap(mode):
    preview=preview_module_swap(project(),'Source','Target',match_mode=mode)
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']==TEXT.replace('fictional character name','replacement character')

def test_reference_swap():
    text=TEXT.replace('fictional character name','<mod:Source>')
    preview=preview_module_swap(project(text),'Source','Target')
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']==text.replace('pose phrase. <mod:Source>','pose phrase, <mod:Target>')

def test_h1_period_preview_deterministic():
    p=project(); request=dict(scene_id='scene',source_module_name='Source',target_module_name='Target',match_mode='strict')
    preview=preview_scene_module_swap(p,request)
    assert preview==preview_scene_module_swap(p,request)
    assert preview['changed_count']==1
    assert preview['review_rows'][0]['after_positive_prompt']['text']==TEXT.replace('fictional character name','replacement character')

from core.operations import module_operation_tokens, _parse_prompt_for_module_preset, apply_create_module_replace, apply_module_swap, preview_replace_with_module
from core.global_module_candidate_apply import build_global_module_candidate_apply_plan, apply_reviewed_global_module_candidates

@pytest.mark.parametrize('text', [
    'pose 1.25. fictional character name, detail',
    '(detail:1.25). fictional character name, detail',
    'https://example.com. fictional character name, detail',
    'example.com. fictional character name, detail',
    'v2.1. fictional character name, detail',
    'image.png. fictional character name, detail',
    'Dr. Name, fictional character name',
    'dr. fictional character name, detail',
    'e.g. fictional character name, detail',
    '(pose phrase. fictional character name), detail',
    '[red, pose phrase. fictional character name], detail',
    '{red, pose phrase. fictional character name}, detail',
    '<mod:A>pose phrase. fictional character name</mod:A>, detail',
    '<mod:A>, pose phrase. fictional character name, </mod:A>, detail',
    '<mod:A>, pose phrase. fictional character name, </mod:B>, detail',
    '<mod:A>, pose phrase. fictional character name, detail',
    '<mod:A><mod:B>pose phrase. fictional character name</mod:B></mod:A>, detail',
    'She is sitting. fictional character name, detail',
    'she is sitting. fictional character name, detail',
    'pose phrase. Fictional Character Name, detail',
    'pose phrase. fictional character name',
    'pose phrase... fictional character name, detail',
])
def test_lexical_exclusions_are_unchanged(text):
    assert module_operation_tokens(text)==_parse_prompt_for_module_preset(text)

def test_global_reviewed_apply_and_no_entity_decoding():
    p=project(TEXT+'&#x20;'); p.module_library.pop('Source')
    library={'Source':{'body':'fictional character name','core_tokens':['fictional character name']}}
    plan, preview=build_global_module_candidate_apply_plan(p,library,['Source'])
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']==(TEXT+'&#x20;').replace('pose phrase. fictional character name','pose phrase, <mod:Source>')
    result=apply_reviewed_global_module_candidates(p,library,plan)
    assert result.applied
    assert result.project.prompt_lines[1].current_text.endswith('&#x20;')

@pytest.mark.parametrize('operation',['candidate','create','swap','replace'])
def test_applied_tokens_retain_legacy_shape_and_unrelated_state(operation):
    p=project()
    from core.operations import normalize_module_library
    normalize_module_library(p)
    before=copy.deepcopy(p)
    if operation=='candidate':
        plan,_=build_module_candidate_apply_plan(p,'Source',core_tokens=['fictional character name'],min_match_tokens=1)
        p=apply_reviewed_module_candidates(p,plan,module_name='Source',core_tokens=['fictional character name'],min_match_tokens=1).project
    elif operation=='create':
        p=apply_create_module_replace(p,'Created','fictional character name',token_targets=['fictional character name'])
    elif operation=='swap':
        p=apply_module_swap(p,'Source','Target')
    else:
        from core.operations import apply_replace_with_module
        p=apply_replace_with_module(p,'Source',token_targets=['fictional character name'])
    line=p.prompt_lines[1]; old=before.prompt_lines[1]
    assert line.current_text!=old.current_text
    assert line.tokens==_parse_prompt_for_module_preset(line.current_text)
    assert line.tokens[0].startswith('pose phrase. ') if operation=='swap' else line.tokens[0]=='pose phrase'
    for field in ['negative_prompt','image_path','generated_candidates','gallery_variants','source_generation_info','lineage_info']:
        assert getattr(line,field)==getattr(old,field)
    assert p.module_library['Target']==before.module_library['Target']

def test_ordinary_parser_and_saved_round_trip_are_not_projected(tmp_path):
    from core.io import save_project_to_json, load_project_from_json
    p=project(); original_tokens=copy.deepcopy(p.prompt_lines[1].tokens)
    assert original_tokens==['pose phrase. fictional character name','scene detail']
    assert module_operation_tokens(TEXT)==['pose phrase','fictional character name','scene detail']
    path=tmp_path/'synthetic.json'; save_project_to_json(p,str(path)); loaded=load_project_from_json(str(path))
    assert loaded.prompt_lines[1].tokens==original_tokens
    assert loaded.prompt_lines[1].current_text==TEXT

def test_lossy_cross_period_multi_token_rewrite_refuses():
    from core.operations import preview_apply_module_candidates
    p=project(); p.module_library['Source']['body']='pose phrase, fictional character name'
    preview=preview_apply_module_candidates(p,'Source',core_tokens=['fictional character name'],min_match_tokens=1)
    assert preview['affected_line_count']==0
    assert preview['skipped_existing_module_block_count']==1
    assert p.prompt_lines[1].current_text==TEXT

def test_existing_whole_period_token_rules_and_selection_remain_usable():
    p=project(); whole='pose phrase. fictional character name'
    p.module_library['Source']={'body':whole,'core_tokens':[whole]}
    preview=preview_module_candidates(p,'Source')
    assert preview['total_candidate_count']==1
    plan,preview=build_module_candidate_apply_plan(p,'Source',core_tokens=[whole],min_match_tokens=1)
    assert preview['examples'][0]['after']=='  <mod:Source>,  scene detail,  '
    assert preview_create_module_replace(p,'Created',whole,token_targets=[whole])['examples'][0]['after']=='  <mod:Created>,  scene detail,  '
    assert preview_module_swap(p,'Source','Target')['examples'][0]['after']=='  replacement character,  scene detail,  '

def test_actual_create_bind_selector_and_full_literal_preview_wiring():
    import ast
    from pathlib import Path
    from core.operations import get_project_module_library, get_available_modules
    source=Path('app.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='module_replace_target_options')
    namespace=dict(get_project_module_library=get_project_module_library,get_available_modules=get_available_modules)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),namespace)
    options=namespace['module_replace_target_options'](project())
    assert 'token::fictional character name' in options
    assert 'token::pose phrase. fictional character name' in options
    grouped=project('[red, blue], detail')
    grouped_options=namespace['module_replace_target_options'](grouped)
    assert 'token::[red, blue]' in grouped_options
    assert 'token::[red' not in grouped_options
    grouped.prompt_lines[1].tokens=[]
    assert not any(key.startswith('token::') for key in namespace['module_replace_target_options'](grouped))
    # Verify the actual mutation review call sites render full literal prompts
    # and request all rows instead of the old 5/50-row examples.
    for name in ['preview_create_module_replace','preview_replace_with_module','build_module_candidate_apply_plan','build_global_module_candidate_apply_plan','preview_module_swap']:
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id==name]
        assert calls and all(any(kw.arg=='example_limit' and ast.unparse(kw.value)=='len(project.prompt_lines)' for kw in call.keywords) for call in calls)

def test_h1_contract_identity_digest_and_persisted_projection_shape():
    from core.agent_facade import _digest
    p=project(); before=copy.deepcopy(p)
    result=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target'))
    assert result['contract_version']=='promptgraph.agent-facade.v1'
    assert result['operation']=='scene_module_swap'
    assert result['prompt_only'] is True
    assert result['target_ids']==['line']
    assert result['target_count']==result['changed_count']==1
    assert result['plan_id']==_digest({k:v for k,v in result.items() if k!='plan_id'})
    assert p==before

@pytest.mark.parametrize('body',['[red, blue]','{red, blue}','(red, blue:1.25)'])
def test_grouped_comma_only_module_rules_keep_original_parser_contract(body):
    from core.operations import _module_rule_tokens
    assert _module_rule_tokens(body)==parse_prompt(body)==[body]
    p=project('fictional character name, scene detail')
    p.module_library['Target']={'body':body}
    preview=preview_module_swap(p,'Source','Target')
    assert preview['examples'][0]['after_tokens']==[body,'scene detail']

def test_ambiguous_period_segment_preserves_unrelated_whitespace_on_valid_comma_target():
    text='  She is sitting. nearby,  fictional character name, scene detail,  '
    p=project(text)
    assert module_operation_tokens(text)==_parse_prompt_for_module_preset(text)
    preview=preview_module_swap(p,'Source','Target')
    assert preview['examples'][0]['after']==text.replace('fictional character name','replacement character')
    plan,preview=build_module_candidate_apply_plan(p,'Source',core_tokens=['fictional character name'],min_match_tokens=1)
    assert preview['examples'][0]['after']==text.replace('fictional character name','<mod:Source>')
    preview=preview_create_module_replace(p,'Created','fictional character name',token_targets=['fictional character name'])
    assert preview['examples'][0]['after']==text.replace('fictional character name','<mod:Created>')

@pytest.mark.parametrize('body',['[red, blue]','{red, blue}'])
def test_empty_stored_tokens_keep_distinct_local_and_global_legacy_fallback(body):
    p=project(body); p.prompt_lines[1].tokens=[]
    p.module_library['Source']={'body':body,'core_tokens':[body]}
    assert preview_module_candidates(p,'Source')['total_candidate_count']==0
    scan=scan_global_module_candidates(p,{'Source':p.module_library['Source']})
    assert scan['results'][0]['core_match_line_count']==1
    assert p.prompt_lines[1].tokens==[]

@pytest.mark.parametrize('group',['[red, blue]','{red, blue}'])
def test_accepted_period_preserves_group_candidates_and_actual_selector(group):
    import ast
    from pathlib import Path
    from core.operations import module_candidate_line_tokens, get_project_module_library, get_available_modules
    text='pose phrase. fictional character name, '+group
    p=project(text)
    p.module_library['Grouped']={'body':group,'core_tokens':[group]}
    expected=['pose phrase','fictional character name',group]
    assert module_operation_tokens(text)==expected
    assert group in module_candidate_line_tokens(p.prompt_lines[1])
    assert '[red' not in module_candidate_line_tokens(p.prompt_lines[1])
    assert '{red' not in module_candidate_line_tokens(p.prompt_lines[1])
    assert 'blue]' not in module_candidate_line_tokens(p.prompt_lines[1])
    assert 'blue}' not in module_candidate_line_tokens(p.prompt_lines[1])
    assert preview_module_candidates(p,'Grouped')['total_candidate_count']==1
    scan=scan_global_module_candidates(p,{'Grouped':p.module_library['Grouped']})
    assert scan['results'][0]['core_match_line_count']==1
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='module_replace_target_options')
    namespace=dict(get_project_module_library=get_project_module_library,get_available_modules=get_available_modules)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),namespace)
    options=namespace['module_replace_target_options'](p)
    assert 'token::'+group in options
    assert 'token::fictional character name' in options
    assert 'token::pose phrase. fictional character name' in options
    assert not any(key in options for key in ['token::[red','token::{red','token::blue]','token::blue}'])
    assert preview_create_module_replace(p,'Created',group,token_targets=[group])['examples'][0]['after']==text.replace(group,'<mod:Created>')
    assert preview_module_swap(p,'Source','Target')['examples'][0]['after']==text.replace('fictional character name','replacement character')


def test_selector_preserves_whole_period_token_before_valid_unrelated_reference():
    import ast
    from pathlib import Path
    from core.operations import get_project_module_library, get_available_modules
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='module_replace_target_options')
    namespace=dict(get_project_module_library=get_project_module_library,get_available_modules=get_available_modules)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),namespace)
    text='pose phrase. fictional character name, <mod:Quality>, detail'
    p=project(text); p.module_library['Quality']={'body':'high quality'}
    options=namespace['module_replace_target_options'](p)
    assert 'token::pose phrase. fictional character name' in options
    assert 'token::fictional character name' in options
    # An identical word outside a protected range must not leak an old whole
    # token from inside that range through a string-only union.
    p=project('<mod:A>, pose phrase. fictional character name, </mod:A>, pose phrase. other name, detail')
    options=namespace['module_replace_target_options'](p)
    assert 'token::pose phrase. fictional character name' not in options
    assert 'token::pose phrase. other name' in options
    assert 'token::other name' in options


def test_valid_preceding_reference_has_documented_conservative_projection_limit():
    text='<mod:Quality>, pose phrase. fictional character name, detail'
    p=project(text); p.module_library['Quality']={'body':'high quality'}
    assert module_operation_tokens(text)==_parse_prompt_for_module_preset(text)
    assert preview_module_candidates(p,'Source')['total_candidate_count']==0
    assert preview_module_swap(p,'Source','Target')['affected_line_count']==0
    assert p.prompt_lines[1].current_text==text


def test_no_comma_period_does_not_activate_or_replace_stale_selector_tokens():
    import ast
    from pathlib import Path
    from core.module_period_projection import project_period_spans, projected_selection_tokens
    from core.operations import get_project_module_library, get_available_modules
    text='pose phrase. fictional character name'
    p=project(text)
    p.prompt_lines[1].tokens=['stored choice']
    legacy=_parse_prompt_for_module_preset(text)
    assert project_period_spans(text,legacy)[1] is False
    assert projected_selection_tokens(text,legacy,['stored choice'])==['stored choice']
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='module_replace_target_options')
    namespace=dict(get_project_module_library=get_project_module_library,get_available_modules=get_available_modules)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),namespace)
    options=namespace['module_replace_target_options'](p)
    assert 'token::stored choice' in options
    assert 'token::'+text not in options
    assert 'token::fictional character name' not in options


@pytest.mark.parametrize('mode',['strict','loose'])
def test_whole_period_body_plus_reference_keeps_reference_precedence_and_h1(mode):
    text='pose phrase. fictional character name, <mod:Source>, detail'
    p=project(text)
    p.module_library['Source']={'body':'pose phrase. fictional character name',
                                'core_tokens':['pose phrase. fictional character name']}
    expected=text.replace('<mod:Source>','<mod:Target>')
    preview=preview_module_swap(p,'Source','Target',match_mode=mode)
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['swap_kind']=='reference'
    assert preview['examples'][0]['after']==expected
    h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target',match_mode=mode))
    assert h1['changed_count']==1
    assert h1['review_rows'][0]['after_positive_prompt']['text']==expected


def test_reference_rewrite_refusal_never_falls_through_to_body_swap(monkeypatch):
    import core.operations as operations
    text='pose phrase. fictional character name, <mod:Source>, detail'
    p=project(text)
    p.module_library['Source']={'body':'pose phrase. fictional character name',
                                'core_tokens':['pose phrase. fictional character name']}
    original=operations._rewrite_module_operation_tokens
    refused=[]
    def refuse_reference(before,after_tokens,before_tokens=None):
        if '<mod:Target>' in after_tokens:
            refused.append(tuple(after_tokens))
            return None
        return original(before,after_tokens,before_tokens)
    # Simulate the lossless source-span owner refusing a reference transform;
    # a body replacement would still be possible, so this proves precedence.
    monkeypatch.setattr(operations,'_rewrite_module_operation_tokens',refuse_reference)
    preview=preview_module_swap(p,'Source','Target')
    assert refused
    assert preview['affected_line_count']==0
    assert preview['examples']==[]
    h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target'))
    assert h1['changed_count']==0
    assert h1['review_rows'][0]['after_positive_prompt']['text']==text
    assert p.prompt_lines[1].current_text==text


def test_mixed_disjoint_whole_and_fragment_creation_refuses_subset_apply():
    text='pose phrase. fictional character name, outfit pose. colored dress, scene detail'
    p=project(text)
    targets=['pose phrase. fictional character name','colored dress']
    preview=preview_create_module_replace(p,'Created','new character',token_targets=targets)
    assert preview['affected_line_count']==0
    assert preview['skipped_malformed_count']==1
    assert preview['examples']==[]
    replace_preview=preview_replace_with_module(p,'Target',token_targets=targets)
    assert replace_preview['affected_line_count']==0
    assert replace_preview['skipped_malformed_count']==1
    applied=apply_create_module_replace(p,'Created','new character',token_targets=targets)
    assert applied.prompt_lines[1].current_text==text

@pytest.mark.parametrize('fragment',['pose phrase','fictional character name','outfit detail'])
@pytest.mark.parametrize('operation',['candidate','create','replace','reference'])
def test_reference_binding_is_independent_persisted_and_toggleable(fragment,operation):
    from core.operations import get_active_tokens, apply_replace_with_module
    from core.parser import extract_mod_info
    text='pose phrase. fictional character name. outfit detail, scene detail'
    p=project(text)
    p.module_library['Source']={'body':fragment,'core_tokens':[fragment]}
    name='Created' if operation=='create' else ('Target' if operation=='reference' else 'Source')
    if operation=='candidate':
        plan,preview=build_module_candidate_apply_plan(p,'Source',core_tokens=[fragment],min_match_tokens=1)
        result=apply_reviewed_module_candidates(p,plan,module_name='Source',core_tokens=[fragment],min_match_tokens=1)
        assert result.applied
        p=result.project
    elif operation=='create':
        preview=preview_create_module_replace(p,name,fragment,token_targets=[fragment])
        p=apply_create_module_replace(p,name,fragment,token_targets=[fragment])
    elif operation=='replace':
        preview=preview_replace_with_module(p,name,token_targets=[fragment])
        p=apply_replace_with_module(p,name,token_targets=[fragment])
    else:
        text=text.replace(fragment,'<mod:Source>')
        p=project(text); p.module_library['Source']={'body':fragment,'core_tokens':[fragment]}
        preview=preview_module_swap(p,'Source','Target')
        h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target'))
        if not preview['affected_line_count']:
            assert preview['skipped_no_match_count']==1
            assert h1['changed_count']==0
            assert apply_module_swap(p,'Source','Target').prompt_lines[1].current_text==text
            return
        assert h1['review_rows'][0]['after_positive_prompt']['text']==preview['examples'][0]['after']
        p=apply_module_swap(p,'Source','Target')
    line=p.prompt_lines[1]
    assert preview['examples'][0]['before']==text
    assert preview['examples'][0]['after']==line.current_text
    marker='<mod:'+name+'>'
    expected=text.replace('<mod:Source>' if operation=='reference' else fragment,marker)
    expected=expected.replace('. '+marker,', '+marker).replace(marker+'. ',marker+', ')
    assert line.current_text==expected
    assert marker in line.tokens
    assert extract_mod_info(marker)['type']=='open'
    active=get_active_tokens(line,module_library=p.module_library)
    from core.comfy_generation_prompt import prepare_generation_injection_line
    injected=prepare_generation_injection_line(line,set(),fallback_prompt='',module_library=p.module_library)
    assert injected.current_text==', '.join(active)
    assert '<mod:' not in injected.current_text
    disabled=get_active_tokens(line,disabled_modules={name},module_library=p.module_library)
    body='replacement character' if operation=='reference' else fragment
    assert body in active and body not in disabled
    assert not any('<mod:' in token for token in active+disabled)
    for other in ['pose phrase','fictional character name','outfit detail']:
        if other!=fragment:
            assert any(other in token for token in disabled)
    if name!='Target':
        swapped=apply_module_swap(p,name,'Target')
        assert '<mod:Target>' in swapped.prompt_lines[1].tokens
        assert marker not in swapped.prompt_lines[1].tokens
        assert 'replacement character' in get_active_tokens(swapped.prompt_lines[1],module_library=swapped.module_library)

@pytest.mark.parametrize('explicit',[True,False])
def test_comma_bearing_legacy_body_strict_swap_and_reviewed_candidate(explicit):
    from core.operations import normalize_module_library
    whole='pose phrase. fictional character name'
    p=project(whole+', red eyes, background')
    p.module_library['Source']={'body':whole+', red eyes'}
    if explicit:
        p.module_library['Source']['core_tokens']=[whole]
    normalize_module_library(p)
    assert p.module_library['Source']['core_tokens']==[whole]
    assert p.module_library['Source']['min_match_tokens']==2
    before=copy.deepcopy(p.module_library)
    preview=preview_module_swap(p,'Source','Target',match_mode='strict')
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']=='replacement character, background'
    assert preview_module_candidates(p,'Source')['module_tokens']==[whole,'red eyes']
    plan,preview=build_module_candidate_apply_plan(p,'Source',core_tokens=[whole],min_match_tokens=2)
    assert preview['affected_line_count']==1
    result=apply_reviewed_module_candidates(p,plan,module_name='Source',core_tokens=[whole],min_match_tokens=2)
    assert result.applied
    assert result.project.prompt_lines[1].tokens==['<mod:Source>','background']
    assert p.module_library==before


def test_authored_fragment_rules_and_legacy_whole_rules_stay_distinct_and_fresh():
    from core.operations import create_library_module, normalize_module_library, set_module_candidate_rules, get_module_min_match_tokens
    whole='pose phrase. fictional character name'
    body=whole+', red eyes'
    p=project(body+', fictional character name, background')
    assert create_library_module(p,'Authored',body)
    normalize_module_library(p)
    assert p.module_library['Authored']['core_tokens']==['pose phrase']
    assert p.module_library['Authored']['min_match_tokens']==3
    assert preview_module_candidates(p,'Authored')['module_tokens']==['pose phrase','fictional character name','red eyes']
    assert set_module_candidate_rules(p,'Authored',[whole],99)
    assert get_module_min_match_tokens(p,'Authored')==2
    plan,preview=build_module_candidate_apply_plan(p,'Authored',core_tokens=[whole],min_match_tokens=2)
    assert preview['examples'][0]['after']=='<mod:Authored>, fictional character name, background'
    assert set_module_candidate_rules(p,'Authored',['fictional character name'],3)
    result=apply_reviewed_module_candidates(p,plan,module_name='Authored',core_tokens=['fictional character name'],min_match_tokens=3)
    assert not result.applied and result.stale
    assert p.prompt_lines[1].current_text==body+', fictional character name, background'


def test_legacy_whole_candidate_global_and_duplicate_reference_safety():
    from core.operations import normalize_module_library, get_active_tokens
    whole='pose phrase. fictional character name'
    p=project(whole+', red eyes, '+whole+', background')
    library={'Legacy':{'body':whole+', red eyes','core_tokens':[whole]}}
    normalize_module_library(p)
    before=copy.deepcopy(p.module_library)
    assert scan_global_module_candidates(p,library)['results'][0]['core_match_line_count']==1
    plan,preview=build_global_module_candidate_apply_plan(p,library,['Legacy'])
    assert preview['affected_line_count']==1
    result=apply_reviewed_global_module_candidates(p,library,plan)
    assert result.applied
    assert result.project.prompt_lines[1].tokens==['<mod:Legacy>','background']
    assert get_active_tokens(result.project.prompt_lines[1],disabled_modules={'Legacy'},module_library=result.project.module_library)==['background']
    assert p.module_library==before

@pytest.mark.parametrize('mode',['strict','loose'])
def test_mixed_persisted_core_rules_refuse_all_body_paths(mode):
    from core.operations import normalize_module_library, preview_apply_module_candidates, apply_module_candidates, preview_apply_detected_modules
    whole='pose phrase. fictional character name'
    body=whole+', outfit pose. colored dress, red eyes'
    text=whole+', different outfit. colored dress, red eyes, background'
    p=project(text)
    p.module_library['Source']={'body':body,'core_tokens':[whole,'colored dress'],'min_match_tokens':2}
    normalize_module_library(p)
    before=copy.deepcopy(p)
    library={'Source':copy.deepcopy(p.module_library['Source'])}
    library_before=copy.deepcopy(library)
    local=preview_module_candidates(p,'Source')
    assert local['total_candidate_count']==0
    assert local['rule_conflict']
    apply_preview=preview_apply_module_candidates(p,'Source')
    assert apply_preview['affected_line_count']==0 and apply_preview['rule_conflict']
    plan,preview=build_module_candidate_apply_plan(p,'Source',core_tokens=[whole,'colored dress'],min_match_tokens=2)
    assert preview['affected_line_count']==0
    assert not apply_reviewed_module_candidates(p,plan,module_name='Source',core_tokens=[whole,'colored dress'],min_match_tokens=2).applied
    assert apply_module_candidates(p,'Source')==before
    scan=scan_global_module_candidates(p,library,min_core_match_lines=0)
    assert scan['results']==[] and scan['rule_conflicts']==['Source']
    global_plan,global_preview=build_global_module_candidate_apply_plan(p,library,['Source'])
    assert global_preview['affected_line_count']==0 and global_preview['rule_conflicts']==['Source']
    assert not apply_reviewed_global_module_candidates(p,library,global_plan).applied
    swap=preview_module_swap(p,'Source','Target',match_mode=mode)
    assert swap['affected_line_count']==0 and swap['rule_conflict']
    assert apply_module_swap(p,'Source','Target',match_mode=mode)==before
    h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target',match_mode=mode))
    assert h1['valid'] is False
    assert h1['reason']=='incompatible_module_core_rules'
    assert h1['diagnostics']==[{'code':'incompatible_module_core_rules'}]
    assert h1['changed_count']==0
    assert h1['review_rows']==[]
    assert p==before and library==library_before


@pytest.mark.parametrize('mode',['strict','loose'])
def test_mixed_body_rules_preserve_explicit_reference_precedence_and_h1_diagnostic(mode):
    whole='pose phrase. fictional character name'
    p=project(whole+', different outfit. colored dress, red eyes, <mod:Source>, background')
    p.module_library['Source']={'body':whole+', outfit pose. colored dress, red eyes',
                                'core_tokens':[whole,'colored dress'],'min_match_tokens':2}
    text=p.prompt_lines[1].current_text
    preview=preview_module_swap(p,'Source','Target',match_mode=mode)
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['swap_kind']=='reference'
    assert preview['examples'][0]['after']==text.replace('<mod:Source>','<mod:Target>')
    h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target',match_mode=mode))
    assert h1['valid'] is True and h1['reason']=='' and h1['changed_count']==1
    assert h1['diagnostics']==[{'code':'incompatible_module_core_rules'}]
    assert h1['review_rows'][0]['after_positive_prompt']['text']==text.replace('<mod:Source>','<mod:Target>')

@pytest.mark.parametrize('mode',['strict','loose'])
def test_mixed_target_rules_refuse_body_materialization_but_allow_reference_swap(mode):
    whole='pose phrase. fictional character name'
    p=project('fictional character name, background')
    p.module_library['Target']={'body':whole+', outfit pose. colored dress, red eyes',
                                'core_tokens':[whole,'colored dress'],'min_match_tokens':2}
    preview=preview_module_swap(p,'Source','Target',match_mode=mode)
    assert preview['affected_line_count']==0 and preview['rule_conflict']
    h1=preview_scene_module_swap(p,dict(scene_id='scene',source_module_name='Source',target_module_name='Target',match_mode=mode))
    assert h1['valid'] is False and h1['reason']=='incompatible_module_core_rules'
    p.prompt_lines[1].current_text='<mod:Source>, background'
    p.prompt_lines[1].tokens=['<mod:Source>','background']
    preview=preview_module_swap(p,'Source','Target',match_mode=mode)
    assert preview['affected_line_count']==1
    assert preview['examples'][0]['after']=='<mod:Target>, background'
