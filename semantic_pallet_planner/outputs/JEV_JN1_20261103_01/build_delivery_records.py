from pathlib import Path
import json,hashlib,subprocess
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_remote import VERSIONS,REGISTRY
from semantic_pallet_planner.jev_select.experiment import source_manifest,file_manifest
from semantic_pallet_planner.jev_select.transport import credential
root=Path('semantic_pallet_planner/outputs/JEV_JN1_20261103_01')
p=read(root/'preregistration.json');c=read(root/'config.snapshot.json');e=read(root/'event.json');s=e['selection'];stats=read(root/'request_statistics.json')
chosen=next(x for x in e['bundle']['physical_candidates'] if x['candidate_id']==s['selected_candidate_id'])
write(root/'resolved_action.json',{'version':'jev_exact_candidate_binding_v1','decision_record_digest':digest(read(root/'decision_record.json')),
 'candidate_pool_digest':digest(e['bundle']),'selected_display_id':s['selected_display_id'],'selected_candidate_id':s['selected_candidate_id'],
 'candidate_digest':digest(chosen),'exact_candidate':chosen,'execution_credential':e['proposed_action'],'submitted_once':e['event']=='PLACE'})
write(root/'scope_stop.json',{'stage':'JN1-A','reason':'JN1_A_SINGLE_DECISION_BOUNDARY','stage_closed':True,
 'order_complete':False,'complete_order_run':'NOT_RUN','JN1_B':'NOT_RUN','next_model_decision':'NOT_RUN',
 'checkpoint_phase':read(root/'checkpoint.json')['phase'],'explanation':'READY is resumable order state; stage driver explicitly closes after one decision and must not continue this order under A authorization.'})
interfaces={'version':'jev_packaging_remote_interfaces_v1','versions':VERSIONS,'method_registry':REGISTRY,
 'factory':'packaging_protocol.selector_factory(method, execution_version=jev_packaging_remote_v6, config, transport, ledger, job_id)',
 'config_factory':'packaging_remote.load_remote_config(data_identity, task_digest, method, enabled=False)',
 'ledger':'packaging_remote.RequestLedger(root, max_sends=1, hook=None)',
 'selector':'PackagingRemoteSelector.select(context, decision_id=...) -> SelectionResult',
 'smoke_driver':'python -m semantic_pallet_planner.jev_select.packaging_api prepare|send|inspect --output ...',
 'request_ledger_states':['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED','UNKNOWN_SEND','FAILED'],
 'ledger_schema':'manual versioned validator RequestLedger._load; atomic digest and one job/decision key; INTENT/SENDING transitions persisted before single send',
 'decision_schema':'packaging_remote.decision_record(event); version jev_packaging_decision_v1; exact_action is existing executor credential bound to immutable candidate pool, resolved geometry in resolved_action.json',
 'json_schemas':{n:'code_snapshot/jev_select/schemas/'+n+'.schema.json' for n in ['config_v6','decision_context_v6','selection_result_v6','candidate_bundle_v6','checkpoint_v6','remote_order_metrics_v1']},
 'unchanged_versions':['physical_commit_v1','jev_packaging_runtime_v1','packaging_physical_facts_v1','packaging_load_en_v1','packaging_loading_metrics_v1','pct_contact_network_v2','pct_stability_result_v2'],
 'version_rationale':'v6 execution envelope/config/context/bundle/selection/checkpoint and remote metrics isolate remote provenance and accounting. Native body, shared physical commit, packaging facts/prompt and monitor kernel remain unchanged. JN0 full-order plan/run v1 stay sealed/local; JN1-A uses separate bounded preregistration/run receipts. Full-order JN1-B routing not implemented.',
 'no_memory':'model_state.memories is schema-constrained empty; no memory dependency accepted by run_episode',
 'origin_model_count':'real transport origin jev; pinned served model; ledger statistics authoritative for all requests including failure/unknown; event summary uses persisted network_attempted; billed amount UNKNOWN',
 'recovery':'INTENT may send once; persisted SENDING becomes UNKNOWN_SEND without retry; RESPONSE_SAVED parses only; SELECTION_SAVED reuses; checkpoint SELECTED/MONITORED/COMMITTED reuse shared episode stages',
 'JN1_B_interfaces':['config_factory','injected selector_factory','RequestLedger','DecisionRecord plus immutable candidate pool and resolved_action'],
 'JN1_B_remaining':['new full-order plan/run registration and frozen <=2-order matrix','ledger-based job/batch metrics aggregation','same new protocol local-vs-Jev complete-order comparison','N05-N07 joint acceptance']}
write(root/'interface_contract.json',interfaces)
items={
'A01':('PASS','717 parent manifest files verified, JN0 admission and conservative boundary retained; v6 registry and six schemas; v1/v5 local guards unchanged',['baseline_verification.json','interface_contract.json','tests/local_verification.xml']),
'A02':('PASS','official contract checked 2026-11-03; frozen current public packaging state; empty memories; negative leakage tests',['official_api_contract.json','frozen/request.json','tests/local_verification.xml']),
'A03':('PASS','native C14 maps to immutable E2_405e193bc2c793bf and exact saved geometry; malformed/unknown/oversized responses rejected without fallback',['selection.json','resolved_action.json','tests/local_verification.xml']),
'A04':('PASS','intent/sending/response/selection/unknown/failure states; response recovery no resend; singleton no API; stage interruptions tested',['request_ledger/requests.json','recovery_validation.json','tests/local_verification.xml']),
'A05':('PASS','99 local tests pass; necessary packaging/monitor/recovery/old transport regressions; credential scanner passes',['tests/local_verification.xml','credential_safety.json']),
'A06':('PASS','one real 24-candidate request, selected C14, monitor STABLE, original commit once, stopped after this decision',['preregistration.json','response.raw.json','decision_record.json','monitor.json','execution.json','scope_stop.json']),
'A07':('PASS','readiness, source/environment snapshots, commands, explicit limitations and handoff complete',['jev_api_readiness.json','source_manifest.json','environment.json','commands.json','handoff.json'])}
acceptance={k:{'status':v[0],'detail':v[1],'evidence':v[2]} for k,v in items.items()}
limits=['only one real multi-candidate decision; no full-order reliability or policy benefit established',
 'JN1-B complete orders and same-protocol controls NOT_RUN; complete JN1 and N05-N07 not closed',
 'known POSE_HEIGHT_MISMATCH conservative stop boundary retained; no real UNSTABLE/UNASSESSABLE/ERROR outcome observed in this call',
 'negative and interruption tests use constructed tasks/injected transports; not real provider error frequency evidence',
 'four exposed training sources, all feasibility UNKNOWN; synthetic packaging capacity; no independent unseen source',
 'probabilities/confidence retain native values; not physical confidence; explicit native ranks unavailable, tie rule UNKNOWN',
 'actual bill UNKNOWN; usage known; no retries or additional connectivity probes',
 'JN0 full-order plan/run v1 remain local; full-order remote plan routing and ledger-aware batch reporting belong to JN1-B',
 'main specification lacks cited 6.4/6.5; explicit goal objective is this implementation contract']
write(root/'engineering_acceptance.json',{'version':'jev_jn1_a_acceptance_v1','stage':'JN1-A','status':'PASS_IN_DECLARED_SCOPE','A01_A07':acceptance,
 'N05_N07':'PARTIAL_STAGE_COVERAGE_REQUIRES_JN1_B','JN1_complete':False,'research_benefit':'NOT_ESTABLISHED','limitations':limits})
readiness={'version':'jev_api_readiness_v1','stage':'JN1-A','status':'PASS_IN_DECLARED_SCOPE','A01_A07':{k:v['status'] for k,v in acceptance.items()},
 'parent_receipt_digest':p['parent_receipt_digest'],'data_identity':p['data_identity'],'config_digest':digest(c),
 'source_manifest_digest':digest(source_manifest()),'runtime_identity':c['runtime_identity'],'versions':VERSIONS,
 'actual_real_requests':stats['model_calls'],'request_statistics':stats,'actual_result':{'model':s['served_model'],'label':s['selected_display_id'],
 'candidate_id':s['selected_candidate_id'],'monitor_status':e['monitor']['status'],'commit_count':1},
 'JN1_B_admitted':True,'JN1_B_admission_scope':'protocol engineering prerequisite only; requires separate explicit authorization and preregistered complete-order matrix',
 'JN1_B_executed':False,'complete_JN1':False,'full_order_reliability':'NOT_ESTABLISHED','limits':limits}
write(root/'jev_api_readiness.json',readiness)
write(root/'commands.json',{'cwd':'NBU_Papper','environment':'existing python; PYTHONPATH=semantic_pallet_planner/src','commands':[
 {'command':'python -m pytest semantic_pallet_planner/tests/unit/test_packaging_remote.py semantic_pallet_planner/tests/unit/test_packaging_full_order.py semantic_pallet_planner/tests/unit/test_stability_monitor.py semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j4_transport.py -q --disable-warnings --junitxml=/tmp/jn1_local_verification.xml','result':'99 passed, 24 warnings; copied tests/local_verification.xml and .log'},
 {'command':'python -m semantic_pallet_planner.jev_select.packaging_api prepare --output '+str(root),'result':'fixed first task, earliest 24-candidate state, 3 arrival events; no selected local-prefix decisions'},
 {'command':'python -m semantic_pallet_planner.jev_select.packaging_api send --output '+str(root)+' --api-key-file typesafe_api_key.md','result':'one real request; STABLE; one commit; stage closed'},
 {'command':'python '+str(root/'audit_saved.py'),'result':'PASS; forbidden network/episode/generator/commit/PCT entrypoints; repeated completed invocation unchanged'},
 {'command':'git diff --check','result':'PASS'}],
 'development_checks':'Initial focused tests 19 then 22 passed. An earlier combined run had 94 pass/1 failure because production source was edited while identity-freezing tests ran. After edits stopped, final full 99-case targeted run passed. These counts overlap and are not summed.',
 'not_run':['JN0 matrix','JN1-B full orders','DeepSeek','memory','forks','unseen tests','historical replay']})
write(root/'source_change_review.json',{'parent_source_manifest_digest':digest(read(Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02/plan/plan.json'))['source_manifest']),
 'current_source_manifest_digest':digest(source_manifest()),'source_snapshot_matches_current':source_manifest()==read(root/'source_manifest.json'),
 'physical_manifest_unchanged':True,'monitor_algorithm_unchanged':True,'old_schema_bytes_unchanged':True,
 'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'automatic_commit_push':False})
# Check actual loaded token against every delivered byte without exposing it.
key=credential('TYPESAFE_API_KEY','typesafe_api_key.md').encode()
leaks=[str(f.relative_to(root)) for f in root.rglob('*') if f.is_file() and key in f.read_bytes()]
if leaks:raise RuntimeError('credential leakage found; filenames suppressed')
del key
write(root/'credential_safety.json',{'status':'PASS','actual_token_occurrences_in_package':0,'auth_headers_persisted':False,
 'credential_reference_only':True,'deepseek_credential_read':False,'scanner':'in-memory exact loaded token comparison across package files; no token/hash written'})
write(root/'handoff.json',{'version':'jev_jn1_a_handoff_v1','stage':'JN1-A','status':'PASS_IN_DECLARED_SCOPE',
 'parent_receipt_digest':p['parent_receipt_digest'],'data_identity':p['data_identity'],
 'source_identity':digest(source_manifest()),'config_identity':digest(c),'algorithm_identity':c['stability_monitor']['algorithm_identity'],
 'interfaces':'interface_contract.json','versions':VERSIONS,'task_ledger':[{'job_id':'A_SMOKE','task_id':p['task_id'],'source_group':p['source_group'],
 'scope':'single earliest multi-candidate decision; 3 arrival events only prefix','real_calls':1,'monitor':'STABLE','commits':1,'order_complete':False}],
 'call_ledger':'request_ledger/requests.json','decision_record':'decision_record.json','exact_candidate':'resolved_action.json','request_statistics':stats,
 'acceptance':{k:v['status'] for k,v in acceptance.items()},'readiness':'jev_api_readiness.json','limitations':limits,
 'JN1_B_admitted':True,'JN1_B_executed':False,'complete_JN1':False,'N05_N07':'requires JN1-A plus JN1-B',
 'report':'docs/03_阶段产出分析/Jev/Jev_JN1-A协议适配与最小真实调用验收_20261103.md',
 'archive_policy':'existing ignores unchanged; output evidence is local, no auto-add/commit/push',
 'stop':'A01-A07 delivered; one-send cap exhausted; no next stage or second model decision authorized'})
print({'status':'DELIVERY_RECORDS_WRITTEN','A01_A07':'PASS_IN_DECLARED_SCOPE','real_requests':1,'commits':1})
