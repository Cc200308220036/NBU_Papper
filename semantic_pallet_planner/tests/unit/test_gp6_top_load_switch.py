"""Two scoped offline acceptance checks. No credentials/network/real kernel."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from test_gp6_jev_integration import (_fake_monitor_snapshot, _make_monitor_double, FakeChoiceTransport, _adapted_synth)
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as protocol
from semantic_pallet_planner.jev_select.contracts import canonical,digest,JevSelectError
from semantic_pallet_planner.jev_select.geometry_jev_protocol import prepare_jev_plan,development_binding
from semantic_pallet_planner.jev_select.geometry_jev_execution import GeometryJevRequestLedger,run_jev_job,load_jev_config,validate_jev_saved_checkpoint,JevOrderStore
from semantic_pallet_planner.jev_select.stability import exact_adapter
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
from semantic_pallet_planner.o4.buffer.buffer_state import physical,place
from semantic_pallet_planner.jev_select.packaging_runtime import evaluate_state

OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_20261122_01')

def fixture():
    task=protocol.synthetic_task('K02_INT')
    task['container']['length_mm']=180
    task['items'][0]['top_load_limit_kg_synthetic']=0.1
    task['attributes']['synth_1']['physical_top_load_limit_kg']=0.1
    task['attributes']['synth_1']['labels']['max_top_load_kg']=0.1
    return task

def test_overload_fixture_both_backends():
    original=protocol.synthetic_task
    task=fixture()
    # Explicit local fixture registration only; production catalogue is unchanged.
    def catalogue(case):return copy.deepcopy(task) if case=='K02_INT' else original(case)
    receipts=[]
    legacy=prepare_jev_plan([_adapted_synth('K01')],data_identity='0'*64)
    assert legacy['version']=='geometry_jev_plan_v1' and 'packaging_top_load_limit_enabled' not in legacy
    with patch.object(protocol,'synthetic_task',catalogue):
        raw=canonical(task).encode();adapted=protocol.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=hashlib.sha256(raw).hexdigest())
        snap=_fake_monitor_snapshot();assess,calls=_make_monitor_double(snap)
        with tempfile.TemporaryDirectory() as td,patch.object(exact_adapter,'assess_candidate',assess):
            for enabled in (True,False):
                plan=prepare_jev_plan([adapted],data_identity='0'*64,packaging_top_load_limit_enabled=enabled,switch_protocol=True,shared_max_sends=38)
                binding=development_binding(plan)
                root=Path(td)/str(enabled)
                ledger=GeometryJevRequestLedger(root/'requests',plan_digest=digest(plan),per_job_max_sends=19,shared_max_sends=38,runtime_version=plan['runtime_version'])
                for job in plan['jobs']:
                    ep=run_jev_job(plan,job['job_id'],adapted,monitor_snapshot=snap,admission=binding,root=root/'run',transport=FakeChoiceTransport(),ledger=ledger)
                    assert len(ep['final_state']['placed_items'])==(1 if enabled else 2)
                    if not enabled:
                        ev=[e for e in ep['events'] if e['event']=='PLACE'][-1]
                        candidate=next(c for c in ev['bundle']['physical_candidates'] if c['candidate_id']==ev['selection']['selected_candidate_id'])
                        before=ev['before'];case=physical(before,candidate['pick_item_id'])
                        assert check_candidate(case,{'container':before['container']},candidate)==['overload']
                        assert not check_candidate(case,{'container':before['container']},candidate,packaging_top_load_limit_enabled=False)
                        try:place(before,candidate)
                        except ValueError:pass
                        else:raise AssertionError('default commit accepted overload')
                        after=place(before,candidate,packaging_top_load_limit_enabled=False)
                        assert not evaluate_state(after,packaging_top_load_limit_enabled=False)['violations']
                        assert any(v['reason']=='overload' for v in evaluate_state(after)['violations'])
                        # Within container, <70% contact; both proposal and oracle still reject.
                        bad=copy.deepcopy(candidate);bad['pose']['x_mm']=-before['placed_items'][0]['pose']['x_mm']
                        errors=check_candidate(case,{'container':before['container']},bad,packaging_top_load_limit_enabled=False)
                        assert 'insufficient_support' in errors or 'support_ratio' in ','.join(errors),errors
                        from semantic_pallet_planner.domain import internal_item,restore_placed
                        from semantic_pallet_planner.planner.constraints import evaluate_pose
                        item=internal_item(case['available_items'][0]);l,w=bad['oriented_size_mm'][:2]
                        raw,reason=evaluate_pose(item,restore_placed(case['placed_items']),bad['pose']['x_mm']-l/2,bad['pose']['y_mm']-w/2,bad['pose']['z_base_mm'],l,w,bad['pose']['yaw_deg'],{'container':before['container'],'support_ratio_min':0.7,'packaging_top_load_limit_enabled':False})
                        assert raw is None and reason=='insufficient_support',reason
                        try:place(before,bad,packaging_top_load_limit_enabled=False)
                        except ValueError:pass
                        else:raise AssertionError('disabled mode accepted insufficient support')
                        cfg=load_jev_config(plan,job['job_id'],monitor_snapshot=snap,admission=binding)
                        store=JevOrderStore(root/'run/jobs'/job['job_id'],plan=plan,job_id=job['job_id'],adapted=adapted,monitor_snapshot=snap,admission=binding,request_ledger=ledger)
                        validate_jev_saved_checkpoint(ep['checkpoint'],adapted['runtime'],cfg,job['job_id'],'jev_no_memory',store)
                        assert ep['summary']['packaging_top_load_compliance']=='NOT_APPLICABLE'
                    receipts.append({'backend':job['backend'],'enabled':enabled,'runtime_version':plan['runtime_version'],'placed':len(ep['final_state']['placed_items']),'reason':ep['checkpoint']['reason']})
    OUT.mkdir(exist_ok=True);(OUT/'fixture_receipt.json').write_text(json.dumps({'status':'PASS','real_calls':0,'monitor':'TEST_DOUBLE','rows':receipts},indent=2)+'\n')

def test_actual_disabled_request():
    adapted=_adapted_synth('K01');snap=_fake_monitor_snapshot();assess,calls=_make_monitor_double(snap)
    plan=prepare_jev_plan([adapted],data_identity='0'*64,packaging_top_load_limit_enabled=False,shared_max_sends=38)
    binding=development_binding(plan)
    with tempfile.TemporaryDirectory() as td,patch.object(exact_adapter,'assess_candidate',assess):
        ledger=GeometryJevRequestLedger(Path(td)/'requests',plan_digest=digest(plan),per_job_max_sends=19,shared_max_sends=38,runtime_version=plan['runtime_version'])
        transport=FakeChoiceTransport()
        ep=run_jev_job(plan,'G00',adapted,monitor_snapshot=snap,admission=binding,root=Path(td)/'run',transport=transport,ledger=ledger)
        body=transport.bodies[0];text=canonical(body)
        for key in ('max_top_load_kg','effective_top_permission_kg','remaining_top_load_kg','capacity_utilization','utilization_status','preserving useful space and capacity','preserve load'):
            assert key not in text,key
        assert 'mass_kg' in text and 'support_ratio' in text and 'support_fractions' in text
        ev=next(e for e in ep['events'] if e['event']=='PLACE');sel=ev['selection'];label=sel['selected_display_id']
        mapped=ev['context']['display_mapping'][label]
        c=next(c for c in ev['bundle']['physical_candidates'] if c['candidate_id']==mapped['candidate_id'])
        assert digest(c)==mapped['candidate_digest'] and c['pose']==ep['final_state']['placed_items'][0]['pose']
        assert calls and ev['monitor']['status']=='STABLE'
        cfg=load_jev_config(plan,'G00',monitor_snapshot=snap,admission=binding)
        assert cfg['stability_monitor']['enabled'] and cfg['stability_monitor']['algorithm']=='pct_exact_pose_network_v3'
        OUT.mkdir(exist_ok=True);(OUT/'disabled_request.json').write_text(json.dumps(body,indent=2)+'\n')
        (OUT/'request_receipt.json').write_text(json.dumps({'status':'PASS','real_calls':0,'monitor':'TEST_DOUBLE','algorithm':cfg['stability_monitor']['algorithm'],'selected_label':label,'candidate_id':c['candidate_id'],'candidate_digest':digest(c),'monitor_enabled':True},indent=2)+'\n')
