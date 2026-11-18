"""Executable acceptance diagnostics with declared expected outcomes."""
import copy
from ..common import O4Error,digest
from ..fixtures import item,policy,render_policy,CONTAINER
from ..online.cases import diagnostic_scenario
from .buffer_state import initial,receive,place,public_state,can_wait,physical
from .buffer_protocol import action,validate_action,validate_state
from .buffer_candidates import pools,public_candidates
from .buffer_search import search,validate_config
from .buffer_evaluation import episode,stable,audit_events,submit


def gold_specs():
    return [('initial_1','ok'),('initial_2','ok'),('initial_3','ok'),('capacity_zero','invalid_capacity'),
      ('capacity_four','invalid_capacity'),('receive_slot0','ok'),('receive_slot1','ok'),('receive_slot2','ok'),
      ('full_wait','invalid_wait'),('duplicate_arrival','duplicate_arrival'),('empty_read_eos','ok'),
      ('eos_wait','invalid_wait'),('empty_without_eos','invalid_arrival'),('unknown_pick','invalid_pick'),
      ('empty_pick','invalid_pick'),('place_releases_slot','ok'),('place_does_not_arrive','ok'),
      ('wait_preserves_pallet','ok'),('tail_one','ok'),('tail_two','ok'),('eos_last_arrival','ok'),
      ('search_budget_low','invalid_search_config'),('search_depth_four','invalid_search_config'),('search_beam_nine','invalid_search_config')]


def run_gold(name,config):
    text=render_policy(policy([]));s=initial(CONTAINER,3);a=item('a');attrs=a.pop('_attributes')
    received=lambda state,identifier: receive(state,{**a,'item_id':identifier},{**attrs,'object_id':identifier})
    if name.startswith('initial_'):s=initial(CONTAINER,int(name[-1]));assert s['pending_items']==[]
    elif name.startswith('capacity_'):initial(CONTAINER,0 if name.endswith('zero') else 4)
    elif name.startswith('receive_slot'):
        count=int(name[-1])+1
        for i in range(count):s=received(s,str(i))
        assert [p['slot'] for p in s['pending_items']]==list(range(count))
    elif name=='full_wait':
        for i in range(3):s=received(s,str(i))
        receive(s,a,attrs)
    elif name=='duplicate_arrival':s=receive(s,a,attrs);receive(s,a,attrs)
    elif name=='empty_read_eos':s=receive(s,eos=True);assert s['end_of_stream'] and not s['arrived_ids']
    elif name=='eos_wait':s=receive(s,eos=True);receive(s,a,attrs)
    elif name=='empty_without_eos':receive(s)
    elif name in ('unknown_pick','empty_pick'):
        if name=='unknown_pick':s=receive(s,a,attrs)
        place(s,{'pick_item_id':'future'})
    elif name in ('place_releases_slot','place_does_not_arrive','wait_preserves_pallet'):
        s=receive(s,a,attrs);before=copy.deepcopy(s)
        groups,_=pools(s,text,policy([]),config);candidate=groups[0]['eligible'][0]
        after=place(s,candidate['raw'])
        if name=='place_releases_slot':assert after['pending_items']==[] and len(after['placed_items'])==1
        elif name=='place_does_not_arrive':assert after['arrived_ids']==s['arrived_ids'] and after['arrival_count']==1
        else:
            after=received(after,'b');assert after['placed_items']==place(before,candidate['raw'])['placed_items']
    elif name.startswith('tail_') or name=='eos_last_arrival':
        scenario,attributes,task=diagnostic_scenario();n=1 if name=='tail_one' else 2
        scenario['items']=scenario['items'][:n];scenario['arrival_order']=scenario['arrival_order'][:n]
        task['reference_policy']=policy([]);task['instruction_text']=text
        row,events,_=episode(scenario,attributes,task,'buffer_search','oracle_ast',config,
                            eos_mode='last_arrival' if name=='eos_last_arrival' else 'empty_read',capacity=2 if name=='tail_two' else 3)
        assert row['completed'] and row['placed_items']==n and row['eos_events']==1
        s=events[-1]['after_state']
    else:
        cfg={'search_depth':3,'beam_width':8,'max_successor_evaluations':256}
        cfg[{'search_budget_low':'max_successor_evaluations','search_depth_four':'search_depth','search_beam_nine':'beam_width'}[name]]={'search_budget_low':47,'search_depth_four':4,'search_beam_nine':9}[name]
        validate_config(cfg)
    return s


def gold_results(config):
    rows=[]
    for name,expected in gold_specs():
        code='ok';evidence=None
        try:evidence=run_gold(name,config)
        except O4Error as exc:code=exc.code
        except AssertionError:code='assertion_failed'
        rows.append({'case_id':name,'expected':expected,'actual':code,'passed':code==expected,'evidence':evidence})
    return rows


def diagnostics(config):
    scenario,attributes,task=diagnostic_scenario();rows=[]
    correct,events,_=episode(scenario,attributes,task,'buffer_search','oracle_ast',config)
    wrong,we,_=episode(scenario,attributes,task,'buffer_search','public_parser',config,fault='drop_rules')
    rows.append({'name':'wrong_valid_ast_visible','passed':wrong['final_business_violation_count']>0 and wrong['physical_violations']==0
                 and all(not e.get('response',{}).get('policy_ast',{}).get('rules') for e in we if e['kind']=='PLACE'),
                 'wrong_summary':wrong,'wrong_events':we})
    _,prefix,cp=episode(scenario,attributes,task,'buffer_search','oracle_ast',config,pause_after=2)
    resumed,re,_=episode(scenario,attributes,task,'buffer_search','oracle_ast',config,checkpoint=cp)
    rows.append({'name':'resume','passed':stable(events)==stable(re) and correct==resumed,'checkpoint':cp})
    # Freeze the same actual public state; future order, mass and attributes change only behind environment boundary.
    _,_,cp=episode(scenario,attributes,task,'buffer_search','oracle_ast',config,pause_after=1)
    s=cp['state'];text=task['instruction_text'];ast=task['reference_policy']
    def decide(st):
        groups,audit=pools(st,text,ast,config);c,reason,tr=search(st,text,ast,config,groups,audit)
        return stable({'chosen':c,'reason':reason,'trace':tr})
    first=decide(s);hidden=copy.deepcopy(scenario);hidden['items'][1]['mass_kg']=99.;hidden['arrival_order'][1:]=reversed(hidden['arrival_order'][1:])
    rows.append({'name':'future_mutation_invariant','passed':decide(s)==first,'before':first,'modified_private_future_digest':digest(hidden),
                 'public_state_digest':digest(s)})
    pub=public_state(s,text);groups,_=pools(s,text,ast,config);candidates=public_candidates(groups,pub['buffer_state_hash'])
    for name in ('future_item','reference_layout','wrong_pending_id'):
        malformed=copy.deepcopy(pub)
        if name=='future_item':malformed['future_items']=[scenario['items'][1]]
        elif name=='reference_layout':malformed['reference_layout']={'answer':1}
        else:malformed['pending_items'][0]['object_id']='unknown'
        malformed['buffer_state_hash']=digest({k:v for k,v in malformed.items() if k!='buffer_state_hash'})
        code=None
        try:validate_state(malformed)
        except O4Error as exc:code=exc.code
        rows.append({'name':name,'passed':code is not None,'actual_code':code})
    value=action(pub,'PLACE',pick=candidates[0]['pick_item_id'],label=candidates[0]['candidate_id'],candidates=candidates)
    for name in ('slot','capacity','pending_id'):
        changed=copy.deepcopy(s)
        if name=='slot':changed['pending_items'][0]['slot']=1
        elif name=='capacity':changed['buffer_capacity']=2
        else:
            old=changed['arrived_ids'][0];changed['arrived_ids'][0]='renamed'
            changed['pending_items'][0]['item']['item_id']='renamed'
            changed['attributes']['renamed']=changed['attributes'].pop(old);changed['attributes']['renamed']['object_id']='renamed'
        code=None
        try:validate_action(public_state(changed,text),value,candidates)
        except O4Error as exc:code=exc.code
        rows.append({'name':'stale_'+name,'passed':code=='invalid_binding','actual_code':code})
    # Search storage order and current-state immutability are independent of hidden inputs.
    s=copy.deepcopy(cp['state']);s=receive(s,scenario['items'][1],attributes[scenario['items'][1]['item_id']])
    a=decide(s);before=digest(s);decide(s);unchanged=digest(s)==before;s['pending_items'].reverse();b=decide(s)
    rows.append({'name':'storage_order','passed':a['chosen']==b['chosen'] and a['trace']['chosen_path']==b['trace']['chosen_path']})
    rows.append({'name':'simulation_no_real_mutation','passed':unchanged and before==digest({**s,'pending_items':list(reversed(s['pending_items']))})})
    return rows
