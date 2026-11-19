"""Pure P2 draft and source inventory; no permits, freeze, candidates or runs."""
import ast,json,hashlib,subprocess
from pathlib import Path
O=Path(__file__).resolve().parent;B=Path('semantic_pallet_planner/outputs');S=Path('semantic_pallet_planner/src/semantic_pallet_planner')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_kernel_completion as c,geometry_native_protocol as n,packaging_versions as v
 from semantic_pallet_planner.jev_select.contracts import digest,canonical,validate_schema
 from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
 assert not (O/'identity_receipt.json').exists(),'NO_OVERWRITE'
 files={str(f.relative_to(S)):sha(f) for f in S.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(S).parts)}
 expected=read(B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_20261119_01/source_manifest.json')
 assert len(files)==591 and files==expected['files'] and digest(files)=='8a860eea3ec22f8805eb6767660301acfd526653f566b1b1bd3e42b4af53578f'
 write('source_manifest.json',{'files':files,'source_files':591,'source_identity':digest(files)})
 Q=B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_RUN_QA_20261119_01';run=B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_RUN_20261119_01'
 for row in read(Q/'delivery_manifest.json')['files']:
  f=Path(row['path']);assert sha(f)==row['sha256'] and f.stat().st_size==row['size_bytes']
 # Read archived original ledger/recovery/timing evidence, no replay.
 history={'run':str(run),'accounting':read(run/'call_accounting.json'),'cases':read(run/'case_results.json')['counts'],'recovery_timing':{f.name:read(f) for f in (run/'R_timing').glob('*.json')}}
 write('historical_evidence_receipt.json',history)
 tasks=[]
 for case in ('K01','K02'):
  f=B/'GEOM_CANDIDATES_GP5_P1_20261117_01/p2_draft'/(case+'_task.json');raw=f.read_bytes()
  t=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw));tasks.append(t)
  (O/(case+'_task.json')).write_bytes(raw);write(case+'_identity.json',t['identity'])
 plan=p.prepare_order_plan(tasks,data_identity=digest({'unit':'GP5_P2_REAL_MONITOR_USABILITY_PREPARATION','tasks':[t['identity'] for t in tasks]}),scope=p.ACCEPTANCE,native=True)
 plan.update(assessment_limit=8,solver_limit=128);p.validate_order_plan(plan)
 assert plan['status']=='DRAFT' and plan['call_ledger_path'] is None
 write('acceptance_plan_DRAFT.json',plan);write('run_denominator_NOT_RUN.json',p.draft_run(plan))
 coverage=c.required_coverage(plan)
 write('required_coverage.json',coverage)
 matrix=[{**r,'method':'local_first_test_double','monitor_evidence_required':'REAL_KERNEL','raw_input':str(O/(r['task_id'].removeprefix('GP5_SYNTH_')+'_task.json')),'task_identity':next(t['identity'] for t in tasks if t['identity']['task_id']==r['task_id']),'expected_placed_items':len(r['poses']),'oriented_sizes':[[80.0,100.0,60.0] if pose['yaw_deg']==90 else [100.0,80.0,60.0] for pose in r['poses']],'actual':'NOT_RUN','checkpoint_requirement':'save consistent last-box selected/monitored/committed only for K01'} for r in coverage['primary']]
 write('matrix_DRAFT.json',{'status':'DRAFT_NOT_EXECUTABLE','rows':matrix,'denominator':4,'extra_cases':[{'id':'K03_ADAPTER_ONLY','status':'NOT_RUN_OUTSIDE_PROPOSAL'},{'id':'PUBLIC_REAL_NEGATIVE_E2E','status':'NOT_RUN_OUTSIDE_PROPOSAL'}]})
 write('recovery_DRAFT.json',{'status':'DRAFT_NOT_EXECUTABLE','rows':[{**r,'status':'NOT_RUN','new_assessment':int(r['phase']=='SELECTED'),'new_commit':int(r['phase']!='COMMITTED'),'monitor_reuse':int(r['phase']=='MONITORED'),'generation_publication_selection':[0,0,0],'checkpoint_source':'FUTURE_SAME_IDENTITY_SAME_RUN_PHASE_CONSISTENT_COPY','metrics_required':True,'timing_rule':'mixed/null => measured_partial only; no fabricated zero'} for r in coverage['recovery']],'denominator':6})
 snap=read(B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_20261119_01/monitor_snapshot.json');validate_monitor_snapshot(snap)
 write('monitor_metadata_READONLY_NOT_FROZEN.json',{'origin':'historical metadata only; future freeze separately authorized','snapshot':snap,'preflight':'PASS_READ_ONLY_NO_FREEZE'})
 # Resolve actual wire schemas; no draft interface names used as implementation.
 names=['geometry_order_plan_v1','geometry_kernel_launch_v1','geometry_scope_authorization_v1','geometry_scope_review_v1','geometry_order_execution_v1','geometry_order_durable_decision_v1','geometry_order_run_v1','geometry_order_metrics_v1','geometry_order_accounting_v1','geometry_real_kernel_receipt_v2','geometry_kernel_completion_review_v1']
 schemas=[]
 for name in [n.wire(plan,k) for k in names]+list(v.GEOMETRY_NATIVE_SCHEMAS.values()):
  path=S/'jev_select/schemas'/(name+'.schema.json')
  if path.exists() and name not in {r['name'] for r in schemas}:
   d=read(path);schemas.append({'name':name,'path':str(path),'sha256':sha(path),'required':d.get('required',[]),'additionalProperties':d.get('additionalProperties')})
 entries=[]
 for module in ('packaging_geometry_protocol','geometry_order_execution','geometry_order_meter','geometry_kernel_completion','geometry_native_protocol'):
  f=S/'jev_select'/(module+'.py');tree=ast.parse(f.read_bytes())
  entries.extend({'path':str(f),'name':x.name,'line':x.lineno,'kind':type(x).__name__} for x in tree.body if isinstance(x,(ast.FunctionDef,ast.ClassDef)))
 write('entrypoint_schema_inventory.json',{'entries':entries,'schemas':schemas,'wire_required_coverage_name':coverage['version'],'coverage_schema_note':'required_coverage returns derived dict; no standalone schema file, consumed by completion via digest and field checks','proposed_future_root':'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_REAL_MONITOR_RUN_PENDING_AUTHORIZATION','shared_ledger':'future frozen plan.call_ledger_path under same new root; not assigned in DRAFT','launch_schema':'geometry_kernel_launch_v2','completion_schema':'geometry_real_kernel_receipt_v3','runtime':'jev_packaging_geometry_order_v17'})
 write('budget_PROPOSAL.json',{'status':'PROPOSAL_NOT_AUTHORIZATION','contract_caps':{'assessment_entries':12,'solver_calls':512},'proposed_limits':{'assessment_entries':8,'solver_calls':128},'fresh':{'jobs':4,'assessment_entries':6,'commits':6,'expected_stable_solver_calls':56},'recovery':{'resumes':6,'assessment_entries':2,'commits':4,'monitor_reuses':2,'generation_publication_selection':0,'expected_stable_solver_calls':12},'combined_expected_stable_solver_calls':68,'derivation':'stable solve_network uses physical_feasibility + max_network_interior + one LP per contact vertex; single floor network4 vertices =>6 LP; upper two-box network8 =>10 LP plus baseline floor6 =>16 per upper assessment; fresh2*(K01 6 + K02 floor6 + upper16)=56; recovery2*6=12','solver_uncertainty':'static estimate only, numerical branches may terminate or differ; no LP executed.128 includes bounded headroom, never allows extra jobs/assessments','K03':'OUTSIDE_PROPOSAL_NOT_RUN','public_negative_E2E':'OUTSIDE_PROPOSAL_NOT_RUN','old_test_double_allowance_carryover':False,'actual_real_calls':0,'stop':'reserve each kind before call; cap exhaustion stops without retry/increase; ERROR/STARTED preserved'})
 write('identity_receipt.json',{'unit':'GP5_P2_REAL_MONITOR_USABILITY_PREPARATION','synced_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_files':591,'source_identity':digest(files),'branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':'FAST_FORWARD 45384dd1..46dd8c06','raw_tasks':{t['identity']['task_id']:t['identity'] for t in tasks},'monitor_metadata_sha256':sha(O/'monitor_metadata_READONLY_NOT_FROZEN.json'),'plan_digest':digest(plan),'new_freeze':'NOT_ISSUED','launch':'NOT_ISSUED','authorization':'NOT_ISSUED','completion':'NOT_ISSUED'})
 print('PASS source591, QA manifest, historical29/6 recovery receipts, DRAFT4+6, schema inventory and budget proposal; no dispatch/freeze')
if __name__=='__main__':main()
