"""GP3-N2 public candidate construction. No plan, permit or execution route.

Common input/admission and backend bindings are independent of N1's new-backend
binding. N1 configuration guards remain intact. Telemetry is not semantic audit.
"""
from .packaging_versions import (GEOMETRY_RUN_VERSION, GEOMETRY_RUN_BUNDLE, GEOMETRY_NATIVE_VERSION,
    GEOMETRY_NATIVE_BUNDLE, GEOMETRY_ORDER_CONFIGS, GEOMETRY_JEV_VERSION, GEOMETRY_JEV_BUNDLE)
import copy
from dataclasses import dataclass, replace
from importlib.resources import files
import json
import time

from . import geometry_runtime_contracts as c
from .geometry_runtime_input import capture_runtime_views_v1, validate_runtime_views_v1
from .contracts import CandidateBundle, JevSelectError, canonical, digest, validate_schema
from .packaging_versions import (GEOMETRY_VERSION, GEOMETRY_BUNDLE, GEOMETRY_COMMON_BINDING,
    GEOMETRY_BACKEND_BINDING, GEOMETRY_ADMISSION, GEOMETRY_AUDIT, GEOMETRY_BACKENDS, DEFAULT_GEOMETRY_BACKEND)


def backend_config(backend):
    if backend not in GEOMETRY_BACKENDS:
        raise JevSelectError('unknown_geometry_backend', str(backend))
    if backend=='e2_original_v1':
        from .config import generator_config
        return generator_config()
    from .geometry_runtime_input import runtime_config
    return runtime_config()


def _identity():
    from .experiment import source_manifest
    from .packaging_runtime import physical_manifest
    return {'source_identity':digest(source_manifest()),'physical_identity':digest(physical_manifest())}


def load_geometry_config(*, backend=DEFAULT_GEOMETRY_BACKEND, data_identity, task_identity, monitor_identity,
                         method='local_geometry_test_double'):
    if backend is None:
        backend=DEFAULT_GEOMETRY_BACKEND
    # No remote transport, model options or monitor preflight are loaded.
    config=json.loads(files(__package__).joinpath('configs/packaging_runtime_v4.json').read_text())
    config.update(version=GEOMETRY_VERSION,candidate_backend=backend,selector=method,
        execution_version='geometry_construction_only_v1',experiment_protocol='geometry_candidate_construction_v1',
        numerical_profile=c.PROFILE,feature_profile='F0_existing_facts',construction_only=True,
        generator_config_digest=digest(backend_config(backend)))
    ids={'data_identity':data_identity,'task_identity':task_identity,'monitor_identity':monitor_identity,**_identity()}
    ids['strategy_identity']=digest({'config':config,'source_identity':ids['source_identity']})
    config['runtime_identity']=ids
    validate_schema('config',config)
    for v in ids.values():c.hash_string(v)
    return config


def preflight_config(config):
    from .packaging_versions import GEOMETRY_ORDER_VERSION
    if config.get('version')==GEOMETRY_JEV_VERSION:
        from .geometry_jev_execution import preflight_jev
        return preflight_jev(config)
    if config.get('version') in GEOMETRY_ORDER_CONFIGS:
        from .geometry_order_execution import preflight_order
        return preflight_order(config)
    if config.get('version')==GEOMETRY_RUN_VERSION:
        from .geometry_execution import preflight_run
        return preflight_run(config)
    validate_schema('config',config)
    c.require(config['version']==GEOMETRY_VERSION,'construction config v14 required')
    ids=config['runtime_identity']
    expected=load_geometry_config(backend=config['candidate_backend'],data_identity=ids['data_identity'],
        task_identity=ids['task_identity'],monitor_identity=ids['monitor_identity'],method=config['selector'])
    c.require(c.same_native(config,expected),'construction config/source/backend drift','RUNTIME_SNAPSHOT_MISMATCH')


def seal(value):
    value['record_digest']=digest(value)
    return value


def _common_binding(n,g,views,config):
    ids=config['runtime_identity']
    return seal({'version':GEOMETRY_COMMON_BINDING,'native_snapshot_sha256':c.sha(n),
        'geometry_input_sha256':c.sha(g),'effective_state_digest':views['geometry']['effective_state_digest'],
        'geometry_values_digest':digest(views['geometry']['payload']),
        'observation_digest':views['native']['observation']['observation_digest'],
        'profile':c.PROFILE,'adapter_version':c.ADAPTER,'serializer_version':c.SERIALIZER,
        'source_identity':ids['source_identity'],'physical_identity':ids['physical_identity'],
        'environment_digest':digest(c.environment()),
        **{k:ids[k] for k in c.IDENTITY_KEYS}})


def capture_common_input(state,observation,config):
    preflight_config(config)
    n,g=capture_runtime_views_v1(state,observation,profile=config['numerical_profile'])
    v=validate_runtime_views_v1(n,g,current_state=state,observation=observation)
    return n,g,_common_binding(n,g,v,config)


def validate_common_input(n,g,binding,config,*,state=None,observation=None):
    preflight_config(config)
    v=validate_runtime_views_v1(n,g,current_state=state,observation=observation)
    expected=_common_binding(n,g,v,config)
    c.closed(binding,set(expected))
    c.require(c.same_native(binding,expected),'common input binding drift','RUNTIME_SNAPSHOT_MISMATCH')
    return v


def _admit(views,common):
    from ..planner.space_candidates.generator import physical_prefix_views
    audit={}
    settings,placed,oracle=physical_prefix_views(views['physical'],audit=audit)
    return seal({'version':GEOMETRY_ADMISSION,'common_input_digest':digest(common),
        'status':'PASS','ledger_views':audit['ledger_views'],
        'physical_prefix_digest':digest(placed),'oracle_prefix_digest':digest(oracle),
        'physical_settings_digest':digest(settings)})


def _backend_binding(common,admission,config):
    extra={} if config['version'] not in (GEOMETRY_NATIVE_VERSION,GEOMETRY_JEV_VERSION) else {'publication_policy_digest':config['publication_policy_digest'],'publication_policy':config['publication_policy'],'native_shape_bridge':config['native_shape_bridge']}
    return seal({**extra,'version':('geometry_backend_binding_v2' if extra else GEOMETRY_BACKEND_BINDING),'common_input_digest':digest(common),
        'admission_digest':digest(admission),'candidate_backend':config['candidate_backend'],
        'generator_config_digest':config['generator_config_digest'],'config_digest':digest(config),
        'source_identity':config['runtime_identity']['source_identity']})


@dataclass(frozen=True)
class GeometryCandidateBundle(CandidateBundle):
    _audit_json: str='{}'
    _telemetry_json: str='{}'

    @property
    def audit(self):return json.loads(self._audit_json)

    @property
    def telemetry(self):return json.loads(self._telemetry_json)

    def with_data(self,value):return replace(self,_json=canonical(value))

    @classmethod
    def from_artifacts(cls,value,audit,telemetry=None):
        return cls(canonical(value),canonical(audit),canonical(telemetry or {}))


class GeometryConstructionError(JevSelectError):
    def __init__(self,scope,code,detail,audit,telemetry=None):
        super().__init__(code,detail)
        self.scope=scope
        self.audit=copy.deepcopy(audit)
        self.telemetry=copy.deepcopy(telemetry or {})


def build_geometry_bundle(state,observation,generator_config,config,*,common_input=None):
    preflight_config(config)
    c.require(c.same_native(generator_config,backend_config(config['candidate_backend'])),
              'wrong backend generator config')
    audit={'version':GEOMETRY_AUDIT,'config':copy.deepcopy(config),'native_bytes_hex':None,
        'geometry_bytes_hex':None,'common_binding':None,'common_admission':None,
        'backend_binding':None,'generation':None,'final_candidates_digest':None,'generation_counts':None}
    try:
        n,g,common=capture_common_input(state,observation,config) if common_input is None else common_input
        views=validate_common_input(n,g,common,config,state=state,observation=observation)
        audit.update(native_bytes_hex=n.hex(),geometry_bytes_hex=g.hex(),common_binding=common)
        admission=_admit(views,common)
        audit['common_admission']=admission
    except (ValueError,KeyError,TypeError) as exc:
        code=getattr(exc,'code','INVALID_COMMON_INPUT')
        audit['generation']={'scope':'COMMON_INPUT_ERROR','code':code,'detail':str(exc)}
        raise GeometryConstructionError('COMMON_INPUT_ERROR',code,str(exc),audit,
            {'backend':config['candidate_backend'],'generation_called':False,
             'cache_hits':None,'cache_misses':None}) from exc
    binding=_backend_binding(common,admission,config)
    audit['backend_binding']=binding
    backend=config['candidate_backend']
    started=time.perf_counter()
    before_cache=None
    stats={'backend':backend,'generation_called':True,'cache_supported':backend=='e2_original_v1','cache_hits':None,'cache_misses':None}
    try:
        if backend=='e2_original_v1':
            from ..o4.extensions.e2.candidates import generate,_cached_generation
            from ..o4.buffer.buffer_state import ordered,physical
            from ..evaluation.geometry_oracle import check_candidate
            before=_cached_generation.cache_info()
            before_cache=before
            candidates=[];counts=[];rows=[]
            for pending in ordered(views['native']['current_state']):
                pick=pending['item']['item_id']
                group,row=generate(views['native']['current_state'],pick,[],copy.deepcopy(generator_config))
                for candidate in group:
                    errors=check_candidate(physical(views['native']['current_state'],pick),
                                            {'container':state['container']},candidate)
                    if errors:raise JevSelectError('physical_candidate_error',str(errors))
                candidates.extend(group)
                elapsed=row.pop('elapsed_seconds')
                stats.setdefault('item_elapsed_s',[]).append(elapsed)
                rows.append(row)
                if row['rejections'].get('independent_physics',0):
                    audit['generation']={'version':'geometry_e2_generation_audit_v1','backend':backend,
                                         'items':rows,'status':'ERROR'}
                    raise JevSelectError('PHYSICAL_CHECK_DISAGREEMENT','E2 independent_physics rejection')
                counts.append({'pick_item_id':pick,'returned':len(group),
                    'sampled_physical':row['public_enriched_physical_count'],
                    'rejections':row['rejections'],'enumeration_attempts':row['public_enumeration_attempts']})
            after=_cached_generation.cache_info()
            stats.update(cache_hits=after.hits-before.hits,cache_misses=after.misses-before.misses)
            audit['generation']={'version':'geometry_e2_generation_audit_v1','backend':backend,'items':rows,
                'raw_valid_candidates':'NOT_AVAILABLE_OLD_E2_INTERFACE','status':'OK' if candidates else 'OK_EMPTY'}
        else:
            from ..planner.space_candidates.generator import _generation_core
            def adapt_common(raw):
                v=validate_common_input(n,raw,common,config)
                return v['exact'],v['physical'],v['geometry_state'],v['geometry_bytes'],digest(binding)
            result=_generation_core(g,adapt_input=adapt_common,identity_namespace='runtime_snapshot_v1')
            audit['generation']=result
            if result['status']=='ERROR':
                raise JevSelectError(result['error']['code'],result['error']['detail'])
            candidates=result['candidates']
            counts=[{'pick_item_id':r['item_id'],'returned':r['final_candidates'],
                     'sampled_physical':r['raw_valid_count'],'rejections':r['rejection_counts'],
                     'enumeration_attempts':r['raw_point_attempts']} for r in result['audit']['items']]
    except (ValueError,KeyError,TypeError) as exc:
        if backend=='e2_original_v1' and before_cache is not None:
            after=_cached_generation.cache_info()
            stats.update(cache_hits=after.hits-before_cache.hits,cache_misses=after.misses-before_cache.misses)
        stats['generation_s']=time.perf_counter()-started
        audit['backend_error']={'code':getattr(exc,'code','GEOMETRY_BACKEND_ERROR'),'detail':str(exc)}
        raise GeometryConstructionError('BACKEND_INTERNAL_ERROR',audit['backend_error']['code'],str(exc),audit,stats) from exc
    stats['generation_s']=time.perf_counter()-started
    if config['version'] in (GEOMETRY_NATIVE_VERSION,GEOMETRY_JEV_VERSION):
        from .geometry_native_shape_bridge import publish_native_shape_pool_v3
        try:
            candidates,publication=publish_native_shape_pool_v3(n,g,common,binding,c.encode(audit['generation']),c.encode(candidates),config=config)
        except (ValueError,KeyError,TypeError) as exc:
            audit['raw_pool_bytes_hex']=c.encode(candidates).hex()
            raise GeometryConstructionError('PUBLICATION_ERROR',getattr(exc,'code','NUM_BRIDGE_IDENTITY_MISMATCH'),str(exc),audit,stats) from exc
        audit.update(version='geometry_provider_audit_v2',publication=publication)
    audit['final_candidates_digest']=digest(candidates)
    audit['generation_counts']=copy.deepcopy(counts)
    from .packaging_runtime import no_policy
    from .packaging_versions import GEOMETRY_ORDER_VERSION, GEOMETRY_ORDER_BUNDLE
    value={'version':GEOMETRY_JEV_BUNDLE if config['version']==GEOMETRY_JEV_VERSION else GEOMETRY_NATIVE_BUNDLE if config['version']==GEOMETRY_NATIVE_VERSION else GEOMETRY_ORDER_BUNDLE if config['version']==GEOMETRY_ORDER_VERSION else GEOMETRY_RUN_BUNDLE if config['version']==GEOMETRY_RUN_VERSION else GEOMETRY_BUNDLE,'observation_digest':observation['observation_digest'],
        'candidate_backend':backend,'generator_config_digest':digest(generator_config),
        'physical_candidates':candidates,'physical_digest':digest(candidates),'generation_counts':counts,
        'selectable_pool':'physical_feasible','selectable_candidates':copy.deepcopy(candidates),
        'selectable_digest':digest(candidates),'policy_digest':digest(no_policy(observation).data),
        'experiment_protocol':config['experiment_protocol'],'business_mode':config['business_mode'],
        'geometry_audit_digest':digest(audit),'geometry_audit_ref':'IN_MEMORY_SIDECAR_V1',
        'common_input_digest':digest(common),'backend_binding_digest':digest(binding)}
    return GeometryCandidateBundle.from_artifacts(value,audit,stats)


def validate_geometry_config_bundle(config,bundle):
    """Check caller identity against the frozen sidecar; never rebind a pool.

    Keep this check independent of context reconstruction so every public
    consumer can reject a mixed pair before projecting any F0 facts.
    """
    validate_schema('config',config)
    c.require(isinstance(bundle,GeometryCandidateBundle),'v14 bundle requires its original audit/byte artifacts')
    audit=bundle.audit
    frozen=audit['config']; binding=audit['backend_binding']; value=bundle.data
    if not (c.same_native(config,frozen) and
            digest(config)==binding['config_digest'] and
            config.get('candidate_backend')==binding['candidate_backend']==value['candidate_backend'] and
            config.get('generator_config_digest')==binding['generator_config_digest']==value['generator_config_digest'] and
            c.same_native(config.get('runtime_identity'),frozen['runtime_identity'])):
        raise JevSelectError('geometry_config_bundle_mismatch','caller config differs from frozen bundle config')
    preflight_config(config)


def validate_geometry_bundle(observation,bundle):
    c.require(isinstance(bundle,GeometryCandidateBundle),'v14 bundle requires its original audit/byte artifacts')
    value,audit=bundle.data,bundle.audit
    native=audit['config']['version'] in (GEOMETRY_NATIVE_VERSION,GEOMETRY_JEV_VERSION)
    c.closed(audit,({'publication'} if native else set()) | {'version','config','native_bytes_hex','geometry_bytes_hex','common_binding',
                    'common_admission','backend_binding','generation','final_candidates_digest','generation_counts'})
    c.require(audit['version']==('geometry_provider_audit_v2' if native else GEOMETRY_AUDIT) and digest(audit)==value['geometry_audit_digest'],'audit digest/version drift')
    config=audit['config']
    n,g=bytes.fromhex(audit['native_bytes_hex']),bytes.fromhex(audit['geometry_bytes_hex'])
    v=validate_common_input(n,g,audit['common_binding'],config)
    c.require(c.same_native(v['native']['observation'],observation),'bundle observation drift')
    admission=audit['common_admission']
    c.closed(admission,{'version','common_input_digest','status','ledger_views','physical_prefix_digest',
                        'oracle_prefix_digest','physical_settings_digest','record_digest'})
    c.require(admission['version']==GEOMETRY_ADMISSION and admission['status']=='PASS' and
        admission['common_input_digest']==digest(audit['common_binding']) and
        admission['record_digest']==digest({k:v for k,v in admission.items() if k!='record_digest'}),'admission drift')
    expected=_backend_binding(audit['common_binding'],admission,config)
    c.closed(audit['backend_binding'],set(expected))
    c.require(c.same_native(audit['backend_binding'],expected) and
        value['backend_binding_digest']==digest(expected) and value['common_input_digest']==digest(audit['common_binding']) and
        value['candidate_backend']==config['candidate_backend'] and
        value['generator_config_digest']==config['generator_config_digest'],'backend binding drift')
    c.require(c.same_native(value['physical_candidates'],value['selectable_candidates']) and
              value['physical_digest']==value['selectable_digest'],'v14 requires complete final physical pool')
    c.require(audit['final_candidates_digest']==value['physical_digest'] and
              c.same_native(audit['generation_counts'],value['generation_counts']),'pool/count audit drift')
    if native:
        from .geometry_native_shape_bridge import validate_native_shape_publication_v3
        raw,generation=validate_native_shape_publication_v3(n,g,audit['common_binding'],audit['backend_binding'],value['physical_candidates'],audit['publication'],config=config)
        c.require(c.same_native(generation,audit['generation']),'publication generation drift')
    elif config['candidate_backend']=='ems_surface_hybrid_v1':
        c.require(c.same_native(audit['generation']['candidates'],value['physical_candidates']),
                  'new backend final pool differs from generation audit')
    return value
