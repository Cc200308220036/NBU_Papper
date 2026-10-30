"""Frozen-source adaptation and declared E5 business specifications, no planner."""
import copy
import hashlib
from pathlib import Path
from ...common import read,digest,O4Error
from ...fixtures import eq,rule,CONTAINER
from ..e2.data import policy,relative,object_at,request,candidate
from ..data import region,spatial
from ..e2.compiler import render_policy
from ..e2.protocol import validate_policy
from ..e2.experiment import verify_seal

F_BASELINE='semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01'
DIRECTIONS=('left_of','right_of','front_of','behind')
FOOD=eq('cargo_category','food');CLEAN=eq('cargo_category','household_cleaner')


def regions_for(container):
    l,w=container['length_mm'],container['width_mm']
    return [region('L',-l/2,l/4,-w/2,w/2),region('R',-l/4,l/2,-w/2,w/2),
            region('F',-l/2,l/2,-w/2,w/4),region('B',-l/2,l/2,-w/4,w/2)]


def rules_for(index,configuration):
    a,b=(('L','R'),('R','L'),('F','B'),('B','F'))[index%4]
    rules=[rule('label',limit='label'),rule('no_top','no_top_load',eq('labels.no_top_load',True),priority=10,overrides=['label']),
           rule('reinforced',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True),eq('labels.no_top_load',False)]},limit=2.,priority=0,overrides=['label']),
           rule('contact','forbidden_contact'),spatial('food_region',FOOD,a),spatial('cleaner_region',CLEAN,b)]
    if configuration==1:rules.append(relative('relation',direction=DIRECTIONS[index%4],gap=50.))
    elif configuration!=0:raise O4Error('invalid_configuration')
    result=policy(rules);validate_policy(result);return result


def source_tasks(workspace):
    workspace=Path(workspace);baseline=workspace/F_BASELINE;verify_seal(baseline)
    path=baseline/'private/input_snapshot.json';snapshot=read(path);sources=sorted(snapshot['data']['sources'],key=lambda r:str(r['source_order_key']))
    if len(sources)!=12 or len({str(r['source_order_key']) for r in sources})!=12:raise O4Error('invalid_source_registry')
    tasks=[];registry=[]
    for index,source in enumerate(sources):
        sid=source['scenario_id'];scenario=snapshot['scenarios'][sid];attrs=snapshot['data']['attributes'][sid]
        if attrs['attribute_source']!='synthetic':raise O4Error('unknown_attribute_source')
        arrival=scenario['arrival_order'];items={o['item_id']:o for o in scenario['items']}
        if len(items)!=len(scenario['items']) or len(set(arrival))!=len(arrival) or any(i not in items for i in arrival) or len(arrival)<4:
            raise O4Error('invalid_source_arrivals',sid)
        selected=arrival[:12];attributes={i:copy.deepcopy(attrs['objects'][i]) for i in selected}
        provenance={'source_order_key':str(source['source_order_key']),'scenario_id':sid,'source_path':str(path.relative_to(workspace)),
                    'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'scenario_digest':digest(scenario),
                    'attribute_digest':digest(attrs),'attribute_source':'synthetic','role':'development',
                    'original_arrival_order':arrival,'selected_arrival_order':selected,'planned_items':len(selected)}
        registry.append(provenance)
        for configuration in (0,1):
            ast=rules_for(index,configuration)
            tasks.append({'task_id':f'E5_SRC{index:02d}_C{configuration}','source_order_key':str(source['source_order_key']),
                          'source_kind':'development_order','source_index':index,'scenario_id':sid,'configuration':configuration,
                          'container':copy.deepcopy(scenario['container']),'items':[copy.deepcopy(items[i]) for i in selected],
                          'attributes':copy.deepcopy(attributes),'regions':regions_for(scenario['container']),
                          'reference_policy':ast,'instruction_text':render_policy(ast),'provenance':provenance})
    return registry,tasks


def construct_tasks():
    """Four legal mixed orders and two independently provable contradictions."""
    tasks=[]
    for index in range(6):
        ast=rules_for(index%4,1)
        # Zero observed load on a deliberately no-top general item, and a
        # reinforced glassware item make all five rule families nonempty.
        items=[object_at('A','food',label=20.),object_at('B','household_cleaner',label=20.),
               object_at('C','general',label=20.,no_top=True),object_at('D','glassware',label=20.,reinforced=True)]
        coordinates=[(-300,0,0),(0,0,0),(300,-250,0),(300,250,0)]
        if index%4==1:coordinates=[(300,0,0),(0,0,0),(-300,-250,0),(-300,250,0)]
        elif index%4==2:coordinates=[(0,-300,0),(0,0,0),(-250,300,0),(250,300,0)]
        elif index%4==3:coordinates=[(0,300,0),(0,0,0),(-250,-300,0),(250,-300,0)]
        if index==4:
            # A< B and B< A cannot both hold for distinct positive-width boxes.
            ast['rules'].append(relative('cycle',subject=CLEAN,reference=FOOD,gap=50.))
        elif index==5:
            ast['rules'][-1]['min_gap_mm']=1100.
        expected={m:index<4 for m in ('single','buffer_fifo','buffer_heuristic','buffer_search')}
        tasks.append({'task_id':f'E5_CONSTRUCT{index+1:02d}','source_order_key':f'constructed_e5_{index+1:02d}',
                      'source_kind':'constructed','configuration':'mixed_guard','container':copy.deepcopy(CONTAINER),
                      'items':[o for o,a in items],'attributes':{a['object_id']:a for o,a in items},
                      'regions':regions_for(CONTAINER),'reference_policy':ast,'instruction_text':render_policy(ast),
                      'expected_by_planner':expected,'manual_witness_xyz':coordinates,'negative':index>=4,
                      'proof':'opposing positive-width pair' if index==4 else '200+1100>1000' if index==5 else 'manual AABB gaps300-100=200, floor-only load0; disjoint contact and declared regions'})
    return tasks


def mixed_gold():
    """Six allowed/six rejected, with active loads, exceptions and conjunction."""
    rows=[];regs=regions_for(CONTAINER)
    def add(purpose,ast,placed,available,candidates,allowed,proof,regions=None,components=None):
        q,_=request(ast,placed=placed,available=available,regions=regs if regions is None else regions)
        rows.append({'case_id':f'E5_G{len(rows)+1:02d}','purpose':purpose,'reference_policy':ast,'request':q,
                     'candidates':candidates,'expected_allowed_ids':allowed,'proof':proof,
                     'component_allowed_ids':components or {}})
    for index,direction in enumerate(DIRECTIONS):
        x,y=((-200,0),(200,0),(0,-200),(0,200))[index]
        add('region_relation_'+direction,rules_for(index,1),[object_at('B','household_cleaner')],
            [object_at('A','food',label=20.)],[candidate(x=x,y=y)],['C'],
            '100mm boxes with center separation200: gap100>=50; declared regions contain both footprints, floor-only load0')
    add('wrong_left_direction',rules_for(0,1),[object_at('B','household_cleaner')],[object_at('A','food')],
        [candidate(x=200)],[],'A x range[150,250], B[-50,50]: A is not left of B even though food regionL contains its footprint')
    ast=policy([relative(gap=0),spatial('region',FOOD,'L'),rule('contact','forbidden_contact')])
    add('zero_gap_does_not_cancel_contact',ast,[object_at('B','household_cleaner')],[object_at('A','food')],
        [candidate(x=-100)],[],'A xmax=-50 equals B xmin=-50: relative gap0 and region true, but positive-area food/cleaner face contact is forbidden')
    ast=policy([relative(),spatial('region',FOOD,'R')])
    add('individually_feasible_disjoint_allowed_sets',ast,[object_at('B','household_cleaner')],[object_at('A','food')],
        [candidate(x=-200,identifier='C_LEFT'),candidate(x=200,identifier='C_RIGHT')],[],
        'left relation alone allows C_LEFT; regionR=[-100,300] alone allows C_RIGHT; empty intersection, both poses independently floor-physical',
        regions=[region('R',-100,300,-100,100)],components={'rel':['C_LEFT'],'region':['C_RIGHT']})
    for mass,good in [(2.,True),(3.,False)]:
        ast=policy([relative(subject=eq('cargo_category','glassware'),gap=50),spatial('region',eq('cargo_category','glassware'),'L'),
                    rule('load',target=eq('cargo_category','general'),limit=2.)])
        add('load_and_relative',ast,[object_at('B','household_cleaner'),object_at('T','general',x=-200)],
            [object_at('A','glassware',mass=mass)],[candidate(x=-200,z=100)],['C'] if good else [],
            'A rests fully on T, gap100 to cleaner B; T load equals A mass, allowed2kg/rejected3kg under business cap2, physical cap100')
    for mass,no_top,good in [(2.,False,True),(3.,False,False),(1.,True,False)]:
        ast=policy([relative(gap=50),spatial('region',FOOD,'L'),rule('label',limit='label'),
             rule('no_top','no_top_load',eq('labels.no_top_load',True),priority=10,overrides=['label']),
             rule('reinforced',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True),eq('labels.no_top_load',False)]},limit=2.,priority=0,overrides=['label']),
             rule('contact','forbidden_contact')])
        add('reinforced_exception_and_no_top_with_region',ast,
            [object_at('B','household_cleaner'),object_at('T','glassware',x=-200,reinforced=True,no_top=no_top,label=5.)],
            [object_at('A','food',mass=mass)],[candidate(x=-200,z=100)],['C'] if good else [],
            'A inside regionL and gap100 to B; glass reinforced T label5 is overridden to2 when no_top false, so2 allowed/3 rejected; no_top true overrides to0 and excludes reinforced exception, rejecting1kg')
    return rows
