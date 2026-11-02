"""Adversarial new-contract tests; all created trajectories/reviews are fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select.contracts import canonical, digest, JevSelectError
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.tests.unit.test_j4_b2a import export_fixture, proposal, response
from semantic_pallet_planner.jev_select.memory_generation import (make_request, summary_input_v2, prepare_generation, validate_prepared, generate_candidates)
from semantic_pallet_planner.jev_select.memory_validation import resolve_fact_links, validate_store, review_materials, import_review, freeze_generation
from semantic_pallet_planner.jev_select.memory_store import MemoryStore, load_snapshot


def export2():
    e=export_fixture();e.update(version='jev_episode_export_v2',object_bindings={'fixture_decision':{'B001':'sealed_box_a'}})
    return e


def prop2(r):
    p=proposal(make_request(export_fixture()))
    del p['evidence_links']
    p['fact_links']=[{'fact_id':'F0002','path':'/features/support_ratio','value':1,'value_type':'integer','unit':'ratio','relation':'support'}]
    return p


def setup(root,p=None):
    e=export2();MemoryStore(root/'source').ingest(e)
    prepare_generation(root/'source',root/'prepared',mode='offline_fixture',protocol='v2')
    r=next(iter(validate_prepared(root/'prepared')[2].values()))
    write(root/'response.json',response({'version':'jev_generation_output_v2','cards':[prop2(r) if p is None else p]}))
    generate_candidates(root/'prepared',r['request_digest'],root/'store',mode='offline_fixture',fixture=root/'response.json')
    return r


def test_old_wire_unchanged_and_unknown_version():
    r=make_request(export_fixture());assert r['version']=='jev_generation_request_v1'
    with pytest.raises(JevSelectError,match='unknown_generation_protocol'):make_request(export_fixture(),protocol='v99')


def test_stable_identity_not_dimensions_or_position():
    e=export2();first=e['events'][0]
    first['public_state']['available_objects'].append({**deepcopy(first['public_state']['available_objects'][0]),'object_id':'B002'})
    e['object_bindings']['fixture_decision']['B002']='sealed_box_b'
    second=deepcopy(first);second['decision_id']='second'
    e['events'].append(second)
    # Same dimensions, aliases swap in second event: identity must follow seal.
    e['object_bindings']['second']={'B001':'sealed_box_b','B002':'sealed_box_a'}
    r=make_request(e,protocol='v2');facts=r['input']['payload']['facts']
    assert [x['object_id'] for x in facts[0]['value']['available_objects']]==['O0001','O0002']
    assert [x['object_id'] for x in facts[3]['value']['available_objects']]==['O0002','O0001']
    wire=canonical(r['body']);assert 'sealed_box' not in wire and 'fixture_decision' not in wire and 'fixture_group' not in wire
    assert r==make_request(deepcopy(e),protocol='v2')
    prefix=summary_input_v2({**e,'events':e['events'][:1]})
    assert prefix['payload']['facts'][:3]==facts[:3]
    del e['object_bindings']['second']['B001']
    with pytest.raises(JevSelectError,match='identity_unresolved'):summary_input_v2(e)


@pytest.mark.parametrize('change',['bool','float','unit','outside','unsent'])
def test_fact_forgery(change):
    r=make_request(export2(),protocol='v2');links=prop2(r)['fact_links']
    if change=='bool':links[0]['value']=True
    if change=='float':links[0]['value']=1.0
    if change=='unit':links[0]['unit']='kg'
    if change=='outside':links[0]['fact_id']='F9999'
    if change=='unsent':links[0]['path']='/candidate_facts/imaginary'
    with pytest.raises(JevSelectError):resolve_fact_links(r,links)


@pytest.mark.parametrize('ident',['E0001','O0001','F0002','B001','R01','J0002','SG_abcdef','EXP_example','C01'])
def test_alias_prose_refused(tmp_path,ident):
    p=prop2(None);p['observed_evidence']+=' '+ident
    setup(tmp_path,p)
    assert not list((tmp_path/'store/cards').glob('*.json'))
    assert read(next((tmp_path/'store/generation/rejections').glob('*.json')))['rejected'][0]['reason']=='memory_card_identifier_leak'
    assert read(next((tmp_path/'store/originals').glob('*.json')))['proposal']==p


def test_pending_realistic_review_freeze_and_recovery(tmp_path,monkeypatch):
    r=setup(tmp_path)
    assert validate_store(tmp_path/'store')['candidate']==1
    c=read(next((tmp_path/'store/cards').glob('*.json')))
    assert c['version']=='jev_memory_card_v3' and c['semantic_review']['version']=='jev_semantic_review_v2'
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('duplicate send'))
    generate_candidates(tmp_path/'prepared',r['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    review_materials(tmp_path/'store',tmp_path/'review')
    assert len(list((tmp_path/'review/source_worksheets').glob('*.json')))==1
    v=deepcopy(c['semantic_review']);v.update(reviewer='fixture_independent_human',status='accepted')
    write(tmp_path/'review.json',v)
    with pytest.raises(JevSelectError,match='declaration_required'):import_review(tmp_path/'store',tmp_path/'review.json')
    v.update(reviewed_at='2026-10-31T10:00:00+08:00',independence_declaration='Fixture only; independent role.',
        source_assessments=[{'source_group_id':'fixture_group','decision':'support','reason':'fixture check','claim_and_scope':c['advice']}],
        supported_source_groups=['fixture_group'],checks={k:'confirmed' for k in v['checks']},conflicts_resolved=True,scope_and_advice_compatible=True)
    write(tmp_path/'review.json',v)
    assert import_review(tmp_path/'store',tmp_path/'review.json')['card_status']=='candidate'
    f=freeze_generation(tmp_path/'store',tmp_path/'frozen')
    assert load_snapshot(tmp_path/'frozen',f['snapshot_digest']).data['cards'][0]['status']=='candidate'
    with pytest.raises(JevSelectError,match='fixture_memory'):load_snapshot(tmp_path/'frozen',remote=True)
    p=next((tmp_path/'frozen/artifacts/originals').glob('*.json'));p.chmod(0o644);write(p,{})
    with pytest.raises(JevSelectError):load_snapshot(tmp_path/'frozen')


def test_r0_columnar_retains_negative_feedback_rules_resources_and_relationships():
    from semantic_pallet_planner.jev_select.memory_export import compact_history_event_v2, expand_history_event_v2
    body={'rules':['complete rule semantics'], 'placed_resources':[{'object_id':f'B{i:03d}','mass_kg':i,'load_kg':i*2,'fragile':False} for i in range(15)],
          'negative_feedback':{'instances':[{'kind':'max_top_load','object_ids':['B001'],'severity':{'value':3,'unit':'kg'}}]},
          'actual_action':{'pick_object':'B001','load_changes':[{'object_id':'B002','after_top_load_kg':10}]},'unknown':['deferred']}
    encoded=compact_history_event_v2(body)
    assert expand_history_event_v2(encoded)==body
    assert encoded==compact_history_event_v2(deepcopy(body))


def accept_fixture(root,card):
    v=deepcopy(card['semantic_review'])
    groups=card['validation']['support_source_groups']
    v.update(reviewer='fixture_independent_human',status='accepted',reviewed_at='2026-10-31T12:00:00+08:00',
        independence_declaration='Synthetic protocol test only; no real human review represented.',
        source_assessments=[{'source_group_id':g,'decision':'support','reason':'fixture check','claim_and_scope':card['advice']} for g in groups],
        supported_source_groups=groups,checks={k:'confirmed' for k in v['checks']},conflicts_resolved=True,scope_and_advice_compatible=True)
    write(root/'fixture_review.json',v);return import_review(root/'store',root/'fixture_review.json')


@pytest.mark.parametrize('split',[False,True])
def test_merge_two_sources_keeps_parent_facts_and_requires_fresh_review(tmp_path,split):
    from semantic_pallet_planner.jev_select.memory_generation import prepare_merge
    for i in range(4):
        e=export2();e.update(episode_id=f'fixture_episode_{i}',source_group_id=f'fixture_group_{i}')
        MemoryStore(tmp_path/('source_extra' if split and i>=2 else 'source')).ingest(e)
    prepare_generation(tmp_path/'source',tmp_path/'prepared',mode='offline_fixture',protocol='v2')
    all_requests=validate_prepared(tmp_path/'prepared')[2]
    extras=[]
    if split:
        prepare_generation(tmp_path/'source_extra',tmp_path/'prepared_extra',mode='offline_fixture',protocol='v2')
        all_requests.update(validate_prepared(tmp_path/'prepared_extra')[2]);extras=[tmp_path/'prepared_extra']
    for r in all_requests.values():
        write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[prop2(r)]}))
        location=tmp_path/'prepared' if (tmp_path/'prepared/requests'/f"{r['request_digest']}.json").exists() else tmp_path/'prepared_extra'
        generate_candidates(location,r['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    parents=[read(p) for p in sorted((tmp_path/'store/cards').glob('*.json'))][:2]
    with pytest.raises(JevSelectError,match='independently_reviewed'):
        prepare_merge(tmp_path/'prepared',tmp_path/'store',[p['card_id'] for p in parents],tmp_path/'bad_merge')
    for p in parents:assert accept_fixture(tmp_path,p)['card_status']=='candidate'
    result=prepare_merge(tmp_path/'prepared',tmp_path/'store',[p['card_id'] for p in parents],tmp_path/'merge',additional_prepared=extras)
    req=validate_prepared(tmp_path/'merge')[2][result['request_digest']]
    user=json.loads(req['body']['messages'][1]['content'])
    assert len(user['parent_requests'])==2 and 'source_group_id' not in canonical(user)
    p=prop2(req);p.update(parent_card_ids=[parent['card_id'] for parent in parents],
                         fact_links=[link for parent in user['parents'] for link in parent['fact_links']])
    write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[p]}))
    generate_candidates(tmp_path/'merge',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'response.json')
    merged=[read(p) for p in (tmp_path/'store/cards').glob('*.json') if read(p)['parent_card_ids']]
    assert len(merged)==1 and merged[0]['status']=='candidate' and merged[0]['semantic_review']['status']=='pending'
    assert len(merged[0]['validation']['support_source_groups'])==2
    assert accept_fixture(tmp_path,merged[0])['card_status']=='active'
    freeze_generation(tmp_path/'store',tmp_path/'frozen')
    loaded=load_snapshot(tmp_path/'frozen')
    assert sum(c['status']=='active' for c in loaded.data['cards'])==1


def test_versioned_severity_units_preserve_v2_rejection_and_accept_v3_context():
    e=export2();e['events'][0]['public_feedback']['instances']=[{'kind':'max_top_load','rule_id':'R01','object_ids':['B001'],'severity':{'value':6.01,'unit':'kg'}}]
    links=[{'fact_id':'F0003','path':'/instances/0/severity/value','value':6.01,'value_type':'number','unit':'kg','relation':'support'}]
    old=make_request(e,protocol='v2');new=make_request(e,protocol='v3')
    with pytest.raises(JevSelectError,match='fact_unit_mismatch'):resolve_fact_links(old,links)
    assert resolve_fact_links(new,links)[0]['value']==6.01
    links[0]['unit']='mm'
    with pytest.raises(JevSelectError,match='fact_unit_mismatch'):resolve_fact_links(new,links)
    assert old['request_digest']!=new['request_digest']
    assert 'context_units_v2' in canonical(new['body'])


def test_v3_prepare_process_recovery_has_no_implicit_send(tmp_path,monkeypatch):
    MemoryStore(tmp_path/'source').ingest(export2())
    prepare_generation(tmp_path/'source',tmp_path/'prepared',mode='offline_fixture',protocol='v3')
    r=next(iter(validate_prepared(tmp_path/'prepared')[2].values()))
    write(tmp_path/'response.json',response({'version':'jev_generation_output_v2','cards':[prop2(r)]}))
    args=(tmp_path/'prepared',r['request_digest'],tmp_path/'store')
    generate_candidates(*args,mode='offline_fixture',fixture=tmp_path/'response.json')
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('duplicate send'))
    assert generate_candidates(*args,mode='offline_fixture',fixture=tmp_path/'response.json')['status']=='PARSED'
    assert validate_store(tmp_path/'store')['candidate']==1
    freeze_generation(tmp_path/'store',tmp_path/'frozen');assert len(load_snapshot(tmp_path/'frozen').data['cards'])==1


def test_combined_prepared_keeps_exact_export_identities(tmp_path):
    from semantic_pallet_planner.jev_select.memory_generation import combined_readiness
    a={'status':'PASS','source_experiment':'source_a','export_digests':['a'],'episode_identities':{'a:0':'original_a'},'source_groups':['group_a'],'events':2}
    b={'status':'PASS','source_experiment':'source_b','export_digests':['b'],'episode_identities':{'b:0':'original_b'},'source_groups':['group_b'],'events':3}
    combined=combined_readiness([a,b,a])
    assert combined['export_digests']==['a','b'] and combined['episode_identities']=={'a:0':'original_a','b:0':'original_b'}
    assert combined['events']==5 and len(combined['sources'])==2
    with pytest.raises(JevSelectError,match='identity_conflict'):
        combined_readiness([a,{**a,'episode_identities':{'a:0':'forged'}}])
