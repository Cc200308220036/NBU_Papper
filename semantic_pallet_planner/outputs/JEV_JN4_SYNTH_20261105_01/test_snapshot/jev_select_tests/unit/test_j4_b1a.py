"""B1-A protocol fixtures; no fixture is production training evidence."""
import json
import math
import shutil
import subprocess
import sys
import pytest
from semantic_pallet_planner.jev_select.contracts import JevSelectError, MemorySnapshot, canonical, digest
from semantic_pallet_planner.jev_select.memory_query import build_query, evaluate_gates, tokenize
from semantic_pallet_planner.jev_select.memory_retrieval import retrieve, card_text, DEFAULT_LIMITS, build_index
from semantic_pallet_planner.jev_select.memory_store import indexed_snapshot, freeze_snapshot, load_snapshot, empty_snapshot, MemoryStore
from semantic_pallet_planner.jev_select.memory_export import build_raw_history


def history(text, identifier='fixture', gates=()):
    return {'history_id':identifier,'source_group_id':'fixture_group','episode_id':'fixture_episode',
            'decision_id':'fixture_decision','export_digest':'1'*64,'text':text,
            'content_digest':digest(text),'utf8_bytes':len(text.encode()),'gates':list(gates)}


def snapshot(rows):return indexed_snapshot([],fixture_only=True,raw_history=rows)
def query(word='load'):return build_query({}, {'english_descriptions':[word]}, {})


def card():
    c={'version':'jev_memory_card_v1','card_id':'fixture_card','card_version':1,'status':'active',
       'knowledge_role':'sequential_resource_strategy','applicability':'load comparison fixture',
       'advice':'load observation fixture, no production advice','observed_evidence':'negative feedback: load violation observed',
       'limitations_counterexamples':'counterexample: support differs; no causal conclusion',
       'evidence_refs':[{'source_group_id':g,'episode_id':'fixture_episode','decision_id':'fixture_decision','export_digest':'1'*64} for g in ('fixture_a','fixture_b')],
       'evidence_level':'observational','created_after_episode':'fixture_episode','parent_card_ids':[],
       'generator_digest':'2'*64,'semantic_review':{'status':'accepted','reviewer':'fixture_only','reason':'test protocol only'},
       'gates':[],'fixture_only':True}
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    return c


def test_public_query_numeric_identity():
    state={'units':{'length':'mm','mass':'kg'},'container':{'length_mm':1200},
        'available_objects':[{'object_id':'B001','mass_kg':10.0,'cargo_category':'Food','dimensions_mm':{'length':20}}],
        'placed_objects':[], 'buffer':{'capacity':3}}
    q=build_query(state,{'english_descriptions':['No top LOAD, 10.000000 kg.']},{})
    state['available_objects'][0]['object_id']='secret_order_identity'
    assert q==build_query(state,{'english_descriptions':['No top LOAD, 10.000000 kg.']},{})
    assert q['facts']['layout_height_mm']==0 and q['facts']['available_categories']==['food']
    assert tokenize('LOAD 10.000 kg 中文 B001 C02')==['load','10','kg']
    assert tokenize('1e-7 -1e-7 +1e+3')==['0','0','1000']


@pytest.mark.parametrize('field',['task','reference_policy','future_items','source_group_id','method_scores'])
def test_private_query_rejected(field):
    with pytest.raises(JevSelectError):build_query({field:{}},{},{})


def test_nested_private_and_query_tamper():
    with pytest.raises(JevSelectError):build_query({'available_objects':[{'labels':{'task':'secret'}}]},{},{})
    with pytest.raises(JevSelectError):build_query({}, {'policy_ast':{}}, {})
    with pytest.raises(JevSelectError):build_query({}, {}, {'C01':{'features':{'candidate_business_score':0}}})
    q=query();q['text']='tampered'
    with pytest.raises(JevSelectError,match='query_changed'):retrieve(q,empty_snapshot(),'cards')
    q=query();q['facts']['order_id']='secret'
    with pytest.raises(JevSelectError):retrieve(q,empty_snapshot(),'cards')


@pytest.mark.parametrize('op,actual,expected',[
    ('eq',3,'APPLICABLE'),('ne',3,'NOT_APPLICABLE'),('lt',2,'APPLICABLE'),
    ('le',3,'APPLICABLE'),('gt',4,'APPLICABLE'),('ge',3,'APPLICABLE')])
def test_finite_operators(op,actual,expected):
    assert evaluate_gates([{'field':'available_count','op':op,'value':3}],{'available_count':actual})[0]==expected


def test_unknown_false_zero_and_invalid_gates():
    rows=[history('load','unknown',[{'field':'layout_height_mm','op':'ge','value':1}]),
          history('load','false',[{'field':'candidate_count','op':'gt','value':0}]),history('xyz','zero')]
    r=retrieve(query(),snapshot(rows),'raw_history')
    assert r['memories']==[] and r['status']=='NO_MATCH'
    assert {e['reason'] for e in r['exclusions']}=={'APPLICABILITY_UNKNOWN','NOT_APPLICABLE','NO_MATCH'}
    for g in ({'field':'future_count','op':'eq','value':1},{'field':'available_count','op':'contains','value':1}):
        with pytest.raises(JevSelectError):snapshot([history('load',gates=[g])])
    assert evaluate_gates([{'field':'available_categories','op':'contains','value':'food'}],{'available_categories':['food']})[0]=='APPLICABLE'


def test_bm25_formula_ties_top3_repeat():
    s=snapshot([history('load '+c,str(i)) for i,c in enumerate(('apple','berry','cargo','delta'))])
    r=retrieve(query(),s,'raw_history');assert r==retrieve(query(),s,'raw_history')
    assert len(r['memories'])==3
    assert [x['content_digest'] for x in r['ranking']]==sorted(x['content_digest'] for x in r['ranking'])
    assert r['ranking'][0]['score']==pytest.approx(math.log1p(.5/4.5))
    assert any(e['reason']=='TOP_K_LIMIT' for e in r['exclusions'])
    assert r['retrieval_digest']==digest({k:v for k,v in r.items() if k!='retrieval_digest'})


def test_modes_share_text_scoring_and_negative_feedback():
    c=card();text=card_text(c);s=indexed_snapshot([],cards=[c],fixture_only=True,raw_history=[history(text)])
    a=retrieve(query(),s,'raw_history');b=retrieve(query(),s,'cards')
    assert a['memories']==b['memories']==[text]
    assert a['ranking'][0]['score']==b['ranking'][0]['score']
    assert a['limits']==b['limits']==DEFAULT_LIMITS
    assert 'negative feedback' in a['memories'][0] and 'counterexample' in b['memories'][0]
    assert a['config_digest']==b['config_digest'] and a['index_digest']==b['index_digest']
    assert a['mode_index_digest']==digest(s.data['index']['modes']['raw_history'])
    assert b['mode_index_digest']==digest(s.data['index']['modes']['cards'])


def test_chinese_utf8_item_limit_and_json_escaping():
    text='load '+'负'*531;long='load '+'负'*532
    r=retrieve(query(),snapshot([history(text,'ok'),history(long,'long')]),'raw_history')
    assert r['memories']==[text] and r['selected'][0]['utf8_bytes']==1598
    assert next(e for e in r['exclusions'] if e['document_id']=='long')['reason']=='ITEM_TOO_LARGE'
    escaped='load '+'\\"\n'*300
    r=retrieve(query(),snapshot([history(escaped)]),'raw_history',dict(DEFAULT_LIMITS,total_max_utf8_bytes=1000))
    assert r['memories']==[] and r['exclusions'][0]['reason']=='TOTAL_BUDGET'


def test_exact_total_budget_whole_skip():
    texts=['load '+c*(n-5) for c,n in [('a',1596),('b',1597),('c',1597)]]
    s=snapshot([history(t,str(i)) for i,t in enumerate(texts)])
    r=retrieve(query(),s,'raw_history');assert len(r['memories'])==3 and r['utf8_bytes']==4800
    r=retrieve(query(),s,'raw_history',dict(DEFAULT_LIMITS,total_max_utf8_bytes=4799))
    assert len(r['memories'])==2 and any(e['reason']=='TOTAL_BUDGET' for e in r['exclusions'])
    assert all(t in texts for t in r['memories'])
    with pytest.raises(JevSelectError):retrieve(query(),s,'cards',dict(DEFAULT_LIMITS,top_k=4))


def test_migration_readonly_and_tamper(tmp_path):
    s=snapshot([history('load: negative feedback remains')]);freeze_snapshot(s,tmp_path/'original')
    shutil.copytree(tmp_path/'original',tmp_path/'moved')
    loaded=load_snapshot(tmp_path/'moved',digest(s.data));assert loaded==s
    assert retrieve(query(),s,'raw_history')==retrieve(query(),loaded,'raw_history')
    with pytest.raises(JevSelectError,match='fixture_memory'):load_snapshot(tmp_path/'moved',remote=True)
    p=tmp_path/'moved/snapshot.json';v=json.loads(p.read_text());v['index']['modes']['raw_history']['documents'][0]['term_counts']['load']=999
    p.write_text(canonical(v))
    with pytest.raises(JevSelectError,match='files_changed'):load_snapshot(tmp_path/'moved')
    v['index_digest']=digest(v['index'])
    with pytest.raises(JevSelectError,match='index_changed'):retrieve(query(),MemorySnapshot.from_dict(v),'raw_history')
    v=s.data;v['raw_history'][0]['text']='changed'
    with pytest.raises(JevSelectError,match='content_changed'):retrieve(query(),MemorySnapshot.from_dict(v),'raw_history')


def test_fixture_does_not_relax_activation():
    c=card();c['semantic_review']['status']='pending'
    with pytest.raises(JevSelectError,match='not_eligible'):indexed_snapshot([],cards=[c],fixture_only=True)
    with pytest.raises(JevSelectError,match='fixture_card'):indexed_snapshot([],cards=[card()])


def minimal_export():
    action={'pick_object':'B001','pose':{'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0},
        'oriented_size_mm':[1,1,1],'features':{'support_ratio':1},'load_changes':[]}
    state={'units':{'length':'mm','mass':'kg'},'container':{'length_mm':2},
        'available_objects':[{'object_id':'B001','mass_kg':1,'cargo_category':'food'}],
        'placed_objects':[],'regions':[], 'business_requirements':{'english_descriptions':['R01: No top load on food.']}}
    instance={'kind':'no_top_load','rule_id':'R01','object_ids':['B001'],'severity':None}
    return {'version':'jev_episode_export_v1','episode_id':'fixture_episode','source_group_id':'fixture_group','partition':'train',
        'fixture_only':True,'protocol_version':'fixture_only','source_code_digest':'1'*64,
        'events':[{'decision_id':'fixture_decision','public_state':state,'candidate_facts':{'C01':action},'selected_action':action,
                   'feedback':{'instances':[],'coverage':[]},'public_feedback':{'instances':[instance],'new_instances':[instance],'coverage':[]}}],
        'terminal_feedback':{'planned_items':2,'placed_items':1,'placed_item_ratio':.5,'placed_volume_ratio':.5,
                             'termination_reason':'STOP_NO_PHYSICAL_CANDIDATE','truncated_by_service_failure':False}}


def test_self_contained_feedback_provenance_exclusion():
    e=minimal_export();h,r=build_raw_history([e]);assert r['injectable_ratio']==1
    b=json.loads(h[0]['text']);assert b['selected_box']['mass_kg']==1
    assert b['actual_feedback']['new_instances'] and b['terminal']['placed_items']==1
    assert h[0]['export_digest']==digest(e) and len(h[0]['text'].encode())<=1600
    e['events'][0]['public_feedback']['new_instances']*=40
    h,r=build_raw_history([e]);assert h==[] and r['exclusion_reasons']=={'EVENT_TOO_LARGE':1}
    del e['events'][0]['public_feedback'];h,r=build_raw_history([e]);assert r['exclusion_reasons']=={'PUBLIC_FEEDBACK_UNRESOLVED':1}


def test_evidence_tamper_and_binding(tmp_path):
    e=minimal_export();s=indexed_snapshot([e]);freeze_snapshot(s,tmp_path/'frozen',evidence_exports=[e])
    assert load_snapshot(tmp_path/'frozen')==s
    p=next((tmp_path/'frozen/evidence').glob('*.json'));p.write_text('{}')
    with pytest.raises(JevSelectError,match='files_changed'):load_snapshot(tmp_path/'frozen')
    v=s.data;v['raw_history'][0]['export_digest']='9'*64
    v['index']=build_index(v);v['index_digest']=digest(v['index'])
    with pytest.raises(JevSelectError,match='history_evidence_changed'):freeze_snapshot(MemorySnapshot.from_dict(v),tmp_path/'bad',evidence_exports=[e])


def test_fresh_import_preflight_freeze_no_network_credentials(tmp_path):
    script="""
import sys,socket,builtins,pathlib,os
original_env=os._Environ.__getitem__
def guard_env(self,key):
 if any(x in str(key).lower() for x in ('api_key','credential','token','secret')): raise AssertionError('credential environment read')
 return original_env(self,key)
os._Environ.__getitem__=guard_env
original=builtins.open
original_path=pathlib.Path.open
def blocked(*a,**k): raise AssertionError('network forbidden')
def guard(path,*a,**k):
 if any(x in pathlib.Path(path).name.lower() for x in ('api_key','credential','typesafe','.env')): raise AssertionError('credential read')
 return original(path,*a,**k)
def guard_path(path,*a,**k):
 if any(x in pathlib.Path(path).name.lower() for x in ('api_key','credential','typesafe','.env')): raise AssertionError('credential read')
 return original_path(path,*a,**k)
builtins.open=guard;pathlib.Path.open=guard_path
class OfflineSocket(socket.socket):
 def connect(self,*a,**k): blocked()
 def connect_ex(self,*a,**k): blocked()
 def sendto(self,*a,**k): blocked()
socket.socket=OfflineSocket;socket.create_connection=blocked
from semantic_pallet_planner.jev_select.memory_query import build_query
from semantic_pallet_planner.jev_select.memory_retrieval import retrieve,preflight_memory
from semantic_pallet_planner.jev_select.memory_store import freeze_snapshot,empty_snapshot,load_snapshot
freeze_snapshot(empty_snapshot(),sys.argv[1]);load_snapshot(sys.argv[1])
retrieve(build_query({}, {}, {}),empty_snapshot(),'cards')
preflight_memory(sys.argv[2],sys.argv[3])
"""
    store=MemoryStore(tmp_path/'store');store.ingest(minimal_export())
    subprocess.run([sys.executable,'-c',script,str(tmp_path/'snapshot'),str(tmp_path/'store'),str(tmp_path/'preflight')],check=True)


def test_b1_runtime_accepts_explicit_nonempty_memory():
    from semantic_pallet_planner.jev_select.tests.unit.test_j4_memory import pipeline
    from semantic_pallet_planner.jev_select.config import load_v3_config
    from semantic_pallet_planner.jev_select.context import ContextBuilder
    s=snapshot([history('load')]);cfg=load_v3_config()
    from semantic_pallet_planner.jev_select.config import config_for_memory
    case,policy,bundle,_=pipeline(cfg)
    cfg=config_for_memory(cfg,'jev_raw_history',s)
    assert ContextBuilder(cfg).build(case['observation'],bundle,policy,memories=s).data['retrieval']['mode']=='raw_history'


def test_production_card_evidence_cannot_be_invented(tmp_path):
    c=card();c['fixture_only']=False
    c['content_digest']=digest({k:c[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role','gates','fixture_only')})
    s=indexed_snapshot([],cards=[c])
    with pytest.raises(JevSelectError,match='evidence_unresolved'):freeze_snapshot(s,tmp_path/'invalid')
    v=s.data;v['cards'][0]['advice']='changed'
    with pytest.raises(JevSelectError,match='card_content_changed'):retrieve(query(),MemorySnapshot.from_dict(v),'cards')


def test_v3_limits_and_empty_b0_identity():
    from semantic_pallet_planner.jev_select.config import load_v3_config, load_v2_config, memory_retrieval_limits
    cfg=load_v3_config()
    assert memory_retrieval_limits(cfg)==DEFAULT_LIMITS
    assert digest(empty_snapshot().data)==cfg['memory_snapshot_digest']
    with pytest.raises(JevSelectError):memory_retrieval_limits(load_v2_config())


def test_gate_type_and_unknown_rule_are_rejected():
    with pytest.raises(JevSelectError):build_query({'available_objects':[{'mass_kg':{'task':'private'}}]},{},{})
    e=minimal_export();e['events'][0]['public_feedback']['new_instances'][0]['rule_id']='R99'
    h,r=build_raw_history([e]);assert not h and r['exclusion_reasons']=={'PUBLIC_RULE_UNRESOLVED':1}
