"""Independent saved metadata QA. No project imports or business execution."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

OUT=Path(__file__).parent
DEV=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N0_R1_20261117_01'
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='f1974261de576944b90910b28dd5b5165427fd08'
def read(p):return json.loads(p.read_bytes())
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

manifest=read(DEV/'delivery_manifest.json')
for r in manifest['files']:
    raw=(subprocess.check_output(['git','show',HEAD+':'+r['path']])
         if Path(r['path']).name=='README.md' else Path(r['path']).read_bytes())
    assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],r['path']
current={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
         if p.is_file() and p.suffix in ('.py','.json')
         and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
frozen=read(OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N0_20261117_01/source_inventory.json')
assert current==frozen['files'] and sha(enc(current))==frozen['source_identity']
historical=0
for folder,rev in [('GEOM_CANDIDATES_GP5_NUM_N0_20261117_01','83327dcb04b2a829cc80318a180e9b3694d5a225'),
                   ('GEOM_CANDIDATES_GP5_NUM_N0_QA_20261117_01','77d3ce5ac0884841609c53396b39b3d1b261e958')]:
    for r in read(OUT.parent/folder/'delivery_manifest.json')['files']:
        raw=(subprocess.check_output(['git','show',rev+':'+r['path']])
             if Path(r['path']).name=='README.md' else Path(r['path']).read_bytes())
        assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],r['path']
        historical+=1

inventory=read(DEV/'identity_contract_inventory.json')
assert inventory['content_excluded_paths']==['/candidate_id','/candidate_fingerprint']
assert 'candidate_digest' not in inventory['shadow_state_required']
assert 'candidate_digest' in inventory['shadow_binding_required']
assert 'physical_and_derived_equivalence' in inventory['proof_core_required']
assert all(x in inventory['shadow_evidence_required'] for x in ('raw_after_ref','published_after_ref','raw_derived_ref','published_derived_ref'))

fixture=read(DEV/'fixed_metadata_example.json');nodes=fixture['nodes']
def validate(graph):
    active=set();done=set();ordered=[]
    def visit(k):
        if k not in graph:raise ValueError('MISSING')
        if k in active:raise ValueError('CYCLE')
        if k in done:return
        n=graph[k];active.add(k);raw=enc(n['value'])
        if sha(raw)!=n['semantic_digest'] or sha(raw)!=n['blob_sha256'] or len(raw)!=n['size_bytes']:raise ValueError('BYTES')
        if set(n['requires'])!=set(n['value']['refs']) or set(n['requires'])!=set(n['value']['dependencies']):raise ValueError('EDGE_SET')
        for d in n['requires']:
            visit(d)
            if n['value']['refs'][d]!={'version':'geometry_blob_ref_v1','sha256':graph[d]['blob_sha256']} or n['value']['dependencies'][d]!=graph[d]['semantic_digest']:raise ValueError('REFERENCE')
        active.remove(k);done.add(k);ordered.append(k)
    for k in graph:visit(k)
    return ordered
order=validate(nodes)
positions={n:i for i,n in enumerate(fixture['topological_order'])}
assert set(positions)==set(nodes) and all(positions[d]<positions[n] for n in nodes for d in nodes[n]['requires'])
edges=sum(len(n['requires']) for n in nodes.values())
def closure(n,seen=None):
    result=set() if seen is None else seen
    for d in nodes[n]['requires']:
        if d not in result:result.add(d);closure(d,result)
    return result
assert not {'full_candidate','fingerprint','published_final_shadow','raw_final_shadow','final_binding','publication'}.intersection(closure('proof'))
assert {'proof','full_candidate','raw_final_shadow','published_final_shadow'}<=closure('final_binding')
assert {'raw_after','published_after','raw_derived','published_derived'}<=closure('proof')
negative=[]
for label in ('missing_published_after','tampered_proof','swapped_after_evidence','swapped_derived_evidence'):
    g=copy.deepcopy(nodes)
    if label=='missing_published_after':del g['published_after']
    elif label=='tampered_proof':g['proof']['value']['payload']['ordinal']=1
    else:
        a,b=('raw_after','published_after') if label=='swapped_after_evidence' else ('raw_derived','published_derived')
        g[a],g[b]=g[b],g[a]
    try:validate(g)
    except ValueError as exc:negative.append({'case':label,'result':'REJECTED','reason':str(exc)})
    else:raise AssertionError(label)

# Specification-level construction dependencies. Every pre-ID core is tied to
# content only; final complete-candidate wrappers are strictly downstream.
save('dag_verification.json',{'status':'PASS_LITERAL_METADATA_AND_DESIGN_DEPENDENCY_AUDIT',
    'fixture_nodes':len(nodes),'fixture_edges':edges,'topological_order':order,
    'proof_transitive_dependencies':sorted(closure('proof')),
    'final_binding_transitive_dependencies':sorted(closure('final_binding')),
    'negative':negative,'ID-01':'CLOSED_DESIGN_ONLY',
    'limits':'Fixture domains and tokens differ from production H/L/B contracts; not production vectors, candidate construction, physical proof or runtime acceptance.'})
namespace={'declared_policy':inventory['versions']['policy'],'namespace_field':inventory['new_publication_namespace']}
assert namespace['declared_policy']=='geometry_native_shape_publication_policy_v3'
assert namespace['namespace_field']=='geometry_native_shape_publication_policy_v2'
save('saved_metadata_verification.json',{'status':'PASS_SAVED_INTEGRITY',
    'delivery_members':len(manifest['files']),'historical_members':historical,
    'production_files':len(current),'source_identity':frozen['source_identity'],'source_drift':False,
    'ID-01':'DESIGN_REMEDIATION_SUPPORTED','namespace_inconsistency':namespace,
    'original_checker':'NOT_RUN_WRITES_ORIGINAL_ARTIFACTS','production_imports':0,
    'candidate_shadow_order_recovery_kernel_solver_freeze_model_execution':0})
print('PASS saved identities and independent metadata DAG; one stale v2 namespace field requires correction before registration; no production imports')
