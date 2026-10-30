"""E2 declared engineering cases and arithmetic witnesses, no interpreters."""
import copy
from ...fixtures import CONTAINER,eq,rule
from ...buffer.buffer_state import initial,receive
from ..data import region,spatial,make_item
from .protocol import POLICY,observation,rebind
from .compiler import render_policy


def policy(rules):return {'schema_version':POLICY,'rules':copy.deepcopy(rules)}


def relative(identifier='rel',subject=None,reference=None,direction='left_of',gap=0.):
    return {'rule_id':identifier,'type':'relative_position','subject':copy.deepcopy(subject if subject is not None else eq('cargo_category','food')),
            'reference':copy.deepcopy(reference if reference is not None else eq('cargo_category','household_cleaner')),
            'relation':direction,'min_gap_mm':gap,'priority':20,'overrides':[]}


def object_at(identifier,category='general',x=0.,y=0.,z=0.,**kwargs):
    obj,attrs=make_item(identifier,category=category,x=x,z=z,**kwargs);obj['pose']['y_mm']=y
    return obj,attrs


def request(ast,placed=(),available=None,regions=(),capacity=1,container=None):
    available=[object_at('A','food')] if available is None else available
    s=initial(container or CONTAINER,capacity)
    for obj,attrs in placed:
        s['arrived_ids'].append(obj['item_id']);s['attributes'][obj['item_id']]=copy.deepcopy(attrs)
        s['placed_items'].append(copy.deepcopy(obj));s['arrival_count']+=1;s['placed_count']+=1
    for obj,attrs in available:s=receive(s,obj,attrs)
    return observation(s,render_policy(ast),list(regions)),s


def candidate(x=0.,y=0.,pick='A',identifier='C',z=0.,size=(100,100,100)):
    return {'candidate_id':identifier,'pick_item_id':pick,'pose':{'x_mm':x,'y_mm':y,'z_base_mm':z,'yaw_deg':0},'oriented_size_mm':list(size)}


def gold_cases():
    rows=[]
    for direction,axis,sign in (('left_of','x',-1),('right_of','x',1),('front_of','y',-1),('behind','y',1)):
        for label,gap,distance,good in (('touch',0.,100.,True),('gap_exact',50.,150.,True),('eps_inside',50.,149.9999995,True),('eps_outside',50.,149.999998,False)):
            ast=policy([relative(direction=direction,gap=gap)])
            q,_=request(ast,placed=[object_at('B','household_cleaner')]);c=candidate(x=sign*distance if axis=='x' else 0,y=sign*distance if axis=='y' else 0)
            rows.append({'case_id':f'E2_G{len(rows)+1:02d}','purpose':f'{direction}_{label}','request':q,'reference_policy':ast,'candidates':[c],
                         'expected_allowed_ids':['C'] if good else [],'proof':f'100mm boxes: oriented center separation {distance} minus100 is clearance; required gap{gap} with eps1e-6'})
    def add(purpose,ast,placed,available,c,good,proof,regions=(),capacity=1):
        q,_=request(ast,placed,available,regions,capacity)
        rows.append({'case_id':f'E2_G{len(rows)+1:02d}','purpose':purpose,'request':q,'reference_policy':ast,'candidates':[c],
                     'expected_allowed_ids':['C'] if good else [],'proof':proof})
    b=object_at('B','household_cleaner');a=object_at('A','food')
    add('center_order_does_not_imply_bbox_order',policy([relative()]),[b],[a],candidate(x=-20,y=200),False,'x center -20<0 but A xmax30>B xmin-50; y separation makes this physically collision-free')
    add('swapped_roles',policy([relative(subject=eq('cargo_category','household_cleaner'),reference=eq('cargo_category','food'))]),[b],[a],candidate(x=-200),False,'B at0 cannot be left of A at-200')
    add('all_pairs_not_exists',policy([relative()]),[b,object_at('S','food',x=100,y=200)],[a],candidate(x=-200),False,'A is left of B, but S xmax150>B xmin-50; all ordered pairs required')
    add('self_pairs_excluded',policy([relative(subject={'all':True},reference={'all':True})]),[],[a],candidate(),True,'one object has no distinct ordered pair; never compare object to itself')
    add('missing_reference_deferred',policy([relative(reference=eq('cargo_category','electronics'))]),[b],[a],candidate(x=-200),True,'no electronics is observed; do not invent future pose or certify relation satisfied')
    add('pending_reference_deferred',policy([relative()]),[],[a,b],candidate(),True,'A placed, B still in buffer; pair deferred until B has a pallet pose',capacity=3)
    add('region_and_relative_conjunction',policy([relative(),spatial()]),[b],[a],candidate(x=-200),False,'left relation true but A bottom[-250,-150] is not contained in region[-150,150]',regions=[region()])
    add('reference_arrives_second_and_old_rules',policy([relative(gap=50),rule('contact','forbidden_contact'),rule('load',limit='label'),spatial()]),
        [object_at('A','food',x=-150)],[object_at('B','household_cleaner')],candidate(pick='B'),True,
        'A right edge-100, B left edge-50 =>50mm gap; no contact; zero top load; both inside region[-300,300]',regions=[region(x0=-300,x1=300,y0=-300,y1=300)])
    return rows


def invalid_cases():
    ast=policy([relative()]);q,_=request(ast,placed=[object_at('B','household_cleaner')]);rows=[]
    def add(name,kind,p):rows.append({'case_id':f'E2_BAD{len(rows)+1:02d}','purpose':name,'kind':kind,'payload':p})
    for name,field,val in (('negative_gap','min_gap_mm',-1),('boolean_gap','min_gap_mm',True),('string_gap','min_gap_mm','50mm'),('unknown_direction','relation','above'),('new_overrides','overrides',['rel']),('extra_field','center_comparison',True)):
        p=copy.deepcopy(ast);p['rules'][0][field]=val;add(name,'policy',p)
    p=copy.deepcopy(ast);p['rules'][0]['subject']={'object_ids':['future']};add('unknown_subject','policy',p)
    p=copy.deepcopy(ast);p['rules'][0]['reference']={'eq':{'field':'mass_kg','value':False}};add('reference_type','policy',p)
    p=copy.deepcopy(ast);p['rules'].append(copy.deepcopy(p['rules'][0]));add('duplicate_rule','policy',p)
    p=copy.deepcopy(q);p['sampling_grid_mm']=[0,999];add('unsupported_sampling_grid','observation',p)
    p=copy.deepcopy(q);p['placed_objects'][0]['pose']['yaw_deg']=180;add('unsupported_yaw','observation',p)
    p=copy.deepcopy(q);p['buffer_context']['end_of_stream']=True;add('stale_eos_binding','observation',p)
    return rows


def physical_candidates(state,poses,pick='A'):
    from ....config import generator_config,load_config
    from ....domain import internal_item,restore_placed
    from ....planner.constraints import evaluate_pose
    settings=generator_config(load_config());settings['container']=state['container'];obj=next(p['item'] for p in state['pending_items'] if p['item']['item_id']==pick)
    item=internal_item(obj);placed=restore_placed(state['placed_items']);out=[]
    for identifier,x,y in poses:
        raw,reason=evaluate_pose(item,placed,x-50,y-50,0,100,100,0,settings)
        if raw is None:raise AssertionError((identifier,reason))
        c=raw['visible'];c['candidate_id']=identifier;out.append(c)
    return out


def pair_cases():
    rows=[]
    for i in range(12):
        direction='left_of' if i%2==0 else 'front_of'
        ast=policy([relative(direction=direction)])
        q,s=request(ast,placed=[object_at('B','household_cleaner')])
        poses=[('NEG',-200,0),('POS',200,0)] if i%2==0 else [('NEG',0,-200),('POS',0,200)]
        c=physical_candidates(s,poses);other=copy.deepcopy(q);expected=copy.deepcopy(ast)
        if i<6:
            if i==0:other['instruction_text']='\n '+render_policy(ast,True)+'\n'
            elif i==1:expected['rules'][0]['rule_id']='renamed'
            elif i in (2,3):
                r=expected['rules'][0];r['subject'],r['reference']=r['reference'],r['subject'];r['relation']='right_of' if direction=='left_of' else 'behind'
            elif i==4:other['request_id']='different_request_identity'
            else:
                ast['rules'][0]['subject']={'and':[eq('cargo_category','food'),{'not':eq('packaging.reinforced',True)}]}
                q['instruction_text']=render_policy(ast);expected=copy.deepcopy(ast);expected['rules'][0]['subject']['and'].reverse()
            if i!=0:other['instruction_text']=render_policy(expected,True)
            allowed=[['NEG'],['NEG']];action=False
        else:
            if i<10:
                expected['rules'][0]['relation']='right_of' if direction=='left_of' else 'behind';allowed=[['NEG'],['POS']];action=True
            else:
                expected['rules'][0]['min_gap_mm']=150.;allowed=[['NEG'],[]];action=True
            other['instruction_text']=render_policy(expected,True)
        rows.append({'pair_id':f'E2_PAIR{i+1:02d}','kind':'invariant' if i<6 else 'changed',
                     'variants':[{'request':rebind(q),'reference_policy':ast},{'request':rebind(other),'reference_policy':expected}],
                     'candidates':c,'expected_allowed':allowed,'expected_action_change':action,
                     'proof':'B at origin; +/-200 centers produce100mm clearance; opposite direction flips legal position; gap150 rejects both'})
    return rows


def construct_cases():
    rows=[]
    for i in range(12):
        objects=[object_at('A','food',label=20.),object_at('B','household_cleaner',label=20.),object_at('C','general',label=20.),object_at('D','glassware',reinforced=True,label=20.)]
        ast=policy([relative()]);container=copy.deepcopy(CONTAINER);regions=[region('R',-400,400,-400,400)]
        expected={m:True for m in ('single','buffer_fifo','buffer_heuristic','buffer_search')}
        witness=[(-300,-200,0),(0,0,0),(300,-200,0),(300,200,0)]
        role='positive'
        if i==1:objects[0],objects[1]=objects[1],objects[0];witness=[(0,0,0),(-300,-200,0),(300,-200,0),(300,200,0)]
        elif i in (2,3):
            axis='x' if i==2 else 'y';container.update(length_mm=500 if axis=='x' else 100,width_mm=100 if axis=='x' else 500,max_height_mm=100)
            regions=[region('R',-250,250,-50,50),region('M',-50,50,-50,50)] if axis=='x' else [region('R',-50,50,-250,250),region('M',-50,50,-50,50)]
            ast=policy([relative(direction='left_of' if axis=='x' else 'front_of',gap=50),spatial('middle',target=eq('cargo_category','household_cleaner'),region_id='M')])
            expected['single']=expected['buffer_fifo']=False
            witness=[(-200,0,0),(0,0,0),(-100,0,0),(100,0,0)] if axis=='x' else [(0,-200,0),(0,0,0),(0,-100,0),(0,100,0)]
            role='joint_opportunity'
        elif 4<=i<8:
            expected={m:False for m in expected};role='negative'
            if i<6:
                ast['rules'].append(relative('cycle',subject=eq('cargo_category','household_cleaner'),reference=eq('cargo_category','food')))
                if i==5:objects[0],objects[1]=objects[1],objects[0]
            else:
                ast['rules'][0]['min_gap_mm']=1100.
                if i==7:objects[0],objects[1]=objects[1],objects[0]
            witness=[]
        elif i>=8:
            role='combination_and_order';ast['rules'] += [spatial(),rule('load',limit='label'),rule('contact','forbidden_contact'),
                rule('exception',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True)]},limit=10.,priority=0,overrides=['load'])]
            if i==9:
                ast['rules'][0]['relation']='right_of';witness=[(300,-200,0),(0,0,0),(-300,-200,0),(-300,200,0)]
            elif i==10:
                ast['rules'][0]['relation']='front_of';witness=[(-200,-300,0),(0,0,0),(200,300,0),(-200,300,0)]
            elif i==11:
                ast['rules'][0]['relation']='behind';witness=[(-200,300,0),(0,0,0),(200,-300,0),(-200,-300,0)]
            if i in (9,11):
                objects[0],objects[1]=objects[1],objects[0];witness[0],witness[1]=witness[1],witness[0]
        rows.append({'task_id':f'E2_ORDER{i+1:02d}','source_order_key':f'constructed_e2_{i+1:02d}','container':container,
                     'items':[o for o,a in objects],'attributes':{a['object_id']:a for o,a in objects},'regions':regions,
                     'reference_policy':ast,'instruction_text':render_policy(ast),'role':role,'expected_by_planner':expected,
                     'manual_witness_xyz':witness,'proof':'cyclic strict separation of positive-width boxes is impossible' if 4<=i<6
                     else '1100mm gap cannot fit inside1000mm pallet' if 6<=i<8 else 'manual coordinate sequence independent of generator; xy gap and region/old rules checked separately'})
    return rows


def dataset():
    return {'version':'o4_e2_development_data_v1','gold':gold_cases(),'invalid':invalid_cases(),'pairs':pair_cases(),'constructs':construct_cases(),
            'independence':'Constructed development coverage; geometry reuse and paired orders do not add independent natural sources.','remote_calls':0}
