"""Declared E1 arithmetic gold/negative/paired/order fixtures, no interpreters."""
import copy
from ..fixtures import item, rule, policy as old_policy, CONTAINER, eq
from ..buffer.buffer_state import initial, receive, place
from .protocol import POLICY, observation
from .compiler import render_policy


def region(identifier='R', x0=-150., x1=150., y0=-150., y1=150.):
    return dict(region_id=identifier, x_min_mm=x0, x_max_mm=x1, y_min_mm=y0, y_max_mm=y1)


def spatial(identifier='region', target=None, region_id='R'):
    return dict(rule_id=identifier, type='inside_region', target=copy.deepcopy(target or {'all': True}),
                region_id=region_id, priority=20, overrides=[])


def policy(rules):
    return {'schema_version': POLICY, 'rules': copy.deepcopy(rules)}


def make_item(identifier, **kwargs):
    obj = item(identifier, **kwargs)
    attrs = obj.pop('_attributes')
    obj.update(supported_load_kg=0., support_fractions=[])
    return obj, attrs


def request(available=None, placed=(), ast=None, regions=None, capacity=1):
    available = available or [make_item('box')]
    s = initial(CONTAINER, capacity)
    # Gold placed records are arithmetic fixtures, not a simulator result.
    for obj, attrs in placed:
        s['arrived_ids'].append(obj['item_id']); s['attributes'][obj['item_id']] = copy.deepcopy(attrs)
        s['placed_items'].append(copy.deepcopy(obj)); s['arrival_count'] += 1; s['placed_count'] += 1
    for obj, attrs in available:
        s = receive(s, obj, attrs)
    ast = ast or policy([spatial()])
    return observation(s, render_policy(ast), regions or [region()]), s


def candidate(x=0., y=0., z=0., size=(100,100,100), yaw=0, pick='box', identifier='C'):
    return {'candidate_id': identifier, 'pick_item_id': pick,
            'pose': {'x_mm': x, 'y_mm': y, 'z_base_mm': z, 'yaw_deg': yaw}, 'oriented_size_mm': list(size)}


def gold_cases():
    # Expectations below are declared from rectangle coordinates, not runtime.
    cases = [('center', 0, 0, True)]
    cases += [(name, x, y, True) for name, x, y in (
        ('left_edge',-100,0), ('right_edge',100,0), ('front_edge',0,-100), ('back_edge',0,100),
        ('corner_lf',-100,-100), ('corner_lb',-100,100), ('corner_rf',100,-100), ('corner_rb',100,100))]
    for axis in ('x', 'y'):
        for sign in (-1, 1):
            for delta, good in ((.5e-6, True), (2e-6, False)):
                coordinate = sign*(100+delta)
                cases.append((f'{axis}_{sign}_{delta}', coordinate if axis=='x' else 0., coordinate if axis=='y' else 0., good))
    cases += [('center_inside_but_corner_out',125,0,False)]
    out = []
    for name, x, y, expected in cases:
        ast = policy([spatial()]); req, _ = request(ast=ast)
        out.append(dict(case_id=f'E1_G{len(out)+1:02d}', purpose=name, request=req, reference_policy=ast,
                        candidates=[candidate(x,y)], expected_allowed_ids=['C'] if expected else [],
                        proof='100mm box half-width=50; rectangle half-width=150; |center|<=100+1e-6'))
    ast = policy([spatial()]); req, _ = request(available=[make_item('box',size=(400,100,100))],ast=ast)
    out.append(dict(case_id='E1_G19',purpose='oversize',request=req,reference_policy=ast,candidates=[candidate(size=(400,100,100))],expected_allowed_ids=[],proof='400>300 along x'))
    ast = policy([spatial(target=eq('cargo_category','food'))]);req,_=request(ast=ast)
    out.append(dict(case_id='E1_G20',purpose='empty_target',request=req,reference_policy=ast,candidates=[candidate(x=300)],expected_allowed_ids=['C'],proof='general is not food; zero applicable instances'))
    ast = policy([spatial(),spatial('small',region_id='S')]);req,_=request(ast=ast,regions=[region(),region('S',-60,60,-60,60)])
    out.append(dict(case_id='E1_G21',purpose='intersect_regions',request=req,reference_policy=ast,candidates=[candidate(x=30)],expected_allowed_ids=[],proof='box right edge80>small region60'))
    base=make_item('base');ast=policy([spatial()]);req,_=request(placed=[base],ast=ast)
    out.append(dict(case_id='E1_G22',purpose='stacking_allowed',request=req,reference_policy=ast,candidates=[candidate(z=100)],expected_allowed_ids=['C'],proof='region applies to xy projection; z does not forbid stacking'))
    ast=policy([spatial(),rule('load','no_top_load',target={'object_ids':['base']})]);req,_=request(placed=[base],ast=ast)
    out.append(dict(case_id='E1_G23',purpose='old_no_top_combination',request=req,reference_policy=ast,candidates=[candidate(z=100)],expected_allowed_ids=[],proof='1kg on zero-limit base; region valid'))
    ast=policy([spatial(),rule('contact','forbidden_contact')]);req,_=request(available=[make_item('box',category='household_cleaner')],placed=[make_item('base',category='food')],ast=ast)
    out.append(dict(case_id='E1_G24',purpose='old_contact_combination',request=req,reference_policy=ast,candidates=[candidate(x=100)],expected_allowed_ids=[],proof='faces touch at x50, overlap y/z positive; region valid'))
    return out


def invalid_cases():
    req,_=request();ast=policy([spatial()]);rows=[]
    def add(name,kind,payload):rows.append({'case_id':f'E1_BAD{len(rows)+1:02d}','purpose':name,'kind':kind,'payload':payload})
    for name,field,value in [('unknown_region','region_id','missing'),('new_overrides','overrides',['region']),('unknown_rule','type','label_facing_outward'),('priority_bool','priority',True),('extra_field','unknown',1)]:
        p=copy.deepcopy(ast);p['rules'][0][field]=value;add(name,'policy',p)
    p=copy.deepcopy(ast);p['rules'][0]['target']={'object_ids':['future']};add('unknown_object','policy',p)
    p=copy.deepcopy(ast);p['rules'][0]['target']={'eq':{'field':'cargo_category','value':'cleaning_supplies'}};add('category_enum','policy',p)
    p=copy.deepcopy(ast);p['rules'][0]['target']={'eq':{'field':'mass_kg','value':True}};add('numeric_bool','policy',p)
    for name,mutate in [('reversed_bounds',lambda p:p['regions'][0].update(x_min_mm=200)),('non_top_label',lambda p:p.update(placement_convention='label_pos_x')),('stale_state',lambda p:p.update(state_hash='0'*64)),('oversized_capacity',lambda p:p['buffer_context'].update(capacity=4))]:
        p=copy.deepcopy(req);mutate(p);add(name,'observation',p)
    return rows


def pair_cases():
    from ...config import generator_config, load_config
    from ...domain import internal_item
    from ...planner.constraints import evaluate_pose
    settings=generator_config(load_config());settings['container']=CONTAINER
    rows=[]
    regions=[region('L',-400,-100,-150,150),region('R',100,400,-150,150)]
    for i in range(12):
        ast=policy([spatial(region_id='L'),rule('load',limit=5.)]);req,s=request(ast=ast,regions=regions)
        candidates=[]
        for x,identifier in ((-250,'LEFT'),(250,'RIGHT')):
            raw,reason=evaluate_pose(internal_item(s['pending_items'][0]['item']),[],x-50,-50,0,100,100,0,settings)
            if raw is None:raise AssertionError(reason)
            c=raw['visible'];c['candidate_id']=identifier;candidates.append(c)
        other=copy.deepcopy(req);expected=copy.deepcopy(ast)
        if i<6:
            other['instruction_text']=render_policy(ast,True)
            if i==0:other['instruction_text']='\n  '+other['instruction_text']+'\n'
            if i==1:other['regions'].reverse()
            if i==2:other['request_id']='renamed_request'
            if i==3:
                for r in expected['rules']:r['rule_id']='renamed_'+r['rule_id']
                other['instruction_text']=render_policy(expected,True)
            if i==4:
                expected['rules'].reverse();other['instruction_text']=render_policy(expected)
            if i==5:
                ast['rules'][0]['target']={'and':[{'all':True},{'not':eq('cargo_category','food')}]}
                req['instruction_text']=render_policy(ast)
                expected=copy.deepcopy(ast);expected['rules'][0]['target']['and'].reverse()
                other['instruction_text']=render_policy(expected)
        else:
            if i<8:expected['rules'][0]['region_id']='R'
            elif i<10:
                other['regions'][0]=region('L',100,400,-150,150)
            else:expected['rules'][0]['target']=eq('cargo_category','food' if i==10 else 'glassware')
            other['instruction_text']=render_policy(expected,True)
        from .protocol import rebind
        rows.append({'pair_id':f'E1_PAIR{i+1:02d}','kind':'invariant' if i<6 else 'changed',
                     'variants':[{'request':rebind(req),'reference_policy':ast},{'request':rebind(other),'reference_policy':expected}],
                     'candidates':candidates,'expected_allowed':[['LEFT'],['LEFT'] if i<6 else ['RIGHT'] if i<10 else ['LEFT','RIGHT']],
                     'expected_action_change':6<=i<10,
                     'proof':'two 100mm floor boxes at +/-250; public regions L=[-400,-100],R=[100,400]'})
    return rows


def construct_cases():
    rows=[]
    for index in range(12):
        objects=[make_item(f'b{i}', category=('glassware' if i%2 else 'general'),reinforced=bool(i%2),label=20.) for i in range(4)]
        ast=policy([spatial()]);reg=region();extra=[]
        if index==1:
            reg=region(x0=-330,x1=-30,y0=-100,y1=200)
            objects=[make_item(f'b{i}',size=(90,110,80),label=20.) for i in range(4)]
        elif index==2:reg=region(x0=-200,x1=200,y0=-60,y1=60)
        elif index==3:reg=region(x0=-50,x1=50,y0=-50,y1=50)
        elif index==4:reg=region(x0=-20,x1=20,y0=-20,y1=20)
        elif index==5:reg=region(x0=-30,x1=30)
        elif index==6:reg=region(y0=-35,y1=35)
        elif index==7:
            reg=region(x0=-60,x1=60,y0=-60,y1=60)
            ast['rules'].append(rule('no_stack','no_top_load'))
        if index>=8:
            ast['rules'].append(rule('load',limit='label'))
            ast['rules'].append(rule('exception',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True)]},limit=10.,priority=0,overrides=['load']))
            ast['rules'].append(rule('contact','forbidden_contact'))
            if index==8:
                reg=region(x0=-300,x1=300,y0=-300,y1=300)
                objects=[make_item(f'b{i}',category=c,reinforced=c=='glassware',label=20.)
                         for i,c in enumerate(('food','household_cleaner','glassware','general'))]
            elif index==9:
                ast['rules'][0]['target']={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True)]}
                objects.reverse()
            elif index==10:
                ast['rules'].append(rule('no_top','no_top_load',target=eq('labels.no_top_load',True),priority=10,overrides=['load']))
                objects[0][1]['labels']['no_top_load']=True
            else:
                extra=[region('S',-100,100,-150,150)]
                ast['rules'].append(spatial('second_region',region_id='S'))
                objects.reverse()
        rows.append({'task_id':f'E1_ORDER{index+1:02d}','source_order_key':f'constructed_e1_{index+1:02d}',
                     'container':copy.deepcopy(CONTAINER),'items':[o for o,_ in objects],
                     'attributes':{a['object_id']:a for _,a in objects},'regions':[reg,*extra],
                     'reference_policy':ast,'instruction_text':render_policy(ast),
                     'expected_completed':not 4<=index<8,
                     'proof':('region width/height below100 forbids a 100mm bottom' if 4<=index<=6 else
                              '120mm square fits at most one 100mm box per layer; no_top_load forbids stacking' if index==7 else
                              'explicit floor or stacked placement within the declared region; no relative-direction or label-outward assumptions'),
                     'geometry_case':index,'role':'positive' if index<4 else 'negative' if index<8 else 'combination_and_order'})
    return rows


def dataset():
    return {'version':'o4_e1_development_data_v1','gold':gold_cases(),'invalid':invalid_cases(),
            'pairs':pair_cases(),'constructs':construct_cases(),
            'independence':'Constructed engineering coverage, not independent unseen orders; repeated geometry is disclosed.',
            'remote_calls':0}
