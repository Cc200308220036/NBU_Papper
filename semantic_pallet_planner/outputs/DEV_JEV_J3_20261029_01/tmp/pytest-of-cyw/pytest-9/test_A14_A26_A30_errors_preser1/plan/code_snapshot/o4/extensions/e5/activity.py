"""Post-hoc rule-instance applicability, separate from symbolic AST correctness."""
from ...evaluator import _accept
from ...observation import public_object


def task_presence(task):
    objects=[public_object(i,task['attributes'][i['item_id']]) for i in task['items']]
    rows=[]
    for r in task['reference_policy']['rules']:
        if r['type'] in ('relative_position','forbidden_contact'):
            a,b=('subject','reference') if r['type']=='relative_position' else ('left','right')
            first=[o['object_id'] for o in objects if _accept(o,r[a])];second=[o['object_id'] for o in objects if _accept(o,r[b])]
            count=sum(x!=y for x in first for y in second)
        else:count=sum(_accept(o,r['target']) for o in objects)
        rows.append({'rule_id':r['rule_id'],'type':r['type'],'has_targets_in_planned_order':count>0,'target_or_pair_count':count})
    return rows


def activity(ast,reference_after):
    rows=[]
    for r in ast['rules']:
        rid=r['rule_id'];targets=reference_after['applicable_objects'].get(rid,[]);deferred=False
        if r['type']=='relative_position':
            state=reference_after['relation_status'][rid];checked=state['checked_pairs'];deferred=state['status']=='deferred';status=state['status']
        elif r['type']=='forbidden_contact':
            checked=len({tuple(sorted((a,b))) for a in targets['left'] for b in targets['right'] if a!=b});status='checked' if checked else 'no_placed_pair'
        elif r['type']=='inside_region':checked=len(targets);status='checked' if checked else 'no_placed_target'
        else:
            checked=sum(rid in rules for rules in reference_after['active_rules'].values());status='checked' if checked else 'overridden' if targets else 'no_placed_target'
        rows.append({'rule_id':rid,'type':r['type'],'checked_instances':checked,'deferred':deferred,'status':status})
    return rows
