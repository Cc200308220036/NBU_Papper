"""P1-B admission/persistence over the sole public episode engine.

Only <=3-box constructions and geometry choices admitted. No resume, journal,
remote/PCT inference, official dataset execution, or duplicate physical engine.
"""
import copy
from collections import Counter
from importlib.resources import files
import json
import math
import os
from pathlib import Path

from .contracts import digest,sha,write_new,validate


def require(ok,code):
    from semantic_pallet_planner.jev_select.contracts import JevSelectError
    if not ok:raise JevSelectError(code)


def source_identity():
    public=files('semantic_pallet_planner.jev_select')
    names=['packaging_versions.py','contracts.py','config.py','candidates.py','context.py',
        'packaging_runtime.py','selector.py','episode.py','execution.py','stability/monitor.py']
    identity={str(n):sha(public.joinpath(n)) for n in names}
    root=Path(__file__).parent
    for p in sorted(root.rglob('*')):
        if p.is_file() and (p.suffix=='.py' or p.name.endswith('.schema.json')):
            identity['pct_baseline/'+str(p.relative_to(root))]=sha(p)
    return identity


def strategy_identity(method):
    from semantic_pallet_planner.jev_select.config import generator_config
    return digest({'version':'pct_b1_constructed_strategy_v1','method':method,
        'source':source_identity(),'generator':generator_config()})


def build_config(task):
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    validate('task_b1_v1',task)
    require(task['exposure_status']=='CONSTRUCTED_P1B_ONLY' and task['task_id'].startswith('CONSTRUCTED_') and 1<=len(task['items'])<=3,'pct_b1_constructed_scope_only')
    config=json.loads(files('semantic_pallet_planner.jev_select').joinpath('configs/packaging_runtime_v4.json').read_text())
    monitor=exact_freeze()
    config.update(version='pct_b1_config_v1',buffer_capacity=1,model=None,selector='geometry_b1',
        execution_spec_digest=task['execution_spec_digest'],model_identity=None,stability_monitor=monitor,
        runtime_identity={'data_identity':task['parent_data_identity'],'physical_identity':digest(physical_manifest()),
            'strategy_identity':strategy_identity('geometry_b1'),'task_identity':digest(task),'monitor_identity':digest(monitor)})
    validate('config_b1_v1',config)
    return config


def preflight(config):
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    from semantic_pallet_planner.jev_select.packaging_runtime import physical_manifest
    validate('config_b1_v1',config)
    frozen=config['stability_monitor']
    require(frozen['enabled'] is True and frozen['algorithm']=='pct_exact_pose_network_v3','pct_b1_exact_monitor_required')
    require(frozen==exact_freeze() and config['runtime_identity']['monitor_identity']==digest(frozen),'pct_b1_monitor_identity_drift')
    require(config['runtime_identity']['physical_identity']==digest(physical_manifest()),'pct_b1_physical_identity_drift')
    require(config['runtime_identity']['strategy_identity']==strategy_identity(config['selector']),'pct_b1_source_strategy_drift')


def execution_binding(task,config,job_id):
    return {'version':'pct_b1_constructed_execution_v1','scope':'P1B_CONSTRUCTED_ONLY','job_id':job_id,
        'task_digest':digest(task),'config_digest':digest(config),'max_items':3,'resume_admitted':False,'network_admitted':False}


def admit_execution(task,selector,config,*,execution,job_id,method,resume,on_checkpoint,
                    expected_events,training_fork,memory_snapshot,memory_view,memory_driver):
    require(execution is not None,'pct_b1_explicit_execution_required')
    require(all(v is None for v in (resume,expected_events,training_fork,memory_snapshot,memory_view,memory_driver)), 'pct_b1_resume_memory_fork_not_admitted')
    validate('constructed_execution_b1_v1',execution)
    require(execution==execution_binding(task,config,job_id),'pct_b1_execution_binding_changed')
    validate('task_b1_v1',task)
    require(task['exposure_status']=='CONSTRUCTED_P1B_ONLY' and task['task_id'].startswith('CONSTRUCTED_') and 1<=len(task['items'])<=3,'pct_b1_constructed_scope_only')
    require(method==config['selector']=='geometry_b1' and isinstance(selector,GeometrySelector),'pct_b1_local_geometry_only')
    require(isinstance(on_checkpoint,CheckpointSink),'pct_b1_persistence_required')
    require(config['runtime_identity']['task_identity']==digest(task) and config['runtime_identity']['data_identity']==task['parent_data_identity'] and config['execution_spec_digest']==task['execution_spec_digest'],'pct_b1_task_identity_drift')
    require(selector.config==config,'pct_b1_selector_config_changed')
    preflight(config)


def validate_selection(context,selection,config):
    value=selection.data
    validate('selection_result_b1_v1',value)
    require(value['local_binding_digest']==digest(context.data['local_binding']),'pct_b1_stale_selection')
    if value['status'] in ('selected','singleton'):
        require((context.data['route']=='SINGLETON_BYPASS') == (value['status']=='singleton'),'pct_b1_selection_route_changed')
        require(value['source']==('singleton' if value['status']=='singleton' else 'local_baseline'),'pct_b1_selection_source_changed')
        label=value['selected_display_id']
        require(label in context.data['display_mapping'] and value['selected_candidate_id']==context.data['display_mapping'][label]['candidate_id'],'pct_b1_selection_candidate_changed')
    require(value['network_attempted'] is False and not value['attempt_ids'] and value['source'] in ('singleton','local_baseline'),'pct_b1_no_network_in_constructions')


class GeometrySelector:
    """Actual deterministic shared-geometry choice; no model or transport."""
    def __init__(self,config):self.config=copy.deepcopy(config);self.calls=0

    def select(self,context,*,decision_id):
        from semantic_pallet_planner.jev_select.context import validate_context
        from semantic_pallet_planner.jev_select.selector import baseline_label,result
        validate_context(context,config=self.config)
        require(context.data['local_binding']['decision_id']==decision_id,'pct_b1_selector_decision_changed')
        self.calls+=1
        return result(context,status='selected',source='local_baseline',label=baseline_label(context,'shared_geometry'))


class CheckpointSink:
    """Fsync append-only stage snapshots; no recovery/journal/locking claims."""
    def __init__(self,output):self.root=Path(output);self.count=0

    def __call__(self,checkpoint):
        validate('checkpoint_b1_v1',checkpoint)
        self.root.mkdir(parents=True,exist_ok=True)
        path=self.root/f'{self.count:04d}_{checkpoint["phase"]}.json'
        with path.open('x',encoding='utf-8') as stream:
            json.dump(checkpoint,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        self.count+=1


def summarize_episode(task,config,method,state,events,reason):
    from semantic_pallet_planner.jev_select.packaging_runtime import evaluate_state
    from semantic_pallet_planner.jev_select.stability.metrics import statistics
    placed=state['placed_items'];total=len(task['items'])
    planned_mass=sum(i['mass_kg'] for i in task['items']);mass=sum(i['mass_kg'] for i in placed)
    planned_volume=sum(math.prod(i['dimensions_mm'].values()) for i in task['items']);volume=sum(math.prod(i['oriented_size_mm']) for i in placed)
    loading={'planned_items':total,'arrived_items':state['arrival_count'],'placed_items':len(placed),
        'placed_item_ratio':len(placed)/total,'planned_mass_kg':planned_mass,'placed_mass_kg':mass,
        'placed_mass_ratio':mass/planned_mass,'placed_volume_mm3':volume,'planned_volume_mm3':planned_volume,
        'placed_volume_ratio':volume/planned_volume,'termination_reason':reason,'completed':reason=='ALL_ITEMS_PLACED' and len(placed)==total}
    c=task['container'];height=max((i['pose']['z_base_mm']+i['oriented_size_mm'][2] for i in placed),default=0)
    return {'version':'pct_b1_constructed_metrics_v1','scope':'P1B_CONSTRUCTED_ONLY','method':method,'loading':loading,
        'monitor':statistics(config,events,loading),'physical_evaluation':evaluate_state(state),
        'fixed_container_utilization':volume/(c['length_mm']*c['width_mm']*c['max_height_mm']),
        'height_mm':height if placed else 'NA','envelope_utilization':volume/(c['length_mm']*c['width_mm']*height) if height else 'NA',
        'algorithm':config['stability_monitor']['algorithm'],'runtime_identity':config['runtime_identity'],
        'model_requests':0,'training':'NOT_RUN','research_benefit':'NOT_ESTABLISHED'}


def run_constructed(task,config,output,*,selector=None,hook=None):
    from semantic_pallet_planner.jev_select.episode import run_episode
    require(not Path(output).exists(),'pct_b1_output_exists')
    selector=GeometrySelector(config) if selector is None else selector
    sink=CheckpointSink(Path(output)/'stages')
    binding=execution_binding(task,config,task['task_id'])
    # Admission before creating output, then repeated at the public engine boundary.
    admit_execution(task,selector,config,execution=binding,job_id=task['task_id'],method=config['selector'],
        resume=None,on_checkpoint=sink,expected_events=None,training_fork=None,memory_snapshot=None,memory_view=None,memory_driver=None)
    Path(output).mkdir(parents=True,exist_ok=False)
    write_new(Path(output)/'task.json',task);write_new(Path(output)/'config.json',config);write_new(Path(output)/'execution.json',binding)
    episode=run_episode(task,selector,config,job_id=task['task_id'],method=config['selector'],on_checkpoint=sink,
        hook=hook,extension_execution=binding)
    write_new(Path(output)/'episode.json',episode)
    return episode
