"""B2 fixtures are protocol tests, never real support or human acceptance."""
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from semantic_pallet_planner.jev_select.contracts import JevSelectError, canonical, digest
from semantic_pallet_planner.jev_select.ledger import read, write
from semantic_pallet_planner.jev_select.memory_store import MemoryStore, load_snapshot
from semantic_pallet_planner.jev_select.memory_generation import summary_input, make_request, prepare_generation, generate_candidates, validate_prepared, prepare_merge
from semantic_pallet_planner.jev_select.memory_validation import validate_store, review_materials, import_review, freeze_generation, eligible


def export_fixture(episode='fixture_episode', group='fixture_group'):
    state={'units':{'length':'mm','mass':'kg'},'container':{'length_mm':100,'width_mm':100,'max_height_mm':100,'max_payload_kg':100},
           'placed_objects':[],'available_objects':[{'object_id':'B001','mass_kg':2,'dimensions_mm':{'length':10,'width':10,'height':10}}],
           'regions':[],'business_requirements':{'english_descriptions':[]}}
    action={'pick_object':'B001','pose':{'x_mm':0,'y_mm':0,'z_mm':0,'yaw_deg':0},'oriented_size_mm':[10,10,10],
            'features':{'support_ratio':1},'load_changes':[]}
    return {'version':'jev_episode_export_v1','episode_id':episode,'source_group_id':group,'partition':'train',
            'protocol_version':'fixture_only_v1','source_code_digest':'1'*64,'fixture_only':True,
            'events':[{'decision_id':'fixture_decision','public_state':state,'selected_action':action,'candidate_facts':{},
                       'feedback':{'instances':[],'coverage':[]},'public_feedback':{'instances':[],'new_instances':[],'coverage':[]}}],
            'terminal_feedback':{'termination_reason':'COMPLETE','planned_items':1,'placed_items':1,'placed_item_ratio':1,
                                 'placed_volume_ratio':.001,'truncated_by_service_failure':False}}


def proposal(req):
    p=req['input']['payload']
    return {'applicability':'fixture observed support comparison','advice':'Compare observed support resources in this fixture.',
            'observed_evidence':'Observed support ratio was one.','comparison_basis':'Observed support surface only.',
            'limitations_counterexamples':'Fixture only; other loads unknown; no causal inference.',
            'expected_effect_hypothesis':'Effect outside the observed event is unknown.',
            'knowledge_role':'sequential_resource_strategy','knowledge_role_basis':'Resource comparison fixture.',
            'parent_card_ids':[],'evidence_links':[{'request_digest':req['request_digest'],'episode_id':p['episode_id'],
               'decision_id':p['events'][0]['decision_id'],'path':'/events/0/selected_action/features/support_ratio','value':1,'relation':'support'}]}


def response(output):
    return {'id':'fixture_response','model':'deepseek-flash','choices':[{'finish_reason':'stop','message':{'content':canonical(output)}}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}


def setup_case(root,count=1,same_group=False):
    for i in range(count):MemoryStore(root/'source').ingest(export_fixture(f'fixture_episode_{i}',f'fixture_group_{0 if same_group else i}'))
    prepare_generation(root/'source',root/'prepared',mode='offline_fixture')
    req=next(iter(validate_prepared(root/'prepared')[2].values()))
    write(root/'fixture.json',response({'version':'jev_generation_output_v1','cards':[proposal(req)]}))
    return req


def execute(root,req,**kw):
    return generate_candidates(root/'prepared',req['request_digest'],root/'store',mode='offline_fixture',fixture=root/'fixture.json',**kw)


def test_deterministic_coverage_and_independent_budgets():
    e=export_fixture();r=make_request(e);assert r==make_request(deepcopy(e))
    assert r['preflight']['status']=='PASS'
    assert '/terminal_feedback' in [c['path'] for c in r['input']['coverage']]
    from semantic_pallet_planner.jev_select.memory_export import build_raw_history
    e['events'][0]['public_state']['business_requirements']['english_descriptions']=['x'*1700]
    assert build_raw_history([e])[1]['injectable_events']==0 and make_request(e)['preflight']['status']=='PASS'
    e['events'][0]['public_state']['business_requirements']['english_descriptions']=['x'*250000]
    r=make_request(e);assert r['preflight']['status']=='GENERATION_INPUT_TOO_LARGE'
    assert r['preflight']['uncovered_events']==['fixture_decision']
    e['terminal_feedback']['truncated_by_service_failure']=True
    assert summary_input(e)['payload']['terminal_feedback']['truncated_by_service_failure']


@pytest.mark.parametrize('field',['reference_policy','policy_ast','future_items','candidate_business_score','api_key'])
def test_leakage(field):
    e=export_fixture();e['events'][0]['public_state'][field]={}
    with pytest.raises(JevSelectError):summary_input(e)


def test_fixture_isolation(tmp_path):
    req=setup_case(tmp_path)
    with pytest.raises(JevSelectError):prepare_generation(tmp_path/'source',tmp_path/'bad',mode='remote_text')
    with pytest.raises(JevSelectError,match='mode_changed'):
        generate_candidates(tmp_path/'prepared',req['request_digest'],tmp_path/'store',mode='remote_text')


def test_resume_review_freeze_migration(tmp_path,monkeypatch):
    r=setup_case(tmp_path);assert execute(tmp_path,r)['status']=='PARSED'
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('duplicate send'))
    assert execute(tmp_path,r)['status']=='PARSED'
    assert validate_store(tmp_path/'store')['candidate']==1
    review_materials(tmp_path/'store',tmp_path/'review')
    c=read(next((tmp_path/'store/cards').glob('*.json')));v=deepcopy(c['semantic_review'])
    v.update(reviewer='fixture_human',status='accepted',supported_source_groups=['fixture_group_0'],conflicts_resolved=True,
             scope_and_advice_compatible=True,reason='Fixture protocol; one source only.')
    write(tmp_path/'review.json',v)
    assert import_review(tmp_path/'store',tmp_path/'review.json')['card_status']=='candidate'
    f=freeze_generation(tmp_path/'store',tmp_path/'frozen');s=load_snapshot(tmp_path/'frozen',f['snapshot_digest'])
    assert s.data['cards'][0]['status']=='candidate'
    with pytest.raises(JevSelectError,match='fixture_memory'):load_snapshot(tmp_path/'frozen',remote=True)
    shutil.copytree(tmp_path/'frozen',tmp_path/'moved');assert load_snapshot(tmp_path/'moved').data==s.data


@pytest.mark.parametrize('change',['value','path','decision','request','identifier'])
def test_forged_evidence(tmp_path,change):
    req=setup_case(tmp_path);p=proposal(req);link=p['evidence_links'][0]
    if change=='value':link['value']=.5
    if change=='path':link['path']='/events/0/candidate_facts/unexecuted_reward'
    if change=='decision':link['decision_id']='unseen'
    if change=='request':link['request_digest']='0'*64
    if change=='identifier':p['advice']='Always select C01.'
    write(tmp_path/'fixture.json',response({'version':'jev_generation_output_v1','cards':[p]}));execute(tmp_path,req)
    assert validate_store(tmp_path/'store')['cards']==0
    assert read(next((tmp_path/'store/generation/rejections').glob('*.json')))['rejected']
    assert len(list((tmp_path/'store/originals').glob('*.json')))==1


@pytest.mark.parametrize('valid',[True,False])
def test_one_structure_repair(tmp_path,valid):
    req=setup_case(tmp_path);write(tmp_path/'fixture.json',response({'wrong':'structure'}))
    write(tmp_path/'repair.json',response({'version':'jev_generation_output_v1','cards':[proposal(req)]} if valid else {'still':'bad'}))
    r=execute(tmp_path,req,repair_fixture=tmp_path/'repair.json')
    assert len(r['attempts'])==2 and r['status']==('PARSED' if valid else 'FAILED')
    assert len(execute(tmp_path,req,repair_fixture=tmp_path/'repair.json')['attempts'])==2


@pytest.mark.parametrize('stage,expected',[('after_reserve','FAILED'),('after_transport','FAILED'),('after_raw_response','PARSED'),('after_response','PARSED'),('after_card','PARSED')])
def test_process_restart(tmp_path,stage,expected):
    req=setup_case(tmp_path)
    code='''import os,sys
from pathlib import Path
from semantic_pallet_planner.jev_select.memory_generation import generate_candidates
r=Path(sys.argv[1])
def hook(stage):
    if stage==sys.argv[3]:os._exit(91)
generate_candidates(r/'prepared',sys.argv[2],r/'store',mode='offline_fixture',fixture=r/'fixture.json',hook=hook)
'''
    run=subprocess.run([sys.executable,'-c',code,str(tmp_path),req['request_digest'],stage],capture_output=True,text=True,env=os.environ.copy())
    assert run.returncode==91,run.stderr
    assert execute(tmp_path,req)['status']==expected
    assert len(list((tmp_path/'store/generation/attempts').glob('*.json')))==1
    assert validate_store(tmp_path/'store')['cards']==int(expected=='PARSED')


@pytest.mark.parametrize('target',['snapshot','evidence','review','config','response','identity'])
def test_frozen_tamper(tmp_path,target):
    req=setup_case(tmp_path);execute(tmp_path,req);freeze_generation(tmp_path/'store',tmp_path/'frozen')
    paths={'snapshot':'snapshot.json','evidence':'evidence/*.json','review':'artifacts/lifecycle/*.json',
           'config':'artifacts/generation/requests/*.json','response':'artifacts/generation/responses/*.json','identity':'memory_manifest.json'}
    p=next((tmp_path/'frozen').glob(paths[target]));p.chmod(0o644);d=read(p);d['tampered']=True;write(p,d)
    with pytest.raises(JevSelectError):load_snapshot(tmp_path/'frozen')


def test_offline_no_network_or_key(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('network'))
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._credential',lambda *a:pytest.fail('key read'))
    req=setup_case(tmp_path);execute(tmp_path,req);review_materials(tmp_path/'store',tmp_path/'review')
    validate_store(tmp_path/'store');freeze_generation(tmp_path/'store',tmp_path/'frozen');load_snapshot(tmp_path/'frozen')


def test_activation_gates(tmp_path):
    req=setup_case(tmp_path);execute(tmp_path,req);c=read(next((tmp_path/'store/cards').glob('*.json')))
    assert not eligible(c)
    c['semantic_review'].update(status='accepted',supported_source_groups=['fixture_group_0'],conflicts_resolved=True,scope_and_advice_compatible=True)
    assert not eligible(c)
    c['semantic_review']['supported_source_groups']=['fixture_group_0','fixture_group_1'];c['validation']['support_source_groups']=['fixture_group_0','fixture_group_1']
    assert eligible(c)
    c['validation']['conflict']=True;assert not eligible(c)
    c['validation']['conflict']=False;c['knowledge_role']='rule_restatement';assert not eligible(c)


def test_false_review(tmp_path):
    req=setup_case(tmp_path);execute(tmp_path,req);c=read(next((tmp_path/'store/cards').glob('*.json')))
    v=deepcopy(c['semantic_review']);v.update(reviewer='fixture_human',supported_source_groups=['invented'])
    write(tmp_path/'review.json',v)
    with pytest.raises(JevSelectError,match='fabricated_source'):import_review(tmp_path/'store',tmp_path/'review.json')
    v['supported_source_groups']=[];v['content_digest']='0'*64;write(tmp_path/'review.json',v)
    with pytest.raises(JevSelectError,match='binding'):import_review(tmp_path/'store',tmp_path/'review.json')


def test_merge_dedup_sources_parents(tmp_path):
    setup_case(tmp_path,count=4,same_group=True)
    for req in validate_prepared(tmp_path/'prepared')[2].values():
        write(tmp_path/'fixture.json',response({'version':'jev_generation_output_v1','cards':[proposal(req)]}));execute(tmp_path,req)
    cards=[read(p) for p in sorted((tmp_path/'store/cards').glob('*.json'))]
    merge=prepare_merge(tmp_path/'prepared',tmp_path/'store',[c['card_id'] for c in cards[:2]],tmp_path/'merge')
    req=validate_prepared(tmp_path/'merge')[2][merge['request_digest']];p=proposal(req)
    p['parent_card_ids']=[c['card_id'] for c in cards[:2]];p['evidence_links']=[link for c in cards[:2] for link in c['evidence_links']]
    write(tmp_path/'merge_fixture.json',response({'version':'jev_generation_output_v1','cards':[p]}))
    assert generate_candidates(tmp_path/'merge',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'merge_fixture.json')['status']=='PARSED'
    assert validate_store(tmp_path/'store')['cards']==5
    merged=[read(p) for p in (tmp_path/'store/cards').glob('*.json') if read(p)['parent_card_ids']][0]
    assert len(merged['validation']['support_source_groups'])==1 and not eligible(merged) and merged['card_version']==2


def test_formal_global_dedup_across_store_and_run_names(tmp_path,monkeypatch):
    from semantic_pallet_planner.jev_select import memory_generation as gen
    repo=tmp_path/'repo';(repo/'semantic_pallet_planner').mkdir(parents=True)
    (repo/'semantic_pallet_planner/pyproject.toml').write_text('fixture')
    def attestation(exports,experiment):
        return {'status':'PASS','source_experiment':'fixture_source','source_code_digest':'1'*64,
                'source_seal_digest':'2'*64,'export_digests':sorted(digest(e) for e in exports),
                'source_groups':['fixture_group'],'episode_identities':{e['episode_id']:'3'*64 for e in exports},'events':len(exports)}
    monkeypatch.setattr(gen,'verify_training',attestation)
    e=export_fixture();e['fixture_only']=False
    MemoryStore(tmp_path/'source').ingest(e)
    gen.prepare_generation(tmp_path/'source',tmp_path/'prepared',experiment='fixture_source',mode='remote_text')
    req=next(iter(gen.validate_prepared(tmp_path/'prepared')[2].values()));calls=[]
    def send(body,repo,config):
        calls.append(1)
        import base64
        return {'status':'OK','raw_body_b64':base64.b64encode(canonical(response({'version':'jev_generation_output_v1','cards':[]})).encode()).decode(),
                'http_status':200,'latency_s':0.,'headers':{},'error':None}
    monkeypatch.setattr(gen,'remote_complete',send)
    for store in ('store_a','store_b'):
        gen.generate_candidates(tmp_path/'prepared',req['request_digest'],tmp_path/store,mode='remote_text',repo=repo)
    assert len(calls)==1
    e['episode_id']='renamed_run:fixture_episode'
    MemoryStore(tmp_path/'renamed_source').ingest(e)
    gen.prepare_generation(tmp_path/'renamed_source',tmp_path/'renamed_prepared',experiment='fixture_source',mode='remote_text')
    req2=next(iter(gen.validate_prepared(tmp_path/'renamed_prepared')[2].values()))
    with pytest.raises(JevSelectError,match='already_reserved'):
        gen.generate_candidates(tmp_path/'renamed_prepared',req2['request_digest'],tmp_path/'store_c',mode='remote_text',repo=repo)
    assert len(calls)==1


def test_oversized_request_never_reserves_or_sends(tmp_path,monkeypatch):
    e=export_fixture();e['events'][0]['public_state']['business_requirements']['english_descriptions']=['x'*250000]
    MemoryStore(tmp_path/'source').ingest(e)
    prepare_generation(tmp_path/'source',tmp_path/'prepared',mode='offline_fixture')
    req=next(iter(validate_prepared(tmp_path/'prepared')[2].values()))
    monkeypatch.setattr('semantic_pallet_planner.jev_select.memory_generation._fixture_complete',lambda *a:pytest.fail('send'))
    assert execute(tmp_path,req)['status']=='GENERATION_INPUT_TOO_LARGE'
    assert not (tmp_path/'store').exists()


def test_merge_before_four_episodes_blocked(tmp_path):
    setup_case(tmp_path,count=2)
    for req in validate_prepared(tmp_path/'prepared')[2].values():
        write(tmp_path/'fixture.json',response({'version':'jev_generation_output_v1','cards':[proposal(req)]}));execute(tmp_path,req)
    parents=[p.stem for p in (tmp_path/'store/cards').glob('*.json')]
    m=prepare_merge(tmp_path/'prepared',tmp_path/'store',parents,tmp_path/'merge')
    with pytest.raises(JevSelectError,match='frequency'):
        generate_candidates(tmp_path/'merge',m['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'fixture.json')


def test_reviewer_identity_is_required(tmp_path):
    req=setup_case(tmp_path);execute(tmp_path,req);c=read(next((tmp_path/'store/cards').glob('*.json')))
    v=c['semantic_review'];v.update(reviewer='codex',status='accepted');write(tmp_path/'review.json',v)
    with pytest.raises(JevSelectError,match='independent_human'):import_review(tmp_path/'store',tmp_path/'review.json')


def test_body_or_request_tamper_even_resigned(tmp_path):
    req=setup_case(tmp_path);execute(tmp_path,req)
    path=next((tmp_path/'store/generation/requests').glob('*.json'));r=read(path)
    r['body']['messages'][1]['content']='invented facts';r['wire_digest']=digest(r['body'])
    from semantic_pallet_planner.jev_select.memory_generation import budget_preflight
    r['preflight']=budget_preflight(r,r['config']);write(path,r)
    with pytest.raises(JevSelectError,match='request_changed'):validate_store(tmp_path/'store')


@pytest.mark.parametrize('status',['OK','HTTP_FAILURE','UNKNOWN_IN_FLIGHT'])
def test_official_transport_envelope_and_secret_redaction(tmp_path,monkeypatch,status):
    import urllib.request
    import urllib.error
    from semantic_pallet_planner.jev_select import memory_generation as gen
    monkeypatch.setattr(gen,'_credential',lambda repo:'sk-FIXTURE_NEVER_REAL_KEY_0123456789')
    captured=[]
    class Reply:
        headers={'x-request-id':'fixture_request','date':'fixture_date'}
        status=200
        def read(self):return b'{"echo":"sk-FIXTURE_NEVER_REAL_KEY_0123456789"}'
        def __enter__(self):return self
        def __exit__(self,*a):pass
    class Opener:
        def open(self,req,timeout):
            captured.append((req.full_url,timeout,req.data))
            if status=='HTTP_FAILURE':
                import io
                raise urllib.error.HTTPError(req.full_url,429,'fixture failure',{},io.BytesIO(b'fixture HTTP error'))
            if status=='UNKNOWN_IN_FLIGHT':raise urllib.error.URLError('fixture timeout')
            return Reply()
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:Opener())
    result=gen.remote_complete({'model':'deepseek-flash'},tmp_path,gen.generator_config())
    assert result['status']==status
    assert captured[0][0]=='https://api.deepseek.com/chat/completions' and captured[0][1]==120
    assert 'sk-FIXTURE' not in canonical(result)
    import base64
    assert b'sk-FIXTURE' not in base64.b64decode(result['raw_body_b64'])


def test_two_group_review_activation_and_b1_bundle_copy(tmp_path):
    setup_case(tmp_path,count=4)
    for req in validate_prepared(tmp_path/'prepared')[2].values():
        p=proposal(req)
        # Retained negative/unknown observation, not a second supporting group.
        adverse=deepcopy(p['evidence_links'][0]);adverse['relation']='counterexample';p['evidence_links'].append(adverse)
        write(tmp_path/'fixture.json',response({'version':'jev_generation_output_v1','cards':[p]}));execute(tmp_path,req)
    cards=[read(p) for p in sorted((tmp_path/'store/cards').glob('*.json'))]
    merge=prepare_merge(tmp_path/'prepared',tmp_path/'store',[c['card_id'] for c in cards[:2]],tmp_path/'merge')
    req=validate_prepared(tmp_path/'merge')[2][merge['request_digest']];p=proposal(req)
    p['parent_card_ids']=[c['card_id'] for c in cards[:2]];p['evidence_links']=[link for c in cards[:2] for link in c['evidence_links']]
    write(tmp_path/'merge_fixture.json',response({'version':'jev_generation_output_v1','cards':[p]}))
    generate_candidates(tmp_path/'merge',req['request_digest'],tmp_path/'store',mode='offline_fixture',fixture=tmp_path/'merge_fixture.json')
    merged=[read(p) for p in (tmp_path/'store/cards').glob('*.json') if read(p)['parent_card_ids']][0]
    v=merged['semantic_review'];v.update(reviewer='fixture_independent_human_protocol',status='accepted',
        supported_source_groups=merged['validation']['support_source_groups'],conflicts_resolved=True,scope_and_advice_compatible=True,
        reason='Synthetic protocol acceptance only; never real human review evidence.')
    write(tmp_path/'review.json',v)
    assert import_review(tmp_path/'store',tmp_path/'review.json')['card_status']=='active'
    freeze_generation(tmp_path/'store',tmp_path/'memory')
    from semantic_pallet_planner.jev_select.batch_j4 import prepare_j4,validate_plan_j4
    prepare_j4(tmp_path/'plan',task_limit=1,methods=['jev_no_memory','jev_raw_history','jev_memory_cards'],memory=tmp_path/'memory')
    validate_plan_j4(tmp_path/'plan')
    copied=load_snapshot(tmp_path/'plan/memory_experience')
    assert copied.data['fixture_only'] and sum(c['status']=='active' for c in copied.data['cards'])==1
    assert len([x for x in merged['evidence_links'] if x['relation']=='counterexample'])==2
