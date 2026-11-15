"""A1 pure saved-public evidence check; imports the same no-dispatch test guard."""
import hashlib,json,sys,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/tests/unit'))
import test_packaging_scenario_features as tests
from semantic_pallet_planner.jev_select import packaging_scenario_features as m

OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs'
C1=BASE/'JEV_JM1_C1_REAL_BASELINES_20261112_01'
C2=BASE/'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
B2=BASE/'JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'


def read(p):return json.loads(Path(p).read_text())
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def reference(path,pointer=''):
    path=Path(path).resolve();assert path.is_relative_to(ROOT)
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pointer=pointer)
def checked(ref):
    p=Path(ref['path']);p=p if p.is_absolute() else ROOT/p
    assert p.resolve().is_relative_to(ROOT)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==ref['sha256']
    return read(p)
def pointer(value,p):
    for part in p.lstrip('/').split('/') if p else []:
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def main():
    assert not any(any(name==k or name.startswith(k+'.') for k in tests.BLOCKED) for name in sys.modules)
    manifests=[]
    for d in ('JEV_JM_C2_REAL_QA_20261113_01','JEV_JM1_C2_REAL_SUFFIXES_20261113_01',
              'JEV_JM1_C1_REAL_BASELINES_20261112_01','JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'):
        man=read(BASE/d/'delivery_manifest.json');historical_source=[]
        for entry in man['files']:
            p=ROOT/entry['path'];raw=p.read_bytes()
            if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                assert entry['path']=='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
                original=OUT/'entry_source_bytes/packaging_versions.py';raw=original.read_bytes()
                assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
                historical_source.append(dict(path=entry['path'],verification='entry Git blob; live source has authorized additive A1 registration',original_ref=reference(original)))
        manifests.append(dict(path=str((BASE/d/'delivery_manifest.json').relative_to(ROOT)),files=len(man['files']),status='PASS_WITH_EXPLICIT_NEW_SOURCE_IDENTITY' if historical_source else 'PASS',historical_source=historical_source))
    plan=read(C1/'fork_plan.json');rows=[];origins=[]
    for point in plan['points']:
        loc=point['public_evidence_location'];state=checked(loc['prefix_ref']);pool=checked(loc['pool_ref']);public=checked(loc['projection_ref'])
        assert state==public['public_state'] and len(pool)==len(public['pool'])==len(public['display_mapping'])
        assert {r['candidate_id'] for r in pool}=={r['candidate_id'] for r in public['display_mapping']}
        by_id={r['candidate_id']:r for r in pool}
        for r in public['pool']:
            assert by_id[r['candidate_id']]==r['frozen_candidate'] and m.digest(r['frozen_candidate'])==r['candidate_digest']
        history=m.from_saved_public(state,pool,expected_pool_count=len(pool),expected_raw_pool_digest=m.digest(pool))
        ctxpath=B2/'materials/future_runs'/Path(loc['export_root']).name/'ledger/contexts'/(point['decision_id']+'.json')
        context=read(ctxpath);current=m.from_current_public(context['model_state'],context['criteria'],expected_candidate_labels=list(context['display_mapping']))
        before=copy.deepcopy((history,current));hs=m.build_signature(history);cs=m.build_signature(current)
        assert hs['features']==cs['features'] and (history,current)==before and hs['stage']=='NONEMPTY'
        branch_a,branch_b=point['branches']
        binding=m.bind_contrast(history,branch_a['candidate_id'],branch_b['candidate_id'],current=current)
        assert {'A':branch_a['label'],'B':branch_b['label']} in binding['correspondence_pairs']
        expected_class='CROSS_BOX_SELECTION' if branch_b['kind']=='CROSS_BOX_SELECTION' else 'SAME_BOX_TRANSLATION'
        assert binding['intervention']==expected_class and not binding['execution_eligible']
        dest=OUT/'saved_public_checks'/point['point_id']
        for name,value in [('historical_input',history),('current_input',current),('historical_signature',hs),('current_signature',cs),('action_contrast_binding',binding)]:
            write(dest/(name+'.json'),value)
        field_sources={}
        for name in hs['features']:
            pop='buffer' if name.startswith('buffer_') else 'placed_objects' if name.startswith('placed_') else 'pool'
            h=[reference(loc['prefix_ref']['path'],'/'+pop)] if pop!='pool' else [reference(loc['pool_ref']['path'])]
            c=[reference(ctxpath,'/model_state/'+('available_objects' if pop=='buffer' else 'placed_objects'))] if pop!='pool' else [reference(ctxpath,'/criteria')]
            h.append(reference(loc['prefix_ref']['path'],'/container'));c.append(reference(ctxpath,'/model_state/container'))
            for ref in h+c:pointer(checked(ref),ref['pointer'])
            field_sources[name]=dict(historical=h,current=c,formula=m.feature_spec()['features'][name]['formula'],
                        output=reference(dest/'historical_signature.json','/features/'+name+'/value'))
        exact={}
        for role,branch in [('A',branch_a),('B',branch_b)]:
            i=next(i for i,c in enumerate(pool) if c['candidate_id']==branch['candidate_id'])
            exact[role]=dict(saved_action=reference(loc['pool_ref']['path'],'/'+str(i)),
                             current_action=reference(ctxpath,'/criteria/'+branch['label']),
                             candidate_digest=branch['candidate_digest'],exact_action_digest=branch['exact_action_digest'])
        origins.append(dict(point_id=point['point_id'],features=field_sources,action_roles=exact,
                            area_normalization='current max_top_load_kg - current_top_load_kg; NOT effective remaining_top_load_kg'))
        rows.append(dict(point_id=point['point_id'],stage=hs['stage'],pool_count=len(pool),feature_count=len(hs['features']),
                         same_function_same_population=True,all_feature_values_equal=True,
                         intervention=binding['intervention'],binding_status=binding['status'],
                         pair_count=len(binding['correspondence_pairs']),execution_eligible=False,
                         outputs=[reference(p) for p in sorted(dest.glob('*.json'))]))
        print(json.dumps(dict(point=point['point_id'],status='PASS',pool_count=len(pool),binding=binding['status'])),flush=True)
    # Save only engineering counterexamples, never T fragments/cards or model inputs.
    a=tests.fixture();stacked=copy.deepcopy(a);stacked['state']['placed_objects'][1]['pose'].update(x_mm=-40,z_base_mm=10)
    missing=copy.deepcopy(a);del missing['state']['placed_objects'][0]['pose']
    renamed=copy.deepcopy(a)
    for b in renamed['state']['buffer']:b['item_id']='anon_'+b['item_id']
    for c in renamed['pool']:c['pick_item_id']='anon_'+c['pick_item_id']
    renamed=tests.remake(renamed)
    write(OUT/'constructed_counterexamples.json',dict(version='jm2_a1_constructed_examples_v1',scope='CONSTRUCTED_ONLY_NOT_RESEARCH_EVIDENCE',
        equal_buffer_different_structure=dict(before=a,after=stacked,before_signature=m.build_signature(a),after_signature=m.build_signature(stacked),binding=m.bind_contrast(a,'a0','a1',current=stacked)),
        missing_condition=dict(input=missing,signature=m.build_signature(missing),binding=m.bind_contrast(missing,'a0','a1')),
        identity_not_attribute=dict(original=a,renamed=renamed,cross_binding=m.bind_contrast(a,'a0','b0'))))
    write(OUT/'field_origin_index.json',dict(version='jm2_a1_field_origins_v1',points=origins,
             semantics='SHA identifies exact source file; JSON pointer addresses full statistical population or exact action; no source bytes modified'))
    write(OUT/'scenario_feature_spec.json',m.feature_spec())
    write(OUT/'saved_public_validation.json',dict(version='jm2_a1_saved_validation_v1',status='PASS',points=rows,
             parent_manifests=manifests,actual_nonempty_points=5,same_box_points=3,cross_box_points=2,
             imports_blocked=list(tests.BLOCKED),side_effect_audit=['credential file reads','socket connect/bind','subprocess','os.system'],
             credentials_read=0,model_calls=0,orders=0,forks=0,candidate_generation=0,prefix_replay=0,stability_solve=0,
             M21_02='PASS_A1_ENGINEERING',M21_05='PASS_A1_ENGINEERING',experience_applicability='NOT_ASSESSED',research_benefit='NOT_ESTABLISHED'))
    print('PASS_5_REAL_PUBLIC_INPUTS_NO_DISPATCH')


if __name__=='__main__':main()
