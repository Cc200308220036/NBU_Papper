"""Independent stdlib saved-fact checks; no runtime imports or mutations of inputs."""
import ast, hashlib, json, platform, subprocess
from pathlib import Path
ROOT=Path('.')
P=Path('PCT/outputs/PCT_P0_CONTRACT_20261114_01')
def read(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def main():
    identity=read(P/'identity.json')
    mismatch=[p for p,h in identity['files'].items() if sha(p)!=h]
    inventories={}
    for base in read(P/'data_audit.json')['inventories']:
        root=Path(base); expected=read(root/'delivery_manifest.json')
        actual={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
        inventories[base]={'count':len(actual),'equal':actual==expected}
    audit=read(P/'data_audit.json'); tasks=[read(t['path']) for t in audit['tasks']]
    byid={t['task_id']:t for t in tasks}
    pack=Path('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02')
    package_identity=digest(dict(config=read(pack/'config.snapshot.json'),tasks=[byid[t] for t in audit['packaging_archive_order']],split=read(pack/'split_manifest.json')))
    syn=read('semantic_pallet_planner/outputs/JEV_JN4_SYNTH_20261105_01/data/dataset.json')
    errors=[]
    for p in [*Path('Online-3D-BPP-PCT').rglob('*.py'),Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/contracts.py')]:
        try: ast.parse(p.read_bytes())
        except SyntaxError as e: errors.append({'path':str(p),'line':e.lineno,'error':e.msg})
    result={'python':platform.python_version(),'source_hashes_checked':len(identity['files']),'source_mismatch':mismatch,'inventories':inventories,'package_identity':package_identity,'package_identity_matches':package_identity==read(pack/'manifest.json')['data_identity'],'synthetic_identity_matches':digest({k:v for k,v in syn.items() if k!='data_identity'})==syn['data_identity'],'tasks':len(tasks),'counts':[len(t['items']) for t in tasks],'arrival_unique_and_equal':all(t['arrival_order']==[i['item_id'] for i in t['items']] and len(t['arrival_order'])==len(set(t['arrival_order'])) for t in tasks),'ast_errors':errors,'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':subprocess.check_output(['git','branch','--show-current'],text=True).strip()}
    assert not mismatch and all(x['equal'] for x in inventories.values())
    assert result['package_identity_matches'] and result['synthetic_identity_matches'] and result['arrival_unique_and_equal']
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
