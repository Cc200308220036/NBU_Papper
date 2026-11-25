"""GP6 fixed-state instruction probe v1. Preparation/offline only; no order engine."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
from .config import load_config
from .contracts import DecisionContext, digest
from .selector import parse_response
from .transport import JevTransport

SOURCE = Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01/jobs/G01/checkpoint.json')
OUTPUT = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_PREP_20261125_01')
ORDERS = [('original','left','right'), ('left','right','original'), ('right','original','left')]
TEXT = {side: f'For this decision, you must choose an offered action whose box touches the {side} pallet edge ({bound} X). Return exactly one of the provided Cxx labels.' for side,bound in [('left','minimum'),('right','maximum')]}

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def config():
    cfg = load_config()
    cfg['probability_sum_validation'] = 'strict_or_2dp_rounding_interval_v1'
    return cfg

def edges(context):
    groups = {k: [] for k in ('left','right','other','both')}
    container = context['request_body']['state']['container']
    half = container['length_mm']/2
    for label, c in context['criteria'].items():
        x, size = c['pose']['x_mm'], c['oriented_size_mm'][0]
        left, right = abs(x-size/2+half)<=1e-6, abs(x+size/2-half)<=1e-6
        groups['both' if left and right else 'left' if left else 'right' if right else 'other'].append(label)
    return groups

def prepare(root=OUTPUT):
    if root.exists():
        raise ValueError('output_exists_use_new_directory')
    raw = SOURCE.read_bytes()
    events = {e.get('decision_id'):e for e in json.loads(raw)['events'] if e.get('context')}
    transport = JevTransport(load_config())
    summaries, slots = {}, []
    for i, order in enumerate(ORDERS):
        state = f'G01_D{i:04d}'
        base = events[state]['context']
        groups = edges(base)
        expected = [(30,12,12),(36,4,4),(30,6,6)][i]
        assert (len(base['criteria']),len(groups['left']),len(groups['right'])) == expected
        assert not groups['both'] and groups['left'] and groups['right']
        assert len(base['request_body']['state']['placed_objects']) == i
        save(root/'contexts'/f'{state}.json',base)
        stripped = []
        bodies = {}
        for condition in ('original','left','right'):
            body = copy.deepcopy(base['request_body'])
            if condition != 'original':
                body['questions']['next_action']['instructions'] += '\n'+TEXT[condition]
            encoded = transport.encode(body)
            name = f'requests/{state}_{condition}.json'
            (root/'requests').mkdir(parents=True,exist_ok=True)
            (root/name).write_bytes(encoded)
            bodies[condition] = {'path':name,'sha256':hashlib.sha256(encoded).hexdigest(),'bytes':len(encoded),'instructions':body['questions']['next_action']['instructions']}
            del body['questions']['next_action']['instructions']
            stripped.append(body)
        assert stripped[0] == stripped[1] == stripped[2]
        summaries[state] = {'context_digest':digest(base),'mapping_digest':digest(base['display_mapping']),'criteria_digest':digest(base['criteria']),'groups':groups,'candidate_count':len(base['criteria']),'requests':bodies}
        for round_id, sequence in enumerate((order,tuple(reversed(order))),1):
            for condition in sequence:
                slots.append({'slot_id':f'S{len(slots)+1:02d}','state':state,'round':round_id,'condition':condition,'request':bodies[condition],'status':'NOT_RUN'})
    plan = {'version':'gp6_instruction_probe_plan_v1','source':str(SOURCE),'source_sha256':hashlib.sha256(raw).hexdigest(),'model':'jev-1.14.0','endpoint':transport.config['endpoint'],'max_send_reservations':18,'real_calls':0,'status':'PREPARED_NOT_AUTHORIZED','states':summaries,'slots':slots}
    save(root/'plan.json',plan)
    save(root/'summary.json',statistics(plan,[]))
    return plan

def classify(groups,label):
    return next((side for side,labels in groups.items() if label in labels),None)

def statistics(plan, rows):
    by_slot = {r['slot_id']:r for r in rows}
    result = {'version':'gp6_instruction_probe_stats_v1','groups':{},'pairs':[],'service_cost_usd':'UNKNOWN'}
    for condition in ('original','left','right'):
        selected = [by_slot[s['slot_id']] for s in plan['slots'] if s['condition']==condition and by_slot.get(s['slot_id'],{}).get('status')=='selected']
        counts = {side:sum(r['side']==side for r in selected) for side in ('left','right','other','both')}
        result['groups'][condition] = {'planned':6,'valid':len(selected),'hits':counts.get(condition),'distribution':counts,'adherence':counts[condition]/len(selected) if condition!='original' and selected else None,'statuses':{status:sum(by_slot.get(s['slot_id'],{}).get('status','NOT_RUN')==status for s in plan['slots'] if s['condition']==condition) for status in ('NOT_RUN','selected','provider_failure','invalid_response','UNKNOWN_SEND')}}
    for state in plan['states']:
        for rnd in (1,2):
            pair = {s['condition']:by_slot.get(s['slot_id'],{}) for s in plan['slots'] if s['state']==state and s['round']==rnd}
            l,r = pair['left'],pair['right']
            valid = l.get('status')==r.get('status')=='selected'
            result['pairs'].append({'state':state,'round':rnd,'valid':valid,'reversed':valid and l['side']=='left' and r['side']=='right','label_changed_without_reversal':valid and l['label']!=r['label'] and not(l['side']=='left' and r['side']=='right')})
    return result

def run_offline(plan, root, transport, *, prepared_root=OUTPUT):
    """Durable isolated reservations; substitute transports only. Never retries/resumes."""
    if transport.origin != 'test_double':
        raise ValueError('real_send_requires_separate_authorization_and_entry')
    if root.exists():
        raise ValueError('ledger_exists_no_implicit_retry')
    assert len(plan['slots'])==18 and plan['max_send_reservations']==18
    rows=[]
    def persist():
        save(root/'ledger.json',{'version':'gp6_instruction_probe_ledger_v1','plan_digest':digest(plan),'origin':'test_double','real_calls':0,'reservations':len(rows),'rows':rows})
    for slot in plan['slots']:
        row={'slot_id':slot['slot_id'],'status':'RESERVED'}; rows.append(row); persist()
        body=json.loads((prepared_root/slot['request']['path']).read_bytes())
        assert hashlib.sha256(JevTransport(load_config()).encode(body)).hexdigest()==slot['request']['sha256']
        row['status']='SENDING';persist()
        try:
            saved=transport.complete(body)
        except Exception:
            row['status']='UNKNOWN_SEND';persist();break
        row['transport']=saved;row['status']='RESPONSE_SAVED';persist()
        base=json.loads((prepared_root/'contexts'/f"{slot['state']}.json").read_text())
        selection=parse_response(DecisionContext.from_dict(base),{'origin':'test_double','attempt_id':slot['slot_id'],'transport':saved},config()).data
        row['selection']=selection
        row['status']='UNKNOWN_SEND' if selection['status']=='unknown_in_flight' else selection['status']
        row['label']=selection['selected_display_id']
        row['side']=classify(plan['states'][slot['state']]['groups'],row['label'])
        if row['label']:
            row['action']=base['criteria'][row['label']]
            probs=selection['probabilities']
            row['native_probability_mass']={side:sum(probs[l] for l in labels) for side,labels in plan['states'][slot['state']]['groups'].items()}
        persist()
        if row['status']=='UNKNOWN_SEND': break
    save(root/'statistics.json',statistics(plan,rows))
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare'])
    args=parser.parse_args()
    if args.command=='prepare': prepare()

if __name__=='__main__': main()
