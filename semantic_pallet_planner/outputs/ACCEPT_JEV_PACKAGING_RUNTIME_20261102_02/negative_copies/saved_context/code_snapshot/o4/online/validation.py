"""C fixed-state diagnostics, legacy equivalence and independent safety checks."""
import copy
from ..common import digest
from ..observation import rebind
from ..compiler import compile_policy
from ..fixtures import render_policy
from ..evaluator import audit_reference
from .planner_adapter import labeled_candidates,select_layout,soft_quality,select_and_commit
from .cases import opportunity_cases,run_opportunities,diagnostic_scenario
from .episode import episode
from ...evaluation.replay_values_v2 import replay_values_equal


def evaluate_fixed(data):
    rows=[];grouped={}
    for row in data['pairs']:
        req=row['request'];public,_=labeled_candidates(row['candidates'])
        response=compile_policy(req)
        label,trace,actual=select_layout(req,response['policy_ast'],public)
        reference=audit_reference(req,row['reference_policy'],public)
        passed=replay_values_equal(actual,reference)
        item={'case_id':row['case_id'],'pair_id':row['pair_id'],'kind':row['kind'],'variant':row['variant'],
              'request':req,'public_candidates':public,'response':response,'selected_label':label,
              'selected_pose':next((c['pose'] for c in public if c['candidate_id']==label),None),
              'trace':trace,'method_evaluation':actual,'reference_evaluation':reference,'passed':passed}
        rows.append(item);grouped.setdefault(row['pair_id'],[]).append(item)
    pairs=[]
    for identifier,items in sorted(grouped.items()):
        a,b=sorted(items,key=lambda r:r['variant'])
        changed=a['reference_evaluation']['allowed_ids']!=b['reference_evaluation']['allowed_ids']
        same_action=a['selected_label']==b['selected_label'] and a['selected_pose']==b['selected_pose']
        invariant=a['kind']=='semantic_invariant'
        pairs.append({'pair_id':identifier,'kind':a['kind'],'allowed_set_changed':changed,
                      'action_changed':not same_action,'passed':not invariant or (not changed and same_action)})
    return {'records':rows,'pairs':pairs,'passed':all(r['passed'] for r in rows+pairs),
            'opportunity_pairs':sum(r['allowed_set_changed'] for r in pairs),
            'action_change_pairs':sum(r['action_changed'] for r in pairs)}


def invariance_checks():
    c=opportunity_cases()[3]['variants'][0]
    req=c['request'];public,_=labeled_candidates(c['raw_candidates'])
    response=compile_policy(req);selected,trace,_=select_layout(req,response['policy_ast'],public)
    expected=next(x['pose'] for x in public if x['candidate_id']==selected)
    checks=[]
    # Reverse input/candidate storage order; explicit stable pose ordering restores labels.
    shuffled=copy.deepcopy(c['raw_candidates']);shuffled.reverse()
    shuffled_public,_=labeled_candidates(shuffled)
    label,other,_=select_layout(req,response['policy_ast'],shuffled_public)
    checks.append({'name':'candidate_storage_order','passed':label==selected and trace==other})
    renamed=copy.deepcopy(req);ids={o['object_id']:'renamed_'+o['object_id'] for k in ('placed_objects','available_objects') for o in renamed[k]}
    for k in ('placed_objects','available_objects'):
        for o in renamed[k]:o['object_id']=ids[o['object_id']]
    renamed=rebind(renamed);new_candidates=copy.deepcopy(public)
    for o in new_candidates:o['pick_item_id']=ids[o['pick_item_id']]
    ast=compile_policy(renamed)['policy_ast'];label,_,_=select_layout(renamed,ast,new_candidates)
    checks.append({'name':'object_id_renaming','passed':next(x['pose'] for x in new_candidates if x['candidate_id']==label)==expected})
    # Explicit-ID rules must rename the instruction references as well as facts.
    specific=opportunity_cases()[5]['variants'][1]
    old_req=specific['request'];old_public,_=labeled_candidates(specific['raw_candidates'])
    old_ast=compile_policy(old_req)['policy_ast']
    old_label,_,old_evaluation=select_layout(old_req,old_ast,old_public)
    id_map={o['object_id']:'mapped_'+o['object_id'] for k in ('placed_objects','available_objects') for o in old_req[k]}
    changed=copy.deepcopy(old_req);changed_ast=copy.deepcopy(old_ast)
    for k in ('placed_objects','available_objects'):
        for o in changed[k]:o['object_id']=id_map[o['object_id']]
    def rename_selector(expr):
        for key,value in expr.items():
            if key=='object_ids':expr[key]=[id_map[i] for i in value]
            elif key in ('and','or'):
                for child in value:rename_selector(child)
            elif key=='not':rename_selector(value)
    for r in changed_ast['rules']:
        for key in ('target','left','right'):
            if key in r:rename_selector(r[key])
    changed['instruction_text']=render_policy(changed_ast);changed=rebind(changed)
    changed_public=copy.deepcopy(old_public)
    for c in changed_public:c['pick_item_id']=id_map[c['pick_item_id']]
    new_label,_,new_evaluation=select_layout(changed,compile_policy(changed)['policy_ast'],changed_public)
    checks.append({'name':'explicit_id_instruction_mapping','passed':old_label==new_label and
                   old_evaluation['allowed_ids']==new_evaluation['allowed_ids']})
    images=copy.deepcopy(req);images['images']=[{'path':'fake-1.png','sha256':digest('fake-1')},{'path':'fake-2.png','sha256':digest('fake-2')}]
    a=rebind(images);images['images'].reverse();b=rebind(images)
    labels=[select_layout(r,compile_policy(r)['policy_ast'],public)[0] for r in (a,b)]
    checks.append({'name':'image_metadata_order_only','passed':labels[0]==labels[1]==selected,
                   'formal_images':'DEFERRED; no pixels or real visual service used'})
    return checks


def legacy_equivalence(data):
    """Identical geometry/soft-budget logic when both hard pools are unrestricted."""
    from ...selectors.layout_preserving_v2 import select_layout as legacy
    from ...o4.fixtures import policy
    controls=[]
    old_policy={'schema_version':'pallet_policy_v2_pilot','hard_constraints':[],
                'soft_priorities':[{'priority':1,'metric':'heavy_low'},{'priority':2,'metric':'heavy_center'}]}
    for anchor in data['anchors']:
        req=anchor['request'];public,_=labeled_candidates(anchor['candidates'])
        def old_object(o):
            result=copy.deepcopy(o);result['item_id']=result.pop('object_id')
            result['top_load_limit_kg_synthetic']=result['physical_top_load_limit_kg']
            result['product_category']='electronics' if o['cargo_category']=='electronics' else 'general'
            return result
        old_req={'container':req['container'],'placed_items':[old_object(o) for o in req['placed_objects']],
                 'available_items':[old_object(o) for o in req['available_objects']],'candidates':public}
        label,trace,_=select_layout(req,policy([]),public)
        old_label,old_trace=legacy(old_req,old_policy,'relaxed_geometry')
        controls.append({'anchor_id':anchor['anchor_id'],'selected':label,'legacy_selected':old_label,
                         'passed':label==old_label and trace['anchor_label']==old_trace['baseline_label'] and
                                  trace['eligible_labels']==old_trace.get('eligible_labels',[])})
    return controls


def diagnostics(config):
    scenario,attributes,task=diagnostic_scenario()
    rows=[]
    for fault in (None,'drop_rules','invalid_ast','invalid_binding','provider_error'):
        summary,events=episode(scenario,attributes,task,'public_parser',config,fault=fault)
        expected={None:'no_compiled_business_candidate','drop_rules':'all_items_placed',
                  'invalid_ast':'invalid_ast','invalid_binding':'invalid_binding','provider_error':'provider_error'}[fault]
        passed=summary['termination_reason']==expected
        if fault=='drop_rules':passed=passed and summary['final_business_violation_count']>0 and summary['completed'] and summary['physical_violations']==0
        rows.append({'case_id':fault or 'correct_policy','fault':fault,'passed':passed,'summary':summary,'events':events})
    limited=copy.deepcopy(scenario);limited['container']['max_height_mm']=100
    summary,events=episode(limited,attributes,task,'public_parser',config,fault='drop_rules')
    rows.append({'case_id':'physical_no_candidate','fault':'drop_rules','passed':summary['termination_reason']=='no_physical_candidate',
                 'summary':summary,'events':events})
    c=opportunity_cases()[0]['variants'][0]
    req=copy.deepcopy(c['request']);req['instruction_text']='无额外业务硬约束。';req=rebind(req)
    raw=[copy.deepcopy(c['raw_candidates'][0])];raw[0]['pose']['x_mm']=1000.
    before=digest(c['state'])
    result,placed=select_and_commit(c['state'],c['attributes'],req,raw,compile_policy(req))
    rows.append({'case_id':'physical_rejection','fault':'invalid_pose',
                 'passed':result['status']=='physical_rejection' and bool(result['physical_errors']) and
                          placed==c['state']['placed_items'] and digest(c['state'])==before,
                 'result':result,'after_placed':placed})
    return rows
