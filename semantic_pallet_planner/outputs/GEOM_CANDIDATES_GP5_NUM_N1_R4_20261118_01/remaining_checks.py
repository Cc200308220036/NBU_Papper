"""Original fifteen X/H/admin entries only. Saved copies/pure checks except H16.
No execution at import. Called only by the gated fixed-suite entrypoint after E/R.
"""
import copy,json,shutil,tempfile
from pathlib import Path
from unittest.mock import patch
from harness import read,write

def run_checks(s):
    from validation_entrypoint import O,check_frozen
    from semantic_pallet_planner.jev_select import geometry_native_shape_bridge as b,geometry_order_execution as order
    from semantic_pallet_planner.jev_select import geometry_execution as ge,packaging_geometry_protocol as p
    from semantic_pallet_planner.jev_select.contracts import JevSelectError,validate_schema,digest,canonical
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import same_native,encode,decode
    from semantic_pallet_planner.jev_select.geometry_runtime_input import validate_runtime_views_v1
    from semantic_pallet_planner.jev_select.stability.monitor import seal_checkpoint
    names=read(O/'validation_scope.json')['X_H_names'];out=[]
    def reject(label,fn):
        try:fn()
        except JevSelectError as exc:return {'case':label,'status':'REJECTED','code':exc.code,'detail':str(exc)}
        raise AssertionError('EXPECTED_REJECTION:'+label)
    def publication(phase='MONITORED'):
        root=O/'R_saved'/('J03_'+phase)/'jobs/J03';cp=read(root/'checkpoint.json');cfg=read(root/'config.json');ev=cp['pending_event']
        doc=ge.GeometryStore(root).get_json(ev['geometry_ref']);a=doc['audit']
        return cp,cfg,ev,a
    def verify(a,cfg,ev):
        return b.validate_native_shape_publication_v3(bytes.fromhex(a['native_bytes_hex']),bytes.fromhex(a['geometry_bytes_hex']),a['common_binding'],a['backend_binding'],ev['bundle']['physical_candidates'],a['publication'],config=cfg)
    def mutation(label,change,phase='MONITORED'):
        cp,cfg,ev,a=publication(phase);change(a,ev,cfg)
        return reject(label,lambda:verify(a,cfg,ev))
    def proof(a):
        store=b.Artifacts(a['publication']['blobs']);return store.get(a['publication']['record']['ordered_mappings'][0]['proof_core_ref'])
    for entry in names:
        check_frozen();name=entry['name'];details=[]
        if name=='X_pure_size_bool_rounding_unrepresentable_axis_yaw':
            for label,raw,dim,yaw in [('bool',[True,80,60],[100,80,60],0),('rounding',[99.99999999999999,80,60],[100,80,60],0),('unrepresentable',[9007199254740992.0,80,60],[9007199254740993,80,60],0),('axis',[100,80,60],[100,80,60],90),('yaw',[100,80,60],[100,80,60],0.0)]:
                details.append(reject(label,lambda:b.restore_size(raw,dict(zip(('length','width','height'),dim)),yaw)))
        elif name=='X_schema_unknown_version_unknown_field':
            cp,_,_,_=publication()
            for k,v in [('version','UNKNOWN'),('UNRECOGNIZED',True)]:
                bad=copy.deepcopy(cp);bad[k]=v;details.append(reject(k,lambda:validate_schema('checkpoint_v17',bad)))
        elif name=='X_missing_proof_three_phases':
            for phase in ('SELECTED','MONITORED','COMMITTED'):
                def change(a,e,c):
                    key=a['publication']['record']['ordered_mappings'][0]['proof_core_ref']['sha256'];del a['publication']['blobs'][key]
                details.append(mutation(phase,change,phase))
        elif name=='X_missing_shadow_derived_final_binding':
            for label in ('raw_after_ref','published_after_ref','raw_derived_ref','published_derived_ref','final_binding_ref'):
                def change(a,e,c):
                    ref=a['publication']['record']['ordered_mappings'][0]['final_binding_ref'] if label=='final_binding_ref' else proof(a)['physical_and_derived_equivalence'][label]
                    del a['publication']['blobs'][ref['sha256']]
                details.append(mutation(label,change))
        elif name=='X_tampered_bytes_signed_zero':
            def tamper(a,e,c):
                k=a['publication']['record']['raw_pool_ref']['sha256'];a['publication']['blobs'][k]='00'
            details.append(mutation('blob_bytes',tamper))
            cp,cfg,ev,a=publication();n=decode(bytes.fromhex(a['native_bytes_hex']));n['current_state']['placed_items'][0]['pose']['x_mm']=-0.0
            details.append(reject('signed_zero',lambda:validate_runtime_views_v1(encode(n),bytes.fromhex(a['geometry_bytes_hex']))))
        elif name=='X_swapped_evidence_raw_P_mismatch':
            def swap(a,e,c):
                # Local synthetic negative: replace proof bytes at original ref.
                # SHA must reject; never re-sign trusted historical material.
                key=a['publication']['record']['ordered_mappings'][0]['proof_core_ref']['sha256'];pr=proof(a);eq=pr['physical_and_derived_equivalence']
                eq['raw_after_ref'],eq['published_after_ref']=eq['published_after_ref'],eq['raw_after_ref'];a['publication']['blobs'][key]=encode(pr).hex()
            details.append(mutation('swapped_shadow',swap))
            def raw_mismatch(a,e,c):e['bundle']['physical_candidates'][0]['pick_item_id']='other_box'
            details.append(mutation('raw_P_source',raw_mismatch))
        elif name=='X_policy_source_config_backend_task_scope_drift':
            for key in ('publication_policy_digest','runtime_identity','candidate_backend','order_task_identity','execution_scope'):
                cp,cfg,ev,a=publication();bad=copy.deepcopy(cfg)
                if key=='runtime_identity':bad[key]['source_identity']='0'*64
                elif key=='order_task_identity':bad[key]['task_id']='wrong'
                else:bad[key]='UNKNOWN'
                details.append(reject(key,lambda:order.preflight_order(bad)))
            details.append(mutation('publication_config',lambda a,e,c:a['publication']['record'].update(config_digest='0'*64)))
        elif name=='H_v14_execution_refusal':
            from semantic_pallet_planner.jev_select.packaging_versions import reject_geometry_execution,GEOMETRY_VERSION
            details.append(reject('construction_only',lambda:reject_geometry_execution({'version':GEOMETRY_VERSION},'run_episode')))
        elif name=='H_v15_real_task_refusal':
            raw=Path('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks/NEW_00100027_controlled_base.json').read_bytes()
            task=p.adapt_task(raw,origin='EXPOSED_TRAIN',expected_sha256=p.sha(raw))
            details.append(reject('fixture_only',lambda:ge.validate_fixture(task['runtime'])))
        elif name=='H_v16_K02_INT_original_failure':
            t=s.tasks['GP5_SYNTH_K02_INT'];plan=p.prepare_order_plan([t],data_identity=digest('R4_H16_FIXED'),scope=p.DEVELOPMENT)
            adm={'version':'geometry_development_binding_v1','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
            with s.monitor('X_H','H_v16') as local:
                result=order.run_order_job(plan,'J02',t,monitor_snapshot=s.monitor_snapshot,admission=adm,root=O/'H_v16')
                assert result['summary']['termination_reason']=='RUNTIME_INPUT_INVALID' and result['summary']['placed_items']==1 and len(local)==1
                assert result['summary']['termination_class']=='TECHNICAL_FAILURE'
            details.append({'case':'original_integer_failure','status':'EXPECTED_TECHNICAL_FAILURE','monitor_entries':1})
        elif name=='H_v1_snapshot_type_bit_refusal':
            cp,cfg,ev,a=publication();nraw=bytes.fromhex(a['native_bytes_hex']);graw=bytes.fromhex(a['geometry_bytes_hex'])
            native=decode(nraw)
            for label,value in [('type',float(native['current_state']['placed_items'][0]['oriented_size_mm'][0])),('sign',-0.0)]:
                n=copy.deepcopy(native)
                if label=='type':n['current_state']['placed_items'][0]['oriented_size_mm'][0]=value
                else:n['current_state']['placed_items'][0]['pose']['x_mm']=value
                details.append(reject(label,lambda:validate_runtime_views_v1(encode(n),graw)))
        elif name=='H_accounting_unknown_dispatch_missing_history':
            from semantic_pallet_planner.jev_select.geometry_order_accounting import invocation
            root=O/'X_contracts/accounting';root.mkdir(parents=True,exist_ok=True)
            cfg=read(O/'configs.json')['J03'];cp=read(O/'R_saved/J03_SELECTED/jobs/J03/checkpoint.json')
            doc=read(O/'R_saved/J03_SELECTED/jobs/J03/accounting.json');doc['invocations'][-1]['status']='STARTED';write(root/'unknown.json',doc)
            def enter(path):
                with invocation(path,cfg,'J03',cp):raise AssertionError('UNEXPECTED_ACCOUNTING_ENTRY')
            details.append(reject('unknown_dispatch',lambda:enter(root/'unknown.json')))
            details.append(reject('missing_history',lambda:enter(root/'absent.json')))
        elif name=='H_terminal_commit_failure_validator':
            from semantic_pallet_planner.jev_select.packaging_runtime import evaluate_state
            cp,cfg,ev,a=publication();task=s.tasks['GP5_SYNTH_K02_INT']
            candidate=copy.deepcopy(cp);event=candidate['pending_event'];event.update(event='COMMIT_FAILURE',reason=ge.COMMIT_TECHNICAL_ERROR,error={'code':ge.COMMIT_TECHNICAL_ERROR,'detail':'PURE_SAVED_CONTRACT'},action=None,after=copy.deepcopy(event['before']),business_after=evaluate_state(event['before']))
            candidate.update(phase='TERMINATED',reason=ge.COMMIT_TECHNICAL_ERROR,pending_event=None,state=copy.deepcopy(event['before']),decision=cp['decision']+1);candidate['events'].append(event);seal_checkpoint(candidate)
            store=order.OrderStore(O/'R_saved/J03_MONITORED/jobs/J03',plan=s.plan,job_id='J03',adapted=task,monitor_snapshot=s.monitor_snapshot,admission=s.adm)
            ge.validate_saved_checkpoint(candidate,task['runtime'],cfg,'J03',cfg['selector'],store)
            write(O/'X_contracts/terminal_commit_failure.json',candidate)
            bad=copy.deepcopy(candidate);bad['reason']='ARBITRARY_ERROR';bad['events'][-1]['reason']='ARBITRARY_ERROR';bad['events'][-1]['error']['code']='ARBITRARY_ERROR';seal_checkpoint(bad)
            details.append(reject('arbitrary_terminal_error',lambda:ge.validate_saved_checkpoint(bad,task['runtime'],cfg,'J03',cfg['selector'],store)))
            details.append({'case':'valid_terminal_commit_failure','status':'PASS_SAVED_CONTRACT_ONLY','new_monitor_commit':0})
        elif name=='H_strong_completion_missing_duplicate_error_no_commit':
            # Explicit single existing pure-contract method, never class discovery.
            # No setUpClass, no other methods, no genuine kernel receipts minted.
            from test_geometry_order_r1 import Remediation
            with tempfile.TemporaryDirectory() as tmp:
                case=Remediation('test_completion_contract_missing_duplicate_error_only_no_commit_recovery');case.tmp=type('Temp',(),{'name':tmp})();case.evidence=None
                captured={};case.save=lambda n,v:captured.update({n:v})
                case.test_completion_contract_missing_duplicate_error_only_no_commit_recovery()
                write(O/'X_contracts/completion_contract.json',captured)
            details.append({'case':'original_coverage_only_method','status':'PASS_PURE_CONTRACT_NOT_GENUINE_RECEIPT'})
        elif name=='ADMIN_real_task_read_adapt_digest_pre_episode_refusal':
            tasks=[]
            for tid in p.TASK_IDS:
                f=Path('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks')/(tid+'.json');raw=f.read_bytes();t=p.adapt_task(raw,origin='EXPOSED_TRAIN',expected_sha256=p.sha(raw));tasks.append(t)
                details.append({'case':tid,'identity':t['identity'],'status':'READ_ADAPT_DIGEST_ONLY'})
            plan=p.prepare_order_plan(tasks,data_identity=digest([t['identity'] for t in tasks]),scope=p.ORDER,native=True)
            with patch('semantic_pallet_planner.jev_select.episode.run_episode',side_effect=AssertionError('REAL_EPISODE_FORBIDDEN')) as episode:
                details.append(reject('DRAFT_no_real_admission',lambda:order.run_order_job(plan,'J00',tasks[0],monitor_snapshot=s.monitor_snapshot,admission=s.adm,root=O/'ADMIN_MUST_NOT_EXIST')))
                assert episode.call_count==0 and not (O/'ADMIN_MUST_NOT_EXIST').exists()
        else:raise AssertionError('UNREGISTERED_FIXED_TEST:'+name)
        out.append({'name':name,'status':'PASS','details':details});write(O/'X_H_admin_results.json',out)
        s.outcomes.append({'group':'X_H_ADMIN','name':name,'validation_status':'PASS'});s.save()
    assert len(out)==15
