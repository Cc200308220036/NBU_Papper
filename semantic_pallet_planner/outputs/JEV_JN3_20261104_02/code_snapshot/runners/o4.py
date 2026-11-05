"""O4 A/B offline build, fixed-state evaluation, acceptance and read-only replay.

No online state submission or network calls are implemented here.
"""
import argparse
import copy
import hashlib
import math
from pathlib import Path
import yaml

from ..config import WORKSPACE
from ..o4.common import O4Error,canonical,digest,read,write
from ..o4.dataset import build_data,export_data
from ..o4.observation import validate_observation,rebind
from ..o4.compiler import compile_policy,response_for
from ..o4.executor import evaluate_candidates
from ..o4.evaluator import audit_reference,compare_policies
from ..o4.invalid import execute_invalid_case
from ..o4.client import OfflineClient,compile_with_client

VERSION='o4_ab_offline_v1'
DEFAULT_CONFIG=WORKSPACE/'semantic_pallet_planner/configs/o4_ab_offline.yaml'


def load_ab_config(config=None,seed=None):
    expected=yaml.safe_load(DEFAULT_CONFIG.read_text())
    actual=yaml.safe_load(Path(config or DEFAULT_CONFIG).read_text())
    if not isinstance(actual,dict) or actual.keys()!=expected.keys():raise ValueError('invalid O4 A/B configuration keys')
    if any(actual[k]!=expected[k] for k in expected if k!='seed'):raise ValueError('this version freezes all A/B quotas and boundaries')
    if seed is not None:actual['seed']=seed
    if type(actual['seed']) is not int or actual['seed']<0:raise ValueError('seed must be a nonnegative integer')
    return actual


def equal(a,b):
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,rel_tol=0,abs_tol=1e-9)
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b


def snapshot_existing():
    roots=[WORKSPACE/'semantic_pallet_dataset_v1',WORKSPACE/'semantic_pallet_planner/outputs',WORKSPACE/'semantic_pallet_planner/src']
    return {str(p.relative_to(WORKSPACE)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
            for root in roots for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def check_protected(hashes):
    changed=[]
    for name,expected in hashes.items():
        path=WORKSPACE/name
        if not path.is_file() or hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=expected:changed.append(name)
    return {'status':'PASS' if not changed else 'FAIL','files_checked':len(hashes),'changed':changed}


def transport_checks(req):
    good=response_for(req,compile_policy(req)['policy_ast'])
    bad=copy.deepcopy(good);bad['state_hash']='0'*64
    cases=[('valid',[good],1,True),('repair',[bad,good],2,True),('repair_failed',[bad,bad,good],2,False),
           ('provider_error',[O4Error('provider_error')],1,False),('timeout',[TimeoutError()],1,False)]
    rows=[]
    for name,responses,count,success in cases:
        client=OfflineClient(responses);result=compile_with_client(req,client)
        rows.append({'name':name,'passed':len(client.calls)==count and (result['response'] is not None)==success,'result':result})
    image_req=copy.deepcopy(req);image_req['images']=[{'path':'offline-test-attachment.png','sha256':digest('simulated bytes')}];image_req=rebind(image_req)
    client=OfflineClient([response_for(image_req,good['policy_ast'])]);result=compile_with_client(image_req,client)
    rows.append({'name':'image_attachment_only','passed':result['status'] is None and client.calls[0]['images']==image_req['images'],
                 'fake':True,'formal_rendering_acceptance':'DEFERRED'})
    return rows


def evaluate_data(data):
    gold_rows=[];invalid_rows=[];fixed=[];failures=[]
    for c in data['gold']:
        req=c['request'];response=compile_policy(req);actual=evaluate_candidates(req,response['policy_ast'],c['candidates'])
        reference=audit_reference(req,c['reference_policy'],c['candidates'])
        expected=c['expected_after']
        passed=all(equal(result['evaluations'][0]['after'][k],v) for result in (actual,reference) for k,v in expected.items())
        passed=passed and actual['allowed_ids']==reference['allowed_ids']==c['expected_allowed_ids']
        gold_rows.append({'case_id':c['case_id'],'passed':passed,'response':response,'actual':actual,'reference':reference,'expected':expected})
        if not passed:failures.append(c['case_id'])
    for c in data['invalid']:
        code=None
        try:execute_invalid_case(c,data['gold'][0]['request'])
        except O4Error as exc:code=exc.code
        passed=code==c['expected_code'];invalid_rows.append({**c,'actual_code':code,'passed':passed})
        if not passed:failures.append(c['case_id'])
    for row in data['pairs']:
        req=row['request'];validate_observation(req)
        response=compile_policy(req);ast=response['policy_ast']
        actual=evaluate_candidates(req,ast,row['candidates']);reference=audit_reference(req,row['reference_policy'],row['candidates'])
        semantic=compare_policies(ast,row['reference_policy'],req['placed_objects']+req['available_objects'])
        same=equal(actual,reference)
        passed=same and semantic['semantic_equal'] and semantic['finite_domain_equal']
        fixed.append({'case_id':row['case_id'],'pair_id':row['pair_id'],'anchor_id':row['anchor_id'],'kind':row['kind'],
                      'variant':row['variant'],'passed':passed,'response':response,'semantic':semantic,'actual':actual,'reference':reference})
        if not passed:failures.append(row['case_id'])
    grouped={}
    for row in fixed:grouped.setdefault(row['pair_id'],[]).append(row)
    pair_rows=[]
    for pair_id,rows in sorted(grouped.items()):
        a,b=sorted(rows,key=lambda r:r['variant'])
        different=a['reference']['allowed_ids']!=b['reference']['allowed_ids']
        invariant=a['kind']=='semantic_invariant'
        passed=not invariant or (not different and a['actual']['allowed_ids']==b['actual']['allowed_ids'])
        pair_rows.append({'pair_id':pair_id,'kind':a['kind'],'allowed_set_changed':different,'passed':passed,
                          'first_allowed_id_equal':(a['actual']['allowed_ids'] or [None])[0]==(b['actual']['allowed_ids'] or [None])[0],
                          'action_policy':'first_allowed_only_for_diagnostic; online planner NOT_RUN'})
        if not passed:failures.append(pair_id)
    injection=[]
    case=data['gold'][0];req=case['request']
    for name,ast in [('missing_rule',{'schema_version':'o4_policy_v1','rules':[]}),
                     ('wrong_object',{'schema_version':'o4_policy_v1','rules':[{**copy.deepcopy(case['reference_policy']['rules'][0]),'target':{'object_ids':['top']}}]}),
                     ('wrong_threshold',{'schema_version':'o4_policy_v1','rules':[{'rule_id':'r1','type':'max_top_load','target':{'object_ids':['base']},'priority':20,'overrides':[],'limit':{'constant_kg':1000.}}]})]:
        # Syntactically valid errors must pass the model boundary unchanged.
        client=OfflineClient([response_for(req,ast)]);result=compile_with_client(req,client)
        actual=evaluate_candidates(req,result['response']['policy_ast'],case['candidates'])
        reference=audit_reference(req,case['reference_policy'],case['candidates'])
        comparison=compare_policies(ast,case['reference_policy'],req['placed_objects']+req['available_objects'])
        detected=not comparison['semantic_equal'] and actual['allowed_ids']!=reference['allowed_ids']
        injection.append({'name':name,'passed':detected,'fake':True,'raw_ast_preserved':result['response']['policy_ast']==ast,
                          'actual':actual,'reference':reference,'comparison':comparison})
        if not detected:failures.append(name)
    transport=transport_checks(req)
    if not all(r['passed'] for r in transport):failures.append('offline_transport')
    opportunities=sum(r['allowed_set_changed'] for r in pair_rows if r['kind']!='semantic_invariant')
    coverage={group:sum(c['group']==group for c in data['gold']) for group in ('no_top_load','max_top_load','forbidden_contact','sets','conditions','overrides')}
    counts={'sources':len(data['sources']),'gold':len(gold_rows),'invalid':len(invalid_rows),'fixed_records':len(fixed),
            'pairs':len(pair_rows),'opportunity_pairs':opportunities,'order_task_definitions':len(data['order_tasks']),
            'online_episodes_executed':0,'remote_calls':0}
    if list(coverage.values())!=[6]*6 or counts['sources']!=12 or counts['fixed_records']!=144 or counts['order_task_definitions']!=72 or opportunities<6:
        failures.append('data_coverage')
    return {'status':'PASS' if not failures else 'FAIL','counts':counts,'coverage':coverage,'failures':failures,
            'gold':gold_rows,'invalid':invalid_rows,'fixed':fixed,'pairs':pair_rows,'injections':injection,'transport':transport}


def artifact_hashes(root):
    return {str(p.relative_to(root)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name!='delivery_manifest.json'}


def _code_hashes():
    source=WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    paths=[*sorted((source/'o4').glob('*.py')),*sorted((source/'schemas').glob('o4_*.json')),source/'runners/o4.py',DEFAULT_CONFIG]
    return {str(p.relative_to(WORKSPACE)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in paths}


def run(output,*,dataset=None,seed=None,protection_before=None,config=None):
    cfg=load_ab_config(config,seed);seed=cfg['seed']
    root=Path(output).resolve()
    if root.exists():raise FileExistsError('choose a new output directory')
    dataset=Path(dataset or WORKSPACE/'semantic_pallet_dataset_v1').resolve()
    if root==dataset or dataset in root.parents:raise ValueError('output may not modify source dataset')
    protected=read(protection_before) if protection_before else snapshot_existing()
    initial=check_protected(protected)
    if initial['status']!='PASS':raise ValueError('protected files already changed: '+str(initial['changed'][:3]))
    data=build_data(dataset,seed)
    repeat=build_data(dataset,seed)
    deterministic=digest(data)==digest(repeat)
    root.mkdir(parents=True)
    export_data(root,data)
    result=evaluate_data(data)
    protection=check_protected(protected)
    write(root/'audit/protected.before.json',protected);write(root/'audit/protected.after.json',protection)
    manifest={'version':VERSION,'seed':seed,'dataset_root':str(dataset),'source_sha256':_code_hashes(),
              'data_digest':digest(data),'role':'development','remote_calls':0,'human_review_status':'PENDING_HUMAN_REVIEW'}
    write(root/'manifest.json',manifest)
    write(root/'config.snapshot.json',cfg)
    for name in ('gold','invalid','fixed','pairs','injections','transport'):
        write(root/f'metrics/{name}.json',result[name])
    write(root/'semantic_acceptance.json',{k:result[k] for k in ('status','counts','coverage','failures')})
    statuses={k:'PASS' for k in ('A1','A2','A3','A4','B1','B2','B3','B4','B5','B6')}
    statuses.update(A5='DEFERRED_FORMAL_IMAGES',A6='AUTOMATED_PASS_HUMAN_REVIEW_PENDING',C='NOT_RUN',D='NOT_RUN',F='NOT_RUN')
    if result['status']!='PASS':
        for k in statuses:
            if statuses[k]=='PASS':statuses[k]='FAIL'
    if not deterministic:statuses['A2']='FAIL'
    if protection['status']!='PASS':statuses['protected_files']='FAIL'
    audit={'status':'PASS' if deterministic and protection['status']=='PASS' else 'FAIL',
           'deterministic_regeneration':deterministic,'protected_files':protection,'counts':result['counts'],
           'public_schema_valid':all(bool(validate_observation(r['request'])) for r in data['pairs']),
           'public_serialization':'closed schema from arrived-state whitelist','unseen_test_evidence':False}
    write(root/'data_audit.json',audit)
    acceptance={'status':'PASS' if result['status']=='PASS' and audit['status']=='PASS' else 'FAIL',
                'scope':'O4_A_B_OFFLINE_CORE','full_o4_status':'INCOMPLETE','criteria':statuses,
                'evidence':{'A1':'data_audit.json','A2':'data_audit.json','A3':'public/ + closed observation schema',
                'A4':'plan.json + split_manifest.json','A5':'formal images deferred','A6':'private/data.json gold expected values; human review pending',
                'B1':'metrics/gold.json','B2':'metrics/invalid.json','B3':'metrics/fixed.json',
                'B4':'metrics/gold.json','B5':'metrics/transport.json','B6':'metrics/injections.json'},
                'remote_calls':0,'counts':result['counts'],'failures':result['failures']}
    write(root/'acceptance_report.json',acceptance)
    write(root/'replay_report.json',{'status':result['status'],'fixed_records':len(result['fixed']),
                                     'gold_records':len(result['gold']),'recomputed_from_saved_data':True})
    lines=['# O4 A/B offline core', '', f"Scope status: {acceptance['status']}; full O4: INCOMPLETE.",
           '',f"Counts: {canonical(result['counts'])}", '',
           'A5 formal images deferred; A6 human review pending; C/D/F NOT_RUN. No API calls or full-order episodes.',
           '', 'Read private/data.json for independently declared references and gold expectations; public/ contains model-visible observations only.',
           'metrics/ stores every compilation, candidate trace, pair and injected error; no failed denominator is removed.',
           '', 'Replay: python -m semantic_pallet_planner.runners.o4 replay --output <this-directory>']
    (root/'README.md').write_text('\n'.join(lines)+'\n')
    write(root/'delivery_manifest.json',{'files':artifact_hashes(root)})
    checked=replay(root)
    if checked['status']!='PASS':raise ValueError('saved delivery fails replay: '+str(checked))
    return acceptance


def replay(output):
    root=Path(output).resolve();failures=[]
    expected=read(root/'delivery_manifest.json')['files'];actual=artifact_hashes(root)
    if expected!=actual:return {'status':'FAIL','failures':['delivery hashes or file set changed']}
    manifest=read(root/'manifest.json')
    if manifest['source_sha256']!=_code_hashes():return {'status':'FAIL','failures':['source drift']}
    data=read(root/'private/data.json')
    if digest(data)!=manifest['data_digest']:failures.append('data digest')
    result=evaluate_data(data)
    for name in ('gold','invalid','fixed','pairs','injections','transport'):
        if not equal(read(root/f'metrics/{name}.json'),result[name]):failures.append(name+' recomputation')
    if not equal(read(root/'semantic_acceptance.json'),{k:result[k] for k in ('status','counts','coverage','failures')}):failures.append('summary recomputation')
    for row in data['pairs']:
        if read(root/'public'/f"{row['case_id']}.json")!=row['request']:failures.append(row['case_id']+' public mismatch')
    protected=check_protected(read(root/'audit/protected.before.json'))
    if protected['status']!='PASS':failures.append('protected files changed')
    if result['status']!='PASS':failures+=result['failures']
    acceptance=read(root/'acceptance_report.json')
    if acceptance['counts']!=result['counts'] or acceptance['status']!='PASS':failures.append('acceptance mismatch')
    return {'status':'FAIL' if failures else 'PASS','failures':failures,'counts':result['counts'],'read_only':True}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','validate','evaluate-fixed','acceptance','replay'])
    p.add_argument('--output',required=True);p.add_argument('--dataset');p.add_argument('--seed',type=int)
    p.add_argument('--config',default=str(DEFAULT_CONFIG))
    p.add_argument('--protection-before')
    args=p.parse_args(argv)
    if args.command=='replay':result=replay(args.output)
    elif args.command=='validate':
        root=Path(args.output);data=read(root/'private/data.json')
        for row in data['pairs']:validate_observation(row['request'])
        result={'status':'PASS','fixed_records':len(data['pairs']),'read_only':True}
    elif args.command=='evaluate-fixed':result={k:v for k,v in evaluate_data(read(Path(args.output)/'private/data.json')).items() if k in ('status','counts','coverage','failures')}
    else:result=run(args.output,dataset=args.dataset,seed=args.seed,protection_before=args.protection_before,config=args.config)
    print(canonical(result))
    if result['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
