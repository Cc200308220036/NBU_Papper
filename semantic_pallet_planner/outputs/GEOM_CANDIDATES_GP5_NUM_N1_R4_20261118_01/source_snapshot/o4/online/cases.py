"""Predeclared cross-attribute decision opportunities and offline failures."""
import copy
from ..common import O4Error,digest
from ..fixtures import item,rule,policy,task_policy,render_policy,CONTAINER,fixture_request
from ..observation import rebind,build_observation
from ..compiler import compile_policy,response_for
from ..executor import evaluate_candidates
from ..evaluator import audit_reference
from ...domain import internal_item,restore_placed
from ...planner.constraints import evaluate_pose
from ...config import generator_config,load_config
from .planner_adapter import labeled_candidates,select_layout,select_and_commit


def opportunity_cases():
    """Six independently designed pairs, using genuine physical score/metadata."""
    out=[]
    kinds=['no_top_label','label_threshold','cargo_category','reinforced_condition','business_threshold','business_scope']
    settings=generator_config(load_config());settings['container']=CONTAINER
    for index,kind in enumerate(kinds):
        base=item('base',category='general',label=5.)
        top=item('top',mass=1.,category='household_cleaner')
        base.update(supported_load_kg=0.,support_fractions=[])
        ast=task_policy(1) if index==0 else policy([rule(limit='label')])
        if index==2:base['_attributes']['cargo_category']='food';ast=policy([rule(kind='forbidden_contact')])
        if index==3:
            base['_attributes']['cargo_category']='glassware';top['mass_kg']=3.;ast=task_policy(5)
        variants=[]
        for variant in range(2):
            attrs={i['item_id']:copy.deepcopy(i['_attributes']) for i in (base,top)}
            current=copy.deepcopy(ast)
            if index==0:attrs['base']['labels']['no_top_load']=bool(variant)
            elif index==1:attrs['base']['labels']['max_top_load_kg']=0. if variant else 5.
            elif index==2:attrs['base']['cargo_category']='general' if variant==0 else 'food'
            elif index==3:attrs['base']['packaging']['reinforced']=bool(variant)
            elif index==4:current=policy([rule(limit=5. if variant==0 else 0.)])
            elif index==5:current=policy([rule(kind='no_top_load',target={'object_ids':['top' if variant==0 else 'base']})])
            state={'request_id':f'O4C_OPP_{index:02d}_{variant}','container':copy.deepcopy(CONTAINER),
                   'placed_items':[copy.deepcopy(base)],'available_items':[copy.deepcopy(top)]}
            req=build_observation(state,attrs,render_policy(current))
            raw=[]
            for x,y,z in [(0.,0.,100.),(400.,400.,0.)]:
                candidate,reason=evaluate_pose(internal_item(top),restore_placed([base]),x-50,y-50,z,100,100,0,settings)
                if candidate is None:raise AssertionError((kind,reason))
                raw.append(candidate['visible'])
            variants.append({'request':req,'reference_policy':current,'raw_candidates':raw,'state':state,'attributes':attrs})
        out.append({'case_id':f'O4C_OPP_{index:02d}','kind':kind,'variants':variants,
                    'expected_before_z_mm':100.,'expected_after_z_mm':0.,'expected_allowed_set_change':True,
                    'selection_basis':'predeclared geometry/attribute opportunity; no model selection'})
    return out


def run_opportunities(cases=None):
    rows=[]
    for c in cases or opportunity_cases():
        variants=[]
        for v in c['variants']:
            response=compile_policy(v['request'])
            result,placed=select_and_commit(v['state'],v['attributes'],v['request'],v['raw_candidates'],response)
            public,mapping=labeled_candidates(v['raw_candidates'])
            reference=audit_reference(v['request'],v['reference_policy'],public)
            selected=mapping[result['committed_label']] if result['committed_label'] else None
            variants.append({'request':v['request'],'response':response,**result,
                             'selected_pose':selected['pose'] if selected else None,
                             'reference_allowed':reference['allowed_ids'],'after_placed':placed})
        a,b=variants
        passed=(a['reference_allowed']!=b['reference_allowed'] and
                a['method_evaluation']['allowed_ids']==a['reference_allowed'] and
                b['method_evaluation']['allowed_ids']==b['reference_allowed'] and
                a['selected_pose'] is not None and b['selected_pose'] is not None and
                a['selected_pose']['z_base_mm']==c['expected_before_z_mm'] and
                b['selected_pose']['z_base_mm']==c['expected_after_z_mm'] and
                not a['physical_errors'] and not b['physical_errors'])
        rows.append({'case_id':c['case_id'],'kind':c['kind'],'passed':passed,
                     'allowed_set_changed':a['reference_allowed']!=b['reference_allowed'],
                     'action_changed':a['selected_pose']!=b['selected_pose'],'variants':variants})
    return rows


def diagnostic_scenario():
    """Fully declared 3-box order: small heavy first, then covering boxes.

    Constrained pallet makes the second box stack; the first has a no-top label.
    A valid empty AST must visibly commit a reference-business violation.
    """
    container=copy.deepcopy(CONTAINER)
    container.update(length_mm=100,width_mm=100,max_height_mm=400)
    items=[item('first',mass=1.,no_top=True),item('second',mass=1.),item('third',mass=1.)]
    for i in items:
        i['supported_load_kg']=0.;i['support_fractions']=[]
    attrs={i['item_id']:i.pop('_attributes') for i in items}
    scenario={'scenario_id':'O4C_DIAG','container':container,'items':items,
              'arrival_order':[i['item_id'] for i in items],'buffer_size':1}
    ast=task_policy(1)
    task={'task_id':'O4C_DIAG','scenario_id':'O4C_DIAG','source_order_key':'constructed',
          'configuration':1,'instruction_text':render_policy(ast),'reference_policy':ast}
    return scenario,attrs,task
