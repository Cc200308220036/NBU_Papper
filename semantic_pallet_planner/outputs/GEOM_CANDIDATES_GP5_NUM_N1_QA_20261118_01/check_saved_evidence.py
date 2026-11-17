"""Read-only N1 identities/metadata/field semantics. No project imports/replay."""
import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

OUT=Path(__file__).parent
DEV=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_20261117_01'
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='37f65434b04cda5e7c136239fb57efdd242386b2'
def read(p):return json.loads(p.read_bytes())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha(enc(v))
def H(kind,v):return digest({'domain':'geometry_native_shape_identity_r1/'+kind+'/v1','payload':v})
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

m=read(DEV/'delivery_manifest.json')
for row in m['files']:
    p=Path(row['path'])
    raw=(subprocess.check_output(['git','show',HEAD+':'+str(p)]) if p.name=='README.md' else p.read_bytes())
    assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],str(p)
current={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
         if p.is_file() and p.suffix in ('.py','.json')
         and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
source=read(DEV/'source_manifest.json');base=read(DEV/'baseline_receipt.json')
assert current==source['files'] and digest(current)==source['source_identity']
modified=[k for k,h in base['files'].items() if current.get(k)!=h]
added=sorted(set(current)-set(base['files']))
assert len(modified)==14 and len(added)==26 and not set(base['files'])-set(current)
protected=[k for k in base['files'] if k.startswith(('planner/','evaluation/','o4/','jev_select/stability/')) and k!='jev_select/stability/monitor.py']+['jev_select/geometry_runtime_contracts.py','jev_select/geometry_runtime_input.py']
assert all(current[k]==base['files'][k] for k in protected)
assert all(current[k]==h for k,h in base['files'].items() if k.startswith('jev_select/schemas/'))
for k in modified+added:
    assert (DEV/'source_snapshot'/k).read_bytes()==(SRC/k).read_bytes(),k
    if k.endswith('.py'):ast.parse((SRC/k).read_text(),filename=k)
    else:read(SRC/k)
history=0
for group in base['manifests']:
    p=Path(group['manifest']);assert sha(p.read_bytes())==group['sha256']
    for row in read(p)['files']:
        raw=(subprocess.check_output(['git','show',group['navigation_revision']+':'+row['path']])
             if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
        assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'];history+=1

rows=read(DEV/'C_results.json');assert len(rows)==6
for row in rows:
    source_axes=('width','length','height') if row['case'].endswith('90') else ('length','width','height')
    for i,(raw,target,proof,axis) in enumerate(zip(row['raw'],row['target'],row['axis_equalities'],source_axes)):
        assert type(target) is type(row['source'][axis]) and target==row['source'][axis]
        assert Fraction(raw)==Fraction(target)
        assert Fraction(raw)==Fraction(int(proof['raw_signature']['numerator']),int(proof['raw_signature']['denominator']))
        assert proof['source_axis']==axis and proof['axis_index']==i
    assert row['L']==digest(row['target']) and row['B']==sha(enc(row['target']))
negative=read(DEV/'X_pure_results.json');assert len(negative)==5 and all(x['status']=='REJECTED' for x in negative)

cp=read(DEV/'E/jobs/J00/checkpoint.json');account=read(DEV/'E/jobs/J00/accounting.json');run=read(DEV/'E/run.json')
calls=read(DEV/'test_double_calls.json');stop=read(DEV/'stop.json')
assert cp['phase']=='SELECTED' and cp['pending_event']['monitor'] is None
assert cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'})
assert cp['state']['placed_count']==0 and not cp['state']['placed_items']
assert len(calls)==1 and account['cumulative']['monitor_entries']==1 and account['cumulative']['selector_calls']==1
assert account['cumulative']['commit_attempts']==account['cumulative']['commit_successes']==0
assert account['invocations'][-1]['status']=='ERROR' and account['invocations'][-1]['result_checkpoint_digest'] is None
assert len(run['rows'])==8 and run['rows'][0]['status']=='TECHNICAL_FAILURE'
assert all(r['status']=='NOT_RUN' for r in run['rows'][1:]) and all(r['metrics'] is None for r in run['rows'])
assert stop['no_retry'] is True
blobdir=DEV/'E/jobs/J00/blobs';blobcount=0
for p in blobdir.iterdir():
    if p.is_file():assert sha(p.read_bytes())==p.name;blobcount+=1
ref=cp['pending_event']['geometry_ref'];side=json.loads((blobdir/ref['sha256']).read_bytes())
pub=side['audit']['publication'];assert pub['digest']==H('publication',pub['record'])
assert len(pub['record']['ordered_mappings'])==2 and len(pub['blobs'])==20
for key,hx in pub['blobs'].items():
    raw=bytes.fromhex(hx);assert sha(raw)==key and (blobdir/key).read_bytes()==raw
assert all([type(v).__name__ for v in c['oriented_size_mm']]==['int','int','int'] for c in side['bundle']['physical_candidates'])
schemas=SRC/'jev_select/schemas'
old=read(schemas/'checkpoint_v16.schema.json')['$defs']['monitor_result']['properties']['candidate_id']
new=read(schemas/'checkpoint_v17.schema.json')['$defs']['monitor_result']['properties']['candidate_id']
assert 'pattern' not in old and not re.fullmatch(new['pattern'],'synth_1')
assert re.fullmatch(new['pattern'],'GP5N3_'+'a'*64)
pattern_locations=[]
for p in sorted(schemas.glob('*v17.schema.json')):
    def walk(v,ptr=''):
        if isinstance(v,dict):
            if v.get('pattern')=='^GP5N3_[0-9a-f]{64}$':pattern_locations.append({'file':str(p),'pointer':ptr})
            for k,x in v.items():walk(x,ptr+'/'+k)
        elif isinstance(v,list):
            for i,x in enumerate(v):walk(x,ptr+'/'+str(i))
    walk(read(p))
save('schema_semantics_review.json',{'issue':'GP5-NUM-N1-SCHEMA-01','status':'CONFIRMED_STATIC_DEFECT',
    'old_field':old,'new_field':new,'literal':'synth_1','new_pattern_matches':False,
    'source_semantics':'monitor.py exception result candidate_id=candidate.pick_item_id; exact adapter/test double box ID unchanged',
    'published_candidate_id_regex_locations':pattern_locations,
    'limits':'stdlib field/regex inspection, not a production monitor or full checkpoint validation; MONITORED in-memory row not reconstructed'})
inventory=read(DEV/'identity_contract_inventory.json')
assert inventory['new_publication_namespace']==inventory['versions']['policy']=='geometry_native_shape_publication_policy_v3'
save('saved_evidence_verification.json',{'status':'PASS_SAVED_FACTS_ONLY','manifest_members':len(m['files']),
    'historical_members':history,'source_files':len(current),'source_identity':source['source_identity'],
    'modified':modified,'added':added,'protected_files':len(protected),'old_schemas_unchanged':True,'source_drift':False,
    'C_rows':6,'X_pure_rejections':5,'E':{'planned':8,'technical_failure':1,'not_run':7,'completed':0},
    'last_disk_phase':'SELECTED','monitor_calls_recorded':1,'commits':0,'metrics':'8_null',
    'content_addressed_files':blobcount,'inline_publication_blobs':20,'published_candidates':2,
    'schema_issue':'CONFIRMED','DOC-01':'CORRECTED_NEW_INVENTORY','R_Xruntime_H':'NOT_RUN',
    'production_imports':0,'candidate_order_shadow_kernel_solver_model_execution':0,
    'not_claimed':'runtime bridge/proof semantics, schema Draft syntax, checkpoint resume or monitor success'})
print('PASS saved identities/counters/blobs; schema role defect confirmed; no project imports or business execution')
