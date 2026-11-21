"""Temporary-only fabricated v17 evidence; never a production credential.

Executed with an independently copied frozen GP5 package. All assessment and LP
results are offline substitutes. The original Schema/admission/durable gates run.
"""
import copy
from contextlib import ExitStack
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import socket
import sys
from unittest.mock import patch

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select import geometry_order_execution as o
from semantic_pallet_planner.jev_select import geometry_order_accounting as a
from semantic_pallet_planner.jev_select.contracts import canonical, digest
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment
from semantic_pallet_planner.jev_select.stability import exact_adapter, balance_network, exact_contracts
from semantic_pallet_planner.jev_select.stability.runtime import environment as monitor_environment
from semantic_pallet_planner.jev_select.ledger import write, read


def build(root):
    assert root.is_relative_to(Path('/tmp')) and root.name == 'SYNTHETIC_ONLY'
    root.mkdir()
    write(root/'SYNTHETIC_ONLY.json', {'not_a_production_credential': True, 'actual_kernel_calls': 0})
    snap=read('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json')
    snap['execution_environment']=monitor_environment()
    # No freezer: the archived identity is verified by the original preflight.
    o.validate_monitor_snapshot(snap)
    def ref(path, value=None):
        if value is not None:write(path,value)
        return {'path':str(path),'sha256':p.sha(path.read_bytes())}
    adapted=[]
    for case in ('K01','K02'):
        raw=canonical(p.synthetic_task(case)).encode()
        adapted.append(p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw)))
    plan=p.prepare_order_plan(adapted,data_identity=digest('SYNTHETIC_ONLY'),scope=p.ACCEPTANCE,native=True)
    plan.update(status='FROZEN',call_ledger_path=str(root/'calls.json'))
    ident=identity_fields(plan)
    approvals={**ident,'scope':p.ACCEPTANCE,'plan_digest':digest(plan),'status':'APPROVED'}
    auth=ref(root/'authorization.json',{'version':'geometry_scope_authorization_v2',**approvals})
    rev=ref(root/'launch_review.json',{'version':'geometry_scope_review_v2',**approvals})
    launch={**ident,'version':'geometry_kernel_launch_v2','scope':p.ACCEPTANCE,'plan_digest':digest(plan),
            'source_identity':plan['source_identity'],'environment_digest':digest(environment()),
            'monitor_digest':digest(snap),'status':'APPROVED','authorization':auth,'review':rev}
    # Any missing schema-required fields cause fixture construction to fail.
    p.validate_admission(plan,snap,launch)
    def fake_lp(*args,**kw):return None
    def fake_assess(state,box,cfg):
        balance_network.linprog('SYNTHETIC_ONLY')
        return exact_contracts.ExactResult(status='STABLE',reason_code='SYNTHETIC_FIXTURE',
            state_digest=digest(asdict(state)),candidate_digest=digest(asdict(box)),
            candidate_id=box.item_id,config_digest=digest(asdict(cfg)),algorithm_identity=snap['algorithm_identity'],
            baseline_status='STABLE',first_bad_prefix=None,failed_item_id=None,height_delta_mm=0.0,
            evaluated_pose=None,kernel_calls=1,diagnostics={},duration_s=0.0)
    records=[];recovery=[];saved={};results={}
    with ExitStack() as stack:
        stack.enter_context(patch.object(exact_adapter,'assess_candidate',fake_assess))
        stack.enter_context(patch.object(balance_network,'linprog',fake_lp))
        stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
        for name in ('exact_freeze','freeze'):
            stack.enter_context(patch('semantic_pallet_planner.jev_select.stability.monitor.'+name,side_effect=AssertionError('FREEZE_FORBIDDEN')))
        for job in plan['jobs']:
            jid=job['job_id'];task=adapted[0 if job['task_id'].endswith('K01') else 1]
            parent=root/'primary'/'jobs'/jid
            def capture(cp):
                if cp['phase'] in ('SELECTED','MONITORED','COMMITTED') and jid in ('J00','J01'):
                    phase=cp['phase'];dest=root/'recovery'/jid/phase/'jobs'/jid
                    write(parent/'checkpoint.json',cp)
                    shutil.copytree(parent,dest)
                    saved[jid,phase]=copy.deepcopy(cp)
            out=o.run_order_job(plan,jid,task,monitor_snapshot=snap,admission=launch,root=root/'primary',on_checkpoint=capture)
            assert out['summary']['completed'],out['checkpoint']['reason']
            records.append(ref(parent/'record.json'));results[jid]=out
        for jid in ('J00','J01'):
            parent=root/'primary'/'jobs'/jid
            cfg=read(parent/'config.json')
            for phase in ('SELECTED','MONITORED','COMMITTED'):
                dest=root/'recovery'/jid/phase/'jobs'/jid;cp=saved[jid,phase]
                cred=a.seal_phase_snapshot_credential(parent,dest,cfg,jid,phase,cp,parent_result=results[jid])
                before=ref(dest/'before.json',cp)
                out=o.run_order_job(plan,jid,adapted[0],monitor_snapshot=snap,admission=launch,
                    root=dest.parents[1],resume=cp,phase_credential=cred)
                assert out['summary']['completed']
                recovery.append({'job_id':jid,'phase':phase,'before':before,'after':ref(dest/'record.json'),'accounting':ref(dest/'accounting.json')})
    log=read(root/'calls.json')
    receipt={**ident,'version':'geometry_real_kernel_receipt_v3','scope':p.ACCEPTANCE,'status':'ACCEPTED',
        'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(snap),
        'launch':ref(root/'launch.json',launch),'acceptance_plan':ref(root/'acceptance.json',plan),
        'records':records,'recovery':recovery,'counts':log['counts'],'counter_log':ref(root/'calls.json')}
    review={**ident,'version':'geometry_kernel_completion_review_v2','scope':p.ACCEPTANCE,'status':'APPROVED',
        'acceptance_plan_digest':digest(plan),'records_digest':digest(records),'recovery_digest':digest(recovery),
        'counter_log':receipt['counter_log'],'coverage_digest':digest(required_coverage(plan))}
    receipt['review']=ref(root/'completion_review.json',review)
    p.validate_real_kernel_receipt(receipt,plan,snap)
    ref(root/'receipt.json',receipt);ref(root/'monitor.json',snap)

if __name__=='__main__':build(Path(sys.argv[1]).resolve())
