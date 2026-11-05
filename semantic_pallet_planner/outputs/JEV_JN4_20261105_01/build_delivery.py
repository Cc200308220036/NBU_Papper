"""Build a blocked JN4-A delivery from saved source audit; never runs orders.

Run from repository root. Does not perform new data selection or source audit.
"""
from pathlib import Path
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select import packaging_evaluation_plan as ep
from semantic_pallet_planner.jev_select.packaging_source_audit import load,sha,validate_partition
from semantic_pallet_planner.jev_select.contracts import digest,canonical
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.dataset_j4 import verify_seal
from semantic_pallet_planner.jev_select.packaging_reanalysis import RULE
from semantic_pallet_planner.jev_select.packaging_experience import RULE as RETRIEVAL, validate_snapshot as validate_T
from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest,QUESTION,OBJECTIVE,INSTRUCTION,load_runtime_dataset
ROOT=Path('semantic_pallet_planner/outputs/JEV_JN4_20261105_01')
PACKAGE=Path('semantic_pallet_planner/src/semantic_pallet_planner')
O=Path('semantic_pallet_planner/outputs')
T='semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json'
E='semantic_pallet_planner/outputs/JEV_JN3_20261104_02/contrast_snapshot.json'
BLOCKERS=[
 'NO_VERIFIED_UNSEEN_COMPONENT: local records are incomplete; no positive closed history attestation for remaining components',
 'NO_ADMITTED_TEST_TASKS: data materialization deliberately not performed on UNKNOWN_EXPOSURE sources',
 'EXECUTION_ADAPTER_NOT_IMPLEMENTED: v9 is limited to 2 exposed train tasks and none/T/E; new unified local+remote+placebo protocol and recovery validation required before any JN4-B',
]
def write(name,value):
 p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')

def main():
 audit=load(ROOT/'source_audit.json');history=load(ROOT/'history_inventory.json')
 assert not history['parse_errors']
 parents={}
 for name in ['JEV_JN3_20261105_01','JEV_JN3_20261104_01','JEV_JN3_20261104_02','JEV_JN2_20261104_03']:
  m=load(O/name/'delivery_manifest.json'); mapping=m['files_sha256']
  assert all((O/name/n).is_file() and sha(O/name/n)==h for n,h in mapping.items()),name
  doc_drift=[n for n,h in m.get('documentation_sha256',{}).items() if not Path(n).is_file() or sha(n)!=h]
  parents[name]={'status':'PASS','scope':'saved hashes, no replay','files_verified':len(mapping),'historical_document_reference_drift':doc_drift,'manifest_sha256':sha(O/name/'delivery_manifest.json')}
 parent_source=load(O/'JEV_JN3_20261105_01/source_manifest.json');current=source_manifest()
 modified={k for k,v in parent_source.items() if current.get(k)!=v};assert modified=={'jev_select/contracts.py'}
 assert len(parent_source)==421 and not set(parent_source)-set(current)
 write('parent_identity_verification.json',{'head':'ee060c8d','initial_worktree':'clean','applicable_agents':['AGENTS.md'],
   'parent_packages':parents,'baseline_production_files':421,'production_files':len(current),
   'modified_existing':sorted(modified),'added':sorted(set(current)-set(parent_source)),
   'parent_claims_vs_evidence':{'pilot_suggestion':load(O/'JEV_JN3_20261105_01/memory_pilot_receipt.json'),
   'verification_scope':'saved file hashes and contracts; no historical physical replay or model call'}})
 write('source_manifest.json',current)
 for name in current:
  target=ROOT/'plan/code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PACKAGE/name,target)
 # Preserve actual algorithm support files in addition to the production .py/.json identity.
 aux={}
 for name in ['LICENSE','compatibility.patch','UPSTREAM.md']:
  p=PACKAGE/'jev_select/stability/vendor/pct'/name
  dest=ROOT/'plan/code_snapshot'/p.relative_to(PACKAGE);shutil.copyfile(p,dest);aux[str(p.relative_to(PACKAGE))]=sha(p)
 write('algorithm_auxiliary_manifest.json',aux)
 ts=validate_T(load(T));es=load(E);assert ts['source_groups']==es['source_groups']
 control=ep.build_control(es);ep.validate_control(control,es);write('memory/unrelated_E_snapshot.json',control)
 write('memory/snapshot_refs.json',{'T':{'path':T,'sha256':sha(T),'snapshot_digest':ts['snapshot_digest']},
  'E':{'path':E,'sha256':sha(E),'snapshot_digest':es['snapshot_digest']},
  'control':{'path':'memory/unrelated_E_snapshot.json','snapshot_digest':control['snapshot_digest']},
  'review':'deterministic placebo construction; not human or LLM evidence review',
  'length_comparison':[{'reference':x['reference_public_digest'],'entry_chars':x['chars'],'entry_utf8_bytes':x['utf8_bytes'],
   'array_chars':x['chars']+2,'tolerance':0} for x in control['entries']]})
 assignments=[{'component':r['component'],'split':r['assigned_split'],'exposure_status':r['exposure_status'],
  'raw_keys':r['raw_keys'],'reason':r['reason']} for r in audit['components']]
 validate_partition(assignments)
 write('split_manifest.json',{'version':'jev_source_split_blocked_v1','assignments':assignments,
   'train':[r['component'] for r in assignments if r['split']=='train'],'dev':[],'test':[],
   'excluded':[r['component'] for r in assignments if r['split']=='excluded'],
   'note':'train is quarantine for contaminated components, not new training authorization; dev/test empty; old splits untouched'})
 write('near_duplicate_components.json',{'rule_ref':'plan/source_audit_registration.json','components':{x['component']:x['raw_keys'] for x in audit['components']},'union_edges':audit['edges'],'fingerprints':audit['descriptors']})
 raw=load('raw/bed_bpp/bed-bpp_v1.json');provenance=load('semantic_pallet_dataset_v1/provenance/manifest.json')
 assert sha('raw/bed_bpp/bed-bpp_v1.json')==provenance['sources'][0]['sha256']
 write('source_access_receipt.json',{'raw_orders':len(raw),'raw_sha256':sha('raw/bed_bpp/bed-bpp_v1.json'),
  'components':len(audit['components']),'status_counts':audit['counts'],'history_metadata_files':len(history['files']),
  'historical_status_semantics':'registered train/dev/test use or frozen source/input metadata; not all hits prove actual model calls; evidence pointers retain this distinction',
  'current_access':'all raw mechanical records statically accessed in JN4-A; no policy, trajectory, model or test tuning',
  'strict_unseen_components':0,'T_E_source_groups':ts['source_groups'],
  'T_E_test_overlap':[],'overlap_interpretation':'empty test set; vacuous isolation check, not data readiness',
  'v1_group_manifest_sha256':sha('semantic_pallet_dataset_v1/splits/group_manifest.json'),
  'v1_provenance_sha256':sha('semantic_pallet_dataset_v1/provenance/manifest.json'),
  'other_source':'MixedPalletBoxes referenced as generator logic, not an independent physical order corpus in this loader; no download or new synthetic orders'})
 spec=load('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/configs/packaging_load_v1.json')
 write('plan/data_build_registration.json',{'version':'jev_evaluation_data_registration_v1','status':'BLOCKED_NO_ADMITTED_SOURCE','materialized':False,
  'scope':'existing BED-BPP raw corpus only; no further collection; VERIFIED_UNSEEN components only',
  'size':{'minimum':6,'maximum':6,'variants_per_source':1,'repeats':1,'basis':'descriptive 3 fixed length strata, 2 sources each; no estimated model variance or power claim'},
  'strata':{'length_bins':[[14,20],[21,30],[31,40]],'per_bin':2,
   'mass_heterogeneity':'CV <= .25 vs > .25','size_heterogeneity':'rotation-normalized distinct box sizes / count <= .5 vs > .5',
   'allocation':'in each length bin sort verified components by sha256([20261105,component]); choose first two; report mass/size/capacity diversity without replacing low diversity sources'},
  'seed':20261105,'representative':'lexicographically smallest raw key in admitted component; full arrival sequence, no truncation',
  'variant':'controlled_heterogeneous only, frozen packaging seed 20261102 and profile hash/profile capacities',
  'calibration':spec['calibration'],'profiles':spec['profiles'],'packaging_config_sha256':sha('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/configs/packaging_load_v1.json'),
  'rule':'reuse profile_for and runtime_task; new explicitly versioned derived loader needed, do not bypass old four-source guard; source mass/dimensions unchanged; no category/region/AST',
  'feasibility':'UNKNOWN; no new witness; no filtering by method outcomes, packing difficulty, hits or monitor results',
  'static_invalid':'record malformed units/source gaps separately; no silent replacement or easier substitution; quota shortage => NOT_READY',
  'new_package_receipt':{'status':'NOT_MATERIALIZED','independent_sources':0,'tasks':0,'variants':0}})
 write('method_protocol_contract.json',{'version':'jev_evaluation_method_design_v1','registry':ep.REGISTRY,'method_order':list(ep.REGISTRY),
  'runtime_implementation':'NOT_IMPLEMENTED_FOR_JN4; no v9 schema widening',
  'audit_existing_v9':{'local_methods':False,'placebo':False,'arbitrary_test_tasks':False,'none_T_E_per_public_decision':True,
    'reuse':['packaging_experiment._run_job','episode.run_episode','commit_physical','PilotLedger','MemoryDriver','DECISION_READY persistence'],
    'required_new':'central version route, closed config/context/bundle/selection/checkpoint/metrics/ledger/plan/run schemas; local same protocol + explicit unrelated memory kind; no parallel engine'},
  'execution_protocol':'UNASSIGNED_BLOCKED; cannot describe proposed v10 as implemented',
  'native_model_observations':{'determinism':'UNKNOWN; no repeat pilot, no claim of immutable model weights','probabilities':'preserve raw native precision and availability; no inferred reasons or confidence; provider tie policy UNKNOWN unless documented','service_drift':'served model or dependency change stops batch; no silent mixed repetitions'},
  'base_model':'jev-1.14.0','endpoint':'https://api.typesafe.ai/v1/systemone','availability':'UNKNOWN_NOT_PROBED',
  'service_contract_reference':'parent JN3-C official_api_contract.json; identity/official protocol must be checked before freezing an executable replacement plan; no auth loaded here',
  'prompt_version':'packaging_load_en_v1','instruction':INSTRUCTION,'question':QUESTION,'objective':OBJECTIVE,
  'source_of_truth':'same exact base prompt/body encoding for all remote methods; only registered memory varies',
  'retrieval':RETRIEVAL,'control_rule':ep.CONTROL_RULE,
  'public_input':'current public state+criteria only; no future arrivals, private task, PCT diagnoses or source IDs as scoring features',
  'private_source_exclusion':'entire connected component aliases/variants/forks excluded from T/E/control before scoring',
  'singleton':'zero model sends; view hits and actual request injections counted separately',
  'empty_hit':'retain registered method identity with explicit empty MemoryView',
  'recovery':'persist DECISION_READY body/query/view/snapshot before sending; saved choice/monitor/commit immutable; no resend/retrieve/reselect/remonitor/recommit',
  'physics':{'identity':physical_manifest(),'monitor_enabled':True,'algorithm':'pct_contact_network_v2','result':'pct_stability_result_v2',
    'order':'original candidates -> independent choice -> save -> independent-state monitor -> save -> original commit or stop',
    'forbidden':'PCT prefilter/reordering/labels, alternate choice on failure, physical parameter or tolerance changes; area ledger separate'},
  'candidate_limits':{'per_object_top_k':16,'joint':48,'display_seed':20261102},
  'information_budget':{'max_entries':1,'max_chars':12000,'max_utf8_bytes':16000,'whole_entry_only':True,
    'actual_token_lengths':'report from sent body, not assumed equal; E placebo exact canonical byte length only'}})
 write('statistical_analysis_plan.json',{'version':'jev_source_paired_analysis_v1','research_question':'conditional loading effects of frozen T/E on independent unseen sources; E superiority not required',
  'evaluation_rule':RULE,'whole_order_interpretation':'pair same task/dataset/denominators/common contract; different trajectories allowed, no identical per-step pool claim; stable complete first then volume, count/mass then equal-loading compactness',
  'primary_comparisons':[['jev_with_trajectory','jev_no_memory'],['jev_with_contrast_experience','jev_no_memory'],['jev_with_contrast_experience','jev_with_trajectory'],['jev_with_contrast_experience','jev_with_unrelated_E_control']],
  'local_baselines':'both fully tabulated for every source; no historical v5/v6 scores mixed into common-protocol pairs',
  'statistical_unit':'connected source component; variants and repeated trajectories nested, never inflate N; single variant/repeat selected',
  'estimands':['stable complete rate difference','paired loaded-volume proportion difference','loaded count/mass difference','height/envelope differences including loading wins and reverse costs'],
  'aggregation':'per-source equal-weight paired differences; mean, median, min/max, valid source count and full registered source/job denominators; no best-seed selection',
  'uncertainty':{'method':'95% percentile bootstrap of independent source means for paired volume/count/mass/height/envelope deltas','draws':10000,'seed':20261105,
    'implementation_spec':'Python random.Random(seed); sorted valid source IDs; choices(ids,k=N) once per draw shared across metrics; quantiles linear at (B-1)*p; N<6 => descriptive range only, CI NOT_ESTIMABLE',
    'binary_completion':'report per-source pairs and rates, no small-N significance claims','limitation':'bootstrap exploratory conditional on admitted finite sample, no model stochastic variance estimate; one repeat cannot estimate it'},
  'pair_invalid':['ERROR','UNKNOWN_SEND','TECHNICAL_LIMIT','CANCELLED','NOT_RUN','UNASSESSABLE or missing monitor coverage/metric/identity'],
  'invalid_policy':'retain all jobs/categories and reasons in full denominator; no strategy winner label for invalid pair; valid-pair descriptions may be biased, report counts and full-cohort volume delta bounds [-1,1] per missing pair',
  'valid_natural':['COMPLETE','EMPTY_POOL','PREDICTED_STATIC_INSTABILITY with certificate'],
  'failures':'all monitor reason/coverage, first stop progress, timeout, cost/usage, latency p50/p95 with n, injection/query/view/body nonempty rates and singleton counts',
  'interpretation':['EMPTY_POOL is sampled-pool stop, not infeasibility proof','prediction is static instability, not real collapse','hard-filter zero violations is not selector benefit','equal loaded volume does not prove equal layouts','remaining capacity sum not future loadability','observational trajectory differences not single-choice causal proof']})
 write('budget_and_stop_contract.json',{'version':'jev_evaluation_blocked_budget_v1','matrix':ep.budget_for_tasks([]),
  'admitted_sources':0,'variants':0,'repetitions':1,'methods':6,'first_batch_jobs':[],
  'future_conditional_formula':'6 verified sources * 1 variant * 1 repeat * 6 methods =36 natural slots, 24 remote slots; sends=4*sum(actual box counts). Conditional design only, no executable or authorized slots now.',
  'order':'sources sorted by preregistered hash within length bins; within source registry insertion order; first admitted source all six methods is technical gate',
  'watchdog':{'max_events':10000,'max_active_wall_s':1800,'network_timeout_s':30,'max_retries':0,'boundary':'persistent event boundaries and transport timeout; not hard realtime; active wall survives resume'},
  'first_gate':['source/config/model/service/dependency identities match','all six methods final with exact ledger/metric/body/monitor/commit consistency','at least one actual nonempty E and E-control request; T injection coverage reported; absent gate coverage => pause, not replacement','saved-record validation without dispatch; documented scope stops and fractions retained'],
  'benefit_gate':False,'stop_batch':['UNKNOWN_SEND','core technical/metrics/recovery error','watchdog','cancellation','model unavailable','service/dependency/source/snapshot identity drift','unexplained or previously unregistered scope reason'],
  'scope':'known POSE_HEIGHT_MISMATCH and declared conservative monitor range stops remain UNASSESSABLE, invalidate pair, retain full denominator; coverage reviewed without choosing by benefit',
  'continuation':'persist first gate before continue; no benefit-dependent sample/method/seed change; failed technical gate leaves remainder NOT_RUN; new protocol identity requires separately explicit new version, never silent mixed batch',
  'budget_recovery':'global/per-job caps tied to all configs/plan identity; reservation before send, UNKNOWN_SEND consumes slot and stops; no reset on resume or refund of unused slots',
  'actual':{'model_api_calls':0,'formal_test_jobs_executed':0,'credential_reads':0,'cost_usd':'UNKNOWN'}})
 data=load_runtime_dataset(O/'DATA_JEV_PACKAGING_LOAD_20261102_02')
 write('static_data_validation.json',{'status':'PASS_EXISTING_EXPOSED_PACKAGE_ONLY','data_identity':data['data_identity'],'tasks_loaded':len(data['tasks']),
  'feasibility':'all UNKNOWN retained','new_test_data_loading':'NOT_RUN_NO_ADMITTED_DATA','calibration':'unchanged frozen m_ref=8.586, scale=9; no test refit',
  'note':'load/schema/provenance only; no candidates or formal jobs'})
 write('frozen_experiment_matrix.json',ep.budget_for_tasks([]))
 # Plans bind contracts/data/parents by bytes, excluding their own future receipts.
 external={T:sha(T),E:sha(E),'raw/bed_bpp/bed-bpp_v1.json':sha('raw/bed_bpp/bed-bpp_v1.json')}
 for n in ['JEV_JN3_20261105_01','JEV_JN3_20261104_01','JEV_JN3_20261104_02','JEV_JN2_20261104_03']:
  for f in ['delivery_manifest.json','handoff.json']:
   name=str(O/n/f);external[name]=sha(name)
 for name in ['semantic_pallet_dataset_v1/provenance/manifest.json','semantic_pallet_dataset_v1/splits/group_manifest.json']:
  external[name]=sha(name)
 artifacts=['plan/source_audit_registration.json','plan/data_build_registration.json','source_audit.json','history_inventory.json','exposure_records.json','split_manifest.json',
  'near_duplicate_components.json','source_access_receipt.json','method_protocol_contract.json','statistical_analysis_plan.json','budget_and_stop_contract.json',
  'memory/unrelated_E_snapshot.json','memory/snapshot_refs.json','frozen_experiment_matrix.json','source_manifest.json','algorithm_auxiliary_manifest.json']
 plan={'version':ep.VERSION,'status':'NOT_READY','JN4_B_admitted':False,'frozen_at':'2026-11-05 Asia/Shanghai',
  'method_registry':ep.REGISTRY,'artifacts':{n:sha(ROOT/n) for n in artifacts},'external_refs':external,
  'snapshots':{'T':T,'E':E,'control':'memory/unrelated_E_snapshot.json'},'matrix':ep.budget_for_tasks([]),'blockers':BLOCKERS}
 plan['plan_digest']=digest(plan);write('plan/plan.json',plan)
 result=ep.validate_plan(ROOT,repo='.');write('plan_validation.json',result)
 try:ep.validate_plan(ROOT,repo='.',for_execution=True)
 except ValueError as exc:write('execution_admission_rejection.json',{'status':'EXPECTED_REJECTION','reason':str(exc),'dispatched_jobs':0,'requests':0})
 else:raise AssertionError('blocked execution admitted')
 print(canonical({'plan_digest':plan['plan_digest'],'sources':0,'jobs':0,'status':'NOT_READY','production_files':len(current)}))

if __name__=='__main__':main()
