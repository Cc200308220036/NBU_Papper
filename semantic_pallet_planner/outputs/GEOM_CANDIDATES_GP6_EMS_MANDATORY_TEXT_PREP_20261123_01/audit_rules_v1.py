"""Post-hoc published-choice audit. Pure saved geometry; no selector/monitor hooks."""
import argparse
import base64
import copy
import hashlib
import json
import math
from pathlib import Path

VERSION='gp6_published_choice_lexicographic_audit_v1'
LENGTH_TOL_MM=1e-6
AREA_TOL_MM2=1e-6

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def bounds(obj):
    p=obj['pose'];l,w,h=obj['oriented_size_mm']
    values=[p['x_mm'],p['y_mm'],p['z_base_mm'],l,w,h]
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in values) or min(l,w,h)<=0:
        raise ValueError('INVALID_AXIS_ALIGNED_GEOMETRY')
    return (p['x_mm']-l/2,p['x_mm']+l/2,p['y_mm']-w/2,p['y_mm']+w/2,p['z_base_mm'],p['z_base_mm']+h)

def union_area(rectangles):
    rectangles=[r for r in rectangles if r[1]-r[0]>LENGTH_TOL_MM and r[3]-r[2]>LENGTH_TOL_MM]
    xs=sorted({x for r in rectangles for x in r[:2]});total=0.
    for x0,x1 in zip(xs,xs[1:]):
        intervals=sorted((y0,y1) for a,b,y0,y1 in rectangles if a<x1 and b>x0)
        covered=0.;end=None
        for a,b in intervals:
            if end is None or a>end:
                covered+=b-a;end=b
            elif b>end:
                covered+=b-end;end=b
        total+=(x1-x0)*covered
    return total

def face_contact_area_mm2(candidate,placed):
    """Union per face: supported bottom plus four sides. No floor/top included."""
    x0,x1,y0,y1,z0,z1=bounds(candidate)
    contacts={name:[] for name in ('bottom','x_min','x_max','y_min','y_max')}
    for other in placed:
        a,b,c,d,e,f=bounds(other)
        if abs(z0-f)<=LENGTH_TOL_MM:
            contacts['bottom'].append((max(x0,a),min(x1,b),max(y0,c),min(y1,d)))
        if abs(x0-b)<=LENGTH_TOL_MM:
            contacts['x_min'].append((max(y0,c),min(y1,d),max(z0,e),min(z1,f)))
        if abs(x1-a)<=LENGTH_TOL_MM:
            contacts['x_max'].append((max(y0,c),min(y1,d),max(z0,e),min(z1,f)))
        if abs(y0-d)<=LENGTH_TOL_MM:
            contacts['y_min'].append((max(x0,a),min(x1,b),max(z0,e),min(z1,f)))
        if abs(y1-c)<=LENGTH_TOL_MM:
            contacts['y_max'].append((max(x0,a),min(x1,b),max(z0,e),min(z1,f)))
    by_face={name:union_area(rects) for name,rects in contacts.items()}
    return {'total_mm2':sum(by_face.values()),'by_face_mm2':by_face}

def candidate_scores(candidate,before):
    x0,_,y0,_,z0,_=bounds(candidate)
    container=before['container']
    if container.get('coordinate_frame')!='container_bottom_center':
        raise ValueError('UNSUPPORTED_COORDINATE_FRAME')
    dx=x0+container['length_mm']/2;dy=y0+container['width_mm']/2
    if min(dx,dy)<-LENGTH_TOL_MM:raise ValueError('PUBLISHED_CANDIDATE_OUTSIDE_MIN_BOUNDARIES')
    dx=0. if abs(dx)<=LENGTH_TOL_MM else dx;dy=0. if abs(dy)<=LENGTH_TOL_MM else dy
    contact=face_contact_area_mm2(candidate,before['placed_items'])
    return {'z_base_mm':z0,'clearance_x_mm':dx,'clearance_y_mm':dy,'total_corner_clearance_mm':dx+dy,
            'touches_both_corner_edges':dx==dy==0.,'face_contact':contact}

def audit_published_choice(event):
    """Never mutate event or choose a substitute action; return diagnostics only."""
    ctx=event.get('context')
    if not ctx:
        return {'audit_version':VERSION,'status':'NO_PUBLISHED_CONTEXT','violation_rule':None}
    body=ctx.get('request_body')
    criteria=body['questions']['next_action']['criteria'] if body else ctx['criteria']
    labels=list(criteria) # Only actually published labels, never all physical candidates.
    mapping=ctx['display_mapping'];candidates=event['bundle']['physical_candidates']
    lookup={c['candidate_id']:c for c in candidates}
    if len(lookup)!=len(candidates):raise ValueError('DUPLICATE_CANDIDATE_ID')
    if set(labels)!=set(mapping):raise ValueError('PUBLISHED_MAPPING_MISMATCH')
    rows=[]
    for label in labels:
        mapped=mapping[label];c=lookup[mapped['candidate_id']]
        if digest(c)!=mapped['candidate_digest']:raise ValueError('CANDIDATE_DIGEST_MISMATCH')
        if mapped.get('pick_item_id')!=c['pick_item_id']:raise ValueError('CANDIDATE_ITEM_MISMATCH')
        rows.append({'Cxx':label,'candidate_id':c['candidate_id'],'item_id':c['pick_item_id'],
                     'pose':copy.deepcopy(c['pose']),'oriented_size_mm':copy.deepcopy(c['oriented_size_mm']),
                     **candidate_scores(c,event['before'])})
    result={'audit_version':VERSION,'decision_id':event.get('decision_id'),'route':ctx['route'],
            'choice_origin':'JEV' if body else 'AUTOMATIC_SINGLETON_NOT_JEV',
            'published_labels_in_original_order':labels,'scores_in_original_order':rows,
            'candidate_pool_digest':digest(candidates),'violation_rule':None,
            'coordinate_tolerance_mm':LENGTH_TOL_MM,'area_tolerance_mm2':AREA_TOL_MM2,
            'final_contiguous_space_rule':'UNASSESSABLE_NO_USER_DEFINED_METRIC'}
    if not rows:return {**result,'status':'NO_PUBLISHED_CANDIDATES'}
    stages=[];remaining=rows
    for rule,key,maximize,tol in ((1,'z_base_mm',False,LENGTH_TOL_MM),(2,'total_corner_clearance_mm',False,LENGTH_TOL_MM)):
        best=(max if maximize else min)(r[key] for r in remaining)
        remaining=[r for r in remaining if abs(r[key]-best)<=tol]
        stages.append({'rule':rule,'metric':key,'best_value':best,'surviving_Cxx':[r['Cxx'] for r in remaining]})
    empty=not event['before']['placed_items']
    if empty:
        stages.append({'rule':3,'status':'SKIPPED_EMPTY_PALLET','surviving_Cxx':[r['Cxx'] for r in remaining]})
    else:
        best=max(r['face_contact']['total_mm2'] for r in remaining)
        remaining=[r for r in remaining if abs(r['face_contact']['total_mm2']-best)<=AREA_TOL_MM2]
        stages.append({'rule':3,'metric':'face_contact_area_mm2','best_value':best,'surviving_Cxx':[r['Cxx'] for r in remaining]})
    result.update(stages=stages,hard_rule_finalists_Cxx=[r['Cxx'] for r in remaining])
    selection=event.get('selection')
    if not selection or selection.get('status') not in ('selected','singleton'):
        return {**result,'status':'NO_VALID_ORIGINAL_SELECTION'}
    selected=selection['selected_display_id']
    if selected not in mapping or selection['selected_candidate_id']!=mapping[selected]['candidate_id']:
        raise ValueError('ORIGINAL_SELECTION_MAPPING_MISMATCH')
    result['original_selected_Cxx']=selected
    result['original_selected_candidate_id']=selection['selected_candidate_id']
    result['original_selected_scores']=next(r for r in rows if r['Cxx']==selected)
    for stage in stages:
        if selected not in stage['surviving_Cxx']:
            result.update(status='VIOLATION',violation_rule=stage['rule'],
                          admissible_after_violated_rule_Cxx=stage['surviving_Cxx'])
            break
    else:
        result['status']='COMPLIANT_UNIQUE_HARD_RULE_WINNER' if len(remaining)==1 else 'NO_HARD_RULE_VIOLATION_FINAL_TIE_UNASSESSABLE'
    result['selected_is_corner']=result['original_selected_scores']['touches_both_corner_edges']
    result['selected_monitor_status']=(event.get('monitor') or {}).get('status','NOT_AVAILABLE')
    return result

def verify_raw_choice(event,request_ledger):
    matches=[r for r in request_ledger['requests'] if r['decision_id']==event['decision_id']]
    if len(matches)!=1:raise ValueError('ORIGINAL_REQUEST_LEDGER_MATCH_REQUIRED')
    row=matches[0];transport=row['transport'];selection=event['selection']
    if row['selection']!=selection or row['selection_digest']!=digest(selection):
        raise ValueError('LEDGER_ORIGINAL_SELECTION_MISMATCH')
    if row['body_digest']!=digest(event['context']['request_body']):
        raise ValueError('LEDGER_BASE_REQUEST_MISMATCH')
    if digest(transport)!=row['transport_digest']:raise ValueError('TRANSPORT_DIGEST_MISMATCH')
    raw=base64.b64decode(transport['raw_body_b64'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=transport['raw_sha256']:raise ValueError('RAW_RESPONSE_DIGEST_MISMATCH')
    if transport['status']!='OK':raise ValueError('VALID_SELECTION_WITHOUT_OK_TRANSPORT')
    choice=json.loads(raw)['answers']['next_action']['choice']
    if choice!=selection['selected_display_id']:raise ValueError('RAW_JEV_CHOICE_MISMATCH')
    return choice


def audit_checkpoint(checkpoint,metrics=None,request_ledger=None):
    if 'checkpoint' in checkpoint:checkpoint=checkpoint['checkpoint']
    saved={}
    for e in [*checkpoint['events'],checkpoint.get('pending_event')]:
        if e and e.get('context') and e.get('decision_id'):
            saved[e['decision_id']]=e
    steps=[]
    for event in saved.values():
        result=audit_published_choice(event)
        result['raw_choice_ledger_verification']='NOT_CHECKED'
        if request_ledger and result.get('choice_origin')=='JEV' and 'original_selected_Cxx' in result:
            result['original_raw_choice_Cxx']=verify_raw_choice(event,request_ledger)
            result['raw_choice_ledger_verification']='PASS'
        steps.append(result)
    first=next((s for s in steps if 'original_selected_Cxx' in s),None)
    return {'version':'gp6_saved_choices_audit_report_v1','evaluation_scope':'POST_HOC_ONLY_NOT_AN_ONLINE_FILTER',
            'instruction_delivery_verified':False,'instruction_delivery_note':'Geometry audit alone does not verify that mandatory text was sent; verify actual wire bodies and ledger separately',
            'steps':steps,'first_original_choice':first,'final_placed_items':len(checkpoint['state']['placed_items']),
            'fixed_container_utilization':metrics['fixed_container_utilization'] if metrics else 'UNKNOWN_NO_METRICS_FILE',
            'termination_reason':checkpoint['reason'],'new_model_calls':0,'new_monitor_calls':0,
            'no_automatic_reselection':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True);parser.add_argument('--metrics',type=Path)
    parser.add_argument('--request-ledger',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('REFUSE_OVERWRITE_AUDIT_REPORT')
    cp=json.loads(args.checkpoint.read_text());metrics=json.loads(args.metrics.read_text()) if args.metrics else None
    ledger=json.loads(args.request_ledger.read_text()) if args.request_ledger else None
    result=audit_checkpoint(cp,metrics,ledger)
    result['input_request_ledger_sha256']=hashlib.sha256(args.request_ledger.read_bytes()).hexdigest() if args.request_ledger else None
    result['input_checkpoint_sha256']=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    result['input_metrics_sha256']=hashlib.sha256(args.metrics.read_bytes()).hexdigest() if args.metrics else None
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'SAVED','decisions':len(result['steps']),'output':str(args.output),'new_calls':0}))
if __name__=='__main__':main()
