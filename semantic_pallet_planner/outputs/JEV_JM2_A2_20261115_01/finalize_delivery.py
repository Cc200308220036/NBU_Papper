"""Local identity/manifest finalizer, no execution or remote calls."""
import ast,hashlib,importlib.metadata,json,platform,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
PKG=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
REPORT='docs/03_阶段产出分析/Jev/Jev_JM2-A2非空T投影与角色一致性工程验收_20261115_01.md'
def read(p):return json.loads(Path(p).read_text())
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def entry(p):
 p=Path(p);return dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p))
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def main():
 head=git('rev-parse','HEAD');assert head=='858c4fb9091f00ecafa08c410b1cb706ac4ef1ab'
 subprocess.check_call(['git','merge-base','--is-ancestor','858c4fb9','HEAD'],cwd=ROOT)
 old=read(ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A1_20261115_01/source_manifest.json')
 added=['jev_select/packaging_t_projection.py']+['jev_select/schemas/'+n+'.schema.json' for n in ('jm_t_projection_v1','jm_t_query_v1','jm_t_observation_v1')]
 source={n:sha(PKG/n) for n in sorted(set(old)|set(added))}
 changes={n:dict(before=h,after=source[n]) for n,h in old.items() if h!=source[n]}
 assert set(changes)=={'jev_select/contracts.py','jev_select/packaging_versions.py'}
 # Registry changes must be exactly additive; no old guards or schemas altered.
 for n in changes:
  before=subprocess.check_output(['git','show',head+':semantic_pallet_planner/src/semantic_pallet_planner/'+n],cwd=ROOT).decode()
  after=(PKG/n).read_text()
  if n.endswith('contracts.py'):
   assert after.replace("'jm_t_projection_v1','jm_t_query_v1',",'')==before
  else:assert after.startswith(before)
 write(OUT/'source_manifest.json',source)
 source_digest=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 write(OUT/'source_identity.json',dict(version='jm2_a2_source_identity_v1',entry_head=head,source_digest=source_digest,source_manifest=entry(OUT/'source_manifest.json'),files=len(source),changed_existing_files=changes,added_files=added,python=sys.version,platform=platform.platform(),dependencies={n:importlib.metadata.version(n) for n in ('jsonschema',)},historical_identity_resigned=False,old_freeze_identity='255afe2a80736838105c759a46597aa8853bdba736b7795672a491b86bbbcce1',recovery='FORBIDDEN_TO_RESUME_OLD_FROZEN_EXECUTION_WITH_NEW_SOURCE',source_identity_scope='new offline engineering identity only'))
 files=['__init__.py','packaging_t_projection.py','packaging_scenario_features.py','packaging_jev_sampling.py','packaging_versions.py','contracts.py','packaging_experience.py','ledger.py']
 review=read(OUT/'import_and_side_effect_review.json');review['final_static_imports']=[dict(file=entry(PKG/'jev_select'/n),imports=[ast.unparse(x) for x in ast.parse((PKG/'jev_select'/n).read_text()).body if isinstance(x,(ast.Import,ast.ImportFrom))]) for n in files];review['extra_import_review']='contracts: jsonschema + stdlib; legacy experience: contracts/ledger + stdlib; ledger has function-only writes, no import-time dispatch';write(OUT/'import_and_side_effect_review.json',review)
 test_log=(OUT/'unit_tests.log').read_text();assert 'Ran 6 tests' in test_log and test_log.rstrip().endswith('OK')
 receipt=read(OUT/'validation_receipt.json');receipt['central_jsonschema']='PASS_ACTUAL_CENTRAL_SCHEMA_ROUTE_AND_OLD_GUARD';receipt['unit_tests']=6;write(OUT/'validation_receipt.json',receipt)
 write(OUT/'entry_identity.json',dict(root='NBU_Papper',branch=git('branch','--show-current'),upstream=git('rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}'),before_pull='47a70829334142d422c0877fd525af8c8175f91c',actual_head=head,QA_858c4fb9_contained=True,pull='git pull --ff-only: fast-forward; first sandbox attempt FETCH_HEAD read-only, authorized escalation succeeded',initial_workspace='CLEAN',preserved_user_changes='NONE_PRESENT',stash_reset_force_push=False,SKILL='EXCLUDED_NO_STAGE_COMMIT_UPLOAD',commit_push='NOT_PERFORMED'))
 write(OUT/'development_attempts.json',dict(version='jm2_a2_development_attempts_v1',attempts=[dict(step='initial saved builder',result='PASS_5_CARDS_9_PAIRS'),dict(step='added placed_item_ratio metric; public identifier leakage check',result='FAIL_ASSERTION_FALSE_POSITIVE',cause='substring item_ matched metric key placed_item_ratio; no original identifier was exposed',fix='inspect string leaf values for original item_ identifiers, separately reject candidate_id keys'),dict(step='corrected guard and final validation',result='PASS',evidence=['saved_checks.log','unit_tests.log','check_attempts.json'])]))
 acceptance=[dict(id=n,status='PASS_A2_LIMITED_ENGINEERING',evidence=e) for n,e in [('M21-01','5 real nonempty cards; old guard dynamically rejected; 1524 scalar provenance entries'),('M21-03','closed query/card schemas; private audit index separate; no live injection'),('M21-04','all 9 pairs:4 improved/3 degraded/2 neutral; policy identity/results/cost/limits retained'),('M21-06','all 18 exact branch actions checked against original full saved pool; roles/coordinate/orientation/delta tamper refusals')]]
 # Counts are taken from final receipt, not copied from an earlier run.
 acceptance[0]['evidence']=f"5 real nonempty cards; old guard dynamically rejected; {receipt['public_field_evidence_count']} scalar provenance entries"
 write(OUT/'acceptance.json',dict(version='jm2_a2_acceptance_v1',plan='JM-plan-v2',items=acceptance,not_closed=[dict(id='M21-07',status='NOT_RUN_A3'),dict(id='M21-02/M21-05',status='INHERITED_A1_LIMITED_NOT_REOPENED')],engineering_status='COMPLETE_A2_DECLARED_SCOPE_PENDING_INDEPENDENT_QA',research_result='NOT_ESTABLISHED',next_stage_admission='INDEPENDENT_QA_ONLY'))
 write(OUT/'trajectory_v2_readiness.json',dict(version='jm2_a2_trajectory_readiness_v1',projection='READY_FOR_INDEPENDENT_QA_ONLY',snapshot='CANDIDATE_ARCHIVE_ONLY',A3='NOT_RUN',M21_07='NOT_CLOSED',retrieval='NOT_IMPLEMENTED',real_request_injection='NOT_RUN',execution_eligible=False,limits=['P01 conflict','P04 single observation','coverage PARTIAL','cross-start support 0','finite A1 features do not establish sufficiency','known non-UNKNOWN monetary costs unsupported by v1 schema: reject rather than fabricate']))
 write(OUT/'handoff.json',dict(version='jm2_a2_handoff_v1',date='2026-11-15',unit='JM2-A2 only',plan='JM-plan-v2',actual_head=head,parent_QA='semantic_pallet_planner/outputs/JEV_JM2_A1_QA_20261115_01/handoff.json',parent_A1='semantic_pallet_planner/outputs/JEV_JM2_A1_20261115_01/handoff.json',parent_C2='semantic_pallet_planner/outputs/JEV_JM1_C2_REAL_SUFFIXES_20261113_01/handoff.json',report=REPORT,snapshot='case_snapshot_candidate.json',evidence='field_and_claim_evidence.json',private='private_audit_index.json',denominators='inherited_denominators.json',acceptance='acceptance.json',source='source_identity.json',validation='validation_receipt.json',failures=['development_attempts.json','check_attempts.json'],readiness='trajectory_v2_readiness.json',manifest='delivery_manifest.json',engineering_status='COMPLETE_A2_DECLARED_SCOPE_PENDING_INDEPENDENT_QA',research_result='NOT_ESTABLISHED',next_stage_admission='INDEPENDENT_QA_ONLY',real_calls_authorized=0,actual_operations=receipt['actual_operations'],stop=True,stop_reason='A2完成交回独立质检；不推进A3或后续，不编写下一任务提示词'))
 paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='delivery_manifest.json']
 paths += [PKG/n for n in added]+[PKG/n for n in changes]+[ROOT/'semantic_pallet_planner/tests/unit/test_packaging_t_projection.py',ROOT/REPORT]
 write(OUT/'delivery_manifest.json',dict(version='jm2_a2_delivery_manifest_v1',self_hash_excluded=True,excluded=['SKILL/ entire tree','shared navigation README','__pycache__'],files=[entry(p) for p in sorted(paths)]))
 print('FINALIZED_NEW_A2_IDENTITY_AND_MANIFEST',len(paths),source_digest)
if __name__=='__main__':main()
