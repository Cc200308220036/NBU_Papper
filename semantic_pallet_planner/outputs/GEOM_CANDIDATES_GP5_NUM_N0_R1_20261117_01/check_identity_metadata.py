"""Standard-library literal metadata/DAG checks only; no project imports or physics.
Writes only this new design evidence package. Not a bridge or candidate builder.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path(__file__).parent
DEV = OUT.parent / 'GEOM_CANDIDATES_GP5_NUM_N0_20261117_01'
QA = OUT.parent / 'GEOM_CANDIDATES_GP5_NUM_N0_QA_20261117_01'
def sha(b): return hashlib.sha256(b).hexdigest()
def enc(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def save(name, value): (OUT/name).write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode()+b'\n')
def read(p): return json.loads(p.read_bytes())
# Verify delivered historical bytes before any navigation edits; saved navigation revisions thereafter.
verified = {}
for folder, rev in [(DEV, '83327dcb04b2a829cc80318a180e9b3694d5a225'), (QA, '77d3ce5ac0884841609c53396b39b3d1b261e958')]:
    m = read(folder/'delivery_manifest.json')
    for row in m['files']:
        p = Path(row['path'])
        b = subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name == 'README.md' else p.read_bytes()
        assert sha(b) == row['sha256'] and len(b) == row['size_bytes'], str(p)
    verified[str((folder/'delivery_manifest.json').relative_to(Path.cwd())) if folder.is_absolute() else str(folder/'delivery_manifest.json')] = {'manifest_sha256':sha((folder/'delivery_manifest.json').read_bytes()), 'members':len(m['files']), 'navigation_revision':rev}
src = Path('semantic_pallet_planner/src/semantic_pallet_planner')
current = {str(p.relative_to(src)):sha(p.read_bytes()) for p in src.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(src).parts)}
old = read(DEV/'source_inventory.json')
assert current == old['files'] and sha(enc(current)) == old['source_identity']
inventory = read(OUT/'identity_contract_inventory.json')
assert 'candidate_digest' not in inventory['shadow_state_required']
assert 'candidate_digest' in inventory['shadow_binding_required']
assert inventory['content_excluded_paths'] == ['/candidate_id','/candidate_fingerprint']
assert 'physical_and_derived_equivalence' in inventory['proof_core_required']
assert all(x in inventory['shadow_evidence_required'] for x in ['raw_after_ref','published_after_ref','raw_derived_ref','published_derived_ref'])
# All leaves below are literal metadata tokens, NOT candidate/state/physical outputs.
# Object references carry exact byte hashes. Semantic digest domains are independent.
nodes = {}
def node(name, deps, payload, domain=None):
    assert name not in nodes and all(x in nodes for x in deps)
    value = {'domain':domain or 'gp5_num_n0_r1_literal_'+name+'_v1','payload':payload,
             'dependencies':{x:nodes[x]['semantic_digest'] for x in deps},
             'refs':{x:{'version':'geometry_blob_ref_v1','sha256':nodes[x]['blob_sha256']} for x in deps}}
    raw = enc(value)
    nodes[name] = {'requires':deps,'value':value,'semantic_digest':sha(raw),'blob_sha256':sha(raw),'size_bytes':len(raw)}
for name in ['bindings','native','geometry','raw_generation','raw_pool','raw_candidate','source_dimensions']:
    node(name, [], {'literal_token':name+'-fixed-01'})
node('raw_content',['raw_candidate'],{'all_non_identity_fields_token':'raw-content-A'})
node('published_content',['raw_content','source_dimensions'],{'all_non_identity_fields_token':'published-content-A'})
for side in ['raw','published']:
    node(side+'_after',[side+'_content','native'],{'placed_items_token':side+'-after-A','candidate_content_digest':nodes[side+'_content']['semantic_digest']})
    node(side+'_derived',[side+'_content','native'],{'derived_fields_token':side+'-derived-A'})
node('equivalence',['raw_after','published_after','raw_derived','published_derived'],{'oracle_errors':[[],[]],'axis_proofs_token':'three-exact-ratios','derived_proofs_token':'all-paths-required'})
node('proof',['bindings','native','geometry','raw_generation','raw_pool','raw_candidate','source_dimensions','raw_content','published_content','equivalence'],{'ordinal':0,'raw_identity_token':'raw-id-A','action_key_token':'fixed-eight-tuple'})
node('fingerprint',['bindings','raw_pool','raw_candidate','published_content','proof'],{'policy':'geometry_native_shape_publication_policy_v3','backend':'literal-backend','publication_action_key_token':'fixed-eight-tuple'})
fingerprint=nodes['fingerprint']['semantic_digest']
node('full_candidate',['published_content','fingerprint'],{'candidate_id':'GP5N3_'+fingerprint,'candidate_fingerprint':fingerprint})
for side in ['raw','published']:
    node(side+'_final_shadow',[side+'_after', 'raw_candidate' if side=='raw' else 'full_candidate','proof'],{'candidate_digest':nodes['raw_candidate' if side=='raw' else 'full_candidate']['semantic_digest']})
node('final_binding',['proof','raw_final_shadow','published_final_shadow','full_candidate','equivalence'],{'ordinal':0,'published_id':'GP5N3_'+fingerprint})
node('mapping',['final_binding','proof','full_candidate','raw_candidate'],{'ordinal':0})
node('published_pool',['full_candidate'],{'ordered_ordinals':[0]})
node('publication',['mapping','published_pool','bindings','raw_generation','raw_pool'],{'validation_counts_token':'NOT_RUN_LITERAL_ONLY'})
node('telemetry',['publication'],{'timings':'NOT_RUN'})
node('audit',['publication','published_pool','raw_generation','telemetry'],{'literal':'audit-A'})
# Traverse actual content-addressed edges, not only an abbreviated ID/proof sketch.
def validate(graph):
    active=set(); done=set()
    def visit(k):
        if k not in graph: raise ValueError('MISSING_ARTIFACT')
        if k in active: raise ValueError('CYCLE')
        if k in done: return
        active.add(k); n=graph[k]
        if sha(enc(n['value'])) != n['semantic_digest'] or sha(enc(n['value'])) != n['blob_sha256']: raise ValueError('TAMPER')
        if set(n['value']['refs']) != set(n['requires']) or set(n['value']['dependencies']) != set(n['requires']): raise ValueError('EDGE_SET')
        for d in n['requires']:
            visit(d)
            if n['value']['refs'][d]['sha256'] != graph[d]['blob_sha256'] or n['value']['dependencies'][d] != graph[d]['semantic_digest']: raise ValueError('SWAPPED_EVIDENCE')
        active.remove(k); done.add(k)
    for k in graph: visit(k)
    return len(done)
assert validate(nodes)==len(nodes)
negative=[]
for label in ['missing_published_after','tampered_proof','swapped_after_evidence','swapped_derived_evidence']:
    g=copy.deepcopy(nodes)
    if label.startswith('missing'): del g['published_after']
    elif label.startswith('tampered'): g['proof']['value']['payload']['ordinal']=1
    else:
        a,b=('raw_after','published_after') if 'after' in label else ('raw_derived','published_derived')
        g[a],g[b]=g[b],g[a]
    try: validate(g)
    except ValueError as e: negative.append({'case':label,'result':'REJECT','reason':str(e)})
    else: raise AssertionError(label)
save('fixed_metadata_example.json',{'scope':'LITERAL_METADATA_NOT_PRODUCTION_CANDIDATES_OR_PHYSICS','nodes':nodes,'topological_order':list(nodes)})
save('verification.json',{'status':'PASS_METADATA_ONLY','nodes':len(nodes),'blob_transitive_edges':sum(len(n['requires']) for n in nodes.values()),'negative_cases':negative,'manifests':verified,'source_files':len(current),'source_identity':old['source_identity'],'production_imports':0,'candidate_shadow_order_kernel_solver_freeze_model_runs':0,'independent_QA':'PENDING'})
print('PASS literal metadata DAG, blob edges, four rejection cases; historical manifests and 565 source files unchanged')
