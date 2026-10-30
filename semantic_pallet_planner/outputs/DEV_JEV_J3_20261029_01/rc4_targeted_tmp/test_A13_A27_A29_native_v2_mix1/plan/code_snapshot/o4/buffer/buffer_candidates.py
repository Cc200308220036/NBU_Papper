"""Independent per-box Top-K, bound joint labels, counted physical/business attempts."""
import time
from ..common import digest,O4Error
from ..online.planner_adapter import labeled_candidates,select_layout
from ...domain import PalletState
from ...planner.generator import ExtremePointGenerator
from ...evaluation.geometry_oracle import check_candidate
from .buffer_state import ordered,physical,observation


def pools(s,text,ast,config,remaining=256):
    required=16*len(s['pending_items'])
    if remaining<required:return None,{'unknown':True,'required_reserve':required}
    req=observation(s,text);out=[];attempts=[];generation=[]
    for p in ordered(s):
        identifier=p['item']['item_id'];case=physical(s,identifier)
        start=time.perf_counter()
        generated=ExtremePointGenerator(config).generate(PalletState.from_dict(case))
        elapsed=time.perf_counter()-start
        raw=generated.candidate_set.data['candidates'];public,mapping=labeled_candidates(raw)
        selected,soft,evaluation=select_layout(req,ast,public)
        allowed=set(soft['eligible_labels']);physical_ok=[]
        by_evaluation={v['candidate_id']:v for v in evaluation['evaluations']}
        for c in public:
            errors=check_candidate(case,{'container':s['container']},mapping[c['candidate_id']])
            ok=not errors
            attempts.append({'pick_item_id':identifier,'candidate_id':c['candidate_id'],
                             'pose':c['pose'],'physical_errors':errors,
                             'business_allowed':c['candidate_id'] in evaluation['allowed_ids'],
                             'soft_allowed':c['candidate_id'] in allowed})
            if ok:physical_ok.append(c['candidate_id'])
        joint=[]
        for c in public:
            local=c['candidate_id'];raw_c=mapping[local]
            fp=digest({'pick':identifier,'pose':c['pose'],'size':c['oriented_size_mm']})
            label=f"A{p['arrival_index']:04d}_{local}_{fp[:12]}"
            joint.append({**c,'candidate_id':label,'display_label':label,'local_label':local,
                          'candidate_fingerprint':fp,'arrival_index':p['arrival_index'],'raw':raw_c})
        out.append({'pick_item_id':identifier,'arrival_index':p['arrival_index'],'mass_kg':p['item']['mass_kg'],
                    'public':public,'joint':joint,'selected':selected,'soft':soft,
                    'business_count':len(evaluation['allowed_ids']),
                    'eligible':[c for c in joint if c['local_label'] in allowed and c['local_label'] in physical_ok],
                    'evaluation':evaluation,'physical_count':len(physical_ok)})
        generation.append({'pick_item_id':identifier,'raw_count':len(raw),'audit':generated.audit.data,
                           'elapsed_seconds':elapsed})
    return out,{'unknown':False,'attempts':attempts,'evaluations':len(attempts),'generation':generation}


def public_candidates(groups,buffer_hash):
    return [{k:c[k] for k in ('candidate_id','pick_item_id','pose','oriented_size_mm','candidate_fingerprint')}
            | {'buffer_state_hash':buffer_hash} for g in groups for c in g['joint']]


def blocked_reason(groups,fifo=False):
    if fifo and groups and not groups[0]['eligible'] and any(g['eligible'] for g in groups[1:]):return 'fifo_head_blocked'
    if not any(g['physical_count'] for g in groups):return 'buffer_no_physical_action'
    return 'buffer_no_compiled_business_action'
