"""Independent saved-byte audit only; stdlib, no business imports or writes to inputs."""
import gzip
import hashlib
import json
import math
from pathlib import Path

Q = Path(__file__).resolve().parent
P = Path('PCT/outputs/PCT_P4_A_20261115_01')
B = P/'build_01'
def read(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

manifest=read(P/'delivery_manifest.json'); checked=0; navigation_differences=[]
for row in manifest['files']:
    p=Path(row['path'])
    if sha(p)!=row['sha256'] or p.stat().st_size!=row['size']:
        assert str(p) in ('PCT/README.md','PCT/docs/README.md'),str(p)
        navigation_differences.append(str(p))
    checked+=1
identity=read(P/'identity.json')
for n,h in identity['files'].items(): assert sha(n)==h,n
protected=read('PCT/outputs/PCT_P3_20261115_01/identity.json')['final_source_sha256']
for n,h in protected.items(): assert sha(n)==h,n
catalog=read(B/'data_catalog.json'); train=read(B/'training_plan.json'); evaluation=read(B/'evaluation_template.json')
for value,key in [(catalog,'catalog_digest'),(train,'plan_digest'),(evaluation,'plan_digest')]:
    assert value[key]==digest({k:v for k,v in value.items() if k!=key})
tasks={t['task_id']:t for t in catalog['tasks']}
for tid,row in tasks.items():
    derived=read(B/'data/tasks'/(tid+'.json'))
    assert len(derived['items'])==row['box_count'] and digest(derived)==row['derived_task_digest']
    assert sha(row['parent_path'])==row['parent_sha256']
assert all(not t['independent_holdout'] for t in tasks.values())
for i,s in enumerate(train['schedules'][:3]):
    assert s['attempts']==train['schedules'][i+3]['attempts'] or [
        (a['epoch'],a['task_id'],a['action_cap']) for a in s['attempts']]==[
        (a['epoch'],a['task_id'],a['action_cap']) for a in train['schedules'][i+3]['attempts']]
assert sum(j['monitor_cap'] for j in evaluation['jobs'])==4280
assert all(j['action_cap']==j['monitor_cap']==tasks[j['task_id']]['box_count'] for j in evaluation['jobs'])
cards=read(B/'method_cards.json')
for model in cards['models']:
    original=read(model['source_manifest'])
    assert sha(model['source_manifest'])==model['manifest_sha256']
    assert model['features']==original['feature_contract'] and model['architecture']==original['architecture']
source=Path('PCT/outputs/PCT_P3_20261115_01/attempt_02/training')
files=0; total=0; transitions=0; capsule_bytes=0
for batch in range(2):
    directory=B/'storage_validation';index=read(directory/f'batch_{batch}.index.json')
    assert index['index_digest']==digest({k:v for k,v in index.items() if k!='index_digest'})
    archive=directory/f'batch_{batch}.jsonl.gz'
    assert sha(archive)==index['compressed_sha256']
    capsule_bytes+=archive.stat().st_size
    with gzip.open(archive,'rt',encoding='utf-8') as stream:
        records=[json.loads(line) for line in stream]
    assert len(records)==len(index['entries'])
    for record,entry in zip(records,index['entries']):
        name=entry['path']; raw=record['utf8_content'].encode('utf-8')
        assert {k:record[k] for k in ('path','sha256','bytes')}==entry
        assert raw==(source/name).read_bytes()==(directory/f'restored_batch_{batch}'/name).read_bytes()
        assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
        total+=len(raw);files+=1
        if name.endswith('/episode.json'):
            transitions+=sum(e.get('selection') is not None for e in json.loads(raw)['events'])
assert (files,total,transitions,capsule_bytes)==(326,27765315,147,3940936)
gates=read(B/'formal_prerequisites.json');cap=gates['capacity_gate']
rate=gates['baseline_resource']['bytes_per_monitored_training_action']
retained=sum(p.stat().st_size for p in Path('PCT/outputs/PCT_P3_20261115_01').rglob('*') if p.is_file())
expected=math.ceil(1.25*(198000+4280)*rate+cap['hot_shard_reserve_bytes']+36*cap['checkpoint_size_reference']*2+retained)
assert expected==cap['required_free_bytes_fallback']
assert cap['observed_free_sufficient_for_fallback']==(cap['observed_free_bytes']>=expected)
receipt={'status':'PASS_SAVED_BYTES_AND_ARITHMETIC','manifest_files':checked,'protected_P3_sources':len(protected),
         'navigation_differences':navigation_differences,
         'input_identity_files':len(train['input_identity']),'capsule_files':files,'capsule_original_bytes':total,
         'capsule_compressed_bytes':capsule_bytes,'transitions':transitions,'required_free_bytes':expected,
         'historical_observed_free_bytes':cap['observed_free_bytes'],'formal_capacity_gate':False,
         'coverage':'hashes, derived task/parent identity, paired traversal, monitor caps, method manifests, raw gzip and restored bytes, resource arithmetic',
         'not_run':['orders','candidate generation','LP','model forward','optimizer','formal crash recovery','remote requests']}
output=Q/('independent_final_recheck.json' if navigation_differences else 'independent_saved_recheck.json')
output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
