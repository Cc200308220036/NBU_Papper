"""E5 entry-point semantic regression from frozen inputs, not past scores."""
import copy
from ...common import O4Error
from ...invalid import invalid_cases as old_invalid,execute_invalid_case
from ...fixtures import gold_cases as old_gold
from ..data import invalid_cases as e1_invalid
from ..e2.data import gold_cases as e2_gold,pair_cases as e2_pairs,invalid_cases as e2_invalid
from ..e2.validation import regression_inputs,regression as old_regression,gold,pairs,invalid
from ..e2.protocol import validate_policy,validate_observation


def inputs():
    return {'legacy':regression_inputs(),'e2_gold':e2_gold(),'e2_pairs':e2_pairs(),
            'old_invalid':old_invalid(),'old_invalid_request':old_gold()[0]['request'],
            'e1_invalid':e1_invalid(),'e2_invalid':e2_invalid()}


def run(frozen):
    rows=old_regression(frozen['legacy'])
    rows += [{'stage':'E2_GOLD',**r} for r in gold(frozen['e2_gold'])]
    pair_rows,pair_checks=pairs(frozen['e2_pairs'])
    rows += [{'stage':'E2_PAIR',**r} for r in pair_rows]
    if len(rows)!=180:raise O4Error('regression_denominator_changed')
    rejected=[]
    for c in frozen['old_invalid']:
        try:execute_invalid_case(c,frozen['old_invalid_request'])
        except O4Error as exc:rejected.append({'stage':'old','case_id':c['case_id'],'passed':exc.code==c['expected_code'],'error':str(exc)})
        else:rejected.append({'stage':'old','case_id':c['case_id'],'passed':False})
    # E1 negative observations deliberately include invalid regions, placement
    # conventions, and stale hashes. Rebinding them here would fix the test.
    from ..protocol import validate_policy as e1_policy,validate_observation as e1_observation
    from ..data import request as e1_request
    q,_=e1_request()
    for c in frozen['e1_invalid']:
        try:(e1_policy(c['payload'],q) if c['kind']=='policy' else e1_observation(c['payload']))
        except O4Error as exc:rejected.append({'stage':'E1','case_id':c['case_id'],'passed':True,'error':str(exc)})
        else:rejected.append({'stage':'E1','case_id':c['case_id'],'passed':False})
    rejected += [{'stage':'E2',**r} for r in invalid(frozen['e2_invalid'],frozen['e2_gold'][0]['request'])]
    if len(rejected)!=48:raise O4Error('invalid_regression_denominator_changed')
    return rows,rejected,pair_checks


def mixed(rows):
    from ..e2.data import policy
    from ..e2.runtime import evaluate_candidates
    from ..e2.reference import audit
    checked=gold(rows)
    for source,result in zip(rows,checked):
        components=[]
        for identifier,expected in source.get('component_allowed_ids',{}).items():
            rule=next(r for r in source['reference_policy']['rules'] if r['rule_id']==identifier)
            ast=policy([rule]);actual=evaluate_candidates(source['request'],ast,source['candidates'])['allowed_ids']
            independent=audit(source['request'],ast,source['candidates'])['allowed_ids']
            passed=actual==independent==expected
            components.append({'rule_id':identifier,'expected':expected,'actual':actual,'reference':independent,'passed':passed})
        result['individual_rule_witnesses']=components
        result['passed']=result['passed'] and all(c['passed'] for c in components)
    return checked
