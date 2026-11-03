"""J4 packaging/load data contract. No candidate, execution or policy adaptation.

Uses DatasetOrderAdapter, frozen exposed sources, existing schema/manifest/guard
helpers. All layout-dependent facts are deliberately absent from fixed records.
"""
from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from importlib.resources import files
from pathlib import Path
import shutil
import subprocess

from .contracts import JevSelectError, digest, validate_schema
from .dataset_j4 import offline_dataset_guard, _sha, _protected_inventory
from .ledger import read, write

VERSION = 'jev_packaging_load_dataset_v1'
CONFIG_SHA256 = 'c08ad9194d29b2d08b58db71a024ce6f2fcba77b17de20ed9f2f8a65c9fd3da8'
SOURCE_AUDIT_SHA256 = 'fb84774d188a17a07f18d38bbdfc963f7819e5d916d975aa45942afc2940d75c'
PACKAGE = Path(__file__).parent
PHYSICS_FILES = ('planner/constraints.py', 'evaluation/geometry_oracle.py')
IMPLEMENTATION_FILES = (
    'dataset_packaging.py', 'dataset.py', 'dataset_j4.py', 'contracts.py', 'cli.py',
    'configs/packaging_load_v1.json', 'schemas/packaging_load_config_v1.schema.json',
    'schemas/packaging_load_task_v1.schema.json', 'tests/unit/test_packaging_load.py',
)


def require(condition, code):
    if not condition:
        raise JevSelectError('packaging_' + code)


def packaging_spec():
    path = files('semantic_pallet_planner.jev_select').joinpath('configs/packaging_load_v1.json')
    import hashlib
    require(hashlib.sha256(path.read_bytes()).hexdigest() == CONFIG_SHA256, 'config_not_frozen')
    result = read(path)
    validate_schema('packaging_load_config_v1', result)
    return result


def geometry_contract():
    return {
        'version':'jev_packaging_geometry_v1', 'mass_distribution':'uniform',
        'centroid_model':'geometric_center', 'shape':'upright rigid cuboid; quasi-static',
        'units':{'length':'mm','mass':'kg','capacity':'kg equivalent vertical load','area':'mm^2'},
        'origin':'pallet bottom center', 'pose':'x/y bottom-face center; z_base bottom elevation',
        'axes':{'x':'container length','y':'container width','z':'up'},
        'dimensions_mm_order':['length','width','height'],
        'oriented_size_mm_order':['world x extent','world y extent','world z extent'],
        'allowed_yaw_deg':[0,90], 'yaw_90':'swap length/width once; upright height unchanged',
        'positive_yaw_handedness':'UNVERIFIED: source only uses 0/90 extents; no signed rotation matrix',
        'centroid_world':'(x_center, y_center, z_base + height/2)',
        'corner_conversion':'(x_center-size_x/2, y_center-size_y/2, z_base); inverse adds half extents',
        'unit_conversion':'mm to m /1000 only at future adapter boundary, capacity kg unchanged',
        'candidate_tolerances':{'height_contact_mm':0,'xy_positive_contact_mm':0,
            'minimum_area_mm2':0,'boundary_mm':0,'collision_overlap_mm':0,
            'payload_kg':0,'load_kg':1e-9,'support_ratio':1e-9},
        'oracle_tolerances':{'height_contact_mm':1e-6,'xy_positive_contact_mm':1e-6,
            'boundary_mm':1e-6,'collision_overlap_mm':1e-6,'payload_kg':1e-6,
            'load_kg':1e-6,'support_ratio':1e-6,
            'minimum_area_mm2':'no standalone threshold; both contact side lengths > 1e-6 mm'},
        'display_rounding':{'pose_mm':3,'support_ratio':6,'support_fraction':9},
        'support_ratio_min':0.70,
        'local_center_check':'projection must lie in an actual contact rectangle, not merely convex hull',
        'load_model':'area-proportional sharing; recursively propagate increments to all ancestors; excludes own mass',
        'approximation':'70% support and local center check are not full static equilibrium or dynamic collapse proof',
        'known_conflicts':['candidate exact height contact vs oracle 1e-6 mm',
            'candidate exact bounds/collision vs oracle tolerances',
            'rounded visible pose must not replace internal decision precision',
            'signed yaw handedness requires explicit audit before non-axis-aligned transforms'],
        'excluded':['impact','sliding/friction','deformation','dynamic collapse'],
        'source_evidence':['planner/constraints.py:evaluate_pose, footprint_overlap, boxes_overlap_3d',
            'evaluation/geometry_oracle.py:bounds, support_rect, check_candidate'],
    }


def source_bundle(root, spec):
    """Authenticate only the already exposed normalized source snapshot."""
    from .dataset import DatasetOrderAdapter, calibrate_v2
    root = Path(root)
    for name, sha in spec['source_file_manifest'].items():
        path = (root/'sources'/name).resolve()
        require(path.is_relative_to(root.resolve()) and path.is_file() and _sha(path) == sha,
                'source_digest_mismatch')
    require(_sha(root/'source_manifest.json') == SOURCE_AUDIT_SHA256, 'source_audit_mismatch')
    base = DatasetOrderAdapter().load(root/'sources')
    originals = [t for t in base['tasks'] if t['business_configuration'] == 'B1']
    require(sorted(t['provenance']['original_source_order_key'] for t in originals) == spec['source_keys'], 'source_scope')
    stats, identities = calibrate_v2(originals)
    require(stats['instance_count'] == spec['expected_source_instances'] and
            stats['m_ref_kg'] == spec['calibration']['m_ref_kg'] and
            math.ceil(stats['m_ref_kg']) == spec['calibration']['scale_kg'], 'calibration_mismatch')
    return originals, stats, identities, base['split_manifest']


def profile_for(spec, sku, setting):
    if setting['assignment'] == 'source':
        return None
    if setting['assignment'] != 'hash':
        return next(p for p in spec['profiles'] if p['id'] == setting['assignment'])
    score = int(digest([VERSION,spec['seed'],sku])[:8],16) / 2**32
    cumulative = 0
    for profile in spec['profiles']:
        cumulative += profile['probability']
        if score < cumulative:
            return profile
    raise JevSelectError('packaging_profile_probability')


def materialize(root, spec):
    originals, stats, identities, split = source_bundle(root, spec)
    tasks = []; sku_map = {}; differences = []
    for source in originals:
        sid = source['scenario_id']
        for layer, setting in spec['layers'].items():
            task = {
                'version':VERSION, 'task_id':sid+'_'+layer, 'scenario_id':sid,
                'source_group_id':source['source_group_id'], 'partition':source['partition'],
                'source_order_key':source['provenance']['original_source_order_key'],
                'source_order_id':source['provenance']['original_source_order_id'],
                'mode':setting['mode'], 'layer':layer, 'buffer_capacity':spec['buffer_capacity'],
                'candidate_limits':copy.deepcopy(spec['candidate_limits']),
                'container':copy.deepcopy(source['container']),
                'arrival_order':copy.deepcopy(source['provenance']['original_arrival_order']),
                'mass_distribution':spec['mass_distribution'], 'centroid_model':spec['centroid_model'],
                'geometry_contract_version':'jev_packaging_geometry_v1',
                'regions':[], 'rules':[], 'items':[],
                'feasibility_status':'UNKNOWN', 'static_screen_status':'STATIC_SCREEN_PASSED',
                'witness':{'status':'NOT_AVAILABLE','candidate_reachability':'NOT_RUN','online_solvability':'NOT_RUN'},
                'runtime_compatibility':'NOT_RUN_TARGET_TWO_REQUIRED',
            }
            original_by_id = {o['item_id']:o for o in source['items']}
            for oid in task['arrival_order']:
                original = original_by_id[oid]; sku = identities[sid][oid]
                profile = profile_for(spec, sku, setting)
                source_profile = 'source_' + digest({k:v for k,v in original.items() if k != 'item_id'})[:16]
                profile_id = source_profile if profile is None else profile['id']+'_x'+str(setting['capacity_factor'])
                stackable = original['stackable'] if profile is None else profile['stackable']
                capacity = original['top_load_limit_kg_synthetic'] if profile is None else profile['capacity_kg']*setting['capacity_factor']
                item = copy.deepcopy(original)
                item.update(sku_id=sku, packaging_profile_id=profile_id, stackable=stackable,
                    top_load_limit_kg_synthetic=capacity, max_top_load_kg=capacity,
                    effective_top_permission_kg=capacity if stackable else 0,
                    physical_provenance='archived_source_geometry_mass; original measurement status unverified',
                    capacity_provenance='source_synthetic' if profile is None else 'controlled_synthetic_experimental',
                    original_physical=copy.deepcopy(original))
                task['items'].append(item)
                key = sku+'|'+profile_id
                entry = {'sku_id':sku, 'packaging_profile_id':profile_id,
                    'source_article_id':source['provenance']['article_ids'][oid],
                    'original_physical':{k:v for k,v in original.items() if k != 'item_id'},
                    'stackable':stackable, 'max_top_load_kg':capacity,
                    'effective_top_permission_kg':item['effective_top_permission_kg'],
                    'capacity_provenance':item['capacity_provenance'],
                    'reason':'unchanged source packaging' if profile is None else
                        'frozen experimental packaging hypothesis; no measured compression evidence',
                    'occurrences':[]}
                if key in sku_map:
                    require({k:v for k,v in sku_map[key].items() if k != 'occurrences'} ==
                            {k:v for k,v in entry.items() if k != 'occurrences'}, 'sku_profile_conflict')
                else:
                    sku_map[key] = entry
                sku_map[key]['occurrences'].append({'task_id':task['task_id'],'item_id':oid})
                differences.append({'task_id':task['task_id'],'item_id':oid,'sku_id':sku,'profile':profile_id,
                    'changes':{k:{'old':original[k],'new':item[k]} for k in original if item[k] != original[k]}})
            validate_schema('packaging_load_task_v1', task)
            tasks.append(task)
    require(len(tasks) == spec['expected_tasks'], 'task_count')
    return {'tasks':tasks, 'business_spec':spec, 'split_manifest':split,
        'sku_map':sku_map, 'differences':differences, 'calibration':stats}


def static_audits(data, root):
    tasks = data['tasks']; spec = data['business_spec']; reports = []; by_layer = defaultdict(Counter)
    for task in tasks:
        validate_schema('packaging_load_task_v1', task)
        c = task['container']; items = task['items']; ids = [o['item_id'] for o in items]
        require(ids == task['arrival_order'] and len(set(ids)) == len(ids), 'arrival_contract')
        volume = 0; mass = 0
        for obj in items:
            d = obj['dimensions_mm']; l,w,h = (d[k] for k in ('length','width','height'))
            require(all(math.isfinite(v) and v > 0 for v in (l,w,h,obj['mass_kg'])), 'invalid_units')
            require(h <= c['max_height_mm'] and any(x <= c['length_mm'] and y <= c['width_mm'] for x,y in ((l,w),(w,l))), 'single_item_fit')
            require(obj['mass_kg'] <= c['max_payload_kg'], 'single_item_payload')
            require(obj['effective_top_permission_kg'] == (obj['max_top_load_kg'] if obj['stackable'] else 0), 'effective_permission')
            require(obj['max_top_load_kg'] == obj['top_load_limit_kg_synthetic'] and
                    (obj['max_top_load_kg'] > 0 if obj['stackable'] else obj['max_top_load_kg'] >= 0), 'capacity_contract')
            original = obj['original_physical']
            changed = {k for k in original if obj[k] != original[k]}
            require(not changed if task['mode']=='source_preserving' else changed <= {'stackable','top_load_limit_kg_synthetic'}, 'source_preservation')
            volume += l*w*h; mass += obj['mass_kg']
            count = by_layer[task['layer']]
            count['instances'] += 1; count['non_stackable'] += not obj['stackable']
            count['source_positive_capacity_but_forbidden_support'] += not obj['stackable'] and obj['max_top_load_kg'] > 0
            count['changed_instances'] += bool(changed)
        capacity_volume = c['length_mm']*c['width_mm']*c['max_height_mm']
        require(volume <= capacity_volume and mass <= c['max_payload_kg'], 'order_necessary_conditions')
        reports.append({'task_id':task['task_id'],'volume_mm3':volume,'volume_ratio':volume/capacity_volume,
            'mass_kg':mass,'payload_ratio':mass/c['max_payload_kg'],'single_item_fit':True,
            'static_screen_status':'STATIC_SCREEN_PASSED','feasibility_status':'UNKNOWN',
            'witness':'NOT_AVAILABLE','candidate_reachability':'NOT_RUN'})
    # Recompute isolation from frozen connected identities and physical fingerprints.
    sources = read(Path(root)/'source_manifest.json')['sources']
    require(len({s['source_group_id'] for s in sources}) == 4, 'source_groups')
    for i,a in enumerate(sources):
        require(a['split'] == 'train', 'exposed_train_only')
        for b in sources[i+1:]:
            aa,bb = a['connected_source_evidence'],b['connected_source_evidence']
            require(not(set(aa['component_raw_keys']) & set(bb['component_raw_keys'])) and
                not(set(aa['original_identities']) & set(bb['original_identities'])) and
                all(aa[k] != bb[k] for k in ('ordered_geometry_digest','multiset_geometry_digest','rotation_invariant_digest')), 'source_independence')
    source_skus = {}
    for task in tasks:
        source_skus.setdefault(task['source_order_key'], set()).update(o['sku_id'] for o in task['items'])
    overlaps = [{'a':a,'b':b,'sku_overlap':sorted(source_skus[a]&source_skus[b])}
        for a in sorted(source_skus) for b in sorted(source_skus) if a < b]
    pair_count = 0
    first,second = spec['single_factor_pair']
    for a in (t for t in tasks if t['layer']==first):
        b = next(t for t in tasks if t['scenario_id']==a['scenario_id'] and t['layer']==second)
        # Only identity metadata and C may differ; eligibility/order/geometry/mass fixed.
        aa,bb = copy.deepcopy(a),copy.deepcopy(b)
        for value in (aa,bb):
            for k in ('task_id','layer'):value.pop(k)
            for obj in value['items']:
                for k in ('packaging_profile_id','max_top_load_kg','top_load_limit_kg_synthetic','effective_top_permission_kg'):obj.pop(k)
        require(aa == bb, 'single_factor_other_fields_changed')
        require(all(y['max_top_load_kg']==x['max_top_load_kg']*.5 for x,y in zip(a['items'],b['items'])), 'capacity_factor')
        pair_count += 1
    return {'static_conditions':reports,'attributes':{'by_layer':dict(by_layer),
        'sku_packaging_pairs':len(data['sku_map']),'physical_skus':data['calibration']['physical_product_count'],
        'conflicts':data['calibration']['conflicts'],'diffs':data['differences'],
        'capacity_distribution_by_layer':{layer:dict(Counter(str(o['max_top_load_kg']) for t in tasks if t['layer']==layer for o in t['items'])) for layer in spec['layers']},
        'profile_distribution_by_layer':{layer:dict(Counter(o['packaging_profile_id'] for t in tasks if t['layer']==layer for o in t['items'])) for layer in spec['layers']},
        'category_rules':0,'independent_business_thresholds':0},
        'difficulty':{'pair_count':pair_count,'factor':'capacity only','other_layer_comparisons':'scenario comparisons, not single-factor claims'},
        'source_isolation':{'source_groups':len(sources),'independent_new_sources':0,
            'cross_partition_variants':0,'partitions':{'train':4},'sku_overlap':overlaps,
            'unseen_sku_generalization':'NOT_ESTABLISHED','test_calibration':False}}


def readiness():
    return {'version':'packaging_stability_readiness_v1','algorithm_status':'NOT_RUN',
        'third_party_api':'UNVERIFIED; no repository/API/license/commit/dependencies audited',
        'field_mapping':{'dimensions_mm':'original length/width/height mm',
            'mass_kg':'original source mass kg; never infer from volume',
            'stackable':'direct support eligibility', 'max_top_load_kg':'single primary C; excludes own mass',
            'top_load_limit_kg_synthetic':'equal alias of C for future legacy physical binding',
            'effective_top_permission_kg':'C if stackable else 0; source positive C is retained',
            'pose/oriented_size_mm':'runtime only; bottom center / rotated extents once',
            'support_fractions/supported_load_kg':'runtime-only area sharing / cumulative load; no fixed defaults',
            'remaining_top_load_kg':'runtime C-L, utilization null/NOT_APPLICABLE when C=0',
            'sku_id/source_order_id/original_physical':'local audit only; anonymize before future requests'},
        'existing_checks':['boundary/height','collision','payload','70% support',
            'center in actual contact rectangle','support eligibility','recursive ancestor capacity'],
        'potential_conflicts':geometry_contract()['known_conflicts']+[
            'new convex hull/equivalent center may disagree with 70% and single-rectangle center checks; version separately',
            'area sharing is approximate, not static force/moment balance; do not mix sharing models or double count load'],
        'missing_runtime_fields':['pose','contact rectangles','support DAG','load fractions','cumulative load','combined centroid','stability result'],
        'next_stage':['audit third-party identity/license/assumptions before integration',
            'adapt context/candidate/execution/evaluation for new explicit protocol; shared for every method',
            'verify constructed counterexamples then separate side-channel protocol; no full rollout authorized here',
            'version physical identity and recertify witnesses if physics changes',
            'reject old semantic memory; real nonempty R0/M0 injection NOT_ESTABLISHED'],
        'runtime_request_evaluation_memory_acceptance':'NOT_RUN'}


def acceptance():
    # Partial items remain NOT_RUN, with the achieved data portion stated explicitly.
    details = {
        'D01':('PASS','Explicit DatasetOrderAdapter dispatch; old source hashes and historical inventory preserved.'),
        'D02':('NOT_RUN','Data rules/regions empty and no category overrides; request/evaluation migration is target two.'),
        'D03':('PASS','source_preserving all original fields equal; controlled differences limited and audited.'),
        'D04':('PASS','SKU+profile consistency checked; composite identity conflicts recorded.'),
        'D05':('PASS','Schema, positive units, capacity alias and effective zero support permission checked.'),
        'D06':('PASS','Constructed existing-oracle checks: self exclusion, 60/40 sharing, ancestor, equality/overload.'),
        'D07':('NOT_RUN','Existing pure physics rejection tested; new shared runtime admission not adapted or run.'),
        'D08':('PASS','geometry_contract/readiness explicitly state approximation and excluded dynamics.'),
        'D09':('PASS','Every task screened; all UNKNOWN without witness; reachability/online solvability NOT_RUN.'),
        'D10':('PASS','Frozen train-only scale/seed; four capacity-only pairs checked; no outcome selection.'),
        'D11':('PASS','Frozen connected-source/geometry identities checked; train-only variants and SKU overlap reported.'),
        'D12':('NOT_RUN','No new requests generated. Prompt migration and future/witness exclusion require target two.'),
        'D13':('NOT_RUN','No outcomes; new metrics not implemented; empty candidate pool is not infeasibility proof.'),
        'D14':('NOT_RUN','New memory protocol rejection/injection not implemented; real nonempty injection NOT_ESTABLISHED.'),
        'D15':('PASS','Manifest, source/code/config snapshots, diffs, checks and explicit NOT_RUN in ignored outputs.'),
        'D16':('PASS','Uniform mass/geometric center frozen; original masses preserved; equal-volume different-mass check.'),
        'D17':('PASS','Closed task/fixed-item schema excludes pose/support/load/combined center/stability answers.'),
        'D18':('PASS','0/90 center/corner and mm/m round trips checked; exact vs oracle tolerances disclosed; signed yaw gap explicit.'),
        'D19':('PASS','Readiness mapping/conflicts/sharing/gaps provided; third-party verification UNVERIFIED, algorithm NOT_RUN.'),
        'D20':('NOT_RUN','Data/physical/strategy identities separated; no third-party or model work; runtime joint binding deferred.'),
    }
    return {'scope':'target one data/static only; no overall D01-D20 PASS',
        'items':{k:{'status':v[0],'evidence':v[1]} for k,v in details.items()},
        'not_run':['candidate coverage','layout witness certification','full order rollout','order effect matrix',
            'branch search','Jev/DeepSeek','PCT download/training/integration','runtime joint identity binding']}


def protected_inventory(repo, source):
    result = _protected_inventory(repo)
    for root in (source, repo/'semantic_pallet_dataset_v1'):
        for path in sorted(root.rglob('*')):
            if path.is_file():result[str(path.relative_to(repo))] = _sha(path)
    return result


def implementation_files():
    return {name:_sha(PACKAGE/name) for name in IMPLEMENTATION_FILES}


def build_packaging_dataset(repo, output):
    from .experiment import _new_output, file_manifest
    repo = Path(repo).resolve(); spec = packaging_spec(); out = _new_output(output)
    allowed = repo/'semantic_pallet_planner/outputs'
    require(out.is_relative_to(allowed) and out != allowed, 'output_must_be_ignored_outputs')
    ignored = subprocess.run(['git','check-ignore','-q',str(out)],cwd=repo,check=False)
    require(ignored.returncode == 0, 'output_not_git_ignored')
    with offline_dataset_guard() as counters:
        source = allowed/spec['source_delivery']
        from .dataset_j4 import load_dataset_v2_delivery
        load_dataset_v2_delivery(source)
        before = protected_inventory(repo, source)
        require(_sha(source/'existing_source_manifest.json') == SOURCE_AUDIT_SHA256, 'source_audit_mismatch')
        out.mkdir(parents=True)
        shutil.copytree(source/'sources',out/'sources')
        shutil.copyfile(source/'existing_source_manifest.json',out/'source_manifest.json')
        shutil.copyfile(PACKAGE/'configs/packaging_load_v1.json',out/'config.snapshot.json')
        # Freeze receipt is checked before any materialization, not reconstructed after it.
        freeze = allowed/'DATA_JEV_PACKAGING_LOAD_20261102_FREEZE_01'
        require(read(freeze/'freeze_receipt.json')['config_sha256']==CONFIG_SHA256 and
                _sha(freeze/'packaging_load_v1.json')==CONFIG_SHA256, 'missing_preimplementation_freeze')
        shutil.copytree(freeze,out/'configuration_freeze')
        data = materialize(out,spec); audits = static_audits(data,out)
        for task in data['tasks']:write(out/'tasks'/f"{task['task_id']}.json",task)
        write(out/'sku_packaging_map.json',data['sku_map'])
        write(out/'split_manifest.json',data['split_manifest'])
        write(out/'geometry_contract.json',geometry_contract())
        write(out/'stability_readiness.json',readiness())
        write(out/'audits/calibration.json',data['calibration'])
        for name,value in audits.items():write(out/'audits'/f'{name}.json',value)
        write(out/'witnesses/status.json',{'all_tasks':'UNKNOWN','witnesses':[],
            'candidate_reachability':'NOT_RUN','online_solvability':'NOT_RUN'})
        checks = constructed_checks()
        write(out/'verification/constructed_checks.json',checks)
        require(protected_inventory(repo,source)==before, 'historical_bytes_changed')
        write(out/'verification/protected_inventory.json',{'before_sha256':before,'after_identical':True})
        code = implementation_files()
        for name in code:
            dest = out/'code_snapshot'/name; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(PACKAGE/name,dest)
        physical = {name:_sha(PACKAGE.parent/name) for name in PHYSICS_FILES}
        for name in physical:
            dest=out/'physical_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(PACKAGE.parent/name,dest)
        manifest = {'version':VERSION,'config_sha256':CONFIG_SHA256,'source_sha256':dict(spec['source_file_manifest']),
            'source_audit_sha256':SOURCE_AUDIT_SHA256,'code_sha256':code,
            'data_identity':digest({'config':spec,'tasks':data['tasks'],'split':data['split_manifest']}),
            'physical_identity':{'status':'UNCHANGED_EXISTING_APPROXIMATION','sha256':physical},
            'strategy_identity':{'status':'NOT_RUN'},'runtime_joint_binding':'NOT_RUN',
            'source_groups':4,'unique_source_instances':66,'task_count':len(data['tasks']),
            'derived_instances':sum(len(t['items']) for t in data['tasks']),
            'mode_counts':dict(Counter(t['mode'] for t in data['tasks']))}
        write(out/'manifest.json',manifest)
        report = acceptance()
        write(out/'verification/acceptance.json',report)
        rows = ['# Jev J4 packaging/load target-one actual acceptance', '',
            'Static data checks complete; every task feasibility UNKNOWN. No overall D01-D20 PASS.', '',
            '| ID | Status | Actual scope / evidence |', '|---|---|---|']
        rows.extend('| '+key+' | '+value['status']+' | '+value['evidence']+' |' for key,value in report['items'].items())
        rows += ['', 'Evidence: audits/*.json; verification/constructed_checks.json; verification/protected_inventory.json; manifest.json.',
            'No model/API/episodes/search/replay/third-party integration. Request, evaluation, memory and runtime binding remain NOT_RUN.']
        (out/'verification/acceptance.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')
        write(out/'verification/offline_guards.json',dict(counters))
        write(out/'handoff.json',{'target':'target two only when separately authorized','data_status':'STATIC_CHECKS_COMPLETE_ALL_FEASIBILITY_UNKNOWN',
            'manifest':manifest,'field_mapping':readiness()['field_mapping'],
            'data_summary':{'tasks':len(data['tasks']),'source_instances':66,'derived_instances':264,
                'layers':list(spec['layers']),'feasibility':'all UNKNOWN; no witnesses'},
            'config_summary':{'profiles':spec['profiles'],'calibration':spec['calibration'],
                'freeze_receipt':'configuration_freeze/freeze_receipt.json','seed':spec['seed']},
            'source_summary':{'groups':4,'partition':'train only, previously exposed',
                'new_independent_sources':0,'snapshot':'sources/','source_audit':'source_manifest.json'},
            'code_summary':'dataset_packaging materialization/checks; DatasetOrderAdapter explicit version dispatch; CLI and closed schemas; physics/runtime unchanged',
            'passed_checks':{k:v for k,v in report['items'].items() if v['status']=='PASS'},
            'unresolved':spec['evidence_gaps']+readiness()['next_stage'],
            'not_run':report['not_run'],'forbidden_historical_artifacts':sorted({str(Path(n).parent) for n in before}),
            'protected_byte_inventory':'verification/protected_inventory.json',
            'old_v1_v2_runtime':'unchanged; do not pass new tasks into old plan/runtime schemas',
            'load':'DatasetOrderAdapter().load(DELIVERY, spec_config="jev_packaging_load_dataset_v1")',
            'commands':{'build':'python -m semantic_pallet_planner.jev_select build-packaging-dataset --repo REPO --output NEW_IGNORED_OUTPUT',
                'load_validate':'python -m semantic_pallet_planner.jev_select validate-packaging-dataset --dataset DELIVERY'},
            'memory':'old semantic cards incompatible; rejection gate and nonempty injection NOT_RUN',
            'model_calls':0,'episodes_run':0})
        write(out/'delivery_manifest.json',file_manifest(out))
        loaded = load_packaging_delivery(out)
        require(loaded['tasks']==data['tasks'], 'export_load_mismatch')
        write(out/'verification/loading.json',{'formal_entry':'DatasetOrderAdapter.load',
            'export_reconstruction':'PASS','task_count':len(loaded['tasks']),
            'tasks_digest':digest(loaded['tasks']),'external_source_required':False})
        write(out/'delivery_manifest.json',file_manifest(out))
        # Final authenticated read includes the actual load receipt.
        load_packaging_delivery(out)
        return {'status':'STATIC_CHECKS_COMPLETE','output':str(out),'task_count':len(data['tasks']),
            'source_groups':4,'feasibility':'ALL_UNKNOWN','offline_guards':dict(counters),'episodes_run':0,
            'D01_D20':'PARTIAL_SCOPE_WITH_NOT_RUN'}


def load_packaging_delivery(root):
    """Read-only independent load with source reconstruction and semantic validation."""
    from .experiment import file_manifest
    root = Path(root).resolve()
    with offline_dataset_guard():
        require(not any(p.is_symlink() for p in root.rglob('*')), 'symlinks_forbidden')
        require(read(root/'delivery_manifest.json')==file_manifest(root), 'delivery_digest_mismatch')
        spec = packaging_spec()
        require(_sha(root/'config.snapshot.json')==CONFIG_SHA256, 'config_not_frozen')
        data = materialize(root,spec)
        require({p.name for p in (root/'tasks').iterdir()}=={t['task_id']+'.json' for t in data['tasks']}, 'task_registry')
        for task in data['tasks']:
            require(read(root/'tasks'/f"{task['task_id']}.json")==task, 'task_snapshot_mismatch')
        for name,value in [('sku_packaging_map',data['sku_map']),('split_manifest',data['split_manifest']),
                           ('geometry_contract',geometry_contract()),('stability_readiness',readiness())]:
            require(read(root/f'{name}.json')==value, name+'_mismatch')
        audits = static_audits(data,root)
        for name,value in audits.items():require(read(root/'audits'/f'{name}.json')==value,'audit_mismatch')
        require(read(root/'audits/calibration.json')==data['calibration'], 'calibration_audit_mismatch')
        manifest = read(root/'manifest.json')
        require(manifest['version']==VERSION and manifest['config_sha256']==CONFIG_SHA256 and
            manifest['data_identity']==digest({'config':spec,'tasks':data['tasks'],'split':data['split_manifest']}), 'data_identity_mismatch')
        require(set(manifest['code_sha256'])==set(IMPLEMENTATION_FILES), 'code_registry_mismatch')
        require(manifest['task_count']==len(data['tasks']) and manifest['source_groups']==4 and
            manifest['unique_source_instances']==66 and manifest['derived_instances']==264 and
            manifest['source_sha256']==spec['source_file_manifest'] and
            manifest['source_audit_sha256']==SOURCE_AUDIT_SHA256 and
            manifest['mode_counts']==dict(Counter(t['mode'] for t in data['tasks'])) and
            manifest['strategy_identity']=={'status':'NOT_RUN'} and
            manifest['runtime_joint_binding']=='NOT_RUN', 'manifest_metadata_mismatch')
        require(read(root/'handoff.json')['manifest']==manifest, 'handoff_identity_mismatch')
        require(read(root/'verification/acceptance.json')==acceptance(), 'acceptance_mismatch')
        require(read(root/'verification/constructed_checks.json')==constructed_checks(), 'constructed_receipt_mismatch')
        for name,sha in manifest['code_sha256'].items():
            require(_sha(root/'code_snapshot'/name)==sha, 'code_snapshot_mismatch')
        require(set(manifest['physical_identity']['sha256'])==set(PHYSICS_FILES), 'physics_registry_mismatch')
        for name,sha in manifest['physical_identity']['sha256'].items():
            require(name in PHYSICS_FILES and _sha(root/'physical_snapshot'/name)==sha, 'physics_snapshot_mismatch')
        return data


def validate_packaging_dataset(root):
    with offline_dataset_guard() as counters:
        data = load_packaging_delivery(root)
        checks = constructed_checks()
        return {'status':'STATIC_CHECKS_COMPLETE','task_count':len(data['tasks']),
            'tasks_digest':digest(data['tasks']),'constructed_checks':checks,
            'offline_guards':dict(counters),'feasibility':'ALL_UNKNOWN','episodes_run':0}


def constructed_checks():
    """Small hand-constructed pure oracle checks, no order simulation/search."""
    from semantic_pallet_planner.planner.constraints import evaluate_pose
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate, bounds
    config = {'container':{'length_mm':1000,'width_mm':1000,'max_height_mm':1000,'max_payload_kg':1000},
        'support_ratio_min':.7,'candidate_generator':{'geometry_score_weights':{'compactness':.25,'height':.25,'stability':.25,'balance':.25}}}
    def item(name,mass=10,capacity=100,stackable=True,size=(100,100,100)):
        return {'item_id':name,'dimensions':list(size),'mass_kg':mass,'stackable':stackable,'top_load_limit_kg_synthetic':capacity}
    def pose(obj,placed=(),x=-50,y=-50,z=0,yaw=0):
        size = obj['dimensions'];l,w = size[:2] if yaw==0 else size[:2][::-1]
        return evaluate_pose(obj,list(placed),x,y,z,l,w,yaw,config)
    def record(obj,x0,x1,y0=-50,y1=50,z0=0,z1=100,load=0,supports=()):
        return {'item_id':obj['item_id'],'item':obj,'x0':x0,'x1':x1,'y0':y0,'y1':y1,
            'z0':z0,'z1':z1,'supported_load_kg':load,'supports':list(supports),'yaw':0}
    checks = {}
    base = record(item('base',capacity=20),-50,50,load=12)
    require(pose(item('top',mass=9),[base],z=100)[1]=='overload', 'example_12_plus_9')
    equal,error = pose(item('top',mass=8),[base],z=100)
    require(error is None and equal['load_increments']=={'base':8} and equal['result_state'][0]['supported_load_kg']==20,'equal_capacity')
    require(equal['record']['supported_load_kg']==0,'self_weight_excluded')
    checks['capacity_equality_overload_self_exclusion']='PASS'
    left = record(item('left'),-50,10); right = record(item('right'),10,50)
    split,error = pose(item('top',mass=10),[left,right],z=100)
    require(error is None and split['load_increments']=={'left':6,'right':4} and
        math.isclose(sum(f for _,f in split['record']['supports']),1), 'split_60_40')
    checks['same_height_double_support_60_40']='PASS'
    a = record(item('a',capacity=20),-50,50,load=12)
    b = record(item('b',mass=12),-50,50,z0=100,z1=200,supports=[('a',1)])
    require(pose(item('c',mass=9),[a,b],z=200)[1]=='overload', 'ancestor_overload')
    require(pose(item('c',mass=8),[a,b],z=200)[0]['load_increments']=={'b':8,'a':8}, 'ancestor_equality')
    checks['ancestor_increment_no_double_count']='PASS'
    for capacity in (0,100):
        base = record(item('base',capacity=capacity,stackable=False),-50,50)
        require(pose(item('top'),[base],z=100)[1]=='non_stackable_support', 'no_support')
    require(pose(item('top'),[record(item('base',capacity=0),-50,50)],z=100)[1]=='overload','zero_capacity')
    checks['zero_capacity_nonstackable_positive_source_capacity']='PASS'
    require(pose(item('top'),[left,right],x=50,z=100)[1]=='insufficient_support','edge_zero_area')
    raised = copy.deepcopy(right); raised['z1'] = 100-2e-6
    require(pose(item('top'),[left,raised],z=100)[1]=='insufficient_support','height_gap')
    checks['zero_area_contact_and_height_gap']='PASS'
    checks['floor']='PASS' if pose(item('floor'))[1] is None else 'FAIL'
    for yaw in (0,90):
        action,error=pose(item('roundtrip',size=(120,80,60)),x=100,y=-120,z=0,yaw=yaw)
        require(error is None, 'rotation')
        v=action['visible']; bb=bounds(v); size=v['oriented_size_mm'];p=v['pose']
        require((bb[0]+size[0]/2,bb[2]+size[1]/2,bb[4])==(p['x_mm'],p['y_mm'],p['z_base_mm']), 'corner_roundtrip')
        center=(p['x_mm'],p['y_mm'],p['z_base_mm']+size[2]/2)
        require(all(math.isclose((n/1000)*1000,n,abs_tol=1e-12) for n in (*bb,*center)), 'unit_roundtrip')
        public={'item_id':'roundtrip','mass_kg':10,'dimensions_mm':dict(zip(('length','width','height'),(120,80,60)))}
        require(not check_candidate({'available_items':[public],'placed_items':[]},{'container':config['container']},v), 'oracle_roundtrip')
    checks['yaw_0_90_corner_center_centroid_mm_m_roundtrip']='PASS'
    light=pose(item('light',mass=2),[left,right],z=100)[0]
    heavy=pose(item('heavy',mass=10),[left,right],z=100)[0]
    require(light['visible']['oriented_size_mm']==heavy['visible']['oriented_size_mm'] and
        math.isclose(sum(light['load_increments'].values()),2) and
        math.isclose(sum(heavy['load_increments'].values()),10), 'actual_mass_not_density')
    checks['equal_volume_different_mass']='PASS'
    require(all(v=='PASS' for v in checks.values()), 'constructed_check_failed')
    return checks
