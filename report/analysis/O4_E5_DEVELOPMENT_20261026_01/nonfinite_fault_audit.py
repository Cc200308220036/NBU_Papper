"""Current-protocol nonfinite-number probes encoded as serializable recipes."""
import copy
from pathlib import Path
from semantic_pallet_planner.o4.common import read, write, O4Error
from semantic_pallet_planner.o4.extensions.e2.protocol import validate_policy

WS = Path('/home/cyw/NBU_Papper')
OUT = WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PLAN = WS/'semantic_pallet_planner/outputs/PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
case = read(PLAN/'private/input_snapshot.json')['gold'][0]
rows = []
for token in ('nan', 'inf', '-inf'):
    ast = copy.deepcopy(case['reference_policy'])
    ast['rules'].append({'rule_id':'NONFINITE_PROBE','type':'max_top_load','target':{'all':True},
                         'limit':{'constant_kg':float(token)},'priority':20,'overrides':[]})
    try:
        validate_policy(ast, case['request'])
    except O4Error as exc:
        rows.append({'purpose': 'nonfinite_current_protocol_'+token, 'injection':'append constant_kg=float(token)',
                     'token':token,'base_case_id':case['case_id'],'expected':'invalid_ast',
                     'passed':exc.code=='invalid_ast','actual':exc.code,'diagnostic':str(exc)})
    else:
        rows.append({'purpose': 'nonfinite_current_protocol_'+token,'passed':False})
write(OUT/'nonfinite_fault_audit.json', {'status':'PASS' if all(r['passed'] for r in rows) else 'FAIL','faults':rows})
print({'passed':sum(r['passed'] for r in rows),'total':len(rows)})
if not all(r['passed'] for r in rows):
    raise SystemExit(1)
