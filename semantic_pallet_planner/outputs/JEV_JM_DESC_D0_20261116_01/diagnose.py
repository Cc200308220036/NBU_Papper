"""JM-D0: inventory sealed saved descriptors only. Standard library, no geometry.

Never import production code, reconstruct rectangles, or access original forks.
All application input reads pass through the frozen allowlist and are logged.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
CLASSES=('OUT_OF_SCOPE_NONFLOOR','OUT_OF_SCOPE_CROSS_BOX','OUT_OF_SCOPE_YAW',
         'DUPLICATE_EXACT_ACTION','ELIGIBLE_FS_PAIR','UNKNOWN')
RELATIONS=('A_STRICT_SUPERSET','B_STRICT_SUPERSET','TRADEOFF','NO_DIRECTION','UNKNOWN')
NUM=r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'

class Invalid(ValueError):pass

def require(ok,code):
    if not ok:raise Invalid(code)

def now():return datetime.now(timezone.utc).isoformat()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha(canonical(v))
def write(path,v):
    require(not path.exists(),'OUTPUT_ALREADY_EXISTS')
    with path.open('xb') as f:f.write(canonical(v)+b'\n')
def pairs_hook(pairs):
    d={}
    for k,v in pairs:
        require(k not in d,'DUPLICATE_JSON_KEY');d[k]=v
    return d

def loads(raw):
    try:return json.loads(raw,parse_float=Decimal,object_pairs_hook=pairs_hook,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid('NONFINITE')))
    except (UnicodeError,ValueError) as e:
        if isinstance(e,Invalid):raise
        raise Invalid('INVALID_JSON') from e

def num(v):
    require(type(v) in (str,int,Decimal),'NUMBER_TYPE')
    if type(v) is str:require(re.fullmatch(NUM,v) is not None,'NUMBER_SYNTAX')
    d=Decimal(v);require(d.is_finite(),'NONFINITE')
    return Fraction(d)

def dec(v):
    v=Fraction(v);a,b=abs(v.numerator),v.denominator;n=m=0
    while b%2==0:b//=2;n+=1
    while b%5==0:b//=5;m+=1
    require(b==1,'NONTERMINATING')
    scale=max(n,m);s=str(a*2**(scale-n)*5**(scale-m)).zfill(scale+1)
    if scale:s=(s[:-scale]+'.'+s[-scale:]).rstrip('0').rstrip('.')
    return ('-' if v<0 else '')+s if v else '0'

def relation(a,b):
    if a is None or b is None:return 'UNKNOWN'
    a,b=set(a),set(b)
    return ('A_STRICT_SUPERSET' if a>b else 'B_STRICT_SUPERSET' if b>a else
            'NO_DIRECTION' if a==b else 'TRADEOFF')

def classify(a,b):
    # Unknown is never filled with zero. Explicit malformed numbers raise Invalid.
    if any(o.get('pose') is None or o['pose'].get('z_base_mm') is None for o in (a,b)):return 'UNKNOWN'
    if any(num(o['pose']['z_base_mm'])!=0 for o in (a,b)):return CLASSES[0]
    if any(o.get('pick_item_id') is None for o in (a,b)):return 'UNKNOWN'
    if a['pick_item_id']!=b['pick_item_id']:return CLASSES[1]
    if any(o['pose'].get('yaw_deg') is None for o in (a,b)):return 'UNKNOWN'
    if num(a['pose']['yaw_deg'])!=num(b['pose']['yaw_deg']):return CLASSES[2]
    if any(o.get('oriented_size_mm') is None or any(o['pose'].get(k) is None for k in ('x_mm','y_mm')) for o in (a,b)):return 'UNKNOWN'
    require(list(map(num,a['oriented_size_mm']))==list(map(num,b['oriented_size_mm'])),'SAME_BOX_SIZE_CONFLICT')
    if all(num(a['pose'][k])==num(b['pose'][k]) for k in ('x_mm','y_mm','z_base_mm','yaw_deg')):return CLASSES[3]
    return CLASSES[4]

def validate_saved(inp,result,raw_sha):
    """Validate archive identity/member bindings, never compute spatial geometry."""
    require(inp['version']=='jev_jm_fs_input_v1','INPUT_VERSION')
    require(inp['descriptor_scope']['mode']=='FULL_POOL','NOT_FULL_POOL')
    sem=result['semantic']
    require(sem['version']=='jev_jm_fs_result_v1' and sem['algorithm']=='jm_fs_floor_grid_neighbor_v1','RESULT_VERSION')
    require(sem['input_sha256']==raw_sha,'RESULT_INPUT_BINDING')
    require(digest({k:v for k,v in sem.items() if k not in ('semantic_digest','input_sha256','cost')})==sem['semantic_digest'],'SEMANTIC_SEAL')
    v=loads(canonical(inp))
    c=v['state']['container']
    for k in c:c[k]=dec(num(c[k]))
    for o in v['state']['buffer']+v['state']['placed_objects']+v['pool']:
        for k in ('size_mm','oriented_size_mm'):
            if o.get(k) is not None:o[k]=[dec(num(x)) for x in o[k]]
        if o.get('pose') is not None:o['pose']={k:dec(num(x)) for k,x in o['pose'].items()}
    v.pop('provenance');v['pool'].sort(key=lambda o:o['candidate_id'])
    for k in ('buffer','placed_objects'):v['state'][k].sort(key=lambda o:o['item_id'])
    require(digest(v)==sem['input_semantic_digest'],'INPUT_SEMANTIC_BINDING')
    require(digest(sem['budget'])==sem['budget_digest'],'BUDGET_SEAL')
    require(digest(dict(input=sem['input_semantic_digest'],scope=sem['descriptor_scope'],algorithm=sem['algorithm'],budget=sem['budget']))==sem['scope_digest'],'SCOPE_SEAL')
    pool=inp['pool'];ids=[a['candidate_id'] for a in pool]
    require(len(set(ids))==len(ids),'DUPLICATE_CANDIDATE_ID')
    require(sem['descriptor_scope']['mode']=='FULL_POOL' and sem['descriptor_scope']['action_ids']==sorted(ids),'POOL_SCOPE_BINDING')
    boxes={o['item_id']:o for o in inp['state']['buffer']}
    require(len(boxes)==len(inp['state']['buffer']),'DUPLICATE_BUFFER_ID')
    H=num(inp['state']['container']['max_height_mm'])
    for a in pool:
        require(a['pick_item_id'] in boxes,'ACTION_IDENTITY_BINDING')
        size=boxes[a['pick_item_id']]['size_mm']
        require(size is not None,'MISSING_BOX_DIMENSIONS')
        original=list(map(num,size));yaw=num(a['pose']['yaw_deg'])
        require(yaw in (0,90) and all(x>0 for x in original),'ACTION_GEOMETRY_BINDING')
        require(list(map(num,a['oriented_size_mm']))==(original if yaw==0 else [original[1],original[0],original[2]]),'ACTION_SIZE_BINDING')
    require(sem['status'] in ('VALUE','NOT_APPLICABLE','UNKNOWN','INVALID_INPUT'),'SCOPE_STATUS')
    require(sem['status']!='INVALID_INPUT','ARCHIVED_SCOPE_INVALID_INPUT')
    if sem['status']=='UNKNOWN':
        return {a['candidate_id']:dict(candidate_id=a['candidate_id'],status='UNKNOWN',fit_ids=None,members=[]) for a in pool},{}
    rows={r['candidate_id']:r for r in sem['actions']}
    require(len(rows)==len(sem['actions']) and set(rows)==set(ids),'ACTION_RESULT_MEMBERSHIP')
    descriptors={d['key']:d for d in sem['descriptors']}
    require(len(descriptors)==len(sem['descriptors']),'DUPLICATE_DESCRIPTOR_KEY')
    references={k:set() for k in descriptors}
    for d in descriptors.values():
        require(num(d['height_mm'])>0 and num(d['maximum_area_mm2'])>=0,'DESCRIPTOR_NUMBER')
        require(len(set(d['action_ids']))==len(d['action_ids']) and set(d['action_ids'])<=set(ids),'DESCRIPTOR_ACTION_MEMBERSHIP')
    for a in pool:
        row=rows[a['candidate_id']];floor=num(a['pose']['z_base_mm'])==0
        if not floor:
            require(row['status']=='NOT_APPLICABLE' and row['fit_ids'] is None and row['members']==[],'NONFLOOR_RESULT_BINDING')
            continue
        require(row['status'] in ('VALUE','UNKNOWN'),'FLOOR_RESULT_STATUS')
        if row['status']=='UNKNOWN':continue
        remaining=set(boxes)-{a['pick_item_id']}
        require(type(row['fit_ids']) is list and len(set(row['fit_ids']))==len(row['fit_ids']) and set(row['fit_ids'])<=remaining,'FIT_IDENTITY_BINDING')
        members={m['item_id']:m for m in row['members']}
        require(len(members)==len(row['members']) and set(members)==remaining,'REMAINING_BUFFER_BINDING')
        derived=set();byheight={}
        for key,m in members.items():
            h=num(boxes[key]['size_mm'][2]); orientations=m['orientations']
            require(len(orientations)==2 and {o['yaw_deg'] for o in orientations}=={0,90},'ORIENTATION_MEMBERSHIP')
            for o in orientations:
                require(type(o['fits']) is bool,'FIT_TYPE')
                dk=o['descriptor_key']
                if h>H:
                    require(dk is None and not o['fits'] and o['witness'] is None,'OVERHEIGHT_BINDING')
                else:
                    require(dk in descriptors,'MISSING_DESCRIPTOR')
                    d=descriptors[dk]
                    require(num(d['height_mm'])==h and a['candidate_id'] in d['action_ids'],'DESCRIPTOR_BINDING')
                    require(h not in byheight or byheight[h]==dk,'HEIGHT_DESCRIPTOR_CONFLICT')
                    byheight[h]=dk;references[dk].add(a['candidate_id'])
                    # Compare saved references only, do not recompute any rectangle.
                    require((o['witness'] in d['maximal_rectangles']) if o['fits'] else o['witness'] is None,'WITNESS_BINDING')
                if o['fits']:derived.add(key)
        require(derived==set(row['fit_ids']),'FIT_ORIENTATION_BINDING')
    for k,d in descriptors.items():require(references[k]==set(d['action_ids']),'DESCRIPTOR_REVERSE_BINDING')
    return rows,descriptors

def area_vector(a,b,boxes,rows,descriptors):
    if any(rows[c]['status']!='VALUE' for c in (a,b)):return 'UNKNOWN',[]
    # The caller passes only the common remaining boxes, preserving identities.
    heights=sorted({num(o['size_mm'][2]) for o in boxes.values()})
    vector=[]
    for h in heights:
        values=[];refs=[]
        for cid in (a,b):
            found={o['descriptor_key'] for member in rows[cid]['members'] if member['item_id'] in boxes and num(boxes[member['item_id']]['size_mm'][2])==h for o in member['orientations']}
            if len(found)!=1 or None in found or next(iter(found)) not in descriptors:
                values.append(None);refs.append(None)
            else:
                dk=next(iter(found));values.append(num(descriptors[dk]['maximum_area_mm2']));refs.append(dk)
        known=all(x is not None for x in values)
        vector.append(dict(height_mm=dec(h),status='VALUE' if known else 'UNKNOWN',A_mm2=None if values[0] is None else dec(values[0]),B_mm2=None if values[1] is None else dec(values[1]),delta_B_minus_A_mm2=dec(values[1]-values[0]) if known else None,descriptor_keys=refs))
    if any(v['status']=='UNKNOWN' for v in vector):return 'UNKNOWN',vector
    return ('EQUAL_FIT_AREA_DIFF' if any(num(v['delta_B_minus_A_mm2'])!=0 for v in vector) else 'EQUAL_FIT_AREA_EQUAL'),vector

def inventory(inp,rows,descriptors):
    pool={a['candidate_id']:a for a in inp['pool']}
    boxes={b['item_id']:b for b in inp['state']['buffer']}
    allrows=[]
    for aid,bid in itertools.combinations(sorted(pool),2):
        a,b=pool[aid],pool[bid];kind=classify(a,b)
        item=dict(A=aid,B=bid,classification=kind,fit_relation=None,A_fit_ids=None,B_fit_ids=None,area_status='NOT_APPLICABLE',area_vector=[],reason='CLASSIFIED')
        if kind=='UNKNOWN':item.update(fit_relation='UNKNOWN',reason='CLASSIFICATION_UNKNOWN')
        if kind=='ELIGIBLE_FS_PAIR':
            ra,rb=rows.get(aid),rows.get(bid)
            known=all(r is not None and r['status']=='VALUE' for r in (ra,rb))
            fa=sorted(ra['fit_ids']) if ra is not None and ra['status']=='VALUE' else None;fb=sorted(rb['fit_ids']) if rb is not None and rb['status']=='VALUE' else None
            rel=relation(fa,fb)
            item.update(fit_relation=rel,A_fit_ids=fa,B_fit_ids=fb,reason='SAVED_FIT_SETS' if known else 'SAVED_RESULT_UNKNOWN')
            if rel=='NO_DIRECTION':
                remaining={k:o for k,o in boxes.items() if k!=a['pick_item_id']}
                item['area_status'],item['area_vector']=area_vector(aid,bid,remaining,rows,descriptors)
        allrows.append(item)
    return allrows

class Reader:
    def __init__(self,manifest):self.allowed={r['path']:r for r in manifest['files']};self.log=[]
    def read(self,path):
        require(path in self.allowed,'READ_NOT_ALLOWLISTED')
        full=ROOT/path;require(full.resolve().is_relative_to(ROOT),'PATH_OUTSIDE_ROOT')
        try:raw=full.read_bytes()
        except FileNotFoundError:raise Invalid('MISSING')
        r=self.allowed[path];require(sha(raw)==r['sha256'] and len(raw)==r['bytes'],'FILE_IDENTITY_MISMATCH')
        self.log.append(dict(sequence=len(self.log)+1,path=path,sha256=sha(raw),bytes=len(raw)))
        return raw


def run():
    # Control files are read first, verified against the independent freeze receipt.
    control={n:(OUT/n).read_bytes() for n in ('diagnostic_plan.json','input_manifest.json','freeze_receipt.json')}
    receipt=loads(control['freeze_receipt.json']);plan=loads(control['diagnostic_plan.json']);manifest=loads(control['input_manifest.json'])
    for name in ('diagnostic_plan.json','input_manifest.json'):require(sha(control[name])==receipt['files'][name],'FROZEN_CONTROL_CHANGED')
    reader=Reader(manifest)
    for path in plan['implementation_files']+plan['identity_files']:reader.read(path)
    require(not (OUT/'execution_receipt.json').exists(),'EXECUTION_ALREADY_RECORDED')
    write(OUT/'execution_receipt.json',dict(version='jm_d0_execution_start_v1',sequence=2,time_utc=now(),freeze_receipt_sha256=sha(control['freeze_receipt.json']),plan_sha256=sha(control['diagnostic_plan.json']),input_manifest_sha256=sha(control['input_manifest.json'])))
    summaries=[];all_count=0
    for point in plan['points']:
        n=point['expected_actions'];expected=n*(n-1)//2;status='COMPLETE';reason='SAVED_RESULTS_ONLY';pairs=[];input_evidence=[];sem=None;inp=None
        try:
            iraw=reader.read(point['input']);rraw=reader.read(point['result'])
            input_evidence=[dict(path=p,sha256=reader.allowed[p]['sha256']) for p in (point['input'],point['result'])]
            inp=loads(iraw);result=loads(rraw)
            require(len(inp['pool'])==n,'POOL_COUNT_MISMATCH')
            require(all_count+expected<=plan['pair_limit'],'PAIR_LIMIT')
            rows,desc=validate_saved(inp,result,sha(iraw));sem=result['semantic']
            pairs=inventory(inp,rows,desc)
            require(len(pairs)==expected,'PAIR_DENOMINATOR')
        except (Invalid,KeyError,TypeError,IndexError) as e:
            status='MISSING' if str(e)=='MISSING' else 'INVALID_INPUT'
            reason=str(e) if isinstance(e,Invalid) else 'MALFORMED_SAVED_STRUCTURE'
        all_count+=expected
        pointer={a['candidate_id']:'/pool/'+str(i) for i,a in enumerate(inp['pool'])} if inp is not None else {}
        result_pointer={a['candidate_id']:'/semantic/actions/'+str(i) for i,a in enumerate(sem['actions'])} if sem is not None else {}
        descriptor_pointer={d['key']:'/semantic/descriptors/'+str(i) for i,d in enumerate(sem['descriptors'])} if sem is not None else {}
        for i,pair in enumerate(pairs):
            pair['point_id']=point['point_id'];pair['ordinal']=i
            pair['evidence']=dict(input_refs=[dict(input_evidence[0],pointer=pointer[pair[k]]) for k in ('A','B')],
                  result_refs=[dict(input_evidence[1],pointer=result_pointer.get(pair[k])) for k in ('A','B')],
                  descriptor_refs=[dict(input_evidence[1],pointer=descriptor_pointer.get(dk)) for row in pair['area_vector'] for dk in row['descriptor_keys'] if dk is not None])
        dest=OUT/(point['point_id']+'_pair_inventory.jsonl')
        require(not dest.exists(),'OUTPUT_ALREADY_EXISTS')
        with dest.open('xb') as f:
            for pair in pairs:f.write(canonical(pair)+b'\n')
        classes=Counter(p['classification'] for p in pairs)
        fit=Counter(p['fit_relation'] for p in pairs if p['classification']=='ELIGIBLE_FS_PAIR')
        area=Counter(p['area_status'] for p in pairs if p['fit_relation']=='NO_DIRECTION')
        samples={k:[p['ordinal'] for p in pairs if p['fit_relation']==k][:3] for k in RELATIONS}
        samples.update({k:[p['ordinal'] for p in pairs if p['area_status']==k][:3] for k in ('EQUAL_FIT_AREA_DIFF','EQUAL_FIT_AREA_EQUAL','UNKNOWN')})
        summaries.append(dict(point_id=point['point_id'],source_component=point['source_component'],source_order=point['source_order'],status=status,reason=reason,actions_planned=n,pairs_planned=expected,pairs_enumerated=len(pairs),unassessed_pair_slots=expected-len(pairs),classification_counts={k:classes[k] for k in CLASSES},fit_relation_counts={k:fit[k] for k in RELATIONS},area_counts={k:area[k] for k in ('EQUAL_FIT_AREA_DIFF','EQUAL_FIT_AREA_EQUAL','UNKNOWN')},area_height_observations=sum(len(p['area_vector']) for p in pairs),samples=samples,pair_inventory=dict(path=dest.relative_to(ROOT).as_posix(),sha256=sha(dest.read_bytes())),input_evidence=input_evidence))
    grouped=[]
    for component in sorted({p['source_component'] for p in summaries}):
        group=[p for p in summaries if p['source_component']==component]
        grouped.append(dict(component=component,states=[p['point_id'] for p in group],pairs_planned=sum(p['pairs_planned'] for p in group),counts={k:sum(p['classification_counts'][k] for p in group) for k in CLASSES},fit_relations={k:sum(p['fit_relation_counts'][k] for p in group) for k in RELATIONS},not_independent_replicates=True))
    write(OUT/'diagnostic_summary.json',dict(version='jm_d0_summary_v1',contract='jm_exposed_descriptive_v1',states=summaries,by_component=grouped,actions_planned=sum(p['actions_planned'] for p in summaries),pairs_planned=all_count,pairs_enumerated=sum(p['pairs_enumerated'] for p in summaries),limitations=plan['limitations'],next_stage_admission='NOT_ASSESSED',return_to='INDEPENDENT_QA',stop=True))
    write(OUT/'actual_reads.json',dict(version='jm_d0_actual_reads_v1',control_reads={k:sha(v) for k,v in control.items()},payload_reads=reader.log,coverage='application-level explicit reads;Python interpreter/stdlib loading excluded;script identities verified separately'))
    write(OUT/'completion_receipt.json',dict(sequence=3,time_utc=now(),execution_receipt_sha256=sha((OUT/'execution_receipt.json').read_bytes()),summary_sha256=sha((OUT/'diagnostic_summary.json').read_bytes()),freeze_receipt_sha256=sha(control['freeze_receipt.json']),stop=True))
    print(json.dumps(dict(states=len(summaries),pairs=all_count,statuses=[p['status'] for p in summaries]),ensure_ascii=False))

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
