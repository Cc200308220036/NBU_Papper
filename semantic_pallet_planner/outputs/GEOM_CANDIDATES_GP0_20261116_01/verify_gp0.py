"""Read-only GP0 verification. Stdlib only; never imports project modules.

Run from repository root. --pre-seal skips the not-yet-written delivery seal.
This checks saved bytes/contracts, NOT geometry, load physics or runtime behavior.
"""
import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
assert (ROOT / 'AGENTS.md').is_file() and ROOT.name == 'NBU_Papper'
PKG = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'
FIXED = ['P01_ffcfcc6e4af4','P02_f17e03ef6116','P03_81c78da5f3a7','P04_53bacc63aa29','P05_392be366b95d']
COUNTS = {}
def ok(name, value=True):
    if not value: raise AssertionError(name)
    COUNTS[name] = 'PASS'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p, exact=False):
    def pairs(items):
        d = {}
        for k,v in items:
            if k in d: raise ValueError('duplicate key: '+k)
            d[k] = v
        return d
    return json.loads(p.read_text(), object_pairs_hook=pairs,
                      parse_float=Decimal if exact else float,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
def canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False)
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()
def pointer(v, p):
    if not p: return v
    assert p.startswith('/')
    for t in p[1:].split('/'):
        t = t.replace('~1','/').replace('~0','~')
        v = v[int(t)] if isinstance(v,list) else v[t]
    return v
def check_ref(r):
    p = ROOT/r['path']
    assert p.is_file(), r['path']
    assert sha(p)==r['sha256'], 'digest mismatch: '+r['path']
    return p
def leaves(v, p=''):
    if isinstance(v,dict) and v:
        for k,x in v.items(): yield from leaves(x,p+'/'+k.replace('~','~0').replace('/','~1'))
    elif isinstance(v,list) and v:
        for i,x in enumerate(v): yield from leaves(x,p+'/'+str(i))
    else: yield p,v
def closed(v, names): assert set(v)==set(names), (set(v)-set(names),set(names)-set(v))

json_files = sorted(OUT.rglob('*.json'))
for p in json_files: load(p)
ok('all_package_json_parse_no_duplicate_or_nonfinite')
src=load(OUT/'source_manifest.json')
actual={p.relative_to(PKG).as_posix():sha(p) for p in sorted(PKG.rglob('*'))
        if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
ok('complete_source_universe_unchanged',actual==src['files'])
baseline=load(OUT/'baseline_inventory.json')
for r in baseline['code_evidence']:
    p=check_ref(r); tree=ast.parse(p.read_text()); n=tree
    for name in r['symbol'].split('.'):
        n=next(x for x in n.body if isinstance(x,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
    assert (n.lineno,n.end_lineno)==(r['line'],r['end_line'])
    assert sorted({ast.unparse(c.func) for c in ast.walk(n) if isinstance(c,ast.Call)})==r['direct_call_expressions']
ok('39_symbol_spans_calls_and_file_hashes',len(baseline['code_evidence'])==39)
for r in baseline['old_output_contracts']:
    s=load(check_ref(r));assert s['required']==r['required'] and s['additionalProperties'] is False
for name,h in baseline['physical_manifest_files'].items():assert sha(PKG/name)==h
for r in baseline['applicable_agents']+[baseline['design']]+baseline['report_claims']:check_ref(r)
for token,old_matches in baseline['occupancy_scan'].items():
    assert old_matches==[]
    assert not any(token in (PKG/k).read_text() for k in actual)
ok('old_contracts_physical_manifest_and_unregistered_names')

conf=load(OUT/'config_snapshot.json');old=load(check_ref(conf['legacy_source']))
assert old==conf['legacy_generator']
d=conf['new_generator_draft']
closed(d,['version','candidate_backend','production_registered','runtime_protocol','geometry_version','audit_version',
          'buffer_capacity','yaw_degrees','per_item_top_k','joint_top_k','feature_profile','feature_version','prompt_version',
          'display_order_seed','max_request_bytes','numerical_profile','publish_quantum_mm','rounding','negative_zero','reducer',
          'budgets','source_types','points_per_host_yaw_max','physical_checks','original_support_ratio_min','geometry_score_weights',
          'monitor_algorithm','monitor_invocation','cache','fallback','partial_pool','wall_clock_cutoff','authorization'])
assert digest(d)==conf['draft_semantic_digest']
assert d['candidate_backend']=='ems_surface_hybrid_v1' and d['runtime_protocol']=='jev_packaging_geometry_compare_v14'
assert d['production_registered'] is False and d['feature_profile']=='F0_existing_facts'
assert (d['buffer_capacity'],d['per_item_top_k'],d['joint_top_k'],d['yaw_degrees'])==(3,16,48,[0,90])
assert d['budgets']==dict(active_spaces=4096,space_containment_comparisons=2000000,surface_event_cells=16384,
                         surface_expansion_cell_checks=2000000,raw_point_attempts_per_item=32768)
assert all(type(x) is int and x>0 for x in d['budgets'].values())
assert d['rounding']=='HALF_EVEN' and d['publish_quantum_mm']=='0.001'
assert d['monitor_algorithm']=='pct_exact_pose_network_v3' and d['max_request_bytes']==96000
assert d['fallback']==d['partial_pool']=='FORBIDDEN' and d['wall_clock_cutoff'] is False
assert d['authorization']==dict(stage='GP0_ONLY',model_calls=0,candidate_generations=0,orders=0,lp_solves=0)
ok('draft_closed_fields_fixed_versions_budgets_and_zero_authorization')

manifest=load(OUT/'input_manifest.json');nav=load(check_ref(manifest['navigation']))
assert manifest['fixed_point_ids']==[p['point_id'] for p in nav['points']]==FIXED
assert manifest['denominator']==len(manifest['points'])==5
total_fields=0
for p in manifest['points']:
    assert p['status']=='READY_SAVED_PUBLIC_INPUT' and p['missing']==p['conflicts']==[]
    for r in p['historical_refs'].values():check_ref(r)
    epfile=check_ref(p['primary_source']);ep=load(epfile);ep_exact=load(epfile,True)
    event=pointer(ep,p['primary_source']['pointer']);event_exact=pointer(ep_exact,p['primary_source']['pointer'])
    snapfile=check_ref(p['snapshot']);snap=load(snapfile);snap_exact=load(snapfile,True)
    closed(snap,['version','point_id','decision_id','current_public_state','public_observation','input_scope'])
    assert snap['version']=='geometry_comparison_saved_input_draft_v1'
    assert snap['point_id']==p['point_id'] and snap['decision_id']==event['decision_id']==p['decision_id']
    assert snap['input_scope']=='CURRENT_PUBLIC_ONLY_NOT_EXECUTABLE_CHECKPOINT'
    b=snap['current_public_state'];o=snap['public_observation']
    assert b==event['before'] and o==event['observation']
    assert snap_exact['current_public_state']==event_exact['before'] and snap_exact['public_observation']==event_exact['observation']
    expected=dict(leaves({'current_public_state':b,'public_observation':o}))
    assert set(expected)=={r['snapshot_pointer'] for r in p['field_provenance']}
    for r in p['field_provenance']:
        v=pointer(ep,r['source_pointer']);assert v==pointer(snap,r['snapshot_pointer'])
        assert digest(v)==r['value_digest']
    total_fields+=len(p['field_provenance'])
    req=manifest['requirements_from_code']
    assert set(req['state'])<=set(b) and set(req['container'])<=set(b['container'])
    ids=[x['item_id'] for x in b['placed_items']]+[x['item']['item_id'] for x in b['pending_items']]
    assert len(set(ids))==len(ids) and set(ids)==set(b['arrived_ids'])==set(b['attributes'])
    assert b['buffer_capacity']==3 and len(b['pending_items'])<=3
    assert b['arrival_count']==len(ids) and b['placed_count']==len(b['placed_items'])
    slots=[x['slot'] for x in b['pending_items']];assert len(set(slots))==len(slots)
    for pending in b['pending_items']:
        assert set(req['pending'])<=set(pending) and set(req['item'])<=set(pending['item'])
        assert pending['arrival_index']==b['arrived_ids'].index(pending['item']['item_id'])
        assert type(pending['slot']) is int and 0<=pending['slot']<3
    for item in b['placed_items']:
        assert set(req['item']+req['placed_extra'])<=set(item)
        assert isinstance(item['support_fractions'],list) and item['supported_load_kg']>=0
        # Presence/identity only. Do not recalculate support geometry/fractions/loads.
        for edge in item['support_fractions']:
            assert set(edge)=={'item_id','fraction'} and edge['item_id'] in {x['item_id'] for x in b['placed_items']}
            assert 0<edge['fraction']<=1
    available=sorted(b['pending_items'],key=lambda x:x['arrival_index'])
    assert [x['object_id'] for x in o['available_objects']]==[x['item']['item_id'] for x in available]
    for observed,item in zip(o['placed_objects'],b['placed_items']):
        assert observed['object_id']==item['item_id']
        for k in ('mass_kg','dimensions_mm','stackable','pose','oriented_size_mm'):assert observed[k]==item[k]
    for observed,pending in zip(o['available_objects'],available):
        for k in ('mass_kg','dimensions_mm','stackable'):assert observed[k]==pending['item'][k]
    for item in b['placed_items']+[x['item'] for x in available]:
        assert type(item['stackable']) is bool and item['mass_kg']>0
        assert all(type(v) in (int,float) and v>0 for v in item['dimensions_mm'].values())
        assert item['top_load_limit_kg_synthetic']>=0
        attrs=b['attributes'][item['item_id']]
        assert set(req['attribute'])<=set(attrs)
        assert attrs['object_id']==item['item_id'] and attrs['physical_top_load_limit_kg']==item['top_load_limit_kg_synthetic']
    assert o['buffer_context']==dict(capacity=3,event_index=b['event_index'],end_of_stream=b['end_of_stream'],
        pending=[dict(object_id=x['item']['item_id'],slot=x['slot'],arrival_index=x['arrival_index']) for x in available])
    # Saved binding digests only, not a production observation reconstruction.
    state_keys=('container','placed_objects','available_objects','regions','buffer_context','capability_version',
                'coordinate_convention','placement_convention','rendering_version','spatial_eps_mm','sampling_grid_mm')
    assert digest({k:o[k] for k in state_keys})==o['state_hash']
    assert digest(o['instruction_text'])==o['instruction_digest']
    assert digest({k:v for k,v in o.items() if k not in ('request_id','observation_digest')})==o['observation_digest']
    pool=load(ROOT/p['historical_refs']['pool']['path'])
    assert pool==event['bundle']['selectable_candidates'] and len(pool)==p['pool_count']
    assert digest(pool)==event['bundle']['selectable_digest']==event['bundle']['physical_digest']
    assert pool==event['bundle']['physical_candidates']
    assert event['context']['local_binding']['physical_digest']==digest(pool)
    assert all(event['context']['local_binding'][k]==o[k]==p['bindings'][k] for k in p['bindings'])
    # Reproduce the SAVED export projection; no physical or support calculation.
    def public_item(x):return dict(item_id=x['item_id'],size_mm=[x['dimensions_mm'][k] for k in ('length','width','height')],
        mass_kg=x['mass_kg'],max_top_load_kg=x['top_load_limit_kg_synthetic'],stackable=x['stackable'])
    projected=dict(container={k:b['container'][k] for k in ('length_mm','width_mm','max_height_mm','max_payload_kg')},
        buffer=[public_item(x['item']) for x in b['pending_items']],placed_objects=[public_item(x)|dict(pose=x['pose'],
        oriented_size_mm=x['oriented_size_mm'],area_current_top_load_kg=x['supported_load_kg'],
        area_remaining_top_load_kg=x['top_load_limit_kg_synthetic']-x['supported_load_kg']) for x in b['placed_items']])
    assert projected==load(ROOT/p['historical_refs']['state']['path'])
    # No new point or pose is constructed; historical upper bounds checked as data.
    assert len(pool)<=48
    assert all(sum(c['pick_item_id']==x['item']['item_id'] for c in pool)<=16 for x in available)
ok('five_sources_hashes_complete_fields_pointers_lexemes_and_saved_bindings')
plan=load(OUT/'comparison_plan.json')
assert manifest['fixed_point_ids']==FIXED and plan['denominator']==5 and plan['fixed_point_ids']==FIXED
assert plan['fairness']['feature_profile']=='F0_existing_facts' and plan['outputs'][-1]=='at most one combined top/side figure per state; <=5'
assert plan['fairness']['per_item_top_k']==16 and plan['fairness']['joint_top_k']==48 and not plan['reuse_old_jm_permit']
assert plan['GP5']==plan['GP6']=='NOT_AUTHORIZED_NOT_SCHEDULED'
assert all(x==0 for x in plan['authorization'].values())
assert plan['input_manifest_sha256']==sha(OUT/plan['input_manifest'])
for r in (plan['source_manifest'],plan['config_snapshot']):check_ref(r)
ok('comparison_plan_frozen_five_F0_zero_execution')
protocol=(OUT/'protocol_draft.md').read_text()
for token in ('HALF_EVEN','POSE_REPRESENTATION_REJECTED','PHYSICAL_CHECK_DISAGREEMENT','GEOMETRY_BUDGET_EXCEEDED',
              'OK_EMPTY','4096','2000000','16384','32768','SELECTED','MONITORED','UNKNOWN_SEND'):
    assert token in protocol
ok('draft_required_semantics_present_not_production_schema_validation')
script=ast.parse(Path(__file__).read_text())
stdlib={'ast','decimal','hashlib','json','pathlib','platform','re','sys'}
for n in ast.walk(script):
    if isinstance(n,ast.Import):assert all(x.name.split('.')[0] in stdlib for x in n.names)
    if isinstance(n,ast.ImportFrom):assert n.module.split('.')[0] in stdlib
ok('verifier_stdlib_imports_only_no_project_entrypoints')

handoff=load(OUT/'handoff.json')
assert handoff['stop'] is True and handoff['next_stage_admission']=='INDEPENDENT_QA_ONLY'
assert handoff['A00']=='PASS_DEVELOPER_SELF_CHECK_PENDING_INDEPENDENT_QA'
assert handoff['production_registered'] is False and handoff['delivery_commit'] is None
checks=load(OUT/'checks.json')
assert all(x['status']=='PASS' for x in checks['A00'])
assert all(checks[k]=='NOT_RUN' for k in ('A01','A02','A03','A04','A05','A06'))
for p in (OUT/'protocol_draft.md',ROOT/handoff['report'],ROOT/'docs/03_阶段产出分析/几何规划模块/README.md'):
    for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if not link.startswith(('https://','http://','#')):assert (p.parent/link.split('#')[0]).exists(),(p,link)
ok('handoff_A00_only_and_new_document_links')
if '--pre-seal' not in sys.argv:
    seal=load(OUT/'delivery_manifest.json')
    assert 'delivery_manifest.json' not in seal['package_files']
    assert set(seal['package_files'])=={p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
    for path,h in seal['package_files'].items():assert sha(OUT/path)==h,path
    for path,h in seal['external_delivery_files'].items():assert sha(ROOT/path)==h,path
    assert set(handoff['new_files'])=={str((OUT/x).relative_to(ROOT)) for x in seal['package_files']}|{str((OUT/'delivery_manifest.json').relative_to(ROOT))}|{x for x in seal['external_delivery_files'] if x!='docs/03_阶段产出分析/README.md'}
    ok('delivery_manifest_complete_no_self_hash_no_cycles')
print(json.dumps(dict(status='PASS_STATIC_SAVED_FACTS_ONLY',mode='PRE_SEAL' if '--pre-seal' in sys.argv else 'SEALED_READ_ONLY',
    python=platform.python_version(),source_files=len(actual),symbols=len(baseline['code_evidence']),states=5,
    field_records=total_fields,checks=COUNTS,excluded=['production imports','candidate generation','order execution','LP','model calls','support/load physics recomputation']),ensure_ascii=False,indent=2))
