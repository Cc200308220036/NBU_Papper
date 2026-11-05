"""Explicit packaging runtime adapters over the existing shared J4 machinery.

No new physical solver or candidate generator. Local smoke selectors are test
substitutes only, with no remote transport or memory loading route.
"""
from __future__ import annotations
import copy
import math
import random
from pathlib import Path

from .contracts import (JevSelectError, CandidateBundle, DecisionContext,
                        PublicPolicyContext, digest, canonical, validate_schema)
from .dataset_packaging import VERSION as DATA_VERSION, require, geometry_contract, readiness

VERSION = 'jev_packaging_choice_v4'
INSTRUCTION = 'Packaging/load protocol v1: use current geometry, mass, support eligibility and capacity only.'
QUESTION = ('Choose one complete box-and-placement action from the shared physical candidate pool. '
            'Use only currently observed boxes, their mass, capacity and cumulative top loads. '
            'Aim to place the order and preserve useful space and supporting capacity. '
            'Every action must pass the shared physical checks. No future arrivals are known.')
OBJECTIVE = 'Complete loading while preserving useful space and capacity using observed facts; physical constraints are mandatory.'
METHODS = ('local_geometry_test_double','local_first_test_double')


def is_packaging(config):
    return config.get('version') in (VERSION, 'jev_packaging_monitored_v5', 'jev_packaging_remote_v6', 'jev_packaging_memory_v7','jev_packaging_contrast_v8','jev_packaging_memory_orders_v9')


def no_policy(observation):
    require(observation['instruction_text']==INSTRUCTION and observation['regions']==[], 'runtime_instruction')
    return PublicPolicyContext.from_dict({'source':'packaging_physical_only',
        'observation_digest':observation['observation_digest'],
        'response':{'policy_ast':{'version':DATA_VERSION,'rules':[]}}})


def runtime_task(frozen):
    validate_schema('packaging_load_task_v1',frozen)
    task = copy.deepcopy(frozen)
    task['frozen_task_digest'] = digest(frozen)
    task['instruction_text'] = INSTRUCTION
    task['reference_policy'] = {'version':DATA_VERSION,'rules':[]}
    task['items'] = []
    task['attributes'] = {}
    # Legacy observation envelope needs these aliases. They are equal derivatives,
    # never independent business rules and never appear in the v4 model context.
    for obj in frozen['items']:
        item = {k:copy.deepcopy(obj[k]) for k in ('item_id','dimensions_mm','mass_kg',
            'stackable','top_load_limit_kg_synthetic','fragile','weight_class')}
        item['product_category'] = 'general'
        task['items'].append(item)
        task['attributes'][item['item_id']] = {'object_id':item['item_id'],
            'cargo_category':'general','packaging':{'reinforced':False},
            'labels':{'no_top_load':not item['stackable'],'max_top_load_kg':item['top_load_limit_kg_synthetic']},
            'physical_top_load_limit_kg':item['top_load_limit_kg_synthetic']}
    return task


def load_runtime_dataset(root):
    from .dataset import DatasetOrderAdapter
    from .ledger import read
    data = DatasetOrderAdapter().load(root,spec_config=DATA_VERSION)
    manifest = read(Path(root)/'manifest.json')
    return {'tasks':[runtime_task(t) for t in data['tasks']], 'manifest':manifest,
        'data_identity':manifest['data_identity'],'geometry_contract':geometry_contract(),
        'target_one_handoff':read(Path(root)/'handoff.json')}


def load_runtime_config(*, data_identity, method=METHODS[0], task_digest=None):
    from importlib.resources import files
    from .ledger import read
    from .experiment import source_manifest
    require(method in METHODS,'runtime_local_method_only')
    config = read(files('semantic_pallet_planner.jev_select').joinpath('configs/packaging_runtime_v4.json'))
    config['selector'] = method
    physical = physical_manifest()
    config['runtime_identity'] = {'data_identity':data_identity,'physical_identity':digest(physical),
        'strategy_identity':digest({'config':config,'question':QUESTION,'objective':OBJECTIVE,
            'source_manifest':source_manifest()}), 'task_identity':task_digest or digest('CONSTRUCTED_ONLY')}
    validate_schema('config',config)
    return config


def physical_manifest():
    from .dataset_j4 import _sha
    package=Path(__file__).parent.parent
    names=('planner/constraints.py','planner/generator.py','planner/scoring.py',
        'evaluation/geometry_oracle.py','evaluation/state.py','domain.py',
        'o4/buffer/buffer_state.py','o4/extensions/candidates.py',
        'o4/extensions/e2/candidates.py','o4/extensions/e2/protocol.py',
        'jev_select/configs/generator_v1.json')
    return {name:_sha(package/name) for name in names}


def layout_facts(objects):
    """Auditable runtime mass propagation, same contact rectangles as commit oracle.

    This is a descriptive calculation, not a second stability admission solver.
    Objects use the internal/public physical item_id interface.
    """
    from semantic_pallet_planner.evaluation.geometry_oracle import bounds, support_rect, TOL
    loads={o['item_id']:0. for o in objects}; edges={}; contacts={}
    for upper in objects:
        name=upper['item_id']; a=bounds(upper); areas=[]; rects=[]
        if a[4]>TOL:
            for lower in objects:
                if lower['item_id']==name:continue
                b=bounds(lower)
                if abs(a[4]-b[5])>TOL:continue
                rect=support_rect(a,b)
                if rect:
                    areas.append((lower['item_id'],(rect[1]-rect[0])*(rect[3]-rect[2])))
                    rects.append({'support_item_id':lower['item_id'],'rectangle_mm':list(rect)})
        total=sum(a for _,a in areas)
        edges[name]=[{'item_id':n,'fraction':a/total} for n,a in areas]
        contacts[name]=rects
    for upper in sorted(objects,key=lambda o:o['pose']['z_base_mm'],reverse=True):
        for edge in edges[upper['item_id']]:
            loads[edge['item_id']] += (upper['mass_kg']+loads[upper['item_id']])*edge['fraction']
    return loads,edges,contacts


def _physical_object(observed):
    return {'item_id':observed['object_id'], **{k:copy.deepcopy(observed[k]) for k in
        ('dimensions_mm','mass_kg','stackable','pose','oriented_size_mm') if k in observed},
        'top_load_limit_kg_synthetic':observed['physical_top_load_limit_kg']}


def resources(obj,load):
    capacity=obj.get('top_load_limit_kg_synthetic',obj.get('physical_top_load_limit_kg'))
    effective=capacity if obj['stackable'] else 0
    return {'max_top_load_kg':capacity,'effective_top_permission_kg':effective,
        'current_top_load_kg':load,'remaining_top_load_kg':effective-load,
        'capacity_utilization':load/capacity if obj['stackable'] and capacity>0 else None,
        'utilization_status':'APPLICABLE' if obj['stackable'] and capacity>0 else 'NOT_APPLICABLE'}


def geometry_facts(pose,size):
    require(pose['yaw_deg'] in (0,90) and len(size)==3,'runtime_orientation')
    x,y,z=(pose[k] for k in ('x_mm','y_mm','z_base_mm'))
    return {'corner_mm':[x-size[0]/2,y-size[1]/2,z],
        'centroid_mm':[x,y,z+size[2]/2], 'oriented_size_mm':list(size)}


def pose_from_corner(corner_mm,size_mm,yaw_deg):
    require(yaw_deg in (0,90) and len(corner_mm)==len(size_mm)==3,'runtime_orientation')
    return {'x_mm':corner_mm[0]+size_mm[0]/2,'y_mm':corner_mm[1]+size_mm[1]/2,
        'z_base_mm':corner_mm[2],'yaw_deg':yaw_deg}


def length_unit(values,source,target):
    require(source in ('mm','m') and target in ('mm','m'),'runtime_units')
    factor=1 if source==target else .001 if source=='mm' else 1000
    return [v*factor for v in values]


def public_facts(config,observation,bundle,policy):
    from semantic_pallet_planner.o4.extensions.e2.protocol import BINDINGS,validate_observation
    from semantic_pallet_planner.evaluation.state import apply_candidate
    from semantic_pallet_planner.planner.scoring import geometry_score
    from .candidates import validate_bundle,PublicBusinessGuard,decision_route
    from .config import protocol_suffix
    validate_observation(observation)
    require(policy.data==no_policy(observation).data,'runtime_policy')
    require(bundle.data==PublicBusinessGuard().filter(observation,policy,bundle,config).data,'runtime_candidate_filter')
    require(observation['buffer_context']['capacity']==3,'runtime_buffer_capacity')
    value=validate_bundle(observation,bundle)
    objects=observation['placed_objects']+observation['available_objects']
    aliases={o['object_id']:f'B{i:03d}' for i,o in enumerate(objects,1)}
    placed=[_physical_object(o) for o in observation['placed_objects']]
    loads,edges,_=layout_facts(placed)
    # apply_candidate needs runtime load and edges, not any fixed SKU property.
    for obj in placed:
        obj.update(supported_load_kg=loads[obj['item_id']],support_fractions=edges[obj['item_id']])
    available=[_physical_object(o) for o in observation['available_objects']]
    def public_object(obj,is_placed):
        name=obj['object_id'];result={'object_id':aliases[name],
            **{k:copy.deepcopy(obj[k]) for k in ('mass_kg','dimensions_mm','stackable')},
            **resources(obj,loads[name] if is_placed else 0)}
        if is_placed:
            result.update(pose=copy.deepcopy(obj['pose']),oriented_size_mm=list(obj['oriented_size_mm']),
                centroid_mm=geometry_facts(obj['pose'],obj['oriented_size_mm'])['centroid_mm'],
                support_fractions=[{'object_id':aliases[e['item_id']],'fraction':e['fraction']} for e in edges[name]])
        return result
    buffer=observation['buffer_context']
    state={'units':{'length':'mm','mass':'kg'},'coordinate_convention':observation['coordinate_convention'],
        'container':{k:observation['container'][k] for k in ('length_mm','width_mm','max_height_mm','max_payload_kg')},
        'assumptions':{'mass_distribution':'uniform','centroid_model':'geometric_center',
            'support_model':'70% area plus local center in actual contact rectangle; area-proportional load sharing'},
        'placed_objects':[public_object(o,True) for o in observation['placed_objects']],
        'available_objects':[public_object(o,False) for o in observation['available_objects']],
        'buffer':{'capacity':3,'end_of_stream':buffer['end_of_stream'],
            'pending':[{**p,'object_id':aliases[p['object_id']]} for p in buffer['pending']]},
        'objective':OBJECTIVE,'memories':[]}
    ordered=sorted(value['selectable_candidates'],key=lambda c:(c['pose']['x_mm'],c['pose']['y_mm'],
        c['pose']['z_base_mm'],c['pose']['yaw_deg'],aliases[c['pick_item_id']]))
    seed=digest([config['display_order_seed'],observation['request_id'],observation['state_hash']])
    random.Random(int(seed[:16],16)).shuffle(ordered)
    criteria={};mapping={}
    for i,c in enumerate(ordered,1):
        label=f'C{i:02d}';after=apply_candidate({'placed_items':placed,'available_items':available},c)
        after_loads,after_edges,_=layout_facts(after)
        changes=[]
        by_id={o['item_id']:o for o in placed}
        for name,before in loads.items():
            delta=after_loads[name]-before
            if delta>0:
                cap=resources(by_id[name],after_loads[name])
                changes.append({'object_id':aliases[name],'before_top_load_kg':before,
                    'increment_top_load_kg':delta,'after_top_load_kg':after_loads[name],
                    'max_top_load_kg':cap['max_top_load_kg'],'remaining_top_load_kg':cap['remaining_top_load_kg']})
        criteria[label]={'pick_object':aliases[c['pick_item_id']],'pose':copy.deepcopy(c['pose']),
            'oriented_size_mm':list(c['oriented_size_mm']),
            'features':{'geometry_score':geometry_score(c),
                'support_ratio':c['support']['support_ratio'],'com_margin_mm':c['support']['com_margin_mm'],
                'supported_by':[aliases[n] for n in c['support']['support_item_ids']],
                'support_fractions':[{'object_id':aliases[e['item_id']],'fraction':e['fraction']} for e in after_edges[c['pick_item_id']]],
                'resulting_max_height_mm':c['resulting_geometry']['max_height_mm'],
                'resulting_volume_utilization':c['resulting_geometry']['volume_utilization']},
            'load_changes':changes}
        mapping[label]={'candidate_id':c['candidate_id'],'pick_item_id':c['pick_item_id'],'candidate_digest':digest(c)}
    return value,state,criteria,mapping,buffer


def build_context(config,observation,bundle,policy,*,memory_view=None,memory_driver=None,retrieval_receipt=None):
    from semantic_pallet_planner.o4.extensions.e2.protocol import BINDINGS
    from .candidates import decision_route
    from .config import protocol_suffix
    require(memory_driver is None,'context_builder_requires_explicit_view')
    value,state,criteria,mapping,buffer=public_facts(config,observation,bundle,policy)
    memory_fields={}
    if config['version']!='jev_packaging_memory_orders_v9' and (memory_driver is not None or retrieval_receipt is not None):
        raise JevSelectError('pilot_memory_protocol_incompatible')
    if config['version'] in ('jev_packaging_memory_v7','jev_packaging_contrast_v8'):
        from .packaging_memory_protocol import memory_interface
        interface=memory_interface(config['version'])
        empty_view,validate_view=interface.empty_view,interface.validate_view
        view=empty_view(config['memory_snapshot_digest']) if memory_view is None else memory_view
        mv=validate_view(view,config['memory_snapshot_digest'])
        require(all(digest(e) in config['memory_entry_digests'] for e in mv['entries']),'memory_entry_not_in_frozen_config')
        state['memories']=mv['entries'];memory_fields={'memory_view':mv}
    elif memory_view is not None and config['version']!='jev_packaging_memory_orders_v9':
        raise JevSelectError('packaging_memory_protocol_incompatible')
    if config['version']=='jev_packaging_memory_orders_v9':
        from .packaging_pilot_memory import validate_view,validate_receipt
        require(memory_view is not None and retrieval_receipt is not None,'pilot_missing_saved_view_or_receipt')
        mv=validate_view(memory_view,config)
        state['memories']=mv['entries']
        validate_receipt(retrieval_receipt,memory_view,config,state,criteria)
        memory_fields={'memory_view':mv,'retrieval_receipt':retrieval_receipt}
    route=decision_route(bundle)
    body=None if route!='CHOICE_REQUIRED' else {'model':config['model'],'state':state,
        'questions':{'next_action':{'type':'choice','instructions':QUESTION,'criteria':criteria}}}
    binding={**{k:observation[k] for k in BINDINGS},'event_index':buffer['event_index'],
        'physical_digest':value['physical_digest'],'selectable_digest':value['selectable_digest'],
        'mapping_digest':digest(mapping),'policy_digest':digest(policy.data),'config_digest':digest(config),
        'generator_config_digest':value['generator_config_digest'],'prompt_version':config['prompt_version'],
        'feature_version':config['feature_version'],'model_state_digest':digest(state),'criteria_digest':digest(criteria),
        'request_body_digest':digest(body),'runtime_identity':copy.deepcopy(config['runtime_identity'])}
    if memory_fields:
        binding.update(memory_snapshot_digest=config['memory_snapshot_digest'],memory_view_digest=mv['view_digest'])
        if config['version']=='jev_packaging_memory_orders_v9':
            binding.update(query_digest=retrieval_receipt['query_digest'],retrieval_digest=retrieval_receipt['receipt_digest'])
    context=DecisionContext.from_dict({**memory_fields,'version':'jev_decision_context_' + protocol_suffix(config),'route':route,'model_state':state,
        'criteria':criteria,'request_body':body,'display_mapping':mapping,'local_binding':binding})
    validate_runtime_context(context,config=config)
    require(body is None or len(canonical(body).encode())<=config['max_request_bytes'],'runtime_request_too_large')
    return context


def validate_runtime_context(context,observation=None,bundle=None,config=None):
    from .candidates import validate_bundle,decision_route
    value=context.data;validate_schema('decision_context',value)
    if value['version']=='jev_decision_context_v9':
        from .packaging_pilot_memory import PilotMemoryView as MemoryView,validate_receipt
        require(config is not None,'pilot_config_required_for_context_validation')
        saved=value['retrieval_receipt'];view=MemoryView.from_dict(value['memory_view'])
        validate_receipt(saved,view,config,value['model_state'],value['criteria'])
        mv=view.data;b=value['local_binding']
        require(value['model_state']['memories']==mv['entries'] and b['memory_snapshot_digest']==mv['snapshot_digest'] and b['memory_view_digest']==mv['view_digest'] and b['retrieval_digest']==saved['receipt_digest'] and b['query_digest']==saved['query_digest'],'pilot_context_memory_changed')
    if value['version'] in ('jev_decision_context_v7','jev_decision_context_v8'):
        from .packaging_experience import public_query
        from .packaging_memory_protocol import memory_interface
        interface=memory_interface('jev_packaging_contrast_v8' if value['version']=='jev_decision_context_v8' else 'jev_packaging_memory_v7')
        MemoryView=interface.EMemoryView if value['version']=='jev_decision_context_v8' else interface.MemoryView
        validate_view=interface.validate_view
        mv=validate_view(MemoryView.from_dict(value['memory_view']),config['memory_snapshot_digest'] if config else None)
        require(value['model_state']['memories']==mv['entries'] and value['local_binding']['memory_view_digest']==mv['view_digest'] and value['local_binding']['memory_snapshot_digest']==mv['snapshot_digest'],'memory_context_changed')
        if config is not None:
            require(all(digest(e) in config['memory_entry_digests'] for e in mv['entries']),'memory_entry_not_in_frozen_config')
        if mv['entries']:
            require(mv['query_digest']==digest(public_query(context)),'memory_query_context_changed')
    binding=value['local_binding'];labels=list(value['display_mapping'])
    require(set(labels)==set(value['criteria']) and sorted(labels)==[f'C{i:02d}' for i in range(1,len(labels)+1)],'runtime_display_mapping')
    for field,key in [('mapping_digest','display_mapping'),('model_state_digest','model_state'),
        ('criteria_digest','criteria'),('request_body_digest','request_body')]:
        require(binding[field]==digest(value[key]),'runtime_context_digest')
    body=value['request_body'];route=value['route']
    if route=='CHOICE_REQUIRED':
        require(len(labels)>=2 and body is not None and body['state']==value['model_state'] and
            body['model']==(config['model'] if config else body['model']) and body['questions']=={'next_action':{'type':'choice','instructions':QUESTION,'criteria':value['criteria']}},'runtime_request_binding')
    else:require(body is None and ((route=='SINGLETON_BYPASS' and len(labels)==1) or
        (route=='STOP_NO_PHYSICAL_CANDIDATE' and not labels)),'runtime_route')
    if config is not None:
        validate_schema('config',config)
        require(is_packaging(config) and binding['config_digest']==digest(config) and
            binding['runtime_identity']==config['runtime_identity'],'runtime_identity_changed')
    if observation is not None:
        from semantic_pallet_planner.o4.extensions.e2.protocol import BINDINGS
        require(all(binding[k]==observation[k] for k in BINDINGS) and
            binding['event_index']==observation['buffer_context']['event_index'],'runtime_stale_context')
    if bundle is not None:
        require(observation is not None and config is not None,'runtime_missing_binding_input')
        b=validate_bundle(observation,bundle)
        require(binding['physical_digest']==b['physical_digest'] and binding['selectable_digest']==b['selectable_digest'] and
            route==decision_route(bundle),'runtime_stale_pool')
        # Deterministic reconstruction checks all public facts, deltas and private mapping.
        extras=({'memory_view':MemoryView.from_dict(value['memory_view']),'retrieval_receipt':value['retrieval_receipt']} if value['version']=='jev_decision_context_v9' else {'memory_view':MemoryView.from_dict(value['memory_view'])} if value['version'] in ('jev_decision_context_v7','jev_decision_context_v8') else {})
        rebuilt=build_context(config,observation,bundle,no_policy(observation),**extras).data
        for key in ('job_id','decision_id'):
            if key in binding:rebuilt['local_binding'][key]=binding[key]
        require(value==rebuilt,'runtime_context_reconstruction')
    return value


class LocalPackagingDouble:
    """No Jev transport; two trivial deterministic selectors for engineering only."""
    def __init__(self,method=METHODS[0]):
        require(method in METHODS,'runtime_local_method_only');self.method=method
    def for_replay(self):return self
    def select(self,context,*,decision_id):
        from .selector import result,baseline_label
        validate_runtime_context(context)
        require(context.data['local_binding']['decision_id']==decision_id,'runtime_selector_binding')
        label=baseline_label(context,'shared_geometry') if self.method==METHODS[0] else min(context.data['criteria'])
        return result(context,status='selected',source='test_double',label=label)


def evaluate_state(state):
    """Independent downstream use of existing oracle and apply_candidate only."""
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate,union_area
    from semantic_pallet_planner.evaluation.state import apply_candidate
    placed=state['placed_items'];loads,edges,contacts=layout_facts(placed)
    prefix=[];violations=[]
    for obj in placed:
        name=obj['item_id']; l,w,h=obj['oriented_size_mm']
        rects=[c['rectangle_mm'] for c in contacts[name]]
        ratio=union_area(rects)/(l*w) if obj['pose']['z_base_mm']>1e-6 else 1.
        volume=sum(math.prod(o['oriented_size_mm']) for o in [*prefix,obj])
        c={'pick_item_id':name,'pose':obj['pose'],'oriented_size_mm':obj['oriented_size_mm'],
            'support':{'support_item_ids':[e['item_id'] for e in edges[name]],'support_ratio':ratio},
            'resulting_geometry':{'max_height_mm':max(o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in [*prefix,obj]),
                'volume_utilization':volume/(state['container']['length_mm']*state['container']['width_mm']*state['container']['max_height_mm'])}}
        errors=check_candidate({'placed_items':prefix,'available_items':[obj]},{'container':state['container']},c)
        violations.extend({'item_id':name,'reason':e} for e in errors)
        # Invalid layouts have no certified reconstruction; never recurse through bad graphs.
        if errors:break
        prefix=apply_candidate({'placed_items':prefix,'available_items':[obj]},c)
    for obj in placed:
        name=obj['item_id'];capacity=obj['top_load_limit_kg_synthetic']
        if not math.isclose(obj['supported_load_kg'],loads[name],abs_tol=1e-9,rel_tol=1e-12):
            violations.append({'item_id':name,'reason':'runtime_load_mismatch'})
        if obj['support_fractions']!=edges[name]:violations.append({'item_id':name,'reason':'runtime_support_mismatch'})
        if loads[name]>capacity+1e-6:violations.append({'item_id':name,'reason':'overload'})
        if not obj['stackable'] and loads[name]>1e-6:violations.append({'item_id':name,'reason':'non_stackable_support'})
    facts={o['item_id']:{**resources(o,loads[o['item_id']]),'support_fractions':edges[o['item_id']],
        'contacts':contacts[o['item_id']],'centroid_mm':geometry_facts(o['pose'],o['oriented_size_mm'])['centroid_mm']} for o in placed}
    raw={'violations':violations,'runtime_facts':facts}
    return {'version':'jev_packaging_physical_state_v1','raw':raw,**raw}


def summary(task,config,method,state,events,reason):
    audit=evaluate_state(state);placed=state['placed_items'];mass=sum(o['mass_kg'] for o in placed)
    volume=sum(math.prod(o['oriented_size_mm']) for o in placed)
    planned_volume=sum(math.prod(o['dimensions_mm'].values()) for o in task['items'])
    planned_mass=sum(o['mass_kg'] for o in task['items']);total=len(task['items'])
    resources_now=list(audit['runtime_facts'].values())
    utilizations=[r['capacity_utilization'] for r in resources_now if r['capacity_utilization'] is not None]
    centroid=[sum(o['mass_kg']*geometry_facts(o['pose'],o['oriented_size_mm'])['centroid_mm'][i] for o in placed)/mass for i in range(3)] if mass else None
    row={'version':'jev_packaging_order_metrics_v1','task_id':task['task_id'],
        'mode':task['mode'],'layer':task['layer'],'selector_backend':method,'origin':'LOCAL_TEST_DOUBLE_NOT_JEV',
        'runtime_identity':config['runtime_identity'],'planned_items':total,'arrived_items':state['arrival_count'],
        'placed_items':len(placed),'placed_item_ratio':len(placed)/total,'placed_volume_ratio':volume/planned_volume,
        'placed_mass_kg':mass,'planned_mass_kg':planned_mass,'placed_mass_ratio':mass/planned_mass,
        'completed':len(placed)==total,'termination_reason':reason,
        'feasibility_status':task['feasibility_status'],'global_infeasibility_proven':False,
        'physical_violation_instances':audit['violations'],'physical_valid':not audit['violations'],
        'physical_zero_violation_interpretation':'shared engineering boundary; not memory or Jev benefit',
        'max_height_mm':max((o['pose']['z_base_mm']+o['oriented_size_mm'][2] for o in placed),default=0),
        'combined_centroid_mm':centroid,'maximum_capacity_utilization':max(utilizations,default=None),
        'remaining_capacity_kg':[r['remaining_top_load_kg'] for r in resources_now],
        'cost':{'model_calls':0,'model_cost_usd':0,'memory_cost_usd':0,
            'decision_segment_wall_s':sum(e.get('timings',{}).get('decision_segments_s',0) for e in events)},
        'policy_effect':'NOT_MEASURED','stability_algorithm':'NOT_RUN'}
    from .stability.monitor import is_monitored
    if is_monitored(config):
        from .stability.metrics import statistics
        row.update(version='jev_packaging_monitored_metrics_v1',
            stability_algorithm='pct_contact_network_v2' if config['stability_monitor']['enabled'] else 'DISABLED',
            monitor_statistics=statistics(config,events,row))
        if config['version']=='jev_packaging_memory_orders_v9':
            from .packaging_remote import event_cost
            row.update(version='jev_packaging_memory_order_metrics_v1',origin='jev',memory_snapshot_digest=config['memory_snapshot_digest'])
            row['cost'].update(event_cost(events))
            validate_schema('pilot_order_metrics_v1',row)
        elif config['version']=='jev_packaging_contrast_v8':
            from .packaging_remote import event_cost
            row.update(version='jev_packaging_contrast_metrics_v1',origin='jev',memory_snapshot_digest=config['memory_snapshot_digest'])
            row['cost'].update(event_cost(events))
            validate_schema('contrast_order_metrics_v1',row)
        elif config['version']=='jev_packaging_memory_v7':
            from .packaging_remote import event_cost
            row.update(version='jev_packaging_memory_metrics_v1',origin='jev',memory_snapshot_digest=config['memory_snapshot_digest'])
            row['cost'].update(event_cost(events))
            validate_schema('memory_order_metrics_v1',row)
        elif config['version'] == 'jev_packaging_remote_v6':
            from .packaging_remote import event_cost
            row.update(version='jev_packaging_remote_metrics_v1', origin='jev' if method=='jev_no_memory' else 'LOCAL_TEST_DOUBLE_NOT_JEV')
            row['cost'].update(event_cost(events))
            validate_schema('remote_order_metrics_v1',row)
        else:
            validate_schema('monitored_order_metrics_v1',row)
    else:
        validate_schema('packaging_order_metrics_v1',row)
    return row


def runtime_readiness():
    result=readiness();result['version']='packaging_runtime_stability_readiness_v1'
    result['runtime_request_evaluation_memory_acceptance']='local request/physical execution/checkpoint/evaluation adapted; memory injection NOT_RUN'
    result['geometry_contract']=geometry_contract()
    result['field_mapping'].update({'runtime_facts':'contacts / support fractions / cumulative load / remaining capacity / geometric centroid, reconstructed from current placed state',
        'criteria.load_changes':'before, increment, after, primary C and remaining capacity for all affected ancestors',
        'runtime_identity':'separate frozen data, shared physical, local strategy and task digests in context/checkpoint/metrics'})
    result['runtime_tolerances']={
        'execution_apply_candidate':{'height_contact_mm':1e-6,'contact_side_min_mm':1e-6,'floor_test':'z_base > 0'},
        'domain_restore_placed':{'height_contact_mm':1e-6,'positive_contact_area_mm2':0,'floor_test':'z_base > 0'},
        'descriptive_layout_facts':{'height_contact_mm':1e-6,'contact_side_min_mm':1e-6,'floor_test':'z_base > 1e-6'},
        'audit_stored_load_comparison':{'absolute_kg':1e-9,'relative':1e-12},
        'note':'Inherited candidate/oracle/execution boundary differences are disclosed, not tuned or merged.'}
    result['potential_conflicts'].append('The unchanged Top-16 sampler may omit a manually oracle-admissible bridge; feasibility does not establish candidate reachability.')
    result['missing_runtime_fields']=['third-party-specific equivalent center/force state UNVERIFIED']
    result['next_stage']=['verify author algorithm/repository/commit/license/dependencies and actual API (UNVERIFIED)',
        'resolve signed-yaw handedness and coordinate conventions before non-axis-aligned conversion',
        'construct eccentric-ancestor and bridge counterexamples; distinguish overload from static instability',
        'freeze sharing model and reconcile area/center checks vs hull/equivalent-center checks; no blind conjunction',
        'use a separately authorized side-channel comparison with a new physical identity; recertify witnesses',
        'real model experiments and genuine nonempty memory injection require separate authorization and protocol']
    return result


def smoke_runtime(dataset,output,*,event_limit=8):
    """Exactly two preregistered source prefixes, at most 8 events each. No matrix.

    First prefix resumes a 4-event checkpoint; the second is a direct prefix.
    This is engineering acceptance, never a new feasible-layout witness.
    """
    from .dataset_j4 import offline_dataset_guard,_sha
    from .experiment import _new_output,file_manifest,source_manifest
    from .ledger import read,write
    from .episode import run_episode
    import shutil
    import subprocess
    root=_new_output(output);repo=Path(__file__).resolve().parents[4]
    allowed=repo/'semantic_pallet_planner/outputs'
    require(root.is_relative_to(allowed) and root!=allowed,'runtime_output_directory')
    require(subprocess.run(['git','check-ignore','-q',str(root)],cwd=repo,check=False).returncode==0,'runtime_output_not_ignored')
    require(type(event_limit) is int and 4<=event_limit<=8,'runtime_smoke_limit')
    with offline_dataset_guard() as counters:
        data=load_runtime_dataset(dataset);baseline_dir=allowed/'CHECK_JEV_PACKAGING_RUNTIME_20261102_BASELINE_01'
        baseline=read(baseline_dir/'baseline.json')
        require(data['data_identity']==baseline['data_identity'],'runtime_target_one_identity')
        protected=baseline['protected_sha256']
        require(all(_sha(repo/n)==h for n,h in protected.items()),'runtime_historical_bytes_changed')
        source_key=min(t['source_order_key'] for t in data['tasks'])
        selected=[next(t for t in data['tasks'] if t['source_order_key']==source_key and t['layer']==layer)
                  for layer in ('source_difficult','controlled_heterogeneous')]
        root.mkdir(parents=True)
        write(root/'scope.json',{'dataset':str(Path(dataset).resolve()),'data_identity':data['data_identity'],
            'selected_task_ids':[t['task_id'] for t in selected],'selection':'lowest source key; fixed source/heterogeneous pair',
            'event_limit_per_task':event_limit,'selector':'local_geometry_test_double',
            'origin':'LOCAL_TEST_DOUBLE_NOT_JEV','purpose':'bounded engineering smoke, no policy effect or witness certification',
            'model_calls':0,'paid_experiment':False,'full_order_rollout':False})
        write(root/'target_one_receipt.json',{'manifest':data['manifest'],
            'handoff_sha256':_sha(Path(dataset)/'handoff.json'),
            'data_load':'PASS','frozen_code_matches_pre_adaptation_baseline':baseline['code_sha256']==data['manifest']['code_sha256']})
        write(root/'stability_readiness.json',runtime_readiness())
        write(root/'geometry_contract.json',geometry_contract())
        write(root/'identity_components.json',{'data_identity':data['data_identity'],
            'physical_sha256':physical_manifest(),'strategy_source_manifest':source_manifest(),
            'question':QUESTION,'objective':OBJECTIVE,'model_backend':'LOCAL_TEST_DOUBLE_NOT_JEV'})
        for index,task in enumerate(selected):
            jid=f'P{index:02d}';job=root/'jobs'/jid
            cfg=load_runtime_config(data_identity=data['data_identity'],task_digest=digest(task))
            write(job/'task.snapshot.json',task);write(job/'config.snapshot.json',cfg)
            def checkpoint(cp):write(job/'checkpoint.json',cp)
            def event_hook(phase,event):
                if phase=='decision_ready':
                    did=event['decision_id']
                    write(job/'contexts'/f'{did}.json',event['context'])
                    write(job/'requests'/f'{did}.json',event['context']['request_body'])
            selector=LocalPackagingDouble()
            if index==0:
                first=run_episode(task,selector,cfg,job_id=jid,method=cfg['selector'],
                    event_limit=4,on_checkpoint=checkpoint,hook=event_hook)
                write(job/'prefix_checkpoint.json',first['checkpoint'])
                result=run_episode(task,selector,cfg,job_id=jid,method=cfg['selector'],
                    resume=first['checkpoint'],event_limit=event_limit,on_checkpoint=checkpoint,hook=event_hook)
                write(job/'recovery_receipt.json',{'phase':first['checkpoint']['phase'],
                    'prefix_events':len(first['events']),'reconstruction_scope':'4-event prefix only, no full-order replay',
                    'prefix_state_recovered':result['events'][:len(first['events'])]==first['events'],
                    'resume_identity':cfg['runtime_identity']})
            else:
                result=run_episode(task,selector,cfg,job_id=jid,method=cfg['selector'],
                    event_limit=event_limit,on_checkpoint=checkpoint,hook=event_hook)
            require(not any(e['event'] in ('COMMIT_FAILURE','DECISION_FAILURE') for e in result['events']),'runtime_smoke_failed')
            write(job/'episode.json',result)
            metrics=summary(task,cfg,cfg['selector'],result['final_state'],result['events'],
                result['checkpoint']['reason'] or 'SMOKE_EVENT_LIMIT_NOT_ORDER_TERMINATION')
            require(metrics['physical_valid'],'runtime_smoke_physical_violation')
            write(job/'metrics.json',metrics)
        require(all(_sha(repo/n)==h for n,h in protected.items()),'runtime_historical_bytes_changed')
        write(root/'protected_inventory.json',{'sha256':protected,'after_identical':True})
        write(root/'offline_guards.json',dict(counters))
        code=source_manifest();write(root/'source_manifest.json',code)
        for name in code:
            target=root/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(Path(__file__).parent.parent/name,target)
        write(root/'delivery_manifest.json',file_manifest(root))
        checked=verify_runtime_output(root)
        return {'status':'PASS','scope':'PACKAGING_RUNTIME_LOCAL_BOUNDED_SMOKE','output':str(root),
            'jobs':checked['jobs'],'placed_in_prefixes':checked['placed_in_prefixes'],
            'origin':'LOCAL_TEST_DOUBLE_NOT_JEV','model_calls':0,'full_order_rollouts':0,
            'data_feasibility':'UNCHANGED_UNKNOWN','offline_guards':dict(counters)}


def verify_runtime_output(root):
    """Authenticate saved records without running an order or selecting new actions."""
    from .experiment import file_manifest,source_manifest
    from .dataset_j4 import offline_dataset_guard,_sha
    from .ledger import read
    from .episode import semantic_record
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    root=Path(root)
    with offline_dataset_guard():
        require(file_manifest(root)==read(root/'delivery_manifest.json'),'runtime_delivery_digest')
        require(source_manifest()==read(root/'source_manifest.json'),'runtime_source_changed_use_snapshot')
        require(all(_sha(root/'code_snapshot'/name)==sha for name,sha in read(root/'source_manifest.json').items()),'runtime_code_snapshot_changed')
        scope=read(root/'scope.json');data=load_runtime_dataset(scope['dataset'])
        require(data['data_identity']==scope['data_identity'],'runtime_data_identity_changed')
        expected_key=min(t['source_order_key'] for t in data['tasks'])
        expected_ids=[next(t['task_id'] for t in data['tasks'] if t['source_order_key']==expected_key and t['layer']==layer)
            for layer in ('source_difficult','controlled_heterogeneous')]
        require(scope['selected_task_ids']==expected_ids and 4<=scope['event_limit_per_task']<=8 and
            scope['origin']=='LOCAL_TEST_DOUBLE_NOT_JEV' and scope['full_order_rollout'] is False,'runtime_scope_changed')
        components=read(root/'identity_components.json')
        require(components['physical_sha256']==physical_manifest() and components['strategy_source_manifest']==source_manifest() and
            components['data_identity']==data['data_identity'],'runtime_identity_components_changed')
        count=0
        for jid,tid in zip(('P00','P01'),scope['selected_task_ids']):
            job=root/'jobs'/jid;task=read(job/'task.snapshot.json');cfg=read(job/'config.snapshot.json')
            require(task==next(t for t in data['tasks'] if t['task_id']==tid),'runtime_frozen_task_changed')
            expected=load_runtime_config(data_identity=data['data_identity'],task_digest=digest(task),method=cfg['selector'])
            require(cfg==expected,'runtime_config_identity_changed')
            ep=read(job/'episode.json');cp=read(job/'checkpoint.json')
            validate_schema('checkpoint_v4',cp)
            require(cp==ep['checkpoint'] and cp['events']==ep['events'] and
                cp['state']==ep['final_state'] and cp['runtime_identity']==cfg['runtime_identity'] and
                cp['task_digest']==digest(task) and cp['config_digest']==digest(cfg),'runtime_checkpoint_record_changed')
            require(len(ep['events'])<=scope['event_limit_per_task'],'runtime_prefix_exceeded')
            previous=None
            for event in ep['events']:
                if previous is not None:require(previous==event['before'],'runtime_state_discontinuity')
                previous=event['after']
                if event.get('context'):
                    require(event['observation']==observation(event['before'],INSTRUCTION,[]),'runtime_observation_changed')
                    ctx=DecisionContext.from_dict(event['context']);bundle=CandidateBundle.from_dict(event['bundle'])
                    validate_runtime_context(ctx,event['observation'],bundle,cfg)
                    require(ctx.data['local_binding']['job_id']==jid and ctx.data['local_binding']['decision_id']==event['decision_id'],'runtime_decision_binding')
                    require(read(job/'contexts'/f"{event['decision_id']}.json")==ctx.data and
                        read(job/'requests'/f"{event['decision_id']}.json")==ctx.data['request_body'],'runtime_saved_request_changed')
                    if event.get('selection'):
                        selection=event['selection'];validate_schema('selection_result',selection)
                        entry=ctx.data['display_mapping'][selection['selected_display_id']]
                        require(selection['local_binding_digest']==digest(ctx.data['local_binding']) and
                            selection['source'] in ('test_double','singleton') and
                            selection['selected_candidate_id']==entry['candidate_id'],'runtime_selection_binding')
                        if event['event']=='PLACE':
                            require(event['action']==event['proposed_action'] and event['action']['candidate_id']==entry['candidate_id'], 'runtime_action_binding')
                            count+=1
                if event['event']=='PLACE':
                    require(event['business_after']==evaluate_state(event['after']),'runtime_evaluation_changed')
            require(previous==cp['state'] and evaluate_state(cp['state'])['violations']==[],'runtime_final_physical_state')
            expected_metrics=summary(task,cfg,cfg['selector'],cp['state'],ep['events'],cp['reason'] or 'SMOKE_EVENT_LIMIT_NOT_ORDER_TERMINATION')
            require(read(job/'metrics.json')==expected_metrics,'runtime_metrics_changed')
            if (job/'prefix_checkpoint.json').is_file():
                prefix=read(job/'prefix_checkpoint.json');receipt=read(job/'recovery_receipt.json')
                require(semantic_record(ep['events'][:len(prefix['events'])])==semantic_record(prefix['events']) and
                    receipt['prefix_state_recovered'] is True,'runtime_recovery_changed')
        require(read(root/'stability_readiness.json')==runtime_readiness(),'runtime_readiness_changed')
        return {'status':'PASS','jobs':2,'placed_in_prefixes':count,'verification':'saved records, no order replay',
            'model_calls':0,'data_feasibility':'UNCHANGED_UNKNOWN'}
