"""Predeclared functional cases. Expected counts/orders are not parsed from results."""
import copy
import itertools
from ..fixtures import item,policy,rule,task_policy,render_policy,CONTAINER
from ..common import digest
from ..evaluator import audit_reference
from ...domain import PalletState
from ...planner.generator import ExtremePointGenerator
from ...evaluation.geometry_oracle import check_candidate
from ...evaluation.state import apply_candidate
from .buffer_state import initial,receive,observation
from .buffer_evaluation import episode,stable


def construct_cases():
    out=[]
    for family in ('load_support','dimensions','contact','condition_override'):
        for variant in range(3):
            c=copy.deepcopy(CONTAINER);c.update(length_mm=100,width_mm=100,max_height_mm=300)
            boxes=[item('a'),item('b'),item('c')];ast=policy([])
            expected_single=expected_search=3;orders=None
            if family=='load_support':
                if variant==0:
                    boxes[0]['_attributes']['labels']['no_top_load']=True;ast=task_policy(1)
                    expected_single=1;orders=[['b','c','a'],['c','b','a']]
                elif variant==1:ast=task_policy(0)
                else:
                    for b in boxes:b['_attributes']['labels']['no_top_load']=True
                    ast=task_policy(1);expected_single=expected_search=1
            elif family=='dimensions':
                if variant==0:
                    c['max_height_mm']=200
                    boxes=[item('a',size=(50,100,100)),item('b'),item('c',size=(50,100,100))]
                    expected_single=1;orders=[['b','a','c'],['b','c','a']]
                elif variant==1:c['length_mm']=300;c['max_height_mm']=100
                else:
                    boxes=[item(i,size=(200,200,100)) for i in ('a','b','c')];expected_single=expected_search=0
            elif family=='contact':
                ast=policy([rule(kind='forbidden_contact')])
                if variant==0:
                    boxes=[item('a',category='food'),item('b',category='household_cleaner'),item('c')]
                    expected_single=1;orders=[['a','c','b'],['b','c','a']]
                elif variant==1:boxes=[item(i,category='food') for i in ('a','b','c')]
                else:
                    boxes=[item('a',category='food'),item('b',category='household_cleaner'),item('c',category='food')]
                    # Two foods may stack; a cleaner cannot share their contacting column.
                    expected_single=1;expected_search=2
            else:
                ast=task_policy(4)
                if variant==0:
                    boxes=[item('a',category='glassware',reinforced=True,label=0.,mass=1.),
                           item('b',mass=2.,label=10.),item('c',mass=2.,label=10.)]
                    ast['rules'][2]['limit']={'constant_kg':0.5}
                    expected_single=1;orders=[['b','c','a'],['c','b','a']]
                elif variant==1:
                    boxes=[item(i,category='glassware',reinforced=True,label=0.,mass=1.) for i in ('a','b','c')]
                else:
                    boxes=[item(i,category='glassware',reinforced=False,label=0.) for i in ('a','b','c')]
                    expected_single=expected_search=1
            attrs={b['item_id']:b.pop('_attributes') for b in boxes}
            for b in boxes:b.update(supported_load_kg=0.,support_fractions=[])
            identifier=f'O4F_{family}_{variant}'
            scenario={'scenario_id':identifier,'container':c,'items':boxes,'arrival_order':['a','b','c'],'buffer_size':3}
            task={'task_id':identifier,'scenario_id':identifier,'source_order_key':'constructed_'+family,
                  'configuration':variant,'instruction_text':render_policy(ast),'reference_policy':ast}
            out.append({'case_id':identifier,'family':family,'variant':variant,'scenario':scenario,'attributes':attrs,'task':task,
                        'decision_opportunity':variant==0,'expected_single_count':expected_single,
                        'expected_search_count':expected_search,'expected_allowed_orders':orders,
                        'expected_no_progress_gain':variant in (1,2) and expected_single==expected_search,
                        'expectation_source':'declared dimensions, direct-contact separation and arithmetic loads; human review pending'})
    return out


def independent_enumerate(case,config):
    """Exhaust small Top-K tree, using independent physics/reference, no search/executor."""
    scenario=case['scenario'];attrs=case['attributes'];ast=case['task']['reference_policy']
    s=initial(scenario['container'],3)
    for b in scenario['items']:s=receive(s,b,attrs[b['item_id']])
    req=observation(s,case['task']['instruction_text'])
    candidates_log=[];paths=[];nodes=0
    def visit(placed,pending,path):
        nonlocal nodes
        nodes+=1;paths.append(path)
        for b in pending:
            raw_state={'request_id':'O4F_ENUM','container':scenario['container'],'placed_items':placed,'available_items':[b]}
            generated=ExtremePointGenerator(config).generate(PalletState.from_dict(raw_state)).candidate_set.data['candidates']
            public_req=copy.deepcopy(req)
            # Restore public placed facts independently from source objects and chosen poses.
            source={o['object_id']:o for o in req['available_objects']}
            public_req['placed_objects']=[{**copy.deepcopy(source[p['item_id']]),'pose':p['pose'],'oriented_size_mm':p['oriented_size_mm']} for p in placed]
            public_req['available_objects']=[source[b['item_id']]]
            audit=audit_reference(public_req,ast,generated)
            candidates_log.append({'path':path,'pick_item_id':b['item_id'],'candidates':generated,'reference':audit})
            for c in generated:
                if c['candidate_id'] not in audit['allowed_ids'] or check_candidate(raw_state,{'container':scenario['container']},c):continue
                after=apply_candidate(raw_state,c)
                visit(after,[p for p in pending if p['item_id']!=b['item_id']],path+[{'item_id':b['item_id'],'pose':c['pose']}])
    visit([],scenario['items'],[])
    best=max(map(len,paths));orders=sorted({tuple(p['item_id'] for p in path) for path in paths if len(path)==best})
    return {'max_placed_count':best,'best_orders':[list(x) for x in orders],'nodes':nodes,'candidate_tree':candidates_log,
            'scope':'independent exhaustive frozen Top-K small-case tree; no claim about continuous global optimum'}


def run_constructs(config):
    rows=[]
    for c in construct_cases():
        single,se,_=episode(c['scenario'],c['attributes'],c['task'],'single_greedy','oracle_ast',config)
        buffered,be,_=episode(c['scenario'],c['attributes'],c['task'],'buffer_search','oracle_ast',config)
        brute=independent_enumerate(c,config)
        order_ok=c['expected_allowed_orders'] is None or buffered['placed_sequence'] in c['expected_allowed_orders']
        passed=(single['placed_items']==c['expected_single_count'] and buffered['placed_items']==c['expected_search_count']
                and brute['max_placed_count']==c['expected_search_count'] and order_ok
                and buffered['physical_violations']==buffered['final_business_violation_count']==0
                and all(x<=256 for x in buffered['search_evaluations']))
        rows.append({**c,'single':single,'search':buffered,'single_events':se,'search_events':be,
                     'independent':brute,'passed':passed,'progress_gain':buffered['placed_items']-single['placed_items'],
                     'reordered':buffered['placed_sequence']!=c['scenario']['arrival_order'][:buffered['placed_items']]})
    return rows
