"""Deterministic synthetic composition. Metadata only; no candidate or retrieval calls."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import copy
import json
from .contracts import canonical, digest, validate_schema
from .ledger import read, write
from .packaging_source_audit import require, sha, fingerprints
from .dataset_packaging import packaging_spec, profile_for

VERSION = 'jev_synthetic_combo_dataset_v1'
GENERATION = 'jev_synthetic_combo_generation_v1'
MEMORY_SCOPE = 'jev_synthetic_combo_memory_scope_v1'
RAW_SHA = '6ecc91d92b9ce88de113ac66c45a450ac3eec303018f14cd73e4bd0eaf8eb3cc'
AUDIT_SHA = 'd5095679bd7a3eccfadb88e0535ffc9ebe84d54ac578d18f4d00651467189711'
TASKS = [(f'SYN_COMBO_{i:02d}', n) for i, n in enumerate((16,20,24,30,34,40),1)]


def decimal_string(v):
    require(not isinstance(v, bool) and isinstance(v, (int,float,Decimal)), 'synthetic_numeric_type')
    try: d = Decimal(str(v))
    except InvalidOperation: require(False, 'synthetic_invalid_decimal')
    require(d.is_finite() and d > 0, 'synthetic_nonpositive_or_nonfinite')
    s = format(d, 'f')
    return s.rstrip('0').rstrip('.') if '.' in s else s


def identity(row):
    v = row.get('id')
    require(v is not None and not isinstance(v,bool) and str(v).strip() != '', 'synthetic_article_id')
    return [str(v)] + [decimal_string(row.get(k)) for k in ('length/mm','width/mm','height/mm','weight/kg')]


def runtime_number(s):
    d = Decimal(s); v = int(d) if d == d.to_integral_value() else float(d)
    require(Decimal(str(v)) == d, 'synthetic_runtime_precision_loss')
    return v


def raw_data(repo):
    p = Path(repo)/'raw/bed_bpp/bed-bpp_v1.json'
    require(sha(p) == RAW_SHA, 'synthetic_raw_identity')
    return json.loads(p.read_text(encoding='utf-8'), parse_float=Decimal, parse_int=Decimal)


def prototype_pool(raw, component_map):
    rows = {}; bad = []; articles = defaultdict(set)
    for key, order in sorted(raw.items()):
        require(key in component_map, 'synthetic_unmapped_material_component')
        for pos, row in sorted(order['item_sequence'].items()):
            try: ident = identity(row)
            except Exception as e:
                bad.append({'raw_key':key,'raw_position':pos,'reason':str(e)});continue
            h = digest(ident)
            if h in rows: require(rows[h]['identity'] == ident, 'synthetic_hash_collision')
            else: rows[h] = {'prototype_digest':h,'identity':ident,'sku_id':'SYN_SKU_'+h,'references':[]}
            rows[h]['references'].append({'raw_key':key,'raw_position':pos,'article_id':ident[0],
                'sequence':str(row['sequence']),'component':component_map[key]})
            articles[ident[0]].add(h)
    require(bool(rows), 'synthetic_empty_pool')
    return {'prototypes':[rows[h] for h in sorted(rows)],'invalid_records':bad,
            'article_physical_conflicts':{k:sorted(v) for k,v in sorted(articles.items()) if len(v)>1}}


def freeze(repo, output):
    """Persist full pool and registration BEFORE generation; never overwrite."""
    repo=Path(repo);out=Path(output);require(not out.exists(),'synthetic_output_exists')
    audit=repo/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json'
    require(sha(audit)==AUDIT_SHA,'synthetic_audit_identity')
    components={k:c['component'] for c in read(audit)['components'] for k in c['raw_keys']}
    pool=prototype_pool(raw_data(repo),components)
    write(out/'pool.json',pool)
    hs=[x['prototype_digest'] for x in pool['prototypes']]
    registration={'version':'jev_synthetic_combo_registration_v1','generation_version':GENERATION,'memory_scope_version':MEMORY_SCOPE,
      'raw_sha256':RAW_SHA,'audit_sha256':AUDIT_SHA,'pool_digest':digest(hs),'pool_file_sha256':sha(out/'pool.json'),
      'references_digest':digest([x['references'] for x in pool['prototypes']]),'seed':20261105,'tasks':[{'task_id':t,'count':n} for t,n in TASKS],
      'encoding':'canonical UTF-8 five decimal-string identity; full lowercase sha256; ASCII digest sort; no axis swap',
      'sampling':'full sha256([generation_version,seed,task_id,1-based-index]) integer modulo pool size; replacement',
      'packaging_config_digest':digest(packaging_spec()),'material_scope':'familiar raw prototypes; synthetic composition, not unseen real sources'}
    validate_schema('synthetic_registration_v1',registration)
    write(out/'registration.json',registration)
    write(out/'sku_mapping.json',{'sku_to_prototype':{x['sku_id']:x['prototype_digest'] for x in pool['prototypes']},
       'prototype_to_sku':{x['prototype_digest']:x['sku_id'] for x in pool['prototypes']}})
    return registration


def static_classification(task):
    c=task['container'];bad=[]
    for o in task['items']:
        d=o['dimensions_mm'];l,w,h=(Decimal(str(d[k])) for k in ('length','width','height'))
        m=Decimal(str(o['mass_kg']))
        if not (h<=c['max_height_mm'] and m<=c['max_payload_kg'] and ((l<=c['length_mm'] and w<=c['width_mm']) or (w<=c['length_mm'] and l<=c['width_mm']))):bad.append(o['item_id'])
    volume=sum(Decimal(str(o['dimensions_mm']['length']))*Decimal(str(o['dimensions_mm']['width']))*Decimal(str(o['dimensions_mm']['height'])) for o in task['items'])
    mass=sum(Decimal(str(o['mass_kg'])) for o in task['items'])
    reasons=[]
    if volume>c['length_mm']*c['width_mm']*c['max_height_mm']:reasons.append('TOTAL_VOLUME_EXCEEDS_CONTAINER')
    if mass>c['max_payload_kg']:reasons.append('TOTAL_MASS_EXCEEDS_PAYLOAD')
    if bad:reasons.append('INDIVIDUAL_ITEM_CANNOT_FIT')
    return {'data_validity':'PASS','single_item_fit':'FAIL' if bad else 'PASS','unfit_items':bad,
      'completion_necessary_conditions':'FAIL' if reasons else 'PASS','reasons':reasons,
      'total_volume_mm3':str(volume),'total_mass_kg':str(mass),'partial_loading_eligible':True,'layout_witness':'NOT_AVAILABLE'}


def generate(pool, registration, template, thresholds):
    require(registration['generation_version']==GENERATION and registration['seed']==20261105,'synthetic_generation_rule')
    require(registration['tasks']==[{'task_id':t,'count':n} for t,n in TASKS],'synthetic_task_lengths')
    spec=packaging_spec();rows=pool['prototypes'];tasks=[];samples=[];classifications={}
    for tid,n in TASKS:
        task=copy.deepcopy(template)
        task.update(version='jev_evaluation_packaging_task_v1',task_id=tid,scenario_id=tid,source_group_id='SYN_GROUP_'+tid,
         source_order_key=tid,source_order_id=tid,partition='test',items=[],arrival_order=[],feasibility_status='UNKNOWN',static_screen_status='STATIC_SCREEN_PASSED')
        for i in range(1,n+1):
            token=digest([GENERATION,20261105,tid,i]);idx=int(token,16)%len(rows);p=rows[idx];ident=p['identity']
            l,w,h,m=[runtime_number(s) for s in ident[1:]];oid=f'{tid}_I{i:04d}'
            prof=profile_for(spec,p['sku_id'],spec['layers']['controlled_heterogeneous'])
            physical={'item_id':oid,'geometry_id':f'G_{max(l,w)}x{min(l,w)}x{h}', 'dimensions_mm':dict(length=l,width=w,height=h),
              'mass_kg':m,'weight_class':'light' if m<=thresholds['light_max'] else 'medium' if m<=thresholds['medium_max'] else 'heavy',
              'material':'unspecified','fragile':False,'product_category':'general','stackable':prof['stackable'],'top_load_limit_kg_synthetic':prof['capacity_kg']}
            item={**physical,'sku_id':p['sku_id'],'packaging_profile_id':prof['id']+'_x1','max_top_load_kg':prof['capacity_kg'],
              'effective_top_permission_kg':prof['capacity_kg'] if prof['stackable'] else 0,
              'physical_provenance':'BED-BPP raw dimensions/mass; measurement unverified; synthetic order composition',
              'capacity_provenance':'controlled_synthetic_experimental','original_physical':physical}
            task['items'].append(item);task['arrival_order'].append(oid)
            samples.append({'task_id':tid,'item_id':oid,'arrival_index':i,'sampling_digest':token,'pool_index':idx,'prototype_digest':p['prototype_digest']})
        classifications[tid]=static_classification(task)
        # Legacy field is a necessary-condition summary only, never a run veto.
        if classifications[tid]['completion_necessary_conditions']=='FAIL':task['static_screen_status']='STATIC_SCREEN_FAILED'
        validate_schema('evaluation_packaging_task_v1',task);tasks.append(task)
    return tasks,samples,classifications


def task_counter(t):
    return Counter((min(round(float(o['dimensions_mm']['length'])),round(float(o['dimensions_mm']['width']))),
       max(round(float(o['dimensions_mm']['length'])),round(float(o['dimensions_mm']['width']))),round(float(o['dimensions_mm']['height'])),round(float(o['mass_kg']),2)) for o in t['items'])


def related(a,b):
    n,m=sum(a.values()),sum(b.values())
    return a==b or (min(n,m)>=.9*max(n,m) and sum((a&b).values())>=.9*min(n,m))


def historical_inputs(repo, raw, audit):
    """Bind all frozen JN training/task snapshots, plus memory parent inputs/forks."""
    repo=Path(repo);base=repo/'semantic_pallet_planner/outputs';files={};records=[];group_components=defaultdict(set);forks=defaultdict(set)
    component={k:c['component'] for c in audit['components'] for k in c['raw_keys']}
    def bind_task(t,path,fork=None):
        require('source_order_key' in t and t['source_order_key'] in component and 'source_group_id' in t,'synthetic_historical_task_identity')
        key=t['source_order_key'];g=t['source_group_id'];comp=component[key];group_components[comp].add(g)
        if fork:forks[g].add(fork)
        records.append({'path':str(path.relative_to(repo)),'task_digest':digest(t),'source_group':g,'component':comp,
          'counter':task_counter(t),'fork_digest':fork})
    for package in sorted(base.glob('JEV_JN[0123]_*')):
        for p in sorted(package.rglob('task.snapshot.json')):
            if {'code_snapshot','test_snapshot'}.intersection(p.parts):continue
            t=read(p);files[str(p.relative_to(repo))]=sha(p);bind_task(t,p)
    data=base/'DATA_JEV_PACKAGING_LOAD_20261102_02'
    split=data/'split_manifest.json';files[str(split.relative_to(repo))]=sha(split)
    for g in read(split)['groups']:
        for sid in g['scenario_ids']:
            key=sid.removeprefix('NEW_');require(key in component,'synthetic_split_missing_raw')
            group_components[component[key]].add(g['source_group_id'])
    # Enumerate frozen fork-input manifest, including non-winning/non-memory forks.
    parent=base/'JEV_JN2_20261104_02';manifest=parent/'delivery_manifest.json'
    files[str(manifest.relative_to(repo))]=sha(manifest)
    for name,h in read(manifest)['files_sha256'].items():
        if name.startswith('inputs/F') and name.endswith('.json'):
            f=parent/name;require(f.is_file() and sha(f)==h,'synthetic_missing_frozen_training_input')
            value=read(f)['value'];t=value['task'];snapshot=value['snapshot']
            require(snapshot['task_digest']==digest(t),'synthetic_training_input_task_binding')
            files[str(f.relative_to(repo))]=sha(f);bind_task(t,f,digest(snapshot))
    for package,name,field in [('JEV_JN3_20261104_01','trajectory_snapshot.json','cases'),('JEV_JN3_20261104_02','contrast_snapshot.json','cards')]:
        p=base/package/name;value=read(p);files[str(p.relative_to(repo))]=sha(p)
        for card in value[field]:
            prov=card['provenance'];f=repo/prov['snapshot_path'];v=read(f)['value'];t=v['task']
            require(digest(t)==prov['task_digest'] and t['source_group_id']==prov['source_group'],'synthetic_memory_parent_mismatch')
            require(digest(v['snapshot'])==prov['fork_digest'],'synthetic_fork_parent_mismatch')
            files[str(f.relative_to(repo))]=sha(f);bind_task(t,f,prov['fork_digest'])
    return records,dict(group_components),dict(forks),files


def relations(tasks,samples,pool,raw,audit,records,groups,forks):
    comps={k:c['component'] for c in audit['components'] for k in c['raw_keys']}
    raw_counts={k:fingerprints(o)[1] for k,o in raw.items()}
    by_digest={p['prototype_digest']:p for p in pool['prototypes']};result={}
    for t in tasks:
        tid=t['task_id'];cnt=task_counter(t);matches=[k for k,c in raw_counts.items() if related(cnt,c)]
        touched={comps[k] for k in matches};record_matches=[r for r in records if related(cnt,r['counter'])]
        touched.update(r['component'] for r in record_matches)
        related_groups=set(g for c in touched for g in groups.get(c,()))
        related_groups.update(r['source_group'] for r in record_matches)
        excluded_forks={f for g in related_groups for f in forks.get(g,())}
        # References disclose shared material only; they do not change order exclusion.
        material={r['component'] for s in samples if s['task_id']==tid for r in by_digest[s['prototype_digest']]['references']}
        peers=[x['task_id'] for x in tasks if x['task_id']!=tid and related(cnt,task_counter(x))]
        result[tid]={'memory_scope_version':MEMORY_SCOPE,'material_source_components':sorted(material),
          'order_related_source_groups':sorted(related_groups),'excluded_fork_digests':sorted(excluded_forks),
          'matched_raw_keys':matches,'matched_historical_inputs':[r['path'] for r in record_matches],
          'matched_synthetic_tasks':peers,'order_related_components':sorted(touched),
          'new_combination_status':'PASS' if not (matches or record_matches or peers) else 'PAUSE_OVERLAPPING_ORDER',
          'rule':'upright yaw normalized mm round / .01kg Python round; exact or length>=.9max and intersection>=.9min; existing component transitive closure'}
    # Existing raw components are already transitive. Also propagate through
    # synthetic-to-synthetic links; a changed filename cannot cut the chain.
    for tid,row in result.items():
        connected={tid};pending=[tid]
        while pending:
            for peer in result[pending.pop()]['matched_synthetic_tasks']:
                if peer not in connected:connected.add(peer);pending.append(peer)
        comps=set(c for peer in connected for c in result[peer]['order_related_components'])
        gs=set(g for c in comps for g in groups.get(c,()))
        gs.update(g for peer in connected for g in result[peer]['order_related_source_groups'])
        row['order_related_components']=sorted(comps)
        row['order_related_source_groups']=sorted(gs)
        row['excluded_fork_digests']=sorted({f for g in gs for f in forks.get(g,())})
    return result


def build(repo,root):
    """Use the already sealed pool registration; generate once, static check only."""
    repo=Path(repo);root=Path(root);require(not (root/'dataset.json').exists(),'synthetic_already_materialized')
    registration=read(root/'registration.json');validate_schema('synthetic_registration_v1',registration);pool=read(root/'pool.json')
    require(registration['pool_file_sha256']==sha(root/'pool.json'),'synthetic_pool_file_changed')
    require(registration['pool_digest']==digest([p['prototype_digest'] for p in pool['prototypes']]),'synthetic_pool_order_changed')
    template_path=repo/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks/NEW_00100027_controlled_heterogeneous.json'
    thresholds_path=repo/'semantic_pallet_dataset_v1/statistics/dataset_summary.json'
    tasks,samples,classification=generate(pool,registration,read(template_path),read(thresholds_path)['weight_class_thresholds_kg'])
    raw=raw_data(repo);audit_path=repo/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json';audit=read(audit_path)
    records,groups,forks,files=historical_inputs(repo,raw,audit)
    rel=relations(tasks,samples,pool,raw,audit,records,groups,forks)
    files.update({str(template_path.relative_to(repo)):sha(template_path),str(thresholds_path.relative_to(repo)):sha(thresholds_path),str(audit_path.relative_to(repo)):sha(audit_path)})
    write(root/'historical_inputs.json',{'files_sha256':files,'component_to_groups':{k:sorted(v) for k,v in groups.items()},'group_to_forks':{k:sorted(v) for k,v in forks.items()},'frozen_task_inputs':len(records)})
    write(root/'samples.json',samples);write(root/'relations.json',rel);write(root/'static_classification.json',classification)
    for t in tasks:write(root/'tasks'/f"{t['task_id']}.json",t)
    d={'version':VERSION,'fixture_only':False,'registration_digest':digest(registration),'tasks':tasks,'relations':rel,
       'classification':classification,'historical_inputs_digest':digest(read(root/'historical_inputs.json')),'samples_digest':digest(samples),'sku_mapping_digest':digest(read(root/'sku_mapping.json'))}
    d['data_identity']=digest(d);validate_schema('synthetic_dataset_v1',d);write(root/'dataset.json',d)
    from .experiment import file_manifest
    write(root/'delivery_manifest.json',file_manifest(root));return load_dataset(root,repo=repo)


def load_dataset(root,*,repo):
    root=Path(root);repo=Path(repo)
    from .experiment import file_manifest
    require(read(root/'delivery_manifest.json')==file_manifest(root),'synthetic_dataset_bytes')
    d=read(root/'dataset.json');validate_schema('synthetic_dataset_v1',d)
    require(d['data_identity']==digest({k:v for k,v in d.items() if k!='data_identity'}),'synthetic_data_identity')
    registration=read(root/'registration.json');validate_schema('synthetic_registration_v1',registration);pool=read(root/'pool.json')
    require(registration['raw_sha256']==RAW_SHA and registration['audit_sha256']==AUDIT_SHA,'synthetic_registration_source')
    require(registration['pool_file_sha256']==sha(root/'pool.json') and registration['packaging_config_digest']==digest(packaging_spec()),'synthetic_pool_or_calibration')
    raw=raw_data(repo);audit_path=repo/'semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json'
    require(sha(audit_path)==AUDIT_SHA,'synthetic_audit_identity')
    audit=read(audit_path)
    component={k:c['component'] for c in audit['components'] for k in c['raw_keys']}
    require(pool==prototype_pool(raw,component),'synthetic_pool_rebuild')
    require(registration['pool_digest']==digest([p['prototype_digest'] for p in pool['prototypes']]) and registration['references_digest']==digest([p['references'] for p in pool['prototypes']]),'synthetic_pool_identity')
    mapping={'sku_to_prototype':{x['sku_id']:x['prototype_digest'] for x in pool['prototypes']},'prototype_to_sku':{x['prototype_digest']:x['sku_id'] for x in pool['prototypes']}}
    require(mapping==read(root/'sku_mapping.json') and digest(mapping)==d['sku_mapping_digest'],'synthetic_sku_mapping')
    history=read(root/'historical_inputs.json')
    for n,h in history['files_sha256'].items():require(sha(repo/n)==h,'synthetic_historical_input_changed')
    records,groups,forks,files=historical_inputs(repo,raw,audit)
    require(history['component_to_groups']=={k:sorted(v) for k,v in groups.items()} and history['group_to_forks']=={k:sorted(v) for k,v in forks.items()} and history['frozen_task_inputs']==len(records),'synthetic_history_mapping')
    require(all(history['files_sha256'].get(k)==h for k,h in files.items()),'synthetic_history_inventory')
    template=read(repo/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/tasks/NEW_00100027_controlled_heterogeneous.json')
    thresholds=read(repo/'semantic_pallet_dataset_v1/statistics/dataset_summary.json')['weight_class_thresholds_kg']
    tasks,samples,classification=generate(pool,registration,template,thresholds)
    rel=relations(tasks,samples,pool,raw,audit,records,groups,forks)
    require(d['registration_digest']==digest(registration) and d['historical_inputs_digest']==digest(history),'synthetic_registration_or_history')
    require(d['tasks']==tasks and read(root/'samples.json')==samples and d['samples_digest']==digest(samples),'synthetic_task_rebuild')
    require(d['classification']==classification==read(root/'static_classification.json') and d['relations']==rel==read(root/'relations.json'),'synthetic_relation_or_static_rebuild')
    from .packaging_runtime import runtime_task
    return {'version':VERSION,'fixture_only':False,'data_identity':d['data_identity'],'tasks':[runtime_task(t) for t in tasks],
      'dataset_root':str(root.resolve().relative_to(repo.resolve())),'relations':rel}
