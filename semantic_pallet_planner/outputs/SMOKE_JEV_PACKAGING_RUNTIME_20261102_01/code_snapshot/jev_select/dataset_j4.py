"""Read-only J4 readiness/exposure audit. No downloads, credentials or model calls."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

from .contracts import digest, JevSelectError
from .ledger import read, write


def geometry_keys(items):
    """Frozen 1 mm / .01 kg ordered and multiset screening signatures."""
    rows = [(round(float(i['length/mm'])), round(float(i['width/mm'])),
             round(float(i['height/mm'])), round(float(i['weight/kg']), 2)) for i in items]
    return digest(rows), digest(sorted(rows))


def raw_items(order):
    return [v for k,v in sorted(order['item_sequence'].items(), key=lambda kv:int(kv[0]))]


def verify_seal(root):
    """Verify original file hashes only; never regenerate candidates or re-sign history."""
    root = Path(root).resolve()
    manifest_path = root/'delivery_manifest.json'
    if not manifest_path.is_file():
        return {'status':'MISSING_MANIFEST','files_verified':0,'missing':[],'changed':[]}
    manifest = read(manifest_path)
    missing, changed = [], []
    for name, expected in manifest.items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            missing.append(name); continue
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024), b''):h.update(chunk)
        if h.hexdigest() != expected:changed.append(name)
    return {'status':'PASS' if not missing and not changed else 'FAIL',
            'scope':'SAVED_FILE_HASHES_NO_REPLAY','files_verified':len(manifest)-len(missing)-len(changed),
            'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'missing':missing,'changed':changed,'restoration_origin':'not_recorded_locally'}


def audit_readiness(repo, output, *, raw_path=None, reme_path=None):
    import importlib.util
    repo=Path(repo).resolve()
    from .experiment import _new_output
    out=_new_output(output);out.mkdir(parents=True)
    raw=Path(raw_path).resolve() if raw_path else repo/'raw/bed_bpp/bed-bpp_v1.json'
    reme=Path(reme_path).resolve() if reme_path else repo/'ReMe-main'
    exposed={}; signatures=set(); mappings=[]
    def expose(key, evidence):
        if isinstance(key,(str,int)) and str(key).isdigit():exposed.setdefault(str(key),set()).add(evidence)
    annotations=repo/'semantic_pallet_dataset_v1/annotations/ground_truth_rules'
    for p in sorted(annotations.glob('*.json')):
        a=read(p)
        for key in ('source_order_id','source_order_key'):expose(a.get(key),str(p.relative_to(repo)))
        mappings.append({k:a.get(k) for k in ('scenario_id','source_order_id','source_order_key','split')})
    # Include available frozen plans/data, not just experiment directory names.
    outputs=repo/'semantic_pallet_planner/outputs'
    inputs=[]
    # Frozen plans can be nested in GEN/diagnostic runs. Never inspect raw responses
    # or credentials: only named plan input/split files under outputs.
    plan_inputs = sorted({p for name in ('input_snapshot.json', 'input_manifest.json', 'split_manifest.json', 'plan.json', 'manifest.json')
                          for p in outputs.rglob(name) if p.is_file()})
    for p in plan_inputs:
        inputs.append(str(p.relative_to(repo)))
        def scan(v):
            if isinstance(v,dict):
                for k,x in v.items():
                    if k in ('source_order_id','source_order_key','original_source_order_id','original_source_order_key','source_order_keys'):
                        for identity in x if isinstance(x,list) else [x]: expose(identity,str(p.relative_to(repo)))
                    else:scan(x)
            elif isinstance(v,list):
                for x in v:scan(x)
        scan(read(p))
    raw_data=read(raw) if raw.is_file() else {}
    # Connected components include raw key, original properties.id/order_nr,
    # ordered/unordered mechanics and orientation-invariant horizontal dimensions.
    # This catches transitive inheritance even if a duplicate is not input-eligible.
    parent = {key:key for key in raw_data}; identity_first = {}; descriptors = {}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]; key = parent[key]
        return key
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b: parent[max(a,b)] = min(a,b)
    for key,order in sorted(raw_data.items()):
        items=raw_items(order); keys=geometry_keys(items)
        rotated=digest(sorted((min(round(float(i['length/mm'])),round(float(i['width/mm']))),
                              max(round(float(i['length/mm'])),round(float(i['width/mm']))),
                              round(float(i['height/mm'])),round(float(i['weight/kg']),2)) for i in items))
        properties=order.get('properties',{})
        ids={str(key), *(str(properties[k]) for k in ('id','order_nr') if properties.get(k) is not None)}
        descriptors[key]={'original_identities':sorted(ids),'ordered_geometry_digest':keys[0],
                          'multiset_geometry_digest':keys[1],'rotation_invariant_digest':rotated}
        for identity in [*(('identity',v) for v in ids),*(('mechanics',v) for v in (*keys,rotated))]:
            if identity in identity_first:union(key,identity_first[identity])
            else:identity_first[identity]=key
    components={}
    for key in raw_data:components.setdefault(find(key),[]).append(key)
    exposed_components={find(key) for key,d in descriptors.items() if set(d['original_identities']).intersection(exposed)}
    candidates=[];exclusions={'length':0,'necessary_conditions':0,'exposed':0,'near_duplicate':0}
    selected_components=set()
    for key,order in sorted(raw_data.items()):
        items=raw_items(order)
        if not 14<=len(items)<=20:exclusions['length']+=1;continue
        necessary=all(0<float(i['weight/kg'])<=100 and 0<float(i['height/mm'])<=850 and
            ((0<float(i['length/mm'])<=1200 and 0<float(i['width/mm'])<=1000) or
             (0<float(i['width/mm'])<=1200 and 0<float(i['length/mm'])<=1000)) for i in items)
        necessary=necessary and sum(float(i['weight/kg']) for i in items)<=1000 and sum(float(i['length/mm'])*float(i['width/mm'])*float(i['height/mm']) for i in items)<=1200*1000*850
        if not necessary:exclusions['necessary_conditions']+=1;continue
        component=find(key)
        if component in exposed_components:exclusions['exposed']+=1;continue
        if component in selected_components:exclusions['near_duplicate']+=1;continue
        selected_components.add(component)
        candidates.append({'source_order_id':str(key),'item_count':len(items),**descriptors[key],
                           'source_component':component,'component_raw_keys':sorted(components[component])})
    history=[]
    for name in ('EXP_JEV_J3_TEST_20261029_01','EXP_JEV_PUBLIC_DEV_20261030_01'):
        r=outputs/name
        history.append({'path':str(r),'episode_files':len(list((r/'episodes').glob('*.json'))),
                        'integrity':verify_seal(r) if r.exists() else {'status':'MISSING'},
                        'historical_replay_status':read(r/'replay_report.json').get('status') if (r/'replay_report.json').exists() else None})
    def installed(name):
        try:return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:return None
    vendor_files=[p for p in (reme/'reme').rglob('*.py')] if (reme/'reme').is_dir() else []
    vendor_digest=digest({str(p.relative_to(reme)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(vendor_files)}) if vendor_files else None
    exposure={'version':'jev_exposure_manifest_v1','scope':'current V1 annotations and recursive output input/split manifests, including nested GEN plans; unknown historical use cannot be disproved',
              'source_orders':[{'source_order_id':k,'evidence':sorted(v)} for k,v in sorted(exposed.items())],
              'scenario_mappings':mappings,'scanned_plan_inputs':inputs,'candidate_new_sources':candidates,
              'deduplication':{'method':'connected raw key/original id/order number and ordered/unordered/rotation invariant mechanical signatures',
                  'precision':'1 mm, 0.01 kg; horizontal yaw-equivalent dimensions normalized for third signature',
                  'raw_components':len(components),'exposed_components':len(exposed_components),
                  'raw_source_identity_manifest':descriptors}}
    write(out/'exposure_manifest.json',exposure)
    report={'version':'jev_j4_readiness_v1','model_api_calls':0,'new_environment_steps':0,
            'data_readiness':{'raw_path':str(raw),'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest() if raw.is_file() else None,
              'parsed_orders':len(raw_data),'source_key_mappings':len(mappings),'exposed_raw_orders':len(exposed),
              'screened_candidate_sources':len(candidates),'exclusion_counts':exclusions,
              'status':'CANDIDATES_AVAILABLE_REQUIRES_FINAL_EXPOSURE_REVIEW' if len(candidates)>=20 else 'INSUFFICIENT',
              'necessary_conditions_are_not_feasibility_proof':True,'exposure_manifest_digest':digest(exposure)},
            'history':history,'generator_readiness':{'status':'NOT_CONFIGURED','reason':'A0 does not assume Choice can generate text; explicit text backend required'},
            'reme_readiness':{'path':str(reme),'entry_present':(reme/'reme/reme.py').is_file(),
              'installed_distribution_version':installed('reme-ai'),'vendor_source_digest':vendor_digest,
              'status':'SOURCE_PRESENT_NOT_INTEGRATION_VERIFIED' if vendor_files else 'MISSING'},
            'dependencies':{n:installed(n) for n in ('numpy','jsonschema','pytest','PyYAML')},
            'new_source_test_status':'NOT_RUN','status':'PASS' if all(h['integrity']['status']=='PASS' for h in history) else 'NEEDS_ATTENTION'}
    write(out/'readiness_report.json',report)
    return report


def prepare_training_sources(repo, readiness, output, *, count=2):
    """Freeze a deterministic full-order train prefix, without any policy rollout.

    Reuse the V1 physical attribute normalizer and published weight thresholds;
    generated business labels use the existing DatasetOrderAdapter unchanged.
    """
    import importlib.util
    from .experiment import _new_output, file_manifest, validate_tasks
    from .dataset import DatasetOrderAdapter
    repo = Path(repo).resolve(); ready = Path(readiness)
    audit = read(ready/'readiness_report.json'); exposure = read(ready/'exposure_manifest.json')
    if count != 2 or digest(exposure) != audit['data_readiness']['exposure_manifest_digest']:
        raise JevSelectError('training_selection_contract_changed')
    raw_path = Path(audit['data_readiness']['raw_path'])
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != audit['data_readiness']['raw_sha256']:
        raise JevSelectError('raw_source_changed')
    selected = exposure['candidate_new_sources'][:count]
    if len(selected) != count: raise JevSelectError('insufficient_independent_training_sources')
    normalizer = repo/'semantic_pallet_dataset_v1/scripts/build_dataset.py'
    config = read(repo/'semantic_pallet_dataset_v1/configs/mvd_v0.1.json')
    thresholds = read(repo/'semantic_pallet_dataset_v1/statistics/dataset_summary.json')['weight_class_thresholds_kg']
    spec = importlib.util.spec_from_file_location('jev_existing_dataset_normalizer',normalizer)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    raw = read(raw_path); out = _new_output(output); out.mkdir(parents=True)
    groups = []; orders = []
    for source in selected:
        key = source['source_order_id']; order = raw[key]; rows = raw_items(order)
        if geometry_keys(rows) != (source['ordered_geometry_digest'],source['multiset_geometry_digest']):
            raise JevSelectError('training_fingerprint_changed')
        sid = 'NEW_'+key; items=[]; articles=[]
        for i,row in enumerate(rows):
            obj = module.normalize_source_item(row,config['dataset_seed'],config['geometry_ood']['height_threshold_mm'])
            obj.update(item_id=f'item_{i+1:02d}',weight_class='light' if obj['mass_kg']<=thresholds['light_max'] else
                       'medium' if obj['mass_kg']<=thresholds['medium_max'] else 'heavy')
            items.append(module.public_item(obj)); articles.append(obj['source_article_id'])
        group = {'scenario_id':sid,'variant_id':'canonical_instruction','base_physical_id':'RAW_'+key,'pair_group_id':'RAW_'+key}
        groups.append(group)
        write(out/'dataset/tasks/scenarios'/f'{sid}.json', {'scenario_id':sid,'buffer_size':1,
            'container':config['container'],'items':items,'arrival_order':[o['item_id'] for o in items],
            'instruction':{'text':'Original business instruction not used; public B1/B2 generated by existing adapter.'}})
        write(out/'dataset/annotations/ground_truth_rules'/f'{sid}.json', {'scenario_id':sid,
            'source_order_id':str(order.get('properties',{}).get('id',key)),'source_order_key':key,
            'source_article_ids':articles,'split':'train'})
        orders.append({'source_order_key':key,'raw_order':order,'fingerprints':source,
                       'split':'train','selection_rank':len(orders)+1})
    write(out/'dataset/splits/group_manifest.json',{'groups':groups})
    adapted = DatasetOrderAdapter().load(out/'dataset'); validate_tasks(adapted['tasks'])
    protocol = {'version':'jev_b2_real_training_selection_v2','source_order':'ascending raw source key after complete recorded exposure and geometry/mass dedup',
        'sources':orders,'source_manifest':adapted['split_manifest'],'tasks_digest':digest(adapted['tasks']),
        'readiness_digest':digest(audit),'exposure_digest':digest(exposure),
        'normalizer_sha256':hashlib.sha256(normalizer.read_bytes()).hexdigest(),
        'normalizer_config':config,'weight_thresholds_kg':thresholds,
        'scope':'two new train groups x B1/B2 x D0; full arrivals; no rollout/outcome selection',
        'termination':'native completion, physical pool empty or service failure; retain complete evidence',
        'service_failure':'retain budget/episode identity; never recreate to retry; no causal layout-failure label',
        'holdout':'all selected sources become exposed train; no validation/test selected',
        'model_api_calls':0,'new_training_episodes':4}
    write(out/'selection_protocol.json',protocol)
    write(out/'delivery_manifest.json',file_manifest(out))
    return {'status':'PASS','sources':[o['source_order_key'] for o in orders],
            'source_groups':len(adapted['split_manifest']['groups']),'planned_episodes':len(adapted['tasks']),
            'selection_digest':digest(protocol),'model_api_calls':0}


# v2 uses only these already exposed source packages. Never invoke readiness or
# prepare_training_sources here: those inspect the full official/raw corpus.
V2_SOURCE_PACKAGES = (
    'SOURCES_JEV_J4_B2_REAL_20261031_02',
    'SOURCES_JEV_J4_B2_EXTENSION_PROPOSAL_20261031_01',
)
V2_PINNED_PLANS = (
    'PLAN_JEV_J4_B2_REAL_SMOKE_20261031_02',
    'PLAN_JEV_J4_B2_EXTENSION_SMOKE_20261031_01',
)


def offline_dataset_guard():
    """Process-local audit guard for the dedicated build/validate commands.

    The hook becomes inactive on exit. It blocks credential files/environment
    and socket/DNS operations before they can have effects; no credentials read.
    """
    import os
    import sys
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def guard():
        counters = {'credential_reads':0, 'network_attempts':0}
        active = [True]
        def audit(event, args):
            if not active[0]: return
            if event in ('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.sendto', 'socket.bind'):
                counters['network_attempts'] += 1
                raise JevSelectError('dataset_network_forbidden')
            if event == 'open' and isinstance(args[0], (str, bytes)):
                name = str(args[0]).lower()
                if any(s in name for s in ('typesafe_api_key', 'deepseek_api.md', '.env', 'credentials')):
                    counters['credential_reads'] += 1
                    raise JevSelectError('dataset_credential_read_forbidden')
        getitem = os._Environ.__getitem__
        def env_getitem(env, key):
            if any(s in str(key).lower() for s in ('api_key', 'token', 'secret', 'password', 'credential')):
                counters['credential_reads'] += 1
                raise JevSelectError('dataset_credential_environment_forbidden')
            return getitem(env, key)
        sys.addaudithook(audit)
        try:
            with patch.object(os._Environ, '__getitem__', env_getitem):
                yield counters
        finally:
            active[0] = False
    return guard()


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def _protected_inventory(repo):
    """Hash existing historical bytes without parsing responses or secrets."""
    outputs = repo/'semantic_pallet_planner/outputs'
    names = [*V2_SOURCE_PACKAGES, *V2_PINNED_PLANS,
        'JEV_J4_GENERATION_ACCOUNTING_V1',
        'GEN_JEV_J4_B2_EXTENSION_RETRY_20261101_01',
        'GEN_JEV_J4_B2_DEV_REVIEW_20261031_01',
        'EXP_JEV_J4_B2_REAL_SMOKE_20261031_01',
        'EXP_JEV_J4_B2_REAL_REST_20261031_01',
        'EXP_JEV_J4_B2_EXTENSION_SMOKE_20261101_02']
    result = {}
    for name in names:
        root = outputs/name
        if not root.is_dir(): raise JevSelectError('missing_v2_baseline', name)
        for p in sorted(root.rglob('*')):
            if p.is_file(): result[str(p.relative_to(repo))] = _sha(p)
    return result


def _v2_sources(repo, target):
    """Copy exact archived normalized sources, retaining existing group IDs."""
    import shutil
    from .dataset import DatasetOrderAdapter, business_spec
    groups = []; sources = []; old = []
    outputs = repo/'semantic_pallet_planner/outputs'
    keys = business_spec('public_generated_v2')['calibration']['source_keys']
    for package, plan in zip(V2_SOURCE_PACKAGES, V2_PINNED_PLANS):
        src = outputs/package/'dataset'
        adapted = DatasetOrderAdapter().load(src)
        pinned = read(outputs/plan/'input_manifest.json')
        protocol = read(outputs/package/'selection_protocol.json')
        pinned_tasks = read(outputs/plan/'private/input_snapshot.json')['tasks']
        if (digest(adapted['tasks']) != protocol['tasks_digest'] or digest(pinned_tasks) != pinned['tasks_digest'] or
            any(t not in adapted['tasks'] for t in pinned_tasks)):
            raise JevSelectError('v1_frozen_compatibility_failed', package)
        old.extend(adapted['tasks'])
        for source in protocol['sources']:
            key = source['source_order_key']
            if key not in keys or source['split'] != 'train':
                raise JevSelectError('v2_source_scope_mismatch')
            rows = raw_items(source['raw_order'])
            task = next(t for t in adapted['tasks'] if t['scenario_id']=='NEW_'+key and t['business_configuration']=='B1')
            if geometry_keys(rows) != (source['fingerprints']['ordered_geometry_digest'], source['fingerprints']['multiset_geometry_digest']):
                raise JevSelectError('archived_raw_fingerprint_mismatch')
            if len(rows)!=len(task['items']): raise JevSelectError('archived_raw_length_mismatch')
            for row, obj in zip(rows, task['items']):
                if (task['provenance']['article_ids'][obj['item_id']] != str(row['id']) or
                    obj['mass_kg'] != float(row['weight/kg']) or any(obj['dimensions_mm'][a] != int(row[b]) for a,b in
                    [('length','length/mm'),('width','width/mm'),('height','height/mm')])):
                    raise JevSelectError('archived_raw_physics_mismatch')
            sources.append({'source_key':key,'split':'train','source_group_id':task['source_group_id'],
                'archived_package':package,'protocol_sha256':_sha(outputs/package/'selection_protocol.json'),
                'raw_order_digest':digest(source['raw_order']), 'item_count':len(rows),
                'normalized_original_sha256':{n:_sha(src/n) for n in (
                    f'tasks/scenarios/NEW_{key}.json',f'annotations/ground_truth_rules/NEW_{key}.json','splits/group_manifest.json')},
                'connected_source_evidence':source['fingerprints']})
        for group in read(src/'splits/group_manifest.json')['groups']:
            if group['scenario_id'] not in {'NEW_'+k for k in keys}:
                raise JevSelectError('v2_source_scope_mismatch')
            groups.append(group)
            for name in (f"tasks/scenarios/{group['scenario_id']}.json", f"annotations/ground_truth_rules/{group['scenario_id']}.json"):
                dest = target/name; dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src/name,dest)
    # Reuse frozen transitive components; no reading additional raw members.
    for i,a in enumerate(sources):
        for b in sources[i+1:]:
            aa,bb = a['connected_source_evidence'],b['connected_source_evidence']
            if (set(aa['component_raw_keys']) & set(bb['component_raw_keys']) or
                set(aa['original_identities']) & set(bb['original_identities']) or
                any(aa[k] == bb[k] for k in ('ordered_geometry_digest','multiset_geometry_digest','rotation_invariant_digest'))):
                raise JevSelectError('v2_connected_sources_not_independent')
    write(target/'splits/group_manifest.json',{'groups':groups})
    return {'sources':sources,'source_groups':len({s['source_group_id'] for s in sources}),
            'independent_new_sources':0,'exposed_training_only':True,'other_component_members_read':False}, old


def _attribute_report(tasks, identities, warning=None):
    from collections import Counter
    rows = []; unique = {}; orders = []
    for t in tasks:
        if t['business_configuration'] != 'B1': continue
        attrs = [t['attributes'][o['item_id']] for o in t['items']]
        products = [identities[t['scenario_id']][o['item_id']] for o in t['items']]
        for identity,a in zip(products,attrs):
            rows.append(a); unique[identity] = a
        count = Counter(products); run = longest = 0
        for a in attrs:
            run = run+1 if a['labels']['no_top_load'] else 0
            longest = max(longest,run)
        n = len(attrs); nt = sum(a['labels']['no_top_load'] for a in attrs)
        orders.append({'scenario_id':t['scenario_id'],'instances':n,'unique_products':len(count),
            'repeated_instances_beyond_first':n-len(count), 'repeated_excess_ratio':(n-len(count))/n,
            'instances_of_repeated_products':sum(c for c in count.values() if c>1),
            'no_top_count':nt, 'no_top_ratio':nt/n, 'longest_no_top_arrival_run':longest,
            'concentration_warning':warning is not None and nt/n>warning,
            'physical_nonstackable_count':sum(not o['stackable'] for o in t['items']),
            'no_top_physical_nonstackable_overlap':sum(a['labels']['no_top_load'] and not o['stackable'] for a,o in zip(attrs,t['items']))})
    def summarize(values):
        values=list(values)
        return {'denominator':len(values),'limit_counts':dict(sorted(Counter(str(a['labels']['max_top_load_kg']) for a in values).items())),
            'no_top_count':sum(a['labels']['no_top_load'] for a in values),
            'no_top_ratio':sum(a['labels']['no_top_load'] for a in values)/len(values),
            'reinforced_packaging_count':sum(a['packaging']['reinforced'] for a in values),
            'reinforced_eligible_count':sum(a['packaging']['reinforced'] and not a['labels']['no_top_load'] for a in values),
            'business_limit_above_physical':sum(a['labels']['max_top_load_kg']>a['physical_top_load_limit_kg'] for a in values)}
    return {'instance_weighted':summarize(rows),'product_deduplicated':summarize(unique.values()),'orders':orders}


def _v2_checks(root, old, adapted):
    """No rollout, candidate generation, policy search or model invocation."""
    import copy
    from .dataset import DatasetOrderAdapter, business_spec, calibrate_v2, v2_labels, ceil_half
    from .experiment import validate_tasks
    from .contracts import validate_schema
    from decimal import Decimal
    def require(value, name):
        if not value: raise JevSelectError('v2_check_failed',name)
    spec = business_spec('public_generated_v2')
    stats,ids = calibrate_v2(old)
    require(stats==spec['calibration']['statistics'],'calibration')
    for name,bundle in adapted.items():
        validate_tasks(bundle['tasks'])
        require(bundle==DatasetOrderAdapter().load(root,spec_config=spec,difficulty=name),'determinism')
        require(bundle['split_manifest']==DatasetOrderAdapter().load(root)['split_manifest'],'source_group_stability')
        for t in bundle['tasks']:
            original = next(o for o in old if o['scenario_id']==t['scenario_id'] and o['business_configuration']==t['business_configuration'])
            require(t['items']==original['items'] and t['container']==original['container'] and t['provenance']==original['provenance'],'physical_fields_and_order')
            unchanged = lambda attrs: {k:v for k,v in attrs.items() if k!='labels'}
            require(all(unchanged(a)==unchanged(original['attributes'][oid]) for oid,a in t['attributes'].items()),'nonlabel_attributes')
            require([r for r in t['reference_policy']['rules'] if r['rule_id']!='reinforced']==
                [r for r in original['reference_policy']['rules'] if r['rule_id']!='reinforced'],'unchanged_other_rules')
            rules={r['rule_id']:r for r in t['reference_policy']['rules']}
            require(rules['reinforced']['limit']['constant_kg']==spec['difficulties'][name]['reinforced_limit_kg'],'reinforced_constant')
            require(rules['reinforced']['overrides']==['label'] and rules['no_top']['overrides']==['label'],'override_graph')
            from semantic_pallet_planner.o4.normalize import resolve_limits
            load_rules={'rules':[r for r in rules.values() if r['type'] in ('max_top_load','no_top_load')]}
            limits,_,active=resolve_limits(list(t['attributes'].values()),load_rules)
            for oid,a in t['attributes'].items():
                require(a['labels']==v2_labels(spec,ids[t['scenario_id']][oid],name),'same_product')
                winner=('no_top' if a['labels']['no_top_load'] else 'reinforced' if
                    a['cargo_category']=='glassware' and a['packaging']['reinforced'] else 'label')
                expected_limit=(0 if winner=='no_top' else spec['difficulties'][name]['reinforced_limit_kg'] if
                    winner=='reinforced' else a['labels']['max_top_load_kg'])
                require(active[oid]==[winner] and limits[oid]==expected_limit,'actual_override_resolution')
        max_label=max(v2_labels(spec,i,name)['max_top_load_kg'] for i in stats['members'])
        require(max_label==spec['difficulties'][name]['maximum_normal_label_kg'],'normal_maximum')
        require(ceil_half(Decimal(str(max_label))*Decimal('1.5'))==spec['difficulties'][name]['reinforced_limit_kg'],'reinforced_factor')
    for identity in stats['members']:
        a,b,c=[v2_labels(spec,identity,n) for n in ('loose','moderate','strict')]
        require(a['max_top_load_kg']>=b['max_top_load_kg']>=c['max_top_load_kg'],'monotonic_limits')
        require(a['no_top_load']<=b['no_top_load']<=c['no_top_load'],'nested_no_top')
    for bad in ({**spec,'version':'unknown'}, {**spec,'attribute_seed':0}, {k:v for k,v in spec.items() if k!='calibration'}):
        try: DatasetOrderAdapter().load(root,spec_config=bad)
        except JevSelectError: pass
        else: raise JevSelectError('v2_invalid_config_accepted')
    validate_schema('business_spec_v2',spec)
    return {'status':'PASS','v1_frozen_output_compatibility':True,'v2_load_and_schema':True,
        'unknown_and_partial_config_rejected':True,'same_product':True,'monotonic_and_nested':True,
        'reinforced_constant_and_override_graph':True,'actual_override_resolution':True,'all_physical_fields_and_arrival_preserved':True,
        'other_business_semantics_preserved':True,'deterministic_full_adaptation':True,
        'task_count':sum(len(b['tasks']) for b in adapted.values()),'episodes_run':0,
        'policy_input_boundary':'existing public observation allowlist; calibration and article IDs remain private',
        'statistics':{k:v for k,v in stats.items() if k not in ('members','conflicts')}}


def build_dataset_v2(repo, output):
    """Materialize the fixed v2 overlay; no experiment execution."""
    from .dataset import DatasetOrderAdapter, business_spec, calibrate_v2, attribute_value
    from .experiment import _new_output, file_manifest
    repo=Path(repo).resolve(); out=_new_output(output)
    with offline_dataset_guard() as guards:
        before = _protected_inventory(repo)
        out.mkdir(parents=True)
        manifest, old = _v2_sources(repo,out/'sources')
        spec=business_spec('public_generated_v2')
        adapted={name:DatasetOrderAdapter().load(out/'sources',spec_config=spec,difficulty=name) for name in spec['difficulties']}
        checks=_v2_checks(out/'sources',old,adapted)
        stats,ids=calibrate_v2(old)
        attributes={}
        for identity,member in stats['members'].items():
            occurrences=[{'scenario_id':t['scenario_id'],'item_id':oid} for t in old if t['business_configuration']=='B1'
                for oid in t['attributes'] if ids[t['scenario_id']][oid]==identity]
            attributes[identity]={'member':member,'occurrences':occurrences,
                'multiplier':spec['product_multipliers'][int(attribute_value(spec,identity,'load_multiplier')*3)],
                'no_top_hash_score':attribute_value(spec,identity,'no_top_load'),
                'v2':{name:next(t['attributes'][occurrences[0]['item_id']] for t in b['tasks'] if t['scenario_id']==occurrences[0]['scenario_id']) for name,b in adapted.items()},
                'v1':next(t['attributes'][occurrences[0]['item_id']] for t in old if t['scenario_id']==occurrences[0]['scenario_id'])}
        report={'scope':'static_attributes_only_no_effect_experiment','v1':_attribute_report(old,ids),
                'v2':{name:_attribute_report(b['tasks'],ids,spec['difficulties'][name]['concentration_warning']) for name,b in adapted.items()}}
        history_root=repo/'semantic_pallet_planner/outputs/GEN_JEV_J4_B2_EXTENSION_RETRY_20261101_01'
        history=read(history_root/'handoff.json'); stop=read(history_root/'smoke_stop_receipt.json')
        # Read only already saved five valid episode summaries, never re-execute.
        summaries=[]
        outputs=repo/'semantic_pallet_planner/outputs'
        for run in ('EXP_JEV_J4_B2_REAL_SMOKE_20261031_01','EXP_JEV_J4_B2_REAL_REST_20261031_01','EXP_JEV_J4_B2_EXTENSION_SMOKE_20261101_02'):
            for p in sorted((outputs/run/'episodes').glob('*.json')):
                e=read(p);summaries.append({'path':str(p.relative_to(repo)),'summary':e['summary']})
        write(out/'baseline_inventory.json',{'historical_only':True,'protected_sha256':before,
            'previous_handoff':history,'previous_stop':stop,'previous_episode_summaries':summaries,
            'not_current_outputs':'5 valid historical trajectories; 7 historical formal generations; active0'})
        write(out/'existing_source_manifest.json',manifest)
        write(out/'business_spec.snapshot.json',spec)
        write(out/'attribute_map.json',{'local_only':True,'conflicts':stats['conflicts'],'products':attributes})
        write(out/'attribute_diff_report.json',report)
        write(out/'dataset/v1_baseline_tasks.json',old)
        write(out/'dataset/split_manifest.json',next(iter(adapted.values()))['split_manifest'])
        tasks=[t for b in adapted.values() for t in b['tasks']]
        write(out/'dataset/tasks.json',tasks)
        for t in tasks: write(out/'dataset/tasks'/f"{t['task_id']}.json",t)
        write(out/'dataset/input_audits.json',{n:b['input_audit'] for n,b in adapted.items()})
        if _protected_inventory(repo)!=before: raise JevSelectError('historical_bytes_changed')
        checks['protected_historical_files_unchanged']=len(before)
        checks['offline_guards']=dict(guards)
        write(out/'verification/engineering_checks.json',checks)
        import shutil
        package=Path(__file__).parent
        changed=('dataset.py','dataset_j4.py','batch_j4.py','cli.py','contracts.py','evaluation.py',
                 'configs/business_spec_v2.json','schemas/business_spec_v2.schema.json','tests/unit/test_dataset_v2.py')
        code_manifest={}
        for name in changed:
            target=out/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(package/name,target);code_manifest[name]=_sha(target)
        write(out/'verification/implementation_manifest.json',code_manifest)
        write(out/'handoff.json',{'date':'2026-11-01','role':'developer_agent','independent_review':False,
            'dataset_engineering_goal_complete':True,'code_status':'IMPLEMENTED','data_tasks':len(tasks),
            'source_groups':manifest['source_groups'],'external_calls':0,'credential_reads':0,'episodes_run':0,
            'physical_fields_preserved':True,'effect_experiment':'NOT_RUN',
            'not_proven':['physical_early_stop_resolved','violation_rate_reduced','B2_nonempty_library_complete','benefit'],
            'load':'DatasetOrderAdapter().load(delivery/sources, spec_config=delivery/business_spec.snapshot.json, difficulty=loose|moderate|strict)',
            'validate':'python -m semantic_pallet_planner.jev_select validate-dataset-v2 --dataset DELIVERY'})
        write(out/'delivery_manifest.json',file_manifest(out))
        # Authenticate the actual exported bytes, including the complete task registry.
        validated=load_dataset_v2_delivery(out)
        if digest(validated['tasks'])!=digest(tasks): raise JevSelectError('v2_export_mismatch')
        return {'status':'PASS','output':str(out),'task_count':len(tasks),'source_groups':manifest['source_groups'],
                'tasks_digest':digest(tasks),'offline_guards':dict(guards),'episodes_run':0}


def load_dataset_v2_delivery(root):
    """Read-only authenticated load, plus recomputation from pinned sources."""
    from .dataset import DatasetOrderAdapter, business_spec
    from .experiment import file_manifest
    root=Path(root).resolve()
    with offline_dataset_guard():
        manifest=read(root/'delivery_manifest.json')
        if manifest!=file_manifest(root): raise JevSelectError('v2_delivery_digest_mismatch')
        spec=read(root/'business_spec.snapshot.json')
        if spec!=business_spec('public_generated_v2'): raise JevSelectError('business_spec_not_frozen')
        bundles={n:DatasetOrderAdapter().load(root/'sources',spec_config=spec,difficulty=n) for n in spec['difficulties']}
        expected=[t for b in bundles.values() for t in b['tasks']]
        tasks=read(root/'dataset/tasks.json')
        if tasks!=expected: raise JevSelectError('v2_task_snapshot_mismatch')
        for t in tasks:
            if read(root/'dataset/tasks'/f"{t['task_id']}.json")!=t: raise JevSelectError('v2_task_snapshot_mismatch')
        split=next(iter(bundles.values()))['split_manifest']
        if read(root/'dataset/split_manifest.json')!=split: raise JevSelectError('v2_split_snapshot_mismatch')
        if read(root/'dataset/input_audits.json')!={n:b['input_audit'] for n,b in bundles.items()}:
            raise JevSelectError('v2_input_audit_snapshot_mismatch')
        if {p.name for p in (root/'dataset/tasks').iterdir()}!={t['task_id']+'.json' for t in tasks}:
            raise JevSelectError('v2_task_registry_mismatch')
        return {'tasks':tasks,'business_spec':spec,'split_manifest':split}


def validate_dataset_v2(root):
    with offline_dataset_guard() as guards:
        data=load_dataset_v2_delivery(root)
        return {'status':'PASS','task_count':len(data['tasks']),
            'tasks_digest':digest(data['tasks']),'offline_guards':dict(guards),'episodes_run':0}
