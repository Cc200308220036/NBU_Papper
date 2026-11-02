"""Expansion guards and explicit user-authorized developer review; fixtures only."""
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.memory_store import MemoryStore,load_snapshot
from semantic_pallet_planner.jev_select.memory_generation import prepare_generation,validate_prepared,run_generation_batch
from semantic_pallet_planner.jev_select.memory_validation import (register_review_authorization,developer_review_template,
    import_review,freeze_generation,review_materials,eligible)
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b2_v2 import export2,prop2,setup
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b2a import response


def batch_setup(root,first='reject'):
    for i in range(2):
        e=export2();e['episode_id']=f'fixture_episode_{i}';MemoryStore(root/'source').ingest(e)
    prepare_generation(root/'source',root/'prepared',mode='offline_fixture',protocol='v3')
    requests=validate_prepared(root/'prepared')[2];ids=sorted(requests);fixtures={}
    for index,key in enumerate(ids):
        p=prop2(requests[key]);cards=[p]
        if index==0 and first=='reject':p['advice']+=' O0001'
        if index==0 and first=='empty':cards=[]
        write(root/f'{index}.json',response({'version':'jev_generation_output_v2','cards':cards}));fixtures[key]=root/f'{index}.json'
    return ids,fixtures


def test_rejection_stops_before_next_episode_reservation_and_resume(tmp_path,monkeypatch):
    ids,fixtures=batch_setup(tmp_path);args=(tmp_path/'prepared',ids,tmp_path/'store',tmp_path/'batch')
    result=run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures)
    assert result['status']=='STOP_TECHNICAL_REJECTION' and len(result['completed'])==1
    assert result['remaining_requests']==ids[1:]
    assert len(read(tmp_path/'store/generation_accounting_fixture/episode_claims.json'))==1
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('send after stop'))
    assert run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures,resume=True)==result
    assert not (tmp_path/'store/generation/processed'/f'{ids[1]}.json').exists()


@pytest.mark.parametrize('first',['valid','empty'])
def test_valid_and_empty_outputs_can_advance_without_semantic_acceptance(tmp_path,first):
    ids,fixtures=batch_setup(tmp_path,first)
    result=run_generation_batch(tmp_path/'prepared',ids,tmp_path/'store',tmp_path/'batch',mode='offline_fixture',fixtures=fixtures)
    assert result['status']=='PASS' and len(result['completed'])==2
    assert result['completed'][0]['gate']['original_proposals']==(0 if first=='empty' else 1)
    assert all(read(p)['semantic_review']['status']=='pending' for p in (tmp_path/'store/cards').glob('*.json'))


def test_crash_after_raw_parse_recovers_without_resend(tmp_path,monkeypatch):
    ids,fixtures=batch_setup(tmp_path,'valid');ids=ids[:1];fixtures={ids[0]:fixtures[ids[0]]}
    args=(tmp_path/'prepared',ids,tmp_path/'store',tmp_path/'batch')
    def crash(phase,key):
        if phase=='after_generate':raise SystemExit('simulated process crash')
    with pytest.raises(SystemExit):run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures,hook=crash)
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('duplicate send'))
    assert run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures,resume=True)['status']=='PASS'


def test_resume_refuses_forged_success_state(tmp_path):
    ids,fixtures=batch_setup(tmp_path);args=(tmp_path/'prepared',ids,tmp_path/'store',tmp_path/'batch')
    run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures)
    state=read(tmp_path/'batch/state.json');state.update(status='PASS',completed=[],remaining_requests=ids)
    write(tmp_path/'batch/state.json',state)
    with pytest.raises(JevSelectError,match='batch_state_changed'):
        run_generation_batch(*args,mode='offline_fixture',fixtures=fixtures,resume=True)


def authorization():
    return {'version':'jev_review_authorization_v1','instruction':'Fixture user explicitly delegates semantic review to development agent.',
        'reviewer_mode':'developer_agent','independent_review_required':False,'scope':'semantic_review_role_only',
        'retained_constraints':['two_independent_source_groups','non_rule_restatement','no_unresolved_conflict','compatible_scope',
                                'original_prose_unchanged','existing_budgets','existing_frequency_limits']}


def developer_accept(root,card,auth):
    v=developer_review_template(root/'store',card,auth)
    v.update(reviewer='Codex',reviewed_at='2026-10-31T20:00:00+08:00',status='accepted',reason='Fixture observational support only.',
        source_assessments=[{'source_group_id':'fixture_group','decision':'support','reason':'fixture observations match','claim_and_scope':card['advice']}],
        supported_source_groups=['fixture_group'],checks={key:'confirmed' for key in v['checks']},conflicts_resolved=True,scope_and_advice_compatible=True)
    return v


def test_developer_review_requires_explicit_bound_policy_and_remains_single_source(tmp_path):
    setup(tmp_path);card=read(next((tmp_path/'store/cards').glob('*.json')))
    with pytest.raises(JevSelectError,match='authorization_required'):developer_review_template(tmp_path/'store',card,None)
    write(tmp_path/'authorization.json',authorization());auth=register_review_authorization(tmp_path/'store',tmp_path/'authorization.json')['authorization_digest']
    review_materials(tmp_path/'store',tmp_path/'developer_packet',reviewer_mode='developer_agent',authorization_digest=auth)
    v=developer_accept(tmp_path,card,auth);write(tmp_path/'review.json',v)
    assert import_review(tmp_path/'store',tmp_path/'review.json')['card_status']=='candidate'
    actual=read(next((tmp_path/'store/cards').glob('*.json')))
    assert actual['semantic_review']['independent_review'] is False and not eligible(actual)
    freeze_generation(tmp_path/'store',tmp_path/'frozen')
    assert load_snapshot(tmp_path/'frozen').data['cards'][0]['semantic_review']['reviewer_kind']=='developer_agent'
    p=tmp_path/'frozen/artifacts/review_authorizations'/f'{auth}.json';p.chmod(0o644);write(p,{})
    with pytest.raises(JevSelectError):load_snapshot(tmp_path/'frozen')


def test_authorization_does_not_override_rule_role_or_fabricate_second_source(tmp_path):
    setup(tmp_path);card=read(next((tmp_path/'store/cards').glob('*.json')))
    write(tmp_path/'authorization.json',authorization());auth=register_review_authorization(tmp_path/'store',tmp_path/'authorization.json')['authorization_digest']
    v=developer_accept(tmp_path,card,auth);v['supported_source_groups'].append('fabricated_second_group');write(tmp_path/'review.json',v)
    with pytest.raises(JevSelectError):import_review(tmp_path/'store',tmp_path/'review.json')
    v=developer_accept(tmp_path,card,auth);v['assessed_knowledge_role']='rule_restatement';card['semantic_review']=v
    card['validation']['support_source_groups']=['fixture_group','fixture_group_b'];v['supported_source_groups']=['fixture_group','fixture_group_b']
    assert not eligible(card)


@pytest.mark.parametrize('oversize',[False,True])
def test_corrective_admission_keeps_raw_refusal_and_does_not_relax_budget(tmp_path,oversize,monkeypatch):
    from semantic_pallet_planner.jev_select.memory_generation import generate_candidates,generation_gate
    from semantic_pallet_planner.jev_select.memory_validation import admit_unit_context_correction,validate_store
    e=export2();e['events'][0]['public_feedback']['instances']=[{'kind':'max_top_load','rule_id':'R01','object_ids':['B001'],'severity':{'value':6.01,'unit':'kg'}}]
    MemoryStore(tmp_path/'source').ingest(e)
    prepare_generation(tmp_path/'source',tmp_path/'prepared',mode='offline_fixture',protocol='v2')
    req=next(iter(validate_prepared(tmp_path/'prepared')[2].values()));p=prop2(req)
    p['fact_links']=[{'fact_id':'F0003','path':'/instances/0/severity/value','value':6.01,'value_type':'number','unit':'kg','relation':'support'}]
    if oversize:p['limitations_counterexamples']='x'*1700
    write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[p]}))
    generate_candidates(tmp_path/'prepared',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    gate=generation_gate(tmp_path/'store',req['request_digest']);assert gate['status']=='STOP_TECHNICAL_REJECTION'
    reject=tmp_path/'store/generation/rejections'/f"{req['request_digest']}.json";original_rejection=reject.read_bytes()
    identity=read(reject)['rejected'][0]['card_id'];original=read(tmp_path/'store/originals'/f'{identity}.json')
    write(tmp_path/'authorization.json',authorization());auth=register_review_authorization(tmp_path/'store',tmp_path/'authorization.json')['authorization_digest']
    receipt=admit_unit_context_correction(tmp_path/'store',identity,auth)
    assert reject.read_bytes()==original_rejection
    assert read(tmp_path/'store/originals'/f'{identity}.json')==original
    assert generation_gate(tmp_path/'store',req['request_digest'])==gate
    if oversize:
        assert receipt['status']=='REJECTED' and receipt['reason']=='memory_card_render_budget_exceeded'
        assert not (tmp_path/'store/cards'/f'{identity}.json').exists()
    else:
        assert receipt['status']=='PASS'
        card=read(tmp_path/'store/cards'/f'{identity}.json');assert card['version']=='jev_memory_card_v4'
        assert card['advice']==p['advice'] and card['semantic_review']['status']=='pending'
        monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('repeat send'))
        generate_candidates(tmp_path/'prepared',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
        assert reject.read_bytes()==original_rejection
        assert validate_store(tmp_path/'store')['candidate']==1
        freeze_generation(tmp_path/'store',tmp_path/'frozen');assert load_snapshot(tmp_path/'frozen').data['cards'][0]['version']=='jev_memory_card_v4'


def test_pairwise_compatibility_is_bound_to_current_parents_and_does_not_infer_from_role(tmp_path):
    from semantic_pallet_planner.jev_select.memory_generation import validate_merge_compatibility
    setup(tmp_path);card=read(next((tmp_path/'store/cards').glob('*.json')))
    write(tmp_path/'authorization.json',authorization());auth=register_review_authorization(tmp_path/'store',tmp_path/'authorization.json')['authorization_digest']
    v=developer_accept(tmp_path,card,auth);card['semantic_review']=v
    other={**card,'card_id':'other_fixture_card','content_digest':'f'*64}
    review={'version':'jev_merge_compatibility_v1','reviewer_kind':'developer_agent','authorization_digest':auth,
       'parent_content_digests':{c['card_id']:c['content_digest'] for c in (card,other)},'compatible':False,
       'scope_intersection':'Both observed packing, but different decision predicates.',
       'advice_compatibility':'Same proposed role does not show that contact and load-limit advice are the same claim.',
       'counterexamples_unknowns_preserved':True,'reason':'Unrelated claims must not be merged to manufacture two sources.',
       'reviewed_at':'2026-10-31T20:00:00+08:00'}
    with pytest.raises(JevSelectError,match='semantically_incompatible'):validate_merge_compatibility(review,[card,other],tmp_path/'store')
    review['compatible']=True
    assert validate_merge_compatibility(review,[card,other],tmp_path/'store')==review
    other['content_digest']='e'*64
    with pytest.raises(JevSelectError,match='parent_changed'):validate_merge_compatibility(review,[card,other],tmp_path/'store')


def test_developer_reviewed_compatible_merge_can_activate_two_fixture_sources(tmp_path):
    from semantic_pallet_planner.jev_select.memory_generation import prepare_merge,generate_candidates
    for i in range(4):
        e=export2();e.update(episode_id=f'fixture_episode_{i}',source_group_id=f'fixture_group_{i}')
        MemoryStore(tmp_path/'source').ingest(e)
    prepare_generation(tmp_path/'source',tmp_path/'prepared',mode='offline_fixture',protocol='v3')
    for req in validate_prepared(tmp_path/'prepared')[2].values():
        write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[prop2(req)]}))
        generate_candidates(tmp_path/'prepared',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    write(tmp_path/'authorization.json',authorization());auth=register_review_authorization(tmp_path/'store',tmp_path/'authorization.json')['authorization_digest']
    parents=[read(p) for p in sorted((tmp_path/'store/cards').glob('*.json'))][:2]
    def accept_card(card):
        v=developer_accept(tmp_path,card,auth)
        groups=card['validation']['support_source_groups']
        v.update(supported_source_groups=groups,source_assessments=[{'source_group_id':g,'decision':'support',
           'reason':'Synthetic compatible resource observation','claim_and_scope':card['advice']} for g in groups])
        write(tmp_path/'review.json',v);return import_review(tmp_path/'store',tmp_path/'review.json')
    for parent in parents:assert accept_card(parent)['card_status']=='candidate'
    parents=[read(tmp_path/'store/cards'/f"{p['card_id']}.json") for p in parents]
    compatibility={'version':'jev_merge_compatibility_v1','reviewer_kind':'developer_agent','authorization_digest':auth,
        'parent_content_digests':{p['card_id']:p['content_digest'] for p in parents},'compatible':True,
        'scope_intersection':'Identical synthetic fixture scope','advice_compatibility':'Identical fixture resource comparison',
        'counterexamples_unknowns_preserved':True,'reason':'Only a synthetic affirmative engineering path.',
        'reviewed_at':'2026-10-31T20:00:00+08:00'}
    write(tmp_path/'compatibility.json',compatibility)
    merged=prepare_merge(tmp_path/'prepared',tmp_path/'store',[p['card_id'] for p in parents],tmp_path/'merge',compatibility_file=tmp_path/'compatibility.json')
    request=validate_prepared(tmp_path/'merge')[2][merged['request_digest']]
    import json
    public=json.loads(request['body']['messages'][1]['content'])
    p=prop2(request);p.update(parent_card_ids=[parent['card_id'] for parent in parents],
        fact_links=[link for parent in public['parents'] for link in parent['fact_links']])
    write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[p]}))
    generate_candidates(tmp_path/'merge',request['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    card=next(read(p) for p in (tmp_path/'store/cards').glob('*.json') if read(p)['parent_card_ids'])
    assert card['semantic_review']['status']=='pending'
    assert accept_card(card)['card_status']=='active'
    freeze_generation(tmp_path/'store',tmp_path/'frozen')
    assert sum(c['status']=='active' for c in load_snapshot(tmp_path/'frozen').data['cards'])==1
