"""New-source DRAFT only; preserve old inputs and evidence bytes."""
from pathlib import Path
import json,hashlib,subprocess
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_kernel_completion as c
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_20261119_01');B=O.parent;OLD=B/'GEOM_CANDIDATES_GP5_P2_REAL_MONITOR_PREPARATION_20261119_01';SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
read=lambda f:json.loads(f.read_bytes())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 assert not (O/'source_manifest.json').exists(),'NO_OVERWRITE'
 files={str(f.relative_to(SRC)):sha(f) for f in SRC.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(SRC).parts)}
 before=read(O/'source_before.json')['files'];assert set(files)==set(before) and len(files)==591
 changed=[n for n in files if files[n]!=before[n]]
 assert set(changed)=={'jev_select/packaging_geometry_protocol.py','jev_select/geometry_kernel_completion.py'}
 for rel,h in read(O/'historical_identity.json')['files'].items():assert sha(Path(rel))==h
 write('source_manifest.json',{'source_files':591,'source_identity':digest(files),'files':files})
 tasks=[]
 for case in ('K01','K02'):
  raw=(OLD/(case+'_task.json')).read_bytes();(O/(case+'_task.json')).write_bytes(raw)
  task=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw));tasks.append(task);write(case+'_identity.json',task['identity'])
 plan=p.prepare_order_plan(tasks,data_identity=digest({'unit':'GP5_P2_R1_EXTERNAL_REVIEW_IDENTITY_BINDING','tasks':[t['identity'] for t in tasks]}),scope=p.ACCEPTANCE,native=True)
 plan.update(assessment_limit=8,solver_limit=128);p.validate_order_plan(plan)
 assert plan['source_identity']==digest(files) and plan['status']=='DRAFT' and plan['call_ledger_path'] is None
 coverage=c.required_coverage(plan);old=read(OLD/'required_coverage.json');assert coverage['primary']==old['primary'] and coverage['recovery']==old['recovery']
 write('acceptance_plan_DRAFT.json',plan);write('required_coverage.json',coverage);write('run_denominator_NOT_RUN.json',p.draft_run(plan))
 write('matrix_DRAFT.json',{'status':'DRAFT_NOT_EXECUTABLE','plan_digest':digest(plan),'source_identity':digest(files),'rows':[{**row,'actual':'NOT_RUN','method':'local_first_test_double','monitor_evidence_required':'REAL_KERNEL','raw_input':str(O/(row['task_id'].removeprefix('GP5_SYNTH_')+'_task.json')),'task_identity':next(t['identity'] for t in tasks if t['identity']['task_id']==row['task_id']),'expected_placed_items':len(row['poses'])} for row in coverage['primary']],'denominator':4})
 recovery=read(OLD/'recovery_DRAFT.json');recovery.update(plan_digest=digest(plan),source_identity=digest(files));write('recovery_DRAFT.json',recovery)
 budget=read(OLD/'budget_PROPOSAL.json');budget.update(status='PROPOSAL_NOT_AUTHORIZATION',source_identity=digest(files),draft_plan_digest=digest(plan));write('budget_PROPOSAL.json',budget)
 write('identity_receipt.json',{'unit':'GP5_P2_R1_EXTERNAL_REVIEW_IDENTITY_BINDING','synced_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_files':591,'before_identity':read(O/'source_before.json')['source_identity'],'after_identity':digest(files),'changed_production_files':[{'path':n,'before':before[n],'after':files[n]} for n in sorted(changed)],'schema_changed':False,'new_draft_digest':digest(plan),'native_identity_fields':identity_fields(plan),'raw_inputs_preserved':True,'old_evidence_preserved':True,'historical_members_checked':len(read(O/'historical_identity.json')['files']),'new_freeze':'NOT_ISSUED','authorization_launch_completion':'NOT_ISSUED','real_calls':0})
 print('PASS source591 identity',digest(files),'two production files only; new DRAFT4/recovery6; raw inputs/history unchanged; proposals8/128; dispatch0')
if __name__=='__main__':main()
