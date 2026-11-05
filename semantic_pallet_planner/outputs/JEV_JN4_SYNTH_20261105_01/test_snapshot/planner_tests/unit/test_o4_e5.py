import copy
import io
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.config import generator_config,load_config,WORKSPACE
from semantic_pallet_planner.o4.common import read,write,O4Error
from semantic_pallet_planner.o4.extensions.e2.validation import gold
from semantic_pallet_planner.o4.extensions.e2.compiler import compile_policy
from semantic_pallet_planner.o4.extensions.e2.protocol import response_for
from semantic_pallet_planner.o4.extensions.e5.data import mixed_gold,construct_tasks,rules_for,source_tasks
from semantic_pallet_planner.o4.extensions.e5.backends import Ledger,LocalCompiler,RemoteCompiler
from semantic_pallet_planner.o4.extensions.e5.episode import episode,verify_episode,stable
from semantic_pallet_planner.o4.remote.transport import ModelConfig,ChatTransport


def fake_transport(monkeypatch,reply=None):
    monkeypatch.setenv('E5_TEST_KEY','offline-only')
    bodies=[]
    def opener(req,timeout):
        b=json.loads(req.data);bodies.append(b)
        envelope=json.loads(b['messages'][1]['content'][0]['text'])['public_input'];q=envelope['public_request']
        response=reply(q,len(bodies)) if reply else compile_policy(q)
        payload={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(response)}}],'usage':{'total_tokens':10}}
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*a):self.close()
        return Response(json.dumps(payload).encode())
    return ChatTransport(ModelConfig(endpoint='https://offline.invalid/chat/completions',model='e5-test-double',api_key_env='E5_TEST_KEY'),opener=opener,test_double=True),bodies


@pytest.mark.parametrize('row',mixed_gold(),ids=lambda x:x['case_id'])
def test_mixed_arithmetic_gold(row):assert gold([row])[0]['passed']


def test_main_sources_immutable_geometry_and_exact_business_delta():
    sources,tasks=source_tasks(WORKSPACE)
    assert len(sources)==len({s['source_order_key'] for s in sources})==12 and len(tasks)==24
    assert sources==sorted(sources,key=lambda x:x['source_order_key'])
    for a,b in zip(tasks[::2],tasks[1::2]):
        assert a['items']==b['items'] and a['attributes']==b['attributes'] and a['regions']==b['regions']
        assert b['reference_policy']['rules'][:-1]==a['reference_policy']['rules']
        assert len(a['items'])==min(12,len(a['provenance']['original_arrival_order']))
        assert len(a['reference_policy']['rules'])==6 and len(b['reference_policy']['rules'])==7
    assert sum(len(t['items'])+1 for t in tasks)*10==3100


@pytest.mark.parametrize('index',range(6))
@pytest.mark.parametrize('method',['single','buffer_fifo','buffer_heuristic','buffer_search'])
def test_mixed_driver_and_all_mode_restore(index,method):
    t=construct_tasks()[index];cfg=generator_config(load_config())
    r=episode(t,'public_parser',method,cfg,LocalCompiler('public_parser'),'job')
    assert r['summary']['completed']==t['expected_by_planner'][method]
    assert not r['summary']['final_business_violations']
    assert verify_episode(r,t,cfg)['summary_recomputed']
    rr=episode(t,'public_parser',method,cfg,LocalCompiler('public_parser'),'job',resume=r['checkpoints'][1])
    assert stable({k:v for k,v in r.items() if k!='checkpoints'})==stable({k:v for k,v in rr.items() if k!='checkpoints'})


def request_for_test():
    from semantic_pallet_planner.o4.extensions.e2.data import request,object_at,policy,relative
    return request(policy([relative()]),placed=[object_at('B','household_cleaner')])[0]


def test_cross_job_budget_and_single_repair_are_durable(tmp_path,monkeypatch):
    q=request_for_test()
    t,bodies=fake_transport(monkeypatch,lambda q,n:{'invalid':'format'} if n==1 else compile_policy(q))
    ledger=Ledger(tmp_path,3,{'a':4,'b':4},test_double=True);compiler=RemoteCompiler(tmp_path,t,ledger)
    a=compiler.compile(q,'a',0,'image');assert a['repaired_valid'] and len(bodies)==2
    b=compiler.compile(q,'b',0,'text');assert b['first_valid'] and len(bodies)==3
    failed=compiler.compile(q,'b',1,'text');assert failed['status']=='budget_exhausted' and len(bodies)==3
    with pytest.raises(O4Error,match='duplicate'):compiler.compile(q,'a',0,'image')
    resumed=Ledger(tmp_path,3,{'a':4,'b':4},test_double=True,resume=True)
    assert resumed.report()['used_attempts']==3 and resumed.report()['real_api_attempts']==0
    recovered=RemoteCompiler(tmp_path,t,resumed,recover=True).compile(q,'a',0,'image')
    assert recovered['response']==a['response'] and len(bodies)==3
    with pytest.raises(O4Error,match='configuration_changed'):Ledger(tmp_path,4,{'a':4,'b':4},test_double=True,resume=True)


def test_valid_wrong_ast_is_executed_and_exposed(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch,lambda q,n:response_for(q,{'schema_version':'o4_e2_policy_v1','rules':[]}))
    task=construct_tasks()[4];ledger=Ledger(tmp_path,10,{'job':10},test_double=True)
    r=episode(task,'remote_text','single',generator_config(load_config()),RemoteCompiler(tmp_path,t,ledger).bound('text'),'job')
    assert r['summary']['completed'] and r['summary']['final_business_violations']
    assert len(bodies)==4 and all(not a['repair'] for a in ledger.rows())
    assert verify_episode(r,task,generator_config(load_config()))['independent_physics']


@pytest.mark.parametrize('method',['single','buffer_search'])
def test_real_encoding_and_actual_image_bound_commit(tmp_path,monkeypatch,method):
    t,bodies=fake_transport(monkeypatch);task=construct_tasks()[0];ledger=Ledger(tmp_path,10,{'job':10},test_double=True)
    r=episode(task,'remote_image',method,generator_config(load_config()),RemoteCompiler(tmp_path,t,ledger).bound('image'),'job')
    assert r['summary']['clean_completed'] and len(bodies)==4
    assert verify_episode(r,task,generator_config(load_config()))['summary_recomputed']
    for e in r['events']:
        if 'request' not in e:continue
        assert e['source_request']['images']==[] and len(e['request']['images'])==1
        assert e['request']['observation_digest']!=e['source_request']['observation_digest']
        assert e['action']['observation_digest']==e['response']['observation_digest']==e['request']['observation_digest']
        assert e['compilation']['test_double']
    assert all(b['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,') for b in bodies)


def test_in_flight_attempt_never_retried_on_resume(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch)
    def crash(body):raise KeyboardInterrupt('simulated process death after reservation')
    monkeypatch.setattr(t,'complete',crash)
    ledger=Ledger(tmp_path,4,{'job':4},test_double=True)
    with pytest.raises(KeyboardInterrupt):RemoteCompiler(tmp_path,t,ledger).compile(request_for_test(),'job',0,'text')
    assert len(ledger.rows())==1 and ledger.rows()[0]['status']=='in_flight'
    r=RemoteCompiler(tmp_path,t,Ledger(tmp_path,4,{'job':4},test_double=True,resume=True),recover=True).compile(request_for_test(),'job',0,'text')
    assert r['status']=='unknown_in_flight' and len(ledger.rows())==1 and not bodies


def test_crash_after_http_finish_recovers_exact_saved_response(tmp_path,monkeypatch):
    import semantic_pallet_planner.o4.extensions.e5.backends as module
    t,bodies=fake_transport(monkeypatch);ledger=Ledger(tmp_path,4,{'job':4},test_double=True);original=module.atomic
    def crash(path,value):
        if 'responses' in Path(path).parts and value['status']=='valid':raise KeyboardInterrupt('after ledger finish')
        original(path,value)
    monkeypatch.setattr(module,'atomic',crash)
    with pytest.raises(KeyboardInterrupt):RemoteCompiler(tmp_path,t,ledger).compile(request_for_test(),'job',0,'text')
    assert ledger.rows()[0]['status']=='valid'
    monkeypatch.setattr(module,'atomic',original)
    r=RemoteCompiler(tmp_path,t,ledger,recover=True).compile(request_for_test(),'job',0,'text')
    assert r['status']=='valid' and len(bodies)==1 and r['attempt_ids']==[1]


def test_crash_before_actual_commit_resumes_without_second_http(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch);task=construct_tasks()[0];ledger=Ledger(tmp_path,10,{'job':10},test_double=True);saved=[]
    def checkpoint(cp,phase):
        saved.append(cp)
        if phase=='before_commit':raise KeyboardInterrupt('before actual PLACE')
    cfg=generator_config(load_config())
    with pytest.raises(KeyboardInterrupt):episode(task,'remote_image','single',cfg,RemoteCompiler(tmp_path,t,ledger).bound('image'),'job',on_checkpoint=checkpoint)
    assert len(bodies)==1 and saved[-1]['state']['placed_count']==0
    r=episode(task,'remote_image','single',cfg,RemoteCompiler(tmp_path,t,ledger,recover=True).bound('image'),'job',resume=saved[-1])
    assert r['summary']['clean_completed'] and len(bodies)==4 and r['final_state']['placed_count']==4
    verify_episode(r,task,cfg)


def test_tampered_summary_and_premature_eos_rejected():
    task=construct_tasks()[0];cfg=generator_config(load_config());r=episode(task,'public_parser','single',cfg,LocalCompiler('public_parser'),'job')
    changed=copy.deepcopy(r);changed['summary']['completed']=False
    with pytest.raises(O4Error,match='summary'):verify_episode(changed,task,cfg)
    changed=copy.deepcopy(r);changed['events'][0]['event']='EOS'
    with pytest.raises(O4Error,match='premature_eos'):verify_episode(changed,task,cfg)


@pytest.mark.parametrize('instruction',['要求箱体旋转180°。','要求箱体旋转270度。','allowed_yaw={0,90}。','要求roll=180。','要求标签朝外。'])
def test_current_scope_refuses_orientation_rules_before_model_call(tmp_path,monkeypatch,instruction):
    from semantic_pallet_planner.o4.extensions.e2.protocol import rebind
    q=rebind({**request_for_test(),'instruction_text':instruction})
    t,bodies=fake_transport(monkeypatch);ledger=Ledger(tmp_path,4,{'job':4},test_double=True)
    with pytest.raises(O4Error,match='unsupported_construct'):RemoteCompiler(tmp_path,t,ledger).compile(q,'job',0,'text')
    assert not bodies and not ledger.rows()


def test_repair_budget_exhaustion_keeps_original_invalid_attempt(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch,lambda q,n:{'bad':'format'})
    ledger=Ledger(tmp_path,1,{'job':4},test_double=True)
    r=RemoteCompiler(tmp_path,t,ledger).compile(request_for_test(),'job',0,'text')
    assert r['status']=='budget_exhausted' and r['response'] is None and len(bodies)==1
    assert ledger.rows()[0]['status']=='invalid_ast' and r['attempt_ids']==[1]


def test_provider_outage_never_falls_back(tmp_path,monkeypatch):
    from urllib.error import URLError
    monkeypatch.setenv('E5_TEST_KEY','offline-only')
    def unavailable(req,timeout):raise URLError('injected provider outage')
    cfg=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='double',api_key_env='E5_TEST_KEY')
    ledger=Ledger(tmp_path,4,{'job':4},test_double=True)
    r=RemoteCompiler(tmp_path,ChatTransport(cfg,opener=unavailable,test_double=True),ledger).compile(request_for_test(),'job',0,'text')
    assert r['status']=='provider_error' and r['response'] is None and len(ledger.rows())==1


def test_physically_invalid_proposal_is_recorded_as_failed_commit(monkeypatch):
    import importlib
    module=importlib.import_module('semantic_pallet_planner.o4.extensions.e5.episode')
    original=module.choose
    def bad_choice(*args):
        selected,groups,trace,reason=original(*args)
        selected=copy.deepcopy(selected);selected['pose']['x_mm']=1e6
        for g in groups:
            for c in g['candidates']:
                if c['candidate_id']==selected['candidate_id']:c['pose']['x_mm']=1e6
        return selected,groups,trace,reason
    monkeypatch.setattr(module,'choose',bad_choice)
    task=construct_tasks()[0];cfg=generator_config(load_config())
    compiler=LocalCompiler('public_parser',transform=lambda a:{**a,'rules':[]})
    r=episode(task,'public_parser','single',cfg,compiler,'physics')
    assert r['summary']['execution_status']=='FAIL' and r['summary']['placed_items']==0
    e=r['events'][-1];assert e['event']=='COMMIT_FAILURE' and e['proposed_action'] and e['action'] is None
    assert verify_episode(r,task,cfg)['independent_physics']


def test_unknown_job_rejected_before_creating_assets(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch);ledger=Ledger(tmp_path,2,{'job':2},test_double=True)
    with pytest.raises(O4Error,match='unplanned_decision'):RemoteCompiler(tmp_path,t,ledger).compile(request_for_test(),'../elsewhere',0,'image')
    assert not (tmp_path/'public').exists() and not bodies


def test_crash_after_saved_place_does_not_repeat_compilation_or_placement(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch);task=construct_tasks()[0];ledger=Ledger(tmp_path,10,{'job':10},test_double=True);saved=[]
    def checkpoint(cp,phase):
        saved.append(cp)
        if phase=='after_decision':raise KeyboardInterrupt('after persistent first PLACE')
    cfg=generator_config(load_config())
    with pytest.raises(KeyboardInterrupt):episode(task,'remote_image','single',cfg,RemoteCompiler(tmp_path,t,ledger).bound('image'),'job',on_checkpoint=checkpoint)
    assert saved[-1]['state']['placed_count']==1 and len(bodies)==1
    r=episode(task,'remote_image','single',cfg,RemoteCompiler(tmp_path,t,ledger,recover=True).bound('image'),'job',resume=saved[-1])
    assert r['summary']['clean_completed'] and len(bodies)==4
    assert len({p['item_id'] for p in r['final_state']['placed_items']})==4
    verify_episode(r,task,cfg)


def test_rule_without_targets_is_na_not_execution_evidence():
    from semantic_pallet_planner.o4.extensions.e5.metrics import aggregate
    from semantic_pallet_planner.o4.extensions.e5.activity import task_presence
    task=copy.deepcopy(construct_tasks()[0])
    task['attributes']['B']['cargo_category']='general'
    presence=task_presence(task)
    assert next(p for p in presence if p['type']=='relative_position')['has_targets_in_planned_order'] is False
    cfg=generator_config(load_config());r=episode(task,'public_parser','single',cfg,LocalCompiler('public_parser'),'na')
    verify_episode(r,task,cfg)
    stats=aggregate(iter([r]),[{'status':'PASS'}]);group=stats['groups'][0]
    relation=group['rule_activity']['relative_position']
    assert relation['planned_without_targets_NA']==1 and relation['checked_instances']==0
    assert group['components']['semantic_equal']['correct']==group['components']['semantic_equal']['comparable']
    assert 'physical applicability' in group['component_scope']


def test_exact_root_memoization_matches_e2_and_returns_independent_copies():
    from semantic_pallet_planner.o4.extensions.e2.data import request,policy,relative,object_at
    from semantic_pallet_planner.o4.extensions.e2.planning import choose as baseline
    from semantic_pallet_planner.o4.extensions.e5.planning import choose,clear_cache
    q,s=request(policy([relative()]),placed=[object_at('B','household_cleaner')]);cfg=generator_config(load_config());ast=compile_policy(q)['policy_ast']
    a=baseline(s,q,ast,cfg,'single');clear_cache();b=choose(s,q,ast,cfg,'single');c=choose(s,q,ast,cfg,'single')
    assert stable(list(b))==stable(list(c))
    assert a[0]==b[0] and stable(a[1])==stable(b[1]) and a[3]==b[3]
    assert {k:v for k,v in b[2].items() if k not in ('elapsed_seconds','memoization_scope','evaluation_count_scope')}==a[2]
    b[0]['pose']['x_mm']=999999
    again=choose(s,q,ast,cfg,'single');assert again[0]['pose']['x_mm']==a[0]['pose']['x_mm']
    hidden={**s,'future_items':[{'private':'not yet arrived'}]};assert stable(list(choose(hidden,q,ast,cfg,'single')))==stable(list(again))


def test_named_offline_accounting_views_keep_zero_api_and_full_denominators(tmp_path):
    from semantic_pallet_planner.o4.extensions.e5.delivery import accounting_views
    t=construct_tasks()[0];cfg=generator_config(load_config());r=episode(t,'public_parser','single',cfg,LocalCompiler('public_parser'),'job');r.pop('checkpoints')
    write(tmp_path/'episodes/job.json',r)
    data={'tasks':[],'constructs':[t],'manual_witnesses':[]};jobs=[{'job_id':'job','task_id':t['task_id'],'status':'PASS'},{'job_id':'unexecuted','task_id':t['task_id'],'status':'NOT_RUN'}]
    v=accounting_views(tmp_path,data,jobs)
    assert v['compiled_decisions']==4 and v['recorded_failure_classifications']==2
    assert read(tmp_path/'audit/attempts.json')==[] and read(tmp_path/'audit/budget.json')['real_api_attempts']==0
    assert len(read(tmp_path/'metrics/failure_attribution.json'))==2


@pytest.mark.parametrize('field,value',[('per_object_top_k',17),('joint_candidates_max',49),('source_orders',11),('new_api_attempts',False),('memoization','none'),('unexpected',1),('yaw_degrees',[0,180]),('online_jobs',239)])
def test_closed_config_rejects_budget_type_and_scope_drift(field,value):
    from semantic_pallet_planner.o4.extensions.e5 import EXPECTED_CONFIG
    from semantic_pallet_planner.o4.extensions.e5.experiment import validate_extension
    cfg=copy.deepcopy(EXPECTED_CONFIG);cfg[field]=value
    with pytest.raises(O4Error,match='unsupported_e5_config'):validate_extension(cfg)


def test_checked_config_matches_runtime_contract():
    from semantic_pallet_planner.o4.extensions.e5.experiment import validate_extension
    assert validate_extension(read(WORKSPACE/'semantic_pallet_planner/configs/o4_e5_090_offline_v2.json'))['per_object_top_k']==16


def test_mixed_gold_has_six_allow_six_reject_and_true_conjunction_conflict():
    from semantic_pallet_planner.o4.extensions.e5.validation import mixed
    rows=mixed_gold();checked=mixed(rows)
    assert len(rows)==12 and sum(bool(r['expected_allowed_ids']) for r in rows)==6
    assert all(r['passed'] for r in checked)
    conflict=next(r for r in checked if r['individual_rule_witnesses'])
    assert len(conflict['individual_rule_witnesses'])==2 and all(r['actual'] for r in conflict['individual_rule_witnesses'])
    assert conflict['actual']['allowed_ids']==[]


def test_resume_rejects_reset_attempt_list_before_any_new_http(tmp_path,monkeypatch):
    t,bodies=fake_transport(monkeypatch);ledger=Ledger(tmp_path,4,{'job':4},test_double=True)
    RemoteCompiler(tmp_path,t,ledger).compile(request_for_test(),'job',0,'text')
    saved=read(tmp_path/'audit/ledger.json');saved['attempts']=[];write(tmp_path/'audit/ledger.json',saved)
    with pytest.raises(O4Error,match='ledger_record_disagreement'):
        Ledger(tmp_path,4,{'job':4},test_double=True,resume=True)
    assert len(bodies)==1


def test_prepare_failure_keeps_stage_and_all_unexecuted_jobs(tmp_path,monkeypatch):
    from semantic_pallet_planner.o4.extensions.e5 import experiment
    def unavailable(workspace):raise O4Error('injected_source_read_failure')
    monkeypatch.setattr(experiment,'source_tasks',unavailable)
    output=tmp_path/'failed_prepare'
    with pytest.raises(O4Error,match='injected_source_read_failure'):
        experiment.prepare(output,tmp_path/'unused.json')
    report=read(output/'acceptance_report.json')
    assert report['status']=='FAIL' and report['not_run_jobs']==240
    assert report['materialized_jobs']==report['recorded_episodes']==0
    assert report['new_api_attempts']==0 and report['phase']=='reading_sources_and_declared_fixtures'
    assert read(output/'audit/jobs.json')==[]
    assert read(output/'audit/initialization_error.json')['error_code']=='injected_source_read_failure'


def test_failure_journal_does_not_write_rejected_existing_directory(tmp_path):
    from semantic_pallet_planner.o4.extensions.e5.experiment import prepare
    output=tmp_path/'existing';output.mkdir();marker=output/'original.txt';marker.write_text('keep')
    with pytest.raises(O4Error,match='unsafe_output'):prepare(output,tmp_path/'unused.json')
    assert sorted(p.name for p in output.iterdir())==['original.txt'] and marker.read_text()=='keep'


def test_compile_failures_and_not_run_groups_keep_full_denominators(tmp_path):
    from semantic_pallet_planner.o4.common import digest
    from semantic_pallet_planner.o4.extensions.e5.metrics import aggregate
    from semantic_pallet_planner.o4.extensions.e5.delivery import lightweight_results
    task=construct_tasks()[0];cfg=generator_config(load_config())
    class Failed:
        def compile(self,q,job_id,decision):
            return {'compiled_request':q,'response':None,'status':'provider_error','backend':'remote_text',
                    'source_digest':digest(q),'compilation_id':f'{job_id}_D{decision:04d}',
                    'first_valid':False,'repaired_valid':False,'attempt_ids':[],'test_double':True}
    result=episode(task,'remote_text','single',cfg,Failed(),'failed')
    result.pop('checkpoints');verify_episode(result,task,cfg)
    write(tmp_path/'episodes/failed.json',result)
    base={'source_kind':task['source_kind'],'source_order_key':task['source_order_key'],
          'configuration':task['configuration'],'planner':'single','task_id':task['task_id']}
    jobs=[{**base,'job_id':'failed','backend':'remote_text','status':'FAIL'},
          {**base,'job_id':'missing','backend':'remote_text','status':'NOT_RUN'},
          {**base,'job_id':'unseen_backend','backend':'remote_image','status':'NOT_RUN'}]
    stats=aggregate(lightweight_results(tmp_path,jobs),jobs)
    text=next(g for g in stats['groups'] if g['backend']=='remote_text')
    image=next(g for g in stats['groups'] if g['backend']=='remote_image')
    assert text['planned_episodes']==2 and text['recorded_episodes']==1 and not text['measurement_complete']
    assert text['compilation']['decisions']==text['compilation']['final_invalid_or_failed']==1
    assert text['compilation']['first_valid_rate']==text['compilation']['final_valid_rate']==0
    assert text['components']=={} and text['business_violation_step_rate'] is None
    assert image['planned_episodes']==image['unrecorded_episodes']==1 and image['recorded_episodes']==0
    assert image['compilation']['final_valid_rate'] is None and image['mean_placed_volume_ratio'] is None


def test_clean_completion_requires_no_violating_submission_in_history():
    from semantic_pallet_planner.o4.extensions.e5.episode import summarize
    task=construct_tasks()[0];cfg=generator_config(load_config())
    result=episode(task,'public_parser','single',cfg,LocalCompiler('public_parser'),'clean')
    assert result['summary']['clean_completed']
    # The summary must honor an earlier audited violation even if the supplied
    # final audit is clean; this is a metric test, not a claimed physical trace.
    history=copy.deepcopy(result['events'])
    next(e for e in history if e.get('action'))['reference_after']['violations']=[{'rule_id':'past_violation'}]
    summary=summarize(task,'public_parser','single',result['final_state'],history,'all_items_placed')
    assert summary['completed'] and not summary['clean_completed'] and summary['violating_steps']==1
