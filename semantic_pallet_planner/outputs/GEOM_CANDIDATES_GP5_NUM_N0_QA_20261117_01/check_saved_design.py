"""Read-only design QA: saved bytes, literal arithmetic and symbolic dependencies.
No project imports, bridge implementation, physical checks or candidate execution.
"""
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import struct
import subprocess

OUT=Path(__file__).parent
DEV=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N0_20261117_01'
SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='83327dcb04b2a829cc80318a180e9b3694d5a225'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
manifest=read(DEV/'delivery_manifest.json')
for row in manifest['files']:
    raw=(subprocess.check_output(['git','show',HEAD+':'+row['path']])
         if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
    assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
current={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
         if p.is_file() and p.suffix in ('.py','.json')
         and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
source=read(DEV/'source_inventory.json')
assert current==source['files'] and digest(current)==source['source_identity']
assert current==read(DEV.parent/'GEOM_CANDIDATES_GP5_P1_R1_20261117_01/source_manifest.json')['files']
historical=0
for group in read(DEV/'readonly_receipt.json')['manifests']:
    p=Path(group['manifest']);assert sha(p.read_bytes())==group['manifest_sha256']
    for row in read(p)['files']:
        raw=(subprocess.check_output(['git','show',group['navigation_revision']+':'+row['path']])
             if Path(row['path']).name=='README.md' else Path(row['path']).read_bytes())
        assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],row['path']
        historical+=1
for row in read(DEV/'read_inventory.json'):
    p=Path(row['path'])
    raw=(subprocess.check_output(['git','show','be4ba50a14f15d6fd822aad9d3d81b8dbc585a2c:'+str(p)])
         if p.name=='README.md' else p.read_bytes())
    assert sha(raw)==row['sha256'],str(p)
names=read(DEV/'proposed_name_inventory.json')['names']
for name,paths in names.items():
    assert not paths and not any(name.encode() in (SRC/k).read_bytes() for k in current),name
examples=read(DEV/'hand_examples.json')
for row in examples['positive']:
    expected=row['source'] if row['yaw']==0 else [row['source'][1],row['source'][0],row['source'][2]]
    for raw,target,origin,proof in zip(row['hand_raw'],row['hand_target'],expected,row['axes']):
        assert Fraction(raw)==Fraction(target) and type(target) is type(origin)
        assert Fraction(raw)==Fraction(int(proof['raw_ratio'][0]),int(proof['raw_ratio'][1]))
        assert Fraction(target)==Fraction(int(proof['target_ratio'][0]),int(proof['target_ratio'][1]))
        if type(target) is float:assert struct.pack('>d',target)==struct.pack('>d',origin)
for row in examples['negative']:
    # repr() strings here are fixed literal int/float source examples, not code.
    def number(text):return float(text) if any(c in text for c in '.eE') else int(text)
    assert Fraction(number(row['a']))!=Fraction(number(row['b']))
failure=read(DEV/'saved_failure_receipt.json');raw=Path(failure['path']).read_bytes()
assert sha(raw)==failure['sha256']
d=json.loads(raw);assert d['summary']['placed_items']==1 and d['summary']['termination_reason']=='RUNTIME_INPUT_INVALID'

# Design data gives proof -> shadow evidence -> published shadow candidate digest.
# Existing candidate_digest convention is digest(full candidate), including ID.
# This is a symbolic specification audit, not a production reproducer.
inventory=read(DEV/'contract_inventory.json')
assert 'physical_and_derived_equivalence' in inventory['proof_core_required']
assert 'published_after_ref' in inventory['shadow_evidence_required']
assert 'candidate_digest' in inventory['shadow_state_required']
dependencies={
    'published_fingerprint':['proof_core_digest'],
    'published_candidate':['published_fingerprint'],
    'published_candidate_digest':['published_candidate'],
    'published_shadow_bytes':['published_candidate_digest'],
    'published_after_ref':['published_shadow_bytes'],
    'proof_core_digest':['published_after_ref'],
}
visiting=[];done=set();cycle=[]
def visit(node):
    global cycle
    if node in visiting:
        cycle=visiting[visiting.index(node):]+[node];return
    if node in done or cycle:return
    visiting.append(node)
    for dep in dependencies[node]:visit(dep)
    visiting.pop();done.add(node)
for node in dependencies:visit(node)
assert cycle
(OUT/'identity_dependency_review.json').write_text(json.dumps({
    'schema':'geometry_num_n0_identity_dependencies_qa_v1',
    'status':'PARTIAL_SPECIFICATION_NOT_PROVEN_ACYCLIC',
    'assumption':'shadow candidate_digest means digest(full published candidate), as current candidate mapping convention; design does not define an identity-free projection',
    'dependency_direction':'node requires listed dependencies',
    'dependencies':dependencies,'cycle':cycle,
    'alternative_interpretation':'If pre-ID content is intended, exact excluded fields, domain/version, shadow field meaning and final-ID binding must be stated; not silently inferred by implementer.',
    'production_execution':False,'not_a_hash_fixed_point_or_bridge_implementation':True,
},ensure_ascii=False,indent=2)+'\n')
(OUT/'saved_design_verification.json').write_text(json.dumps({
    'status':'PASS_SAVED_INTEGRITY_AND_LITERAL_ARITHMETIC_ONLY',
    'manifest_members':len(manifest['files']),'historical_members':historical,
    'source_files':len(current),'source_identity':source['source_identity'],
    'source_drift':False,'proposed_names_unregistered':len(names),
    'literal_positive_rows':len(examples['positive']),'literal_negative_rows':len(examples['negative']),
    'NUM-01':'OPEN_ARCHIVED_FAILURE_PRESERVED','identity_dag':'BLOCKING_DESIGN_AMBIGUITY',
    'production_imports':0,'candidate_order_shadow_kernel_solver_model_execution':0,
    'original_verifier':'failed precommit HEAD assertion; independent check uses pinned delivery/navigation revisions without altering original',
},ensure_ascii=False,indent=2)+'\n')
print('PASS saved bytes/source/literal arithmetic; identity DAG has blocking unresolved dependency; no project imports')
