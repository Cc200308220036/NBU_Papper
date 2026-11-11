"""Read saved evidence only; no business imports, model, solver, or mutations to reviewed package."""
from pathlib import Path
import ast,collections,hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[3]; OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def ptr(v,p):
 for s in p[1:].split('/') if p else []:
  k=s.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
def hist_sha(path,commit='3a3f83384b6cdde19cd5262cc86f27c4b8cd7011'):
 return hashlib.sha256(subprocess.check_output(['git','show',commit+':'+path],cwd=ROOT)).hexdigest()
manifest=[]
for e in read(B/'delivery_manifest.json')['files']:
 p=ROOT/e['path'];actual=sha(p) if p.is_file() else None
 row={'path':e['path'],'expected':e['sha256'],'actual':actual,'matches':actual==e['sha256']}
 if not row['matches'] and e['path']=='docs/03_阶段产出分析/Jev/README.md':row['historical_3a3f8338_matches']=hist_sha(e['path'])==e['sha256']
 manifest.append(row)
receipt=read(B/'source_and_exposure_receipt.json')
appendices=[{'path':e['path'],'matches':sha(ROOT/e['path'])==e['sha256']} for e in receipt['appendices']]
evidence=[];pointer_count=0
for e in read(B/'evidence_index.json')['files']:
 p=ROOT/e['path'];row={'path':e['path'],'expected_exists':e['exists'],'current_exists':p.is_file()}
 if p.is_file():
  row['matches']=sha(p)==e['sha256']
  if p.suffix=='.json':
   v=read(p)
   for point in e['pointers']:ptr(v,point);pointer_count+=1
  if not row['matches'] and e['path']=='docs/03_阶段产出分析/Jev/README.md':row['historical_3a3f8338_matches']=hist_sha(e['path'])==e['sha256']
 evidence.append(row)
symbols=[]
for item in read(B/'interface_inventory.json')['items']:
 for ref in item['references']:
  p=ROOT/ref['path'];row={'path':ref['path'],'exists':p.is_file()}
  if 'symbol' in ref:
   row.update(symbol=ref['symbol'],line=ref['line'],matches=any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==ref['symbol'] and n.lineno==ref['line'] for n in ast.walk(ast.parse(p.read_text()))))
  symbols.append(row)
src=read(B/'source_task_register.json');rows=src['source_rows']
file_checks=[{'path':e['data_path'],'matches':sha(ROOT/e['data_path'])==e['file_sha256']} for e in rows if 'file_sha256' in e]
workbooks=[]
for e in rows[-1]['workbook_identity_checks']:
 p=ROOT/e['path'];workbooks.append({'path':e['path'],'exists':p.is_file(),'matches':sha(p)==e['sha256'] if p.is_file() else None,'archived_identity_match_claim':e['matches_archived_review']})
components=read(B/'inherited_component_register.json'); cov=read(B/'material_coverage.json')
inherited_parent=read(ROOT/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json')['components']
assert len(inherited_parent)==len(components['rows'])
for original,row in zip(inherited_parent,components['rows']):
 assert all(row[k]==v for k,v in original.items()), row['component']
source_ref_count=0
for row in rows:
 for ref in row.get('evidence',[]):
  path=ROOT/ref['path']
  if path.is_file() and path.suffix=='.json':ptr(read(path),ref.get('json_pointer',''));source_ref_count+=1
parents=[]
for e in read(B/'parent_identity_checks.json')['checks']:
 parents.append({'path':e['path'],'matches':sha(ROOT/e['path'])==e['actual_sha256']==e['manifest_sha256']})
status=subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all'],cwd=ROOT,text=True)
source_diff=subprocess.check_output(['git','diff','--name-only','5e6bfe47','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests','semantic_pallet_dataset_v1'],cwd=ROOT,text=True)
result={'version':'jm0_a_resync_independent_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'original_script_result':'FAIL at evidence_index README SHA; script inspected and run without --write; no original files changed','manifest':manifest,'appendices':appendices,'evidence':evidence,'validated_available_json_pointers':pointer_count,'symbols':symbols,'source_rows':{'count':len(rows),'types':dict(collections.Counter(e['row_type'] for e in rows)),'required_use_fields_complete':all(all(k in e['recommended_use'] for k in ['train','dev','eval']) for e in rows),'strict_unseen_admitted':src['strict_unseen_eval_admitted'],'synthetic_pair_relation_count':len(src['synthetic_pair_relations'])},'source_file_checks':file_checks,'workbook_checks':workbooks,'inherited_rows_match_parent':True,'source_evidence_references_checked':source_ref_count,'component_count':len(components['rows']),'strict_unseen_component_admitted':components['strict_unseen_admitted_this_audit'],'coverage':{'fork_points':len(cov['fork_points']),'comparisons':len(cov['comparisons']),'unique_branches':cov['unique_branch_receipts'],'same_start_repeats':cov['same_start_repeats'],'labels_v2':cov['labels_v2'],'pool_probability_checks':all(e['probability_complete'] and e['mapping_pool_identity_equal'] for e in cov['fork_points'])},'selected_parent_checks':parents,'business_source_tests_data_diff_since_start':source_diff,'git_status_at_check':status,'not_run':['business behavior tests','model/network/credential access','orders/forks/candidate rebuilding/solver','missing third-party originals','full historical replay']}
assert all(e['matches'] for e in appendices+file_checks+parents)
assert all(e.get('matches',True) and e['exists'] for e in symbols)
assert len(rows)==27 and len(components['rows'])==3648
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'manifest_total':len(manifest),'manifest_current_matches':sum(e['matches'] for e in manifest),'manifest_historical_readme_match':all(e['matches'] or e.get('historical_3a3f8338_matches',False) for e in manifest),'appendices_matches':len(appendices),'evidence_total':len(evidence),'evidence_current_missing':sum(not e['current_exists'] for e in evidence),'evidence_current_matches':sum(e.get('matches',False) for e in evidence),'pointers':pointer_count,'symbol_references':len(symbols),'source_rows':result['source_rows'],'source_files_checked':len(file_checks),'workbooks_unavailable':sum(not e['exists'] for e in workbooks),'coverage':result['coverage'],'selected_parents_matches':len(parents),'business_diff_empty':not source_diff},ensure_ascii=False))
