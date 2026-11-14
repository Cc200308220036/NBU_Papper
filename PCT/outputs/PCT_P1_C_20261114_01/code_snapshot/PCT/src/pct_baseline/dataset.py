"""Authenticate frozen parent bytes, then derive only the declared runtime projection.

No planner import: original parent schema acceptance is inherited exclusively from
P0-authenticated exact bytes. Full runtime Schema validation remains a separate
check requiring jsonschema; it is never silently claimed by these checks.
"""
import copy
from pathlib import Path
from .contracts import require, read, digest, sha, write_new
from .protocol import validate_value

P0 = 'PCT/outputs/PCT_P0_CONTRACT_20261114_01'
AUDIT_SHA = '81d1a2048bfb587daaed6a9129793881c5068bac81c2de76867b8ca1004ae450'
IDENTITY_SHA = 'd49618a326c560ca784214f7f488ca078a3ec2492ab7b69111556f5c8278d51f'
PACK = 'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02'
SYN = 'semantic_pallet_planner/outputs/JEV_JN4_SYNTH_20261105_01/data'
INSTRUCTION = 'Packaging/load protocol v1: use current geometry, mass, support eligibility and capacity only.'
FIELDS = ('item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic','fragile','weight_class')


def authenticate(repo):
    repo=Path(repo)
    require(sha(repo/P0/'data_audit.json') == AUDIT_SHA, 'P0_AUDIT_IDENTITY_DRIFT')
    require(sha(repo/P0/'identity.json') == IDENTITY_SHA, 'P0_IDENTITY_DRIFT')
    audit=read(repo/P0/'data_audit.json'); identity=read(repo/P0/'identity.json')
    # Includes both manifests, handoffs, splits, source manifests and provenance.
    for path, expected in identity['files'].items():
        if path.startswith((PACK+'/', SYN+'/')) and '/tasks/' not in path:
            require(sha(repo/path)==expected, 'DATA_IDENTITY_DRIFT:'+path)
    parents=[]
    for root, expected in zip((PACK,SYN), identity['parent_data']):
        manifest=read(repo/root/('manifest.json' if root==PACK else 'dataset.json'))
        require(manifest['data_identity']==expected,'DATA_IDENTITY_DRIFT')
        inventory=read(repo/root/'delivery_manifest.json')
        actual={str(p.relative_to(repo/root)):sha(p) for p in (repo/root).rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
        require(actual==inventory,'PARENT_INVENTORY_DRIFT')
        if root==PACK:
            by_id={row['task_id']:read(repo/row['path']) for row in audit['tasks'] if row['path'].startswith(PACK+'/')}
            task_order=[by_id[k] for k in audit['packaging_archive_order']]
            require(digest({'config':read(repo/root/'config.snapshot.json'),'tasks':task_order,'split':read(repo/root/'split_manifest.json')})==expected,'DATA_IDENTITY_DRIFT')
        else:
            require(digest({k:v for k,v in manifest.items() if k!='data_identity'})==expected,'DATA_IDENTITY_DRIFT')
        parents.append({'root':root,'data_identity':expected,'manifest_sha256':sha(repo/root/('manifest.json' if root==PACK else 'dataset.json'))})
    rows=[]
    for row in audit['tasks']:
        parent=read(repo/row['path'])
        require(sha(repo/row['path'])==row['sha256'] and digest(parent)==row['digest'],'TASK_IDENTITY_DRIFT')
        check_order(parent)
        if row['path'].startswith(SYN+'/'):
            require(parent in read(repo/SYN/'dataset.json')['tasks'],'TASK_IDENTITY_DRIFT')
        rows.append((row,parent,identity['parent_data'][0 if row['path'].startswith(PACK+'/') else 1]))
    require(len(rows)==22,'PARENT_TASK_SET_DRIFT')
    return parents,rows


def check_order(parent):
    ids=[i['item_id'] for i in parent['items']]
    require(bool(ids),'EMPTY_TASK')
    require(len(ids)==len(set(ids)),'DUPLICATE_ITEM')
    require(ids==parent['arrival_order'],'ARRIVAL_ORDER_MISMATCH')


def project(parent):
    check_order(parent)
    items=[];attributes={}
    for original in parent['items']:
        item={k:copy.deepcopy(original[k]) for k in FIELDS}
        require(original['max_top_load_kg']==item['top_load_limit_kg_synthetic'] and original['effective_top_permission_kg']==(item['top_load_limit_kg_synthetic'] if item['stackable'] else 0),'PHYSICAL_FIELD_DRIFT')
        item['product_category']='general';items.append(item)
        attributes[item['item_id']]={'object_id':item['item_id'],'cargo_category':'general','packaging':{'reinforced':False},
            'labels':{'no_top_load':not item['stackable'],'max_top_load_kg':item['top_load_limit_kg_synthetic']},
            'physical_top_load_limit_kg':item['top_load_limit_kg_synthetic']}
    return items,attributes


def derive(row,parent,parent_identity,execution):
    expected_identity=('9cf6d039543df402d04d406f45cd8cff00ee0a5ab49540190662e7f0d18f21de'
        if row['path'].startswith(PACK+'/') else 'b13d9c6ea93b24e6f76032284560913cd26ed4e09315650552ceefd8c20d86e6')
    require(parent_identity==expected_identity,'DATA_IDENTITY_DRIFT')
    require(digest(parent)==row['digest'] and parent['task_id']==row['task_id'],'TASK_IDENTITY_DRIFT')
    items,attributes=project(parent)
    result={'version':'pct_b1_task_v1','task_id':parent['task_id'],
        'parent_data_identity':parent_identity,'parent_task_sha256':row['sha256'],'parent_task_digest':row['digest'],
        'execution_spec_digest':digest(execution),'parent_partition':parent['partition'],'partition':parent['partition'],
        'source_component_id':row['conservative_component'],'exposure_status':row['purpose'],
        'layer':'synthetic_combo' if parent['layer']=='synthetic_combo' else parent['layer'],'parent_layer':parent['layer'],
        'container':copy.deepcopy(parent['container']),'arrival_order':list(parent['arrival_order']),
        'items':items,'attributes':attributes,'regions':[],
        'reference_policy':{'version':'jev_packaging_load_dataset_v1','rules':[]},'instruction_text':INSTRUCTION,
        'buffer_capacity':1,'candidate_limits':copy.deepcopy(parent['candidate_limits'])}
    if row['path'].startswith(SYN+'/'):result['layer']='synthetic_combo'
    result['derived_task_digest']=digest(result)
    validate_value('task_b1_v1',result)
    return result


def execution_spec(repo,spec_path):
    repo=Path(repo);spec=read(spec_path)
    require(set(spec)=={'version','execution_spec'},'DATA_SPEC_FIELDS')
    require(spec['version']=='pct_b1_data_spec_v1','DATA_SPEC_VERSION')
    execution=spec['execution_spec']
    expected={'version':'pct_b1_execution_spec_v1','buffer_capacity':1,'yaw_deg':[0,90],'per_box':16,'joint':48,
        'candidate_manifest_digest':digest(read(repo/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/configs/generator_v1.json')),
        'display_order_seed':20261102,'monitor_algorithm':'pct_exact_pose_network_v3'}
    require(execution==expected,'EXECUTION_SPEC_DRIFT')
    return execution


def prepare(repo,spec_path,output):
    repo=Path(repo);execution=execution_spec(repo,spec_path)
    parents,rows=authenticate(repo)
    tasks=[derive(row,parent,identity,execution) for row,parent,identity in rows]
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    (output/'tasks').mkdir()
    manifest={'version':'pct_b1_dataset_v1','parents':parents,'execution_spec':execution,'tasks':[],'execution_admitted':False}
    for task in tasks:
        path='tasks/'+task['task_id']+'.json';write_new(output/path,task)
        manifest['tasks'].append({'path':path,'sha256':sha(output/path),'digest':digest(task),'parent_task_sha256':task['parent_task_sha256']})
    manifest['data_identity']=digest(manifest);write_new(output/'dataset.json',manifest)
    return {'status':'DATA_AUTHENTICATED_DERIVED','tasks':len(tasks),'items':sum(len(t['items']) for t in tasks),'data_identity':manifest['data_identity'],'schema_validation':'NOT_RUN','execution_admitted':False}


def validate_data(repo,dataset,*,full_schema=False):
    parents,rows=authenticate(repo);dataset=Path(dataset);manifest=read(dataset/'dataset.json')
    require(set(manifest)=={'version','parents','execution_spec','tasks','execution_admitted','data_identity'},'DATASET_FIELDS')
    require(manifest['version']=='pct_b1_dataset_v1' and manifest['execution_admitted'] is False,'DATASET_VERSION')
    require(manifest['data_identity']==digest({k:v for k,v in manifest.items() if k!='data_identity'}),'DERIVED_DATA_IDENTITY_DRIFT')
    require(manifest['parents']==parents and len(manifest['tasks'])==len(rows),'PARENT_DATA_IDENTITY_DRIFT')
    spec=execution_spec(repo,Path(repo)/'PCT/configs/data_b1_v1.json')
    require(manifest['execution_spec']==spec,'EXECUTION_SPEC_DRIFT')
    if full_schema:
        from .contracts import validate
        validate('execution_spec_b1_v1',spec)
    expected_tasks=[derive(row,parent,identity,spec) for row,parent,identity in rows]
    for entry,expected in zip(manifest['tasks'],expected_tasks):
        require(entry['path']=='tasks/'+expected['task_id']+'.json','TASK_PATH_DRIFT')
        task=read(dataset/entry['path'])
        require(sha(dataset/entry['path'])==entry['sha256'] and digest(task)==entry['digest'],'DERIVED_TASK_IDENTITY_DRIFT')
        require(entry['parent_task_sha256']==expected['parent_task_sha256'],'TASK_IDENTITY_DRIFT')
        require(task==expected,'PHYSICAL_FIELD_OR_DERIVATION_DRIFT')
        if full_schema:
            from .contracts import validate
            validate('task_b1_v1',task)
    require({str(p.relative_to(dataset)) for p in dataset.rglob('*') if p.is_file()}=={'dataset.json'}|{e['path'] for e in manifest['tasks']},'DATASET_INVENTORY_DRIFT')
    return {'status':'PASS','tasks':len(rows),'items':sum(len(t['items']) for t in expected_tasks),'schema_validation':'PASS' if full_schema else 'NOT_RUN','execution_admitted':False}
