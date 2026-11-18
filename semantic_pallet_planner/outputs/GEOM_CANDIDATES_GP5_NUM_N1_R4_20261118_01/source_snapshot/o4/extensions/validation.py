"""Requirement-level checks for E0/E1 (not a substitute for unit tests)."""
import copy
from ..common import O4Error, digest
from ..fixtures import gold_cases as old_gold
from .protocol import validate_policy, validate_observation, rebind, response_for
from .compiler import compile_policy
from .runtime import evaluate_candidates
from .reference import audit, compare
from .planning import select_layout


def gold(rows):
    out=[]
    for row in rows:
        req=row['request'];response=compile_policy(req)
        actual=evaluate_candidates(req,response['policy_ast'],row['candidates'])
        reference=audit(req,row['reference_policy'],row['candidates'])
        metrics=compare(response['policy_ast'],row['reference_policy'],req['placed_objects']+req['available_objects'])
        out.append({'case_id':row['case_id'],'expected_allowed_ids':row['expected_allowed_ids'],
                    'actual':actual,'reference':reference,'metrics':metrics,
                    'passed':actual['allowed_ids']==reference['allowed_ids']==row['expected_allowed_ids'] and metrics['semantic_equal']})
    return out


def invalid(rows, req):
    out=[]
    for row in rows:
        try:
            if row['kind']=='policy':validate_policy(row['payload'],req)
            else:validate_observation(row['payload'])
        except (O4Error,ValueError,TypeError) as exc:
            out.append({'case_id':row['case_id'],'passed':True,'error':str(exc)})
        else:out.append({'case_id':row['case_id'],'passed':False,'error':None})
    return out


def pairs(rows):
    records=[];checks=[]
    for row in rows:
        for backend in ('public_parser','oracle_ast'):
            variants=[]
            for i,v in enumerate(row['variants']):
                req=v['request']
                response=compile_policy(req) if backend=='public_parser' else response_for(req,v['reference_policy'])
                chosen,trace,ev=select_layout(req,response['policy_ast'],row['candidates'])
                ref=audit(req,v['reference_policy'],row['candidates'])
                metrics=compare(response['policy_ast'],v['reference_policy'],req['placed_objects']+req['available_objects'])
                result={'pair_id':row['pair_id'],'variant':i,'backend':backend,'response':response,
                        'allowed_ids':ev['allowed_ids'],'reference_allowed_ids':ref['allowed_ids'],
                        'selected':chosen,'trace':trace,'metrics':metrics,
                        'passed':ev['allowed_ids']==ref['allowed_ids']==row['expected_allowed'][i] and metrics['semantic_equal']}
                variants.append(result);records.append(result)
            a,b=variants
            changed=a['allowed_ids']!=b['allowed_ids'];action_changed=a['selected']!=b['selected']
            checks.append({'pair_id':row['pair_id'],'backend':backend,'kind':row['kind'],
                           'allowed_set_changed':changed,'action_changed':action_changed,
                           'passed':all(v['passed'] for v in variants) and changed==(row['kind']=='changed') and action_changed==row['expected_action_change']})
    return records,checks


def regression():
    rows=[]
    for c in old_gold():
        req=copy.deepcopy(c['request']);ids=[o['object_id'] for o in req['available_objects']]
        req.update(schema_version='o4_e1_request_v1',capability_version='o4_e1_v1',
                   coordinate_convention='bottom_center_x_right_y_back_z_up_v1',placement_convention='upright_label_pos_z_v1',
                   rendering_version='o4_e1_top_label_render_v1',spatial_eps_mm=1e-6,regions=[],
                   buffer_context={'capacity':1,'event_index':0,'end_of_stream':False,
                                   'pending':[{'object_id':i,'slot':0,'arrival_index':0} for i in ids]})
        req=rebind(req);ast=copy.deepcopy(c['reference_policy']);ast['schema_version']='o4_e1_policy_v1'
        actual=evaluate_candidates(req,ast,c['candidates']);ref=audit(req,ast,c['candidates'])
        rows.append({'case_id':c['case_id'],'passed':actual['allowed_ids']==ref['allowed_ids']==c['expected_allowed_ids'],
                     'actual_allowed_ids':actual['allowed_ids'],'reference_allowed_ids':ref['allowed_ids']})
    return rows
