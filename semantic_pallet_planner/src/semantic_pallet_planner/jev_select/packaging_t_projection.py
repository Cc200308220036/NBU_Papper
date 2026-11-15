"""JM2-A2 pure archive projection. No dispatch, retrieval or applicability route.

The producer audits source bytes separately. Observations are historical training
facts, never current query fields. Exact IDs and full trajectories remain private.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from . import packaging_scenario_features as scenario
from .packaging_jev_sampling import _validate, digest
from .packaging_versions import JM_T_PROJECTION, JM_T_QUERY, JM_T_SCHEMAS

METRICS=('placed_items','placed_volume_mm3','placed_volume_ratio','placed_item_ratio',
         'placed_mass_kg','placed_mass_ratio','fixed_container_utilization','actual_height_mm',
         'envelope_utilization','elapsed_s','requests','input_tokens','output_tokens')
LIMITS=['ARCHIVE_ONLY_PENDING_A3', 'FEATURE_EQUALITY_IS_NOT_SUFFICIENCY_OR_APPLICABILITY',
        'NO_CROSS_START_OR_CAUSAL_MECHANISM_SUPPORT', 'SYNTHETIC_PACKAGING_FEASIBILITY_UNKNOWN',
        'COVERAGE_PARTIAL', 'PREDICTED_STATIC_INSTABILITY_ONLY',
        'CONNECTED_FREE_SPACE_EXPOSED_SURFACE_LOAD_PATHS_NOT_IMPLEMENTED']


def validate(value):
    scenario.require(type(value) is dict and value.get('version') in JM_T_SCHEMAS,
                     'UNKNOWN_T_PROTOCOL')
    schema=json.loads((Path(__file__).with_name('schemas') /
                      (JM_T_SCHEMAS[value['version']]+'.schema.json')).read_text())
    digest(value)
    _validate(value,schema)
    state=value['structure'];boxes={b['box_role']:b for b in state['buffer']}
    ids=[b['box_role'] for b in state['buffer']+state['placed_objects']]
    scenario.require(len(ids)==len(set(ids)),'DUPLICATE_ANONYMOUS_BOX')
    if value['version']==JM_T_PROJECTION:
        for role in ('A','B'):
            a=value['actions'][role]
            scenario.require(a['box_role'] in boxes,'ROLE_BOX_NOT_IN_BUFFER')
            b=boxes[a['box_role']];attrs=a['attributes'];pose=a['pose'];container=state['container']
            expected_size=b['size_mm'] if pose['yaw_deg']==0 else [b['size_mm'][1],b['size_mm'][0],b['size_mm'][2]]
            scenario.require(a['oriented_size_mm']==expected_size,'ROLE_ORIENTATION_MISMATCH')
            expected=dict(zip(scenario.ROLE_KEYS,[*b['size_mm'],b['mass_kg'],b['max_top_load_kg'],b['stackable'],
                *a['oriented_size_mm'],pose['x_mm']/container['length_mm'],
                pose['y_mm']/container['width_mm'],pose['z_base_mm']/container['max_height_mm'],pose['yaw_deg']]))
            scenario.require(attrs==expected,'ROLE_ATTRIBUTE_COORDINATE_MISMATCH')
        a,b=(value['actions'][r] for r in ('A','B'))
        directions={k:scenario._direction(a['attributes'][k],b['attributes'][k]) for k in scenario.ROLE_KEYS}
        scenario.require(directions==value['attribute_directions'],'ROLE_DIRECTION_MISMATCH')
        relation=scenario._relation(dict(a,pick_item_id=a['box_role']),dict(b,pick_item_id=b['box_role']))
        scenario.require(relation==value['intervention'] and relation!='IDENTICAL_ACTION','INTERVENTION_MISMATCH')
        scenario.require(len(value['observations'])>0,'OBSERVATIONS_REQUIRED')
        for row in value['observations']:
            for k in METRICS:
                scenario.require(row['delta_B_minus_A'][k]==row['B'][k]-row['A'][k],
                                 'ROLE_OUTCOME_DIRECTION_MISMATCH')
    return value


def _public(history):
    scenario.validate_input(history)
    signature=scenario.build_signature(history)
    scenario.require(signature['stage']=='NONEMPTY','NONEMPTY_REQUIRED')
    scenario.require(history['pool'] is not None and len(history['pool'])>0,'FULL_POOL_REQUIRED')
    scenario.require(all(v['status']!='MISSING' for v in signature['features'].values()),
                     'MISSING_PUBLIC_CONDITION')
    state=copy.deepcopy(history['state'])
    aliases={b['item_id']:f'box_{i+1}' for i,b in enumerate(state['buffer'])}
    aliases.update({b['item_id']:f'placed_{i+1}' for i,b in enumerate(state['placed_objects'])})
    for b in state['buffer']+state['placed_objects']:
        b['box_role']=aliases.pop(b.pop('item_id'))
    query=dict(version=JM_T_QUERY,coordinate=scenario.COORDINATE,structure=state,
               features=copy.deepcopy(signature['features']))
    return validate(query)


def query_projection(history):
    """Only current public state/full pool accepted; no outcome or reference answer."""
    return _public(history)


def project_case(history,a_id,b_id,*,observations,continuation,evidence_grade,repeat_conflict):
    """A=registered reference, B=registered alternative; never winners/losers.

    No current correspondence is selected. A1 binding is reused for historical
    action attributes and directions, not as evidence of transfer or sufficiency.
    Missing facts reject; closed schemas exclude extra diagnostics and trajectories.
    """
    query=_public(history)
    scenario.require(a_id!=b_id,'DISTINCT_INTERVENTIONS_REQUIRED')
    binding=scenario.bind_contrast(history,a_id,b_id)
    scenario.require(binding['status'] in ('BOUND_DIAGNOSTIC_ONLY','AMBIGUOUS_DIAGNOSTIC'),
                     'MISSING_ROLE_CONDITION')
    actions={}
    for role in ('A','B'):
        r=binding['roles'][role];a=r['exact_action']
        actions[role]=dict(box_role=r['box_role'],pose=copy.deepcopy(a['pose']),
                           oriented_size_mm=copy.deepcopy(a['oriented_size_mm']),
                           attributes=copy.deepcopy(r['attributes']))
    scenario.require(type(observations) is list and len(observations)>0,'OBSERVATIONS_REQUIRED')
    for row in observations:
        observation_schema=json.loads((Path(__file__).with_name('schemas') /
                                       'jm_t_observation_v1.schema.json').read_text())
        _validate(row,observation_schema)
        for k in METRICS:
            scenario.require(row['delta_B_minus_A'][k]==row['B'][k]-row['A'][k],
                             'ROLE_OUTCOME_DIRECTION_MISMATCH')
    result=dict(version=JM_T_PROJECTION,coordinate=query['coordinate'],structure=query['structure'],
        features=query['features'],actions=actions,intervention=binding['intervention'],
        attribute_directions=binding['attribute_directions'],continuation=copy.deepcopy(continuation),
        observations=copy.deepcopy(observations),evidence_grade=evidence_grade,
        repeat_conflict=repeat_conflict,cross_start_support=0,limits=LIMITS.copy(),
        outcome_rule='jev_branch_comparison_rule_v2; B relative to A; labels are local observations',
        execution_eligible=False,sufficiency_review='NOT_RUN_A3')
    return validate(result)
