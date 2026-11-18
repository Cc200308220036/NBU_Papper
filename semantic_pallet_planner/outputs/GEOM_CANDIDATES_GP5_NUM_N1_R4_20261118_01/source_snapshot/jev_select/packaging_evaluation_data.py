"""New derived data envelope. Frozen packaging calibration, no order execution.

A positive admission is recomputed from independently pinned trust policy and
bound source statements on every load; neither a split name nor a receipt is proof.
"""
from pathlib import Path
import copy
import importlib.util
from .contracts import digest,validate_schema
from .ledger import read,write
from .packaging_source_audit import sha,require,raw_items
from .packaging_source_provenance import adjudicate
from .dataset_packaging import packaging_spec,profile_for
VERSION='jev_evaluation_dataset_v1'
TASK='jev_evaluation_packaging_task_v1'



def observed_uses(repo,identity,policy):
    if policy['fixture_only']:return []
    # This version admits only the already registered raw corpus, not arbitrary
    # self-selected new data. Local contamination overrides signed claims.
    root=Path(repo);original=root/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01'
    require(identity['raw_manifest_sha256']==read(original/'source_access_receipt.json')['raw_sha256']==sha(root/'raw/bed_bpp/bed-bpp_v1.json'),'evaluation_unregistered_raw_corpus')
    comp=next((c for c in read(original/'source_audit.json')['components'] if c['component']==identity['component']),None)
    require(comp is not None and sorted(comp['raw_keys'])==identity['raw_keys'] and sorted(comp['identities'])==identity['identities'],'evaluation_registered_component_changed')
    status=comp['exposure_status']
    return ['policy_development'] if status=='TRAIN_DEV_OR_REAL_RUN' else ['historical_testing'] if status=='HISTORICAL_TEST' else []

def select_sources(raw,admissions):
    eligible={x['source_identity']['component']:x for x in admissions if x['strict_test_eligible']}
    bins=[(14,20),(21,30),(31,40)];selected=[]
    for lo,hi in bins:
        rows=[]
        for component,a in eligible.items():
            key=min(a['source_identity']['raw_keys']);n=len(raw_items(raw[key]))
            if lo<=n<=hi:rows.append((digest([20261105,component]),component,key))
        rows.sort();require(len(rows)>=2,'evaluation_insufficient_length_stratum')
        selected.extend({'component':c,'raw_key':k,'admission_digest':eligible[c]['admission_digest']} for _,c,k in rows[:2])
    return selected


def materialize_tasks(repo,raw,selection):
    repo=Path(repo);spec=packaging_spec()
    # Reuse an archived task's envelope only; all item fields are rebuilt from raw.
    data=repo/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02'
    # Frozen task filenames are located through the package's actual layout.
    candidates=sorted(data.rglob('*controlled_heterogeneous.json'))
    require(bool(candidates),'evaluation_missing_frozen_template')
    template=read(candidates[0]);normalizer=repo/'semantic_pallet_dataset_v1/scripts/build_dataset.py'
    mspec=importlib.util.spec_from_file_location('jev_frozen_raw_normalizer',normalizer);module=importlib.util.module_from_spec(mspec);mspec.loader.exec_module(module)
    cfg=read(repo/'semantic_pallet_dataset_v1/configs/mvd_v0.1.json')
    thresholds=read(repo/'semantic_pallet_dataset_v1/statistics/dataset_summary.json')['weight_class_thresholds_kg']
    sku_physical={};tasks=[]
    for row in selection:
        key=row['raw_key'];task=copy.deepcopy(template)
        task.update(version=TASK,task_id='EVAL_'+key,scenario_id='EVAL_'+key,source_group_id='COMP_'+row['component'],
             source_order_key=key,source_order_id=str(raw[key].get('properties',{}).get('id',key)),partition='test',items=[],arrival_order=[],
             feasibility_status='UNKNOWN',static_screen_status='STATIC_SCREEN_PASSED')
        for i,original in enumerate(raw_items(raw[key])):
            normalized=module.normalize_source_item(original,cfg['dataset_seed'],cfg['geometry_ood']['height_threshold_mm'])
            normalized.update(item_id=f'item_{i+1:02d}',weight_class='light' if normalized['mass_kg']<=thresholds['light_max'] else 'medium' if normalized['mass_kg']<=thresholds['medium_max'] else 'heavy')
            physical=module.public_item(normalized);physical['product_category']='general'
            sku=str(original['id']);signature=digest({k:v for k,v in physical.items() if k!='item_id'})
            require(sku not in sku_physical or sku_physical[sku]==signature,'evaluation_raw_article_conflict')
            sku_physical[sku]=signature
            profile=profile_for(spec,sku,spec['layers']['controlled_heterogeneous'])
            item=copy.deepcopy(physical);item.update(sku_id=sku,packaging_profile_id=profile['id']+'_x1',stackable=profile['stackable'],
               max_top_load_kg=profile['capacity_kg'],top_load_limit_kg_synthetic=profile['capacity_kg'],
               effective_top_permission_kg=profile['capacity_kg'] if profile['stackable'] else 0,
               physical_provenance='archived raw dimensions and mass; original measurement status unverified',
               capacity_provenance='controlled_synthetic_experimental',original_physical=physical)
            task['items'].append(item);task['arrival_order'].append(item['item_id'])
        import math
        c=task['container'];necessary=all(o['mass_kg']<=c['max_payload_kg'] and o['dimensions_mm']['height']<=c['max_height_mm'] and any(l<=c['length_mm'] and w<=c['width_mm'] for l,w in [(o['dimensions_mm']['length'],o['dimensions_mm']['width']),(o['dimensions_mm']['width'],o['dimensions_mm']['length'])]) for o in task['items'])
        necessary=necessary and sum(o['mass_kg'] for o in task['items'])<=c['max_payload_kg'] and sum(math.prod(o['dimensions_mm'].values()) for o in task['items'])<=c['length_mm']*c['width_mm']*c['max_height_mm']
        task['static_screen_status']='STATIC_SCREEN_PASSED' if necessary else 'STATIC_SCREEN_FAILED'
        validate_schema('evaluation_packaging_task_v1',task);tasks.append(task)
    return tasks


def build(repo,raw_path,selection,proofs,policy,output,*,as_of):
    root=Path(output);require(not root.exists(),'evaluation_data_output_exists')
    raw=read(raw_path);raw_sha=sha(raw_path);admissions=[]
    for component,proof in sorted(proofs.items()):
        identity=proof['statement']['body']['source_identity']
        require(identity['component']==component and identity['raw_manifest_sha256']==raw_sha,'evaluation_raw_identity')
        require(all(digest(raw[k])==h for k,h in identity['raw_order_digests'].items()),'evaluation_raw_record_changed')
        result=adjudicate(identity,proof['statement'],policy,evidence_root=proof['root'],observed_uses=observed_uses(repo,identity,policy),as_of=as_of)
        require(result['strict_test_eligible'],'evaluation_source_not_admitted');admissions.append(result)
    require(selection==select_sources(raw,admissions),'evaluation_unregistered_selection')
    tasks=materialize_tasks(repo,raw,selection);root.mkdir(parents=True)
    import shutil
    for c,proof in proofs.items():
        write(root/'proofs'/c/'statement.json',proof['statement'])
        for n in proof['statement']['body']['evidence_files']:
            dest=root/'proofs'/c/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(proof['root'])/n,dest)
    write(root/'raw_orders.json',{k:raw[k] for p in proofs.values() for k in p['statement']['body']['source_identity']['raw_keys']})
    write(root/'trust_policy.json',policy);write(root/'selection.json',selection)
    spec=packaging_spec();payload={'version':VERSION,'fixture_only':policy['fixture_only'],'tasks':tasks,'admissions':admissions,
       'raw_manifest_sha256':raw_sha,'as_of':as_of,'policy_digest':digest(policy),'calibration':spec['calibration'],
       'packaging_config_digest':digest(spec),'normalizer_sha256':sha(Path(repo)/'semantic_pallet_dataset_v1/scripts/build_dataset.py')}
    payload['data_identity']=digest(payload);validate_schema('evaluation_dataset_v1',payload);write(root/'dataset.json',payload)
    from .experiment import file_manifest
    write(root/'delivery_manifest.json',file_manifest(root));return load_dataset(root,repo=repo,policy=policy)


def load_dataset(root,*,repo,policy):
    root=Path(root);d=read(root/'dataset.json');validate_schema('evaluation_dataset_v1',d);require(d['version']==VERSION,'evaluation_data_version')
    from .experiment import file_manifest
    require(read(root/'delivery_manifest.json')==file_manifest(root),'evaluation_dataset_bytes')
    require(d['data_identity']==digest({k:v for k,v in d.items() if k!='data_identity'}),'evaluation_data_digest')
    require(d['policy_digest']==digest(policy) and read(root/'trust_policy.json')==policy,'evaluation_untrusted_embedded_policy')
    spec=packaging_spec();require(d['calibration']==spec['calibration'] and d['packaging_config_digest']==digest(spec),'evaluation_calibration_changed')
    require(d['normalizer_sha256']==sha(Path(repo)/'semantic_pallet_dataset_v1/scripts/build_dataset.py'),'evaluation_normalizer_changed')
    results=[];selection=read(root/'selection.json');raw=read(root/'raw_orders.json')
    for f in sorted((root/'proofs').glob('*/statement.json')):
        statement=read(f);identity=statement['body']['source_identity']
        require(identity['raw_manifest_sha256']==d['raw_manifest_sha256'],'evaluation_bound_source_changed')
        require(all(digest(raw[k])==h for k,h in identity['raw_order_digests'].items()),'evaluation_raw_record_changed')
        result=adjudicate(identity,statement,policy,evidence_root=f.parent,observed_uses=observed_uses(repo,identity,policy),as_of=d['as_of'])
        require(result['strict_test_eligible'],'evaluation_admission_revoked');results.append(result)
    require(results==d['admissions'],'evaluation_admission_receipt_changed')
    require(selection==select_sources(raw,results),'evaluation_data_selection_changed')
    from .packaging_source_audit import components
    groups,_,desc=components(raw,[a['source_identity']['raw_keys'] for a in results])
    require(len({desc[r['raw_key']]['component'] for r in selection})==len(selection),'evaluation_near_duplicate_cross_source')
    require(materialize_tasks(repo,raw,selection)==d['tasks'],'evaluation_task_provenance_changed')
    from .packaging_runtime import runtime_task
    tasks=[runtime_task(t) for t in d['tasks']]
    require(len({t['source_group_id'] for t in tasks})==len(tasks)==6,'evaluation_source_split_overlap')
    return {'version':VERSION,'data_identity':d['data_identity'],'fixture_only':d['fixture_only'],'tasks':tasks,'dataset':d}
