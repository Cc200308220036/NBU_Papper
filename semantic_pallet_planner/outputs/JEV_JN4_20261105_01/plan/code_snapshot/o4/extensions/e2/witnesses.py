"""Manual coordinates and independent checks, never a candidate-generator oracle."""
import math
from ...buffer.buffer_state import initial,receive,place,physical
from ....evaluation.geometry_oracle import check_candidate
from .protocol import observation
from .reference import state as reference_state


def verify(task, *, physical_only=False):
    positions=task['manual_witness_xyz']
    if physical_only:positions=[(-300,-200,0),(0,0,0),(300,-200,0),(300,200,0)]
    if not positions:return {'task_id':task['task_id'],'kind':'analytic_negative','proof':task['proof'],'passed':True}
    s=initial(task['container'],1);steps=[]
    for obj,(x,y,z) in zip(task['items'],positions):
        s=receive(s,obj,task['attributes'][obj['item_id']]);size=[obj['dimensions_mm'][k] for k in ('length','width','height')]
        volume=sum(math.prod(o['oriented_size_mm']) for o in s['placed_items'])+math.prod(size)
        c={'candidate_id':'MANUAL_'+obj['item_id'],'pick_item_id':obj['item_id'],'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':0},
           'oriented_size_mm':size,'support':{'support_item_ids':[],'support_ratio':1.},
           'resulting_geometry':{'max_height_mm':max([z+size[2],*[o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in s['placed_items']]]),
                                 'volume_utilization':volume/(task['container']['length_mm']*task['container']['width_mm']*task['container']['max_height_mm'])}}
        errors=check_candidate(physical(s,obj['item_id']),{'container':task['container']},c)
        if errors:return {'task_id':task['task_id'],'passed':False,'physical_errors':errors}
        s=place(s,c);q=observation(s,task['instruction_text'],task['regions'])
        ref=reference_state(q['placed_objects'],task['reference_policy'],task['regions'],pending_objects=q['available_objects'])
        if not physical_only and ref['violations']:return {'task_id':task['task_id'],'passed':False,'business_violations':ref['violations']}
        steps.append({'candidate':c,'physical_errors':errors,'reference_violations':ref['violations']})
    certificate=None
    if physical_only:
        relations=[r for r in task['reference_policy']['rules'] if r['type']=='relative_position']
        widths=[o['dimensions_mm']['length'] for o in task['items'] if task['attributes'][o['item_id']]['cargo_category'] in ('food','household_cleaner')]
        if len(relations)==2:
            certificate={'kind':'opposing_x_separation','positive_width_sum_mm':sum(widths),'maximum_tolerance_slack_mm':2e-6,
                         'contradiction':sum(widths)>2e-6}
        else:
            required=sum(widths)+relations[0]['min_gap_mm']
            certificate={'kind':'gap_exceeds_pallet','minimum_required_extent_mm':required,'container_extent_mm':task['container']['length_mm'],
                         'contradiction':required>task['container']['length_mm']+3e-6}
    return {'task_id':task['task_id'],'kind':'physical_only' if physical_only else 'legal_manual_path','steps':steps,'analytic_certificate':certificate,
            'passed':s['placed_count']==len(task['items']) and (bool(steps[-1]['reference_violations']) and certificate['contradiction'] if physical_only else True),
            'proof':task['proof']}


def all_witnesses(tasks):
    return [verify(t,physical_only=t['role']=='negative') for t in tasks]
