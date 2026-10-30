"""O4 hard-feasible pool + frozen V2 relaxed_geometry ranking principles.

No reference AST or evaluator is accepted here. Candidate coordinates and scores
are public physical facts; no future items or reference pruning are used.
"""
import copy
import math
from ...o4.common import O4Error, digest
from ...o4.executor import evaluate_candidates, transition
from ...o4.compiler import validate_response
from ...o4.observation import build_observation
from ...planner.scoring import geometry_score
from ...selectors.layout_preserving_v2 import stable_best
from ...evaluation.geometry_oracle import check_candidate
from ...evaluation.state import apply_candidate

VERSION = 'o4_relaxed_geometry_v1'
POLICY_EPS = 1e-6
RANKING_EPS = 1e-12
SOFT_BUDGETS = (0.05, 0.25)


def labeled_candidates(candidates):
    """Pose ordering is invariant to request IDs and object-ID renaming."""
    if len(candidates) > 16:
        raise O4Error('invalid_candidate', 'Top-K exceeds 16')
    def key(c):
        p=c['pose']
        return (p['x_mm'], p['y_mm'], p['z_base_mm'], p['yaw_deg'], *c['oriented_size_mm'])
    ordered=sorted(copy.deepcopy(candidates), key=key)
    if len({c['candidate_id'] for c in ordered}) != len(ordered):
        raise O4Error('invalid_candidate', 'duplicate candidate ID')
    if len({key(c) for c in ordered}) != len(ordered):
        raise O4Error('invalid_candidate', 'duplicate pose')
    mapping={f'C{i:02d}': c for i,c in enumerate(ordered,1)}
    public=[]
    for label,c in mapping.items():
        public.append({'candidate_id': label, 'display_label': label,
                       'pick_item_id': c['pick_item_id'], 'pose': copy.deepcopy(c['pose']),
                       'oriented_size_mm': list(c['oriented_size_mm']),
                       'geometry_score': geometry_score(c)})
    return public,mapping


def soft_quality(req,candidate):
    placed=transition(req,candidate)
    heavy=[o for o in placed if o['weight_class']=='heavy']
    mass=math.fsum(o['mass_kg'] for o in heavy)
    if not mass: return [None,None]
    z=math.fsum(o['mass_kg']*o['pose']['z_base_mm'] for o in heavy)/mass
    distance=math.fsum(o['mass_kg']*math.hypot(o['pose']['x_mm'],o['pose']['y_mm']) for o in heavy)/mass
    c=req['container']
    return [max(0.,1.-z/c['max_height_mm']),
            max(0.,1.-distance/math.hypot(c['length_mm']/2,c['width_mm']/2))]


def select_layout(req,policy,candidates):
    """Only this method's AST determines hard feasibility."""
    evaluation=evaluate_candidates(req,policy,candidates)
    feasible=[i for i,c in enumerate(candidates) if c['candidate_id'] in evaluation['allowed_ids']]
    trace={'version': VERSION, 'soft_order':['heavy_low','heavy_center'],
           'soft_budgets':list(SOFT_BUDGETS), 'policy_epsilon':POLICY_EPS,
           'ranking_epsilon':RANKING_EPS, 'hard_feasible_labels':evaluation['allowed_ids'],
           'anchor_label':None,'eligible_labels':[], 'soft_values':{}}
    if not feasible: return None,trace,evaluation
    scores={i:soft_quality(req,candidates[i]) for i in feasible}
    trace['soft_values']={candidates[i]['candidate_id']:scores[i] for i in feasible}
    strict=list(feasible)
    for tier in (0,1):
        applicable=[scores[i][tier] for i in strict if scores[i][tier] is not None]
        if applicable:
            best=max(applicable)
            strict=[i for i in strict if scores[i][tier] is not None and scores[i][tier]>=best-POLICY_EPS]
    # The original anchor uses exact geometry ordering, as frozen V2 does.
    anchor=min(strict,key=lambda i:(-candidates[i]['geometry_score'],candidates[i]['display_label']))
    eligible=[i for i in feasible if all(a is None or (q is not None and q>=a-budget-POLICY_EPS)
               for a,q,budget in zip(scores[anchor],scores[i],SOFT_BUDGETS))]
    if anchor not in eligible: raise O4Error('invalid_ranking','anchor escaped budget')
    tied=stable_best(eligible,lambda i:candidates[i]['geometry_score'],RANKING_EPS)
    selected=min(tied,key=lambda i:candidates[i]['display_label'])
    trace.update(anchor_label=candidates[anchor]['candidate_id'],anchor_soft_quality=scores[anchor],
                 strict_equivalent_labels=[candidates[i]['candidate_id'] for i in strict],
                 eligible_labels=[candidates[i]['candidate_id'] for i in eligible],
                 geometry_tie_labels=[candidates[i]['candidate_id'] for i in tied],
                 selected_soft_quality=scores[selected],
                 soft_loss_from_anchor=[None if a is None or b is None else max(0.,a-b)
                                        for a,b in zip(scores[anchor],scores[selected])])
    return candidates[selected]['candidate_id'],trace,evaluation


def action_for(req,public_candidates,label):
    return {k: req[k] for k in ('request_id','state_hash','observation_digest','instruction_digest')} | {
        'candidate_set_digest':digest(public_candidates),'label':label}


def submit_action(state,attributes,req,raw_candidates,response,action):
    """Validate bindings, local business and independent physics before commit.

    A reference policy/evaluation is deliberately not an argument.
    """
    rebuilt=build_observation(state,attributes,req['instruction_text'],req['images'])
    if rebuilt != req: raise O4Error('invalid_binding','stale state or observation')
    validate_response(response,req)
    public,mapping=labeled_candidates(raw_candidates)
    for key in ('request_id','state_hash','observation_digest','instruction_digest'):
        if action.get(key) != req[key]: raise O4Error('invalid_binding','stale action')
    if action.get('candidate_set_digest') != digest(public):
        raise O4Error('invalid_binding','candidate set changed')
    label=action.get('label')
    if label not in mapping: raise O4Error('invalid_candidate','unknown display label')
    local=evaluate_candidates(req,response['policy_ast'],public)
    if label not in local['allowed_ids']:
        return None,'business_rejection',[]
    errors=check_candidate(state,{'container':state['container']},mapping[label])
    if errors: return None,'physical_rejection',errors
    return apply_candidate(state,mapping[label]),'select',[]


def select_and_commit(state,attributes,req,raw_candidates,response):
    validate_response(response,req)
    public,mapping=labeled_candidates(raw_candidates)
    label,trace,evaluation=select_layout(req,response['policy_ast'],public)
    result={'proposed_label':label,'committed_label':None,'action':None,
            'trace':trace,'method_evaluation':evaluation,'physical_errors':[]}
    if not public:
        result['status']='no_physical_candidate'
        return result,copy.deepcopy(state['placed_items'])
    if label is None:
        result['status']='no_compiled_business_candidate'
        return result,copy.deepcopy(state['placed_items'])
    action=action_for(req,public,label)
    placed,status,errors=submit_action(state,attributes,req,raw_candidates,response,action)
    result.update(action=action,status=status,physical_errors=errors)
    if placed is not None: result['committed_label']=label
    return result,placed if placed is not None else copy.deepcopy(state['placed_items'])
