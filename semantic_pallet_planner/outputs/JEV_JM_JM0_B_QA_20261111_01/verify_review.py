"""JM0-B independent saved-contract audit. Stdlib only, no production imports."""
from pathlib import Path
import ast,collections,hashlib,itertools,json,subprocess
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent
B=R/'semantic_pallet_planner/outputs/JEV_JM0_B_20261111_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def hist(path,commit):return hashlib.sha256(subprocess.check_output(['git','show',commit+':'+path],cwd=R)).hexdigest()
def ptr(v,p):
 for t in p[1:].split('/') if p else []:
  k=t.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
names=['research_contract','data_admission_plan','exposure_register','method_design','admission_policy','analysis_contract','sampling_policy','parameter_register','budget_and_stop_contract','risk_and_assumptions']
docs={n:read(B/(n+'.json')) for n in names};c={k:v['payload'] for k,v in docs.items()}
shape=read(B/'contract_shapes.json');checks=[]
for n,d in docs.items():
 assert set(d)==set(shape['top_level_required']) and set(d['payload'])==set(shape['payload_required'][n]),n
 assert d['execution_authorized'] is False and d['task']=='JM0-B' and d['plan_version']=='JM-plan-v2'
 checks.append(n)
refs=[]
def walk(v):
 if isinstance(v,dict):
  if 'path' in v and 'json_pointer' in v:refs.append(v)
  for x in v.values():walk(x)
 elif isinstance(v,list):
  for x in v:walk(x)
for d in docs.values():walk(d)
for ref in refs:ptr(read(R/ref['path']),ref['json_pointer'])
manifest=[]
for e in read(B/'delivery_manifest.json')['files']:
 p=R/e['path'];v={'path':e['path'],'matches':p.is_file() and sha(p)==e['sha256']}
 if not v['matches'] and e['path']=='docs/03_阶段产出分析/Jev/README.md':v['matches_56819f90']=hist(e['path'],'56819f90')==e['sha256']
 assert v['matches'] or v.get('matches_56819f90'),v
 manifest.append(v)
inputs=[];points=0
for e in read(B/'input_evidence_index.json')['files']:
 p=R/e['path'];assert not any(x in e['path'].lower() for x in ['.aws/','.env','credentials','api_key'])
 row={'path':e['path'],'exists_at_design':e['exists_at_design'],'exists_now':p.is_file()}
 if not e['exists_at_design']:
  row['later_arrived']=p.is_file()
 elif 'verification_source' in e:
  v=e['verification_source'];row['historic_blob_matches']=hist(v['path'],v['commit'])==e['sha256_at_design'];assert row['historic_blob_matches']
 elif p.is_file():row['matches']=sha(p)==e['sha256_at_design'];assert row['matches'],row
 if e['exists_at_design'] and p.is_file() and p.suffix=='.json':
  for point in e['pointers']:ptr(read(p),point);points+=1
 inputs.append(row)
for ref in c['research_contract']['actual_interfaces']:
 p=R/ref['path'];assert sha(p)==ref['sha256']
 assert any(isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)) and n.name==ref['symbol'] and n.lineno==ref['line'] for n in ast.walk(ast.parse(p.read_text())))
rule_tree=ast.parse((R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_reanalysis.py').read_text())
rule=next(n.value for n in rule_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RULE' for t in n.targets))
for key in ['levels','tolerances']:
 node=next(v for k,v in zip(rule.keys,rule.values) if isinstance(k,ast.Constant) and k.value==key)
 assert ast.literal_eval(node)==c['analysis_contract']['comparison_rule'][key]
D=c['data_admission_plan'];assert set(map(frozenset,D['forbidden_overlap_pairs']))==set(map(frozenset,itertools.combinations(D['roles'],2)))
assert D['existing_materials']['formal_assignments']==[] and D['existing_materials']['formal_partition_status']=='DEFER'
E=c['exposure_register'];parent=read(R/'semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01/source_task_register.json')['source_rows']
assert [r['existing_id'] for r in E['rows']]==[r['id'] for r in parent]
assert all(r['current_role']=='historical_diagnostic_only' and r['strict_unseen_eligible'] is False for r in E['rows'])
assert [r['id'] for r in c['method_design']['methods']]==['N','T0','T1','E0','E1','U1','G1']
assert [r['id'] for r in c['method_design']['local_conditions']]==['L-N','L-T','L-E','L-A','L-G']
budget=c['budget_and_stop_contract'];assert len(set(r['id'] for r in budget['allocations']))==9
assert all(type(x)is int and x==0 for x in budget['current_authorized'].values())
assert budget['arithmetic']['training_total_suffixes']==12*3+4*3==48
assert budget['arithmetic']['local_choices']['total']==4*5==20
assert budget['arithmetic']['local_suffixes']['total']==4*3*2==24
assert budget['arithmetic']['pilot']['total']==(4+2)*7==42
for parameter in c['parameter_register']['parameters']:
 assert parameter['inputs'] and parameter['freeze_by'] and parameter['on_missing'] and parameter['owner']
 assert 'procedure' in parameter or 'procedure_ref' in parameter
# Execute only the inspected standalone metadata-set checker, isolated from script top level.
# This is a static metadata probe, not a production admission/solver/order runtime.
tree=ast.parse((B/'check_contracts.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='assignment_errors')
keys=['entity_identity_sha256','source_group_ids','near_duplicate_component_ids','material_family_ids','prototype_ids','seed_family_ids']
env={'D':D,'keys':keys,'itertools':itertools};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<metadata helper only>','exec'),env)
def fixture(identity,role):
 return {'entity_identity_sha256':identity,'role':role,'source_group_ids':[],'near_duplicate_component_ids':[],'material_family_ids':[],'prototype_ids':[],'seed_family_ids':[],'parent_entity_ids':[],'evidence_refs':[],'exposure_status':'UNKNOWN'}
probe=env['assignment_errors']([fixture('a','training'),fixture('b','evaluation')])
# Verify arrived parent QA identity; shared navigation README is a mutable historical entry.
P=R/'semantic_pallet_planner/outputs/JEV_JM_JM0_A_QA_20261111_01';pm=read(P/'delivery_manifest.json');parent_qa=[]
for row in pm['files']:
 if row['path']=='docs/03_阶段产出分析/Jev/README.md':continue
 assert sha(R/row['path'])==row['sha256'],row['path'];parent_qa.append(row['path'])
assert read(P/'next_stage_admission.json')['status']=='READY'
for row in read(B/'handoff.json')['contracts']:assert sha(R/row['path'])==row['sha256']
assert sha(B/'input_evidence_index.json')==read(B/'handoff.json')['parent_identity_index']['sha256']
result={'version':'jm0_b_independent_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'contract_shape_checks':checks,'contract_references_checked':len(refs),'delivery_manifest':manifest,'inputs':inputs,'input_json_pointers_checked':points,'actual_interface_references_checked':len(c['research_contract']['actual_interfaces']),'analysis_rule_matches_source':True,'exposure_rows_checked':len(E['rows']),'isolation_forbidden_role_pairs_checked':len(D['forbidden_overlap_pairs']),'budget_arithmetic':'PASS','parameter_procedures_checked':len(c['parameter_register']['parameters']),'arrived_parent_QA_digest_checks':parent_qa,'arrived_parent_QA_admission':'READY_JM0_B_CONTRACT_DESIGN_ONLY','original_check_contracts_current_run':'FAIL at missing raw/mixed_pallet_boxes/MixedPalletBoxes-v1.0/README.md; subsequent original checks NOT_RUN','metadata_probe':{'scope':'standalone static checker only','all_group_tokens_empty_and_exposure_UNKNOWN_returned_errors':sorted(probe),'expected_by_text_contract':'UNKNOWN_GROUP_RELATION or DEFER; no complete identity evidence','interpretation':'coverage limitation in static checker; no production assignment or future production admission exercised'},'business_source_data_test_diff_since_B_start':subprocess.check_output(['git','diff','--name-only','8b1b98b7','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests','semantic_pallet_dataset_v1'],cwd=R,text=True),'not_run':['models/network/credentials','orders/forks/candidate reconstruction/solver','business behavior tests','original checker complete success','primary literature verification','missing third-party originals']}
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'contracts':len(checks),'contract_refs':len(refs),'manifest_entries':len(manifest),'manifest_current_matches':sum(r['matches'] for r in manifest),'input_entries':len(inputs),'input_previously_present_currently_missing':sum(r['exists_at_design'] and not r['exists_now'] for r in inputs),'missing_at_design_now_available':sum(r.get('later_arrived',False) for r in inputs),'input_pointers':points,'source_symbols':len(c['research_contract']['actual_interfaces']),'parent_QA_digest_checks':len(parent_qa),'empty_metadata_probe_errors':sorted(probe)},ensure_ascii=False))
