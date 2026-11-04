"""Deterministic O4 development derivation; no source dataset writes."""
import copy
from collections import defaultdict
from pathlib import Path
from ..repository import DatasetRepository
from .common import digest,read,write
from .observation import derive_attributes,build_observation,rebind
from .fixtures import gold_cases,task_policy,render_policy,policy,rule
from .invalid import invalid_cases


def _variants(req,candidates,anchor_id):
    """Six public records / three pairs; reference policies kept separately."""
    result=[]
    base=copy.deepcopy(req)
    for o in base['placed_objects']+base['available_objects']:
        o['labels']={'no_top_load':False,'max_top_load_kg':100000.}
    attribute_policy=task_policy(1)
    records=[]
    for variant in range(2):
        r=copy.deepcopy(base)
        if variant:
            for o in r['placed_objects']:o['labels']['no_top_load']=True
        records.append((r,attribute_policy))
    records.extend([(copy.deepcopy(base),policy([rule(limit=0)])),(copy.deepcopy(base),policy([rule(limit=100000)]))])
    records.extend([(copy.deepcopy(req),task_policy(5)),(copy.deepcopy(req),task_policy(5))])
    for i,(r,ast) in enumerate(records):
        r['request_id']=f'{anchor_id}_{i}'
        r['instruction_text']=render_policy(ast,paraphrase=i==5)
        r=rebind(r)
        result.append({'case_id':r['request_id'],'anchor_id':anchor_id,'pair_id':f'{anchor_id}_P{i//2}',
                       'kind':('attribute_change','business_change','semantic_invariant')[i//2],
                       'variant':i%2,'request':r,'reference_policy':copy.deepcopy(ast),'candidates':copy.deepcopy(candidates)})
    return result


def build_data(dataset_root,seed=20261021):
    repo=DatasetRepository(dataset_root)
    scenarios=sorted(repo.list_scenarios('train'))
    selected=[];keys=set()
    for sid in scenarios:
        record=read(repo.root/'annotations/ground_truth_rules'/f'{sid}.json')
        source=str(record.get('source_order_key',record['source_order_id']))
        if source not in keys:selected.append((sid,source));keys.add(source)
        if len(selected)==12:break
    if len(selected)!=12:raise ValueError('need twelve independent train sources')
    grouped=defaultdict(list)
    for cid in sorted(repo.list_cases('train')):
        c=repo.get_decision_case(cid);grouped[c['base_scenario_id']].append(c)
    side_tables={};anchors=[];order_tasks=[];source_manifest=[]
    for si,(sid,source) in enumerate(selected):
        scenario=repo.get_scenario(sid)
        attrs={i['item_id']:derive_attributes(i,sid,seed) for i in scenario['items']}
        side_tables[sid]={'attribute_source':'synthetic','seed':seed,'source_scenario_sha256':digest(scenario),'objects':attrs}
        source_manifest.append({'scenario_id':sid,'source_order_key':source,'source_split':'train','role':'development'})
        cases=grouped[sid][:2]
        if len(cases)!=2:raise ValueError(f'{sid}: fewer than two fixed states')
        for ci,c in enumerate(cases):
            identifier=f'O4_ANCHOR_{si*2+ci+1:02d}'
            state={'request_id':identifier,'container':scenario['container'],
                   'placed_items':c['placed_items'],'available_items':c['available_items']}
            req=build_observation(state,attrs,render_policy(task_policy(5)))
            candidates=repo.get_candidate_set(c['candidate_set_id'])['candidates']
            # ID mapping is private to the fixed-state evaluation, not model input.
            anchors.append({'anchor_id':identifier,'source_scenario':sid,'source_case':c['decision_case_id'],
                            'constructed':False,'request':req,'candidates':candidates})
        for configuration in range(6):
            order_tasks.append({'task_id':f'O4_ORDER_{si:02d}_{configuration}','scenario_id':sid,
                'source_order_key':source,'configuration':configuration,'instruction_text':render_policy(task_policy(configuration)),
                'reference_policy':task_policy(configuration),'role':'development','execution_status':'NOT_RUN',
                'planned_items':len(scenario['arrival_order'])})
    # Check opportunity before any compiler/model call, using independent reference only.
    from .evaluator import audit_reference
    def opportunities(anchor):
        rows=_variants(anchor['request'],anchor['candidates'],anchor['anchor_id'])
        allowed=[audit_reference(r['request'],r['reference_policy'],r['candidates'])['allowed_ids'] for r in rows]
        return sum(allowed[i]!=allowed[i+1] for i in (0,2))
    replacements=[]
    total=sum(opportunities(a) for a in anchors)
    if total<6:
        for index,anchor in enumerate(anchors):
            if total>=6:break
            if opportunities(anchor):continue
            gold=gold_cases()[0]
            replacement={**anchor,'constructed':True,'request':copy.deepcopy(gold['request']),
                         'candidates':copy.deepcopy(gold['candidates'])}
            total+=opportunities(replacement)
            replacements.append({'anchor_id':anchor['anchor_id'],'original_source_case':anchor['source_case'],
                                 'reason':'reference opportunity quota; independent of compiler output',
                                 'replacement_fixture':gold['case_id']})
            anchors[index]=replacement
    pairs=[r for a in anchors for r in _variants(a['request'],a['candidates'],a['anchor_id'])]
    return {'seed':seed,'sources':source_manifest,'attributes':side_tables,'anchors':anchors,'pairs':pairs,
            'order_tasks':order_tasks,'gold':gold_cases(),'invalid':invalid_cases(),'replacements':replacements,
            'reference_opportunity_pairs':total,
            'split_manifest':{'role':'development','source_orders':12,'anchors':24,'dependent_records':144,
                              'unseen_test_evidence':False,'human_review_status':'PENDING_HUMAN_REVIEW'}}


def export_data(root,data):
    root=Path(root)
    write(root/'private/data.json',data)
    write(root/'private/attributes.json',data['attributes'])
    write(root/'private/order_tasks.json',data['order_tasks'])
    write(root/'private/anchors.json',data['anchors'])
    write(root/'split_manifest.json',{'sources':data['sources'],**data['split_manifest'],'replacements':data['replacements']})
    write(root/'plan.json',{'fixed_records':144,'gold_cases':36,'invalid_cases':24,'order_definitions':72,
                          'order_executions':0,'remote_calls':0,'seed':data['seed']})
    for row in data['pairs']:
        write(root/'public'/f"{row['case_id']}.json",row['request'])
    for row in data['gold']:
        write(root/'public'/f"GOLD_{row['case_id']}.json",row['request'])
