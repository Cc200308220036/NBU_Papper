"""Frozen GP0 joint-key coverage reducer; no learned/research scores."""
from fractions import Fraction

VERSION='yaw_floor_required_then_joint_group_coverage_v1'


def action_order(record):
    k=record['action_key']
    return (k[0], *(Fraction(v) for v in k[1:]))


def coverage(record):
    k=record['action_key']
    support=tuple(sorted(record['candidate']['support']['support_item_ids'])) if Fraction(k[7]) else ('GROUND',)
    return {(int(k[4]),k[7],(Fraction(k[5])>=0,Fraction(k[6])>=0),support,s)
            for s in record['sources']}


def reduce_candidates(records):
    rank=lambda r:(-r['geometry_score'],action_order(r))
    groups={}
    for r in sorted(records,key=rank):
        k=r['action_key']
        groups.setdefault((int(k[4]),'floor' if Fraction(k[7])==0 else 'upper'),r)
    selected=[]
    covered=set()
    trace=[]
    def add(r, reason):
        new=coverage(r)-covered
        selected.append(r)
        covered.update(coverage(r))
        trace.append({'action_key':r['action_key'],'reason':reason,'new_joint_keys':len(new)})
    for group in sorted(groups):
        add(groups[group],'REQUIRED_YAW_LEVEL')
    remaining=[r for r in records if r not in selected]
    while remaining and len(selected)<16:
        r=min(remaining,key=lambda r:(-len(coverage(r)-covered),*rank(r)))
        add(r,'JOINT_COVERAGE' if coverage(r)-covered else 'SCORE_FILL')
        remaining.remove(r)
    all_keys=set().union(*(coverage(r) for r in records)) if records else set()
    serial=lambda keys:sorted([[a,b,list(c),list(d),e] for a,b,c,d,e in keys])
    return sorted(selected,key=action_order), {'version':VERSION,'required_groups':[list(g) for g in sorted(groups)],
        'selection_order':trace,'raw_joint_keys':serial(all_keys),'final_joint_keys':serial(covered),
        'uncovered_joint_keys':serial(all_keys-covered),'compressed_count':len(records)-len(selected)}
