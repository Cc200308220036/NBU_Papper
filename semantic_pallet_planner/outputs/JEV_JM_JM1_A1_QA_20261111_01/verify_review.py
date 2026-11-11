"""JM1-A1 independent saved-data audit; no project imports, tests, selector, commit or solver."""
from pathlib import Path
import ast,collections,hashlib,importlib.util,json,math,subprocess,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent;B=R/'semantic_pallet_planner/outputs/JEV_JM1_A1_20261111_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def ptr(v,p):
 for s in p[1:].split('/') if p else []:
  k=s.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
identity=read(B/'source_identity.json');manifest=read(B/'delivery_manifest.json')
for p,h in identity['changed_source_and_test_sha256'].items():assert sha(R/p)==h,p
for p,h in identity['runtime_package_source_sha256'].items():assert sha(R/'semantic_pallet_planner/src/semantic_pallet_planner'/p)==h,p
for p,h in manifest['files_sha256'].items():assert sha(B/p)==h,p
for p,h in manifest['repository_files_sha256'].items():assert sha(R/p)==h,p
inputs=read(B/'input_evidence_index.json');assert not inputs['missing_required_inputs']
for row in inputs['files']:assert sha(R/row['path'])==row['sha256'],row['path']
rows=[]
for path in sorted((B/'constructed_evidence').glob('*/branch/counts.json')):
 if path.parent.parent.is_symlink():continue
 branch=path.parent;c=read(path);bind=read(branch/'binding.json');ep=read(branch/'episode.json');s=bind['start']['snapshot'];event=ep['events'][0]
 assert len(ep['events'])==1 and ep['checkpoint']['decision']==1
 assert event['before']==s['state'] and event['bundle']==s['pool'] and event['context']['display_mapping']==s['mapping']
 assert event['proposed_action']==bind['exact_action'] and event['selection']['selected_candidate_id']==bind['forced_candidate']['candidate_id']
 assert event['selection']['fork_binding_digest']==digest(bind)
 assert event['selection']['source']=='FORCED_FROM_FROZEN_POOL' and not event['selection']['network_attempted'] and event['selection']['attempt_ids']==[]
 assert c['forced_actions']==1 and c['monitor_calls']==1
 assert all(c[k]==0 for k in ['model_calls','transport_calls','solver_calls','credential_reads'])
 stages=[read(p) for p in sorted((branch/'stages').glob('*.json'))]
 assert stages[0]['phase']=='SELECTED' and stages[0]['pending_event']['monitor'] is None and stages[1]['phase']=='MONITORED'
 stable=c['monitor_status']=='STABLE';assert c['commits']==sum(cp['phase']=='COMMITTED' for cp in stages)==int(stable)
 def q(state):return (len(state['placed_items']),sum(math.prod(o['oriented_size_mm']) for o in state['placed_items']),sum(o['mass_kg'] for o in state['placed_items']))
 before=q(s['state']);after=q(ep['final_state']);delta=[b-a for a,b in zip(before,after)]
 if stable:
  chosen=bind['forced_candidate'];mass=next(x['item']['mass_kg'] for x in s['buffer'] if x['item']['item_id']==chosen['pick_item_id'])
  assert delta==[1,math.prod(chosen['oriented_size_mm']),mass]
  assert ep['checkpoint']['reason']=='JM_CONTINUATION_NOT_IMPLEMENTED'
 else:assert delta==[0,0,0] and ep['final_state']==s['state'] and event['action'] is None
 rows.append({'path':str(branch.relative_to(R)),'intervention':c['intervention'],'monitor_status':c['monitor_status'],'commits':c['commits'],'delta':delta})
assert len(rows)==12 and len(set((x['intervention'],x['monitor_status']) for x in rows))==12
parents=[]
for row in read(B/'parent_saved_evidence_review.json')['starts']:
 p=R/row['path'];receipt=R/row['parent_receipt'];assert sha(p)==row['sha256'] and sha(receipt)==row['parent_receipt_sha256']
 snapshot=ptr(read(p),row['pointer']);task=read(R/row['task_path'])
 assert sha(R/row['task_path'])==row['task_sha256'] and digest(task)==snapshot['task_digest']
 assert read(receipt)['files_sha256'][str(p.relative_to(receipt.parent))]==row['sha256']
 parents.append({'path':row['path'],'cursor':snapshot['cursor'],'placed_count':snapshot['state']['placed_count'],'pool_count':len(snapshot['pool']['selectable_candidates'])})
junit={}
for name in ['constructed_junit.xml','public_regression_junit.xml']:
 suites=list(ET.parse(B/name).getroot().iter('testsuite'));junit[name]={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ['tests','errors','failures','skipped']}
 assert junit[name]['errors']==junit[name]['failures']==0
package=R/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select';jm=ast.parse((package/'packaging_jev_forks.py').read_text())
functions={n.name:n.lineno for n in jm.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
legacy_diff=subprocess.check_output(['git','diff','--name-only','42654d35','HEAD','--',str((package/'packaging_counterfactual.py').relative_to(R)),str((package/'stability').relative_to(R)),str((package/'candidates.py').relative_to(R)),str((package/'configs/generator_v1.json').relative_to(R))],cwd=R,text=True)
assert not legacy_diff
result={'version':'jm1_a1_independent_saved_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'original_verify_delivery_this_turn':'PASS (read-only stdlib script; no business execution)','changed_source_and_test_hashes':len(identity['changed_source_and_test_sha256']),'runtime_source_hashes':len(identity['runtime_package_source_sha256']),'delivery_output_hashes':len(manifest['files_sha256']),'repository_delivery_hashes':len(manifest['repository_files_sha256']),'input_hashes':len(inputs['files']),'first_step_records':rows,'saved_parent_starts':parents,'archived_junit':junit,'interface_symbols':functions,'protected_legacy_candidate_stability_diff':legacy_diff,'available_local_dependencies':{name:importlib.util.find_spec(name)is not None for name in ['pytest','jsonschema','numpy','scipy']},'broken_pytest_current_symlinks':[str(p.relative_to(R)) for p in (B/'constructed_evidence').iterdir() if p.is_symlink() and not p.exists()],'not_run_this_turn':['pytest behavior tests (dependencies unavailable)','run_forced_first/run_episode/commit','monitor dispatch/solver','candidate rebuilding','models/network/credentials','order/fork execution','full historical replay'],'scope':'saved-byte hashes, AST/source reading, JSON identity/counters/stages and archived JUnit only; no project imports'}
(O/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['changed_source_and_test_hashes','runtime_source_hashes','delivery_output_hashes','repository_delivery_hashes','input_hashes','archived_junit','available_local_dependencies']},ensure_ascii=False))
