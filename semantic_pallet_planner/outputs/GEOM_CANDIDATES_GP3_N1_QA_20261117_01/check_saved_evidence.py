"""Independent saved-fact checks only; stdlib, no production imports/generation."""
from pathlib import Path
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import struct
import subprocess

DEV = Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N1_20261117_01')
PKG = Path('semantic_pallet_planner/src/semantic_pallet_planner')

def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def digest(v): return sha(canonical(v))
def read(p): return json.loads(p.read_bytes())
def pairs(rows):
    result = {}
    for k,v in rows:
        assert k not in result, ('duplicate key', k)
        result[k] = v
    return result

def exact_json(p):
    raw = p.read_bytes()
    value = json.loads(raw, object_pairs_hook=pairs)
    assert canonical(value) == raw, str(p)
    return value

def strict(a,b):
    if type(a) is not type(b): return False
    if type(a) is float: return struct.pack('>d',a) == struct.pack('>d',b)
    if type(a) is dict: return a.keys()==b.keys() and all(strict(a[k],b[k]) for k in a)
    if type(a) is list: return len(a)==len(b) and all(strict(x,y) for x,y in zip(a,b))
    return a==b

def number(v):
    assert type(v) in (int,float)
    d=Decimal(v) if type(v) is int else Decimal(repr(v))
    assert d.is_finite()
    if not d: return '0'
    s=format(d,'f')
    return s.rstrip('0').rstrip('.') if '.' in s else s

ITEM = {'item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic'}
PLACED = ITEM | {'pose','oriented_size_mm','supported_load_kg','support_fractions'}
CONTAINER = ('length_mm','width_mm','max_height_mm','max_payload_kg')
def payload(s):
    return {'container':{k:s['container'][k] for k in CONTAINER},
            'placed_items':[{k:p[k] for k in PLACED} for p in s['placed_items']],
            'buffer_items':[{**{k:p['item'][k] for k in ITEM},'arrival_index':p['arrival_index']}
                            for p in sorted(s['pending_items'],key=lambda p:p['arrival_index'])]}
def convert(v,key=''):
    if type(v) in (int,float): return v if key in ('yaw_deg','arrival_index') else number(v)
    if type(v) is dict: return {k:convert(x,k) for k,x in v.items()}
    if type(v) is list: return [convert(x,key) for x in v]
    return v

m=read(DEV/'delivery_manifest.json')
for row in m['files']:
    p=Path(row['path'])
    assert p.is_file()
    raw=p.read_bytes()
    if sha(raw)!=row['sha256'] and p.as_posix()=='docs/03_阶段产出分析/几何规划模块/README.md':
        raw=subprocess.run(['git','show','d69d904f09686c323edcf949f7e01022a7d564cb:'+p.as_posix()],check=True,capture_output=True).stdout
    assert sha(raw)==row['sha256']
    assert len(raw)==row['size_bytes']
src=read(DEV/'source_manifest.json')['files']
actual={p.relative_to(PKG).as_posix():sha(p.read_bytes()) for p in PKG.rglob('*')
        if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert actual==src
local=read(DEV/'local_identity.json')
assert local['identity']['adapter_source_digest']==digest({n:sha((PKG/'jev_select'/n).read_bytes()) for n in ('geometry_runtime_input.py','geometry_runtime_contracts.py')})
physical=('planner/constraints.py','planner/generator.py','planner/scoring.py','evaluation/geometry_oracle.py','evaluation/state.py','domain.py','o4/buffer/buffer_state.py','o4/extensions/candidates.py','o4/extensions/e2/candidates.py','o4/extensions/e2/protocol.py','jev_select/configs/generator_v1.json')
assert local['identity']['physical_identity']==digest({n:sha((PKG/n).read_bytes()) for n in physical})
case_rows=[]
raw_total=final_total=0
for case in sorted((DEV/'cases').iterdir()):
    n=exact_json(case/'B_native.json');g=exact_json(case/'B_geometry.json')
    b=exact_json(case/'binding.json');r=exact_json(case/'result.json');a=r['audit']
    s=n['current_state'];p=payload(s)
    assert strict(g['payload'],convert(p))
    assert b['native_snapshot_sha256']==sha((case/'B_native.json').read_bytes())==g['native_snapshot_sha256']
    assert b['geometry_input_sha256']==sha((case/'B_geometry.json').read_bytes())
    effective={**{k:s[k] for k in ('buffer_capacity','arrived_ids','event_index','arrival_count','placed_count','end_of_stream')},
               'payload':p,'pending_slots':[{'item_id':x['item']['item_id'],'slot':x['slot'],'arrival_index':x['arrival_index']}
                                            for x in sorted(s['pending_items'],key=lambda x:x['arrival_index'])]}
    assert digest(effective)==b['effective_state_digest']==g['effective_state_digest']
    assert digest(g['payload'])==b['geometry_values_digest']
    assert b['observation_digest']==g['observation_digest']==n['observation']['observation_digest']
    assert b['profile']==g['profile']=='geometry_runtime_shortest_decimal_v1'
    assert b['record_digest']==digest({k:v for k,v in b.items() if k!='record_digest'})
    assert b['source_manifest_digest']==digest(src)
    for k,v in local['identity'].items(): assert b[k]==v
    for k,v in local['fixture_external_identities'].items(): assert b[k]==v
    assert digest(local['environment'])==b['environment_digest']
    assert digest(read(DEV/'config_snapshot.json'))==b['config_digest']
    assert strict(a['binding'],b)
    assert a['semantic_digest']==digest({k:v for k,v in a.items() if k!='semantic_digest'})
    assert a['outcome']==r['status'] and len(r['candidates'])<=48
    ids=[c['candidate_id'] for c in r['candidates']]
    assert len(ids)==len(set(ids)) and all(x.startswith('GR1_') for x in ids)
    pool=[];raw_count=0
    for item in a['items']:
        raw_count+=len(item['raw_valid_candidates'])
        assert item['raw_valid_count']==len(item['raw_valid_candidates'])
        if r['status']!='ERROR':
            assert item['enumeration_complete'] and item['final_candidates']<=16
            by_key={tuple(x['action_key']):x for x in item['raw_valid_candidates']}
            assert len(by_key)==len(item['raw_valid_candidates'])
            assert len(item['final_action_keys'])==item['final_candidates']
            for key in item['final_action_keys']: pool.append(by_key[tuple(key)]['candidate'])
        for rec in item['raw_valid_candidates']:
            c=rec['candidate'];key=rec['action_key']
            assert c['pick_item_id']==item['item_id']==key[0]
            assert c['pose']['yaw_deg']==int(key[4])
            assert [Fraction(str(c['pose'][k])) for k in ('x_mm','y_mm','z_base_mm')]==list(map(Fraction,key[5:]))
            fp=digest({'backend':r['backend'],'input':digest(b),'action':key,'source_contract':'runtime_snapshot_v1'})
            assert c['candidate_fingerprint']==fp and c['candidate_id']=='GR1_'+fp[:24]
    if r['status']!='ERROR': assert strict(pool,r['candidates'])
    else: assert r['candidates']==[]
    if 'ledger_views' in a:
        saved=[{k:x[k] for k in ('item_id','supported_load_kg','support_fractions')} for x in s['placed_items']]
        assert strict(saved,a['ledger_views']['saved'])
    raw_total+=raw_count;final_total+=len(r['candidates'])
    case_rows.append({'case':case.name,'status':r['status'],'raw_saved_actions':raw_count,'final_saved_actions':len(r['candidates']),'error':r['error']})
for row in read(DEV/'case_summary.json')['legacy_regression']:
    expected=Path(row['input_path'].replace('_input.json','_result.json'))
    assert canonical(read(expected))==canonical(read(DEV/'legacy_regression'/f"{row['case']}_actual.json"))
faults=[]
for p in sorted((DEV/'faults').glob('*/result.json')):
    r=read(p);assert r['status']=='ERROR' and r['candidates']==[]
    faults.append({'case':p.parent.name,'saved_error':r['error']})
print(json.dumps({'status':'PASS_SAVED_FACTS_ONLY','manifest_files':len(m['files']),'production_files':len(src),
                 'cases':case_rows,'raw_saved_actions':raw_total,'final_saved_actions':final_total,
                 'faults':faults,'legacy_full_saved_result_comparisons':3,
                 'production_imports':0,'candidate_generation':0,'orders':0,'PCT_LP':0,'models':0,
                 'not_proven':['live capture rejection behavior','physical generation rerun','checkpoint resume','public wiring','research benefit']},ensure_ascii=False,indent=2))
