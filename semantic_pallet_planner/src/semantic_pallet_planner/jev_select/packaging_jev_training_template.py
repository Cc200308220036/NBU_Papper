"""JM1-B2 non-executable templates, arithmetic and saved-fact checking only.

No transport/engine/solver imports. Private full-item counts are budget metadata,
never passed to the B1 sampler. No formal freezing or execution API exists here.
"""
from __future__ import annotations

import argparse
import copy
from fractions import Fraction
import json
from pathlib import Path

from .packaging_versions import JM_TRAINING_TEMPLATE_VERSION, JM_SAVED_BYTES_AUDIT_VERSION
from . import packaging_jev_sampling as public

LIMITS={'baselines':6,'points':12,'per_task_stage':1,'branches_per_point':3,
        'initial_suffixes':36,'repeat_points':4,'extra_repeats_per_branch':1,
        'repeat_suffixes':12,'total_suffixes':48}
IDENTITIES=('v3_execution','v3_recovery','data','arrival','model_service','prompt',
            'strategy','dependencies','algorithm','source_isolation','user_send_authorization')
SCHEMAS=Path(__file__).with_name('schemas')
require=public.require


def schema(value,name):
    public._validate(value,json.loads((SCHEMAS/(name+'.schema.json')).read_text()))


def saved_ref(path, *, root, pointer=''):
    root=Path(root).resolve();p=(root/path).resolve()
    require(not Path(path).is_absolute() and p.is_relative_to(root),'B2_PATH_ESCAPE')
    return {'path':Path(path).as_posix(),'sha256':public.sha(p.read_bytes()),'pointer':pointer}


def read_saved(ref, *, root):
    # Same closed ref shape as B1; never loads a module from a referenced path.
    require(type(ref) is dict and set(ref)=={'path','sha256','pointer'},'B2_REF_SHAPE')
    root=Path(root).resolve();p=(root/ref['path']).resolve()
    require(not Path(ref['path']).is_absolute() and p.is_relative_to(root),'B2_PATH_ESCAPE')
    require(p.is_file(),'B2_MISSING_SAVED_FILE')
    raw=p.read_bytes();require(public.sha(raw)==ref['sha256'],'B2_SAVED_BYTES_CHANGED')
    value=public.strict_load(raw);pointer=ref['pointer']
    require(pointer=='' or pointer.startswith('/'),'B2_INVALID_POINTER')
    try:
        for part in pointer.split('/')[1:]:
            key=part.replace('~1','/').replace('~0','~')
            value=value[int(key)] if isinstance(value,list) else value[key]
    except (KeyError,IndexError,ValueError,TypeError) as exc:
        raise public.SamplingError('B2_INVALID_POINTER') from exc
    return value


def make_template(*, policy_ref, source_candidates_ref):
    """Six unbound capacity slots, NOT a six-task assignment or send config."""
    return {'version':JM_TRAINING_TEMPLATE_VERSION,'state':'TEMPLATE_ONLY',
        'execution_state':'NOT_EXECUTABLE','execution_authorized':False,'evidence_kind':'TEMPLATE_ONLY',
        'policy_ref':copy.deepcopy(policy_ref),'source_candidates_ref':copy.deepcopy(source_candidates_ref),
        'slots':[{'slot_id':f'W{1+i//3}S{1+i%3}','wave':1+i//3,'ordinal':i+1,'assignment':None} for i in range(6)],
        'points':[],'repeat_point_ids':[],'limits':dict(LIMITS),'sampling_protocol':public.JM_SAMPLING_VERSION,
        'real_epsilon':'NOT_MATERIALIZED_DEFER_C1','real_identities':dict.fromkeys(IDENTITIES),
        'gates':{'baseline':'DEFER_REAL_IDENTITY_AND_FORMAL_TASKS',
                 'c1':'BASELINE_THEN_PUBLIC_SAMPLING_THEN_STOP',
                 'c2':'CONSUME_SEPARATELY_FROZEN_C1_PLAN_ONLY'}}


def relation_components(rows):
    """Conservative transitive union of *saved* relation tokens; no source mining.

    This returns material components, not certified independent real sources.
    UNKNOWN membership makes the independent denominator UNKNOWN, never zero.
    """
    components=[]
    for row in rows:
        task=row['task_id'];tokens=set(row['relation_tokens'])|{'SOURCE:'+row['source_group']}
        merged={'tasks':{task},'tokens':tokens}
        kept=[]
        for c in components:
            if c['tokens'] & merged['tokens']:
                merged['tasks'] |= c['tasks'];merged['tokens'] |= c['tokens']
            else:kept.append(c)
        # Previously disjoint components may become connected by a bridge.
        again=True
        while again:
            again=False;rest=[]
            for c in kept:
                if c['tokens'] & merged['tokens']:
                    merged['tasks']|=c['tasks'];merged['tokens']|=c['tokens'];again=True
                else:rest.append(c)
            kept=rest
        components=kept+[merged]
    result=[{'tasks':sorted(c['tasks']),'tokens':sorted(c['tokens'])} for c in components]
    result.sort(key=lambda c:public.digest(c))
    return {'material_components':result,'component_count':len(result),
            'independent_real_sources':'UNKNOWN_NOT_CERTIFIED',
            'membership_status':'UNKNOWN' if any(r['relation_completeness']=='UNKNOWN' for r in rows) else 'CONSTRUCTED_COMPLETE'}


def repeat_priority(points, *, task_order):
    """Closed public metadata only; stage rounds, new components first.

    Alternate OPENING/NONEMPTY queues in rounds; within each queue prefer unseen components,
    task order next, then task/decision digest. At most four distinct starts.
    All branches at each selected start receive exactly one extra repeat.
    """
    allowed={'point_id','task_id','stage','source_component','decision_digest'}
    require(all(type(p) is dict and set(p)==allowed for p in points),'B2_REPEAT_PUBLIC_FIELDS_ONLY')
    require(type(task_order) is list and len(task_order)==len(set(task_order))<=6,'B2_REPEAT_TASK_ORDER')
    require(all(p['task_id'] in task_order and p['stage'] in ('OPENING','NONEMPTY') for p in points),'B2_REPEAT_UNKNOWN_POINT')
    require(len({p['point_id'] for p in points})==len(points),'B2_DUPLICATE_POINT')
    require(len({(p['task_id'],p['stage']) for p in points})==len(points),'B2_DUPLICATE_STAGE')
    selected=[];seen=set()
    queues={stage:[p for p in points if p['stage']==stage] for stage in ('OPENING','NONEMPTY')}
    while any(queues.values()) and len(selected)<4:
        for stage in ('OPENING','NONEMPTY'):
            remaining=queues[stage]
            if not remaining or len(selected)>=4:
                continue
            p=min(remaining,key=lambda p:(p['source_component'] in seen,task_order.index(p['task_id']),
                                          public.digest(p['task_id']),p['decision_digest'],p['point_id']))
            selected.append(p['point_id']);seen.add(p['source_component']);remaining.remove(p)
    return selected


def _same_fact(actual, expected, code):
    """Value and JSON type equality, so true/1 or 1.0/1 cannot mask a mismatch."""
    require(public.digest(actual)==public.digest(expected),code)


def _saved_ratio(value, code):
    require(type(value) is dict and set(value)=={'numerator','denominator'} and
            type(value['numerator']) is int and type(value['denominator']) is int and
            value['denominator']>0,code)
    ratio=Fraction(value['numerator'],value['denominator'])
    _same_fact(value,public._ratio(ratio),code)
    return ratio


def _probability_facts(projection):
    # Pure original-byte parser and exact grouping only. Never B1.sample.
    native=public.parse_probabilities(projection)
    groups=public._groups(projection,native)
    top=max(g['score'] for g in groups.values())
    require(top>0,'B2_NONPOSITIVE_NATIVE_MAX')
    gaps={key:(top-g['score'])/top for key,g in groups.items()}
    original=projection['original']['exact_action_digest']
    stratum=('OBSERVED_EXACT_TOP_TIE' if gaps[original]==0 and
             sum(gap==0 for gap in gaps.values())>1 else 'RELATIVE_NEAR_TOP')
    return {'native':native,'groups':groups,'gaps':gaps,'stratum':stratum}


def _validate_point_diagnostic(ref, projection, point, facts, *, root):
    """Bind epsilon to the same hashed diagnostic that contains selected_point.

    Validate saved threshold arithmetic and this decision's raw-derived facts;
    do not regenerate point selection or infer missing baseline decisions.
    Standalone selected-point files cannot prove their epsilon and are refused.
    """
    parts=ref['pointer'].split('/')
    require(len(parts)==3 and parts[0]=='' and parts[1]=='selected_points' and
            parts[2].isdigit(),'B2_MISSING_SAMPLING_DIAGNOSTIC')
    diagnostic=read_saved({**ref,'pointer':''},root=root)
    require(type(diagnostic) is dict and diagnostic.get('version')=='jev_jm_sampling_diagnostic_v1' and
            diagnostic.get('scope')=='CONSTRUCTED_ONLY' and diagnostic.get('execution_authorized') is False and
            diagnostic.get('policy_sha256')==public.POLICY_SHA256 and
            diagnostic.get('epsilon_status')=='DIAGNOSTIC_NOT_FORMAL_FROZEN_VALUE' and
            diagnostic.get('real_epsilon')=='NOT_MATERIALIZED_DEFER_C1','B2_DIAGNOSTIC_IDENTITY_CHANGED')
    epsilon=_saved_ratio(diagnostic.get('diagnostic_epsilon'),'B2_INVALID_DIAGNOSTIC_EPSILON')
    require(0<=epsilon<=Fraction(1,10),'B2_INVALID_DIAGNOSTIC_EPSILON')
    rows=diagnostic.get('rows')
    require(type(rows) is list,'B2_MISSING_DIAGNOSTIC_ROWS')
    positive=[]
    for row in rows:
        require(type(row) is dict,'B2_INVALID_DIAGNOSTIC_ROW')
        if row.get('min_positive_gap') is not None:
            gap=_saved_ratio(row['min_positive_gap'],'B2_INVALID_DIAGNOSTIC_GAP')
            require(gap>0 and row.get('probability_complete') is True,'B2_INVALID_DIAGNOSTIC_GAP')
            positive.append(gap)
    positive.sort()
    expected=min(positive[(len(positive)+3)//4-1],Fraction(1,10)) if positive else Fraction(0)
    require(type(diagnostic.get('positive_gap_denominator')) is int and
            diagnostic['positive_gap_denominator']==len(positive) and epsilon==expected,
            'B2_DIAGNOSTIC_EPSILON_PROCEDURE_CHANGED')
    matches=[r for r in rows if r.get('projection_digest')==public.digest(projection)]
    require(len(matches)==1,'B2_DIAGNOSTIC_PROJECTION_NOT_UNIQUE')
    row=matches[0]
    require(row.get('selected') is True and row.get('status')=='ELIGIBLE' and
            row.get('task_id')==projection['task_id'] and row.get('decision_id')==projection['decision_id'] and
            row.get('stage')==point['stage'] and row.get('stratum')==point['stratum'],
            'B2_DIAGNOSTIC_POINT_CHANGED')
    native=facts['native'];groups=facts['groups'];gaps=facts['gaps']
    _same_fact(row.get('native_lexemes'),native['lexemes'],'B2_DIAGNOSTIC_NATIVE_CHANGED')
    require(row.get('raw_sha256')==native['raw_sha256'],'B2_DIAGNOSTIC_RAW_CHANGED')
    expected_groups=[{k:v for k,v in g.items() if k!='score'}|{'score':public._ratio(g['score'])}
                     for _,g in sorted(groups.items())]
    _same_fact(row.get('groups'),expected_groups,'B2_DIAGNOSTIC_GROUPS_CHANGED')
    _same_fact(row.get('gaps'),{k:public._ratio(v) for k,v in sorted(gaps.items())},'B2_DIAGNOSTIC_GAPS_CHANGED')
    positives=[v for v in gaps.values() if v>0]
    _same_fact(row.get('min_positive_gap'),public._ratio(min(positives)) if positives else None,
               'B2_DIAGNOSTIC_MIN_GAP_CHANGED')
    layer=sorted(k for k,v in gaps.items() if v<=epsilon)
    _same_fact(row.get('registered_layer'),layer,'B2_DIAGNOSTIC_LAYER_CHANGED')
    require(all(b['exact_action_digest'] in layer for b in point['branches']),'B2_BRANCH_OUTSIDE_SAVED_LAYER')


def _branch_facts(projection,point):
    require(point['task_id']==projection['task_id'] and point['decision_id']==projection['decision_id'] and
            point['projection_digest']==public.digest(projection),'B2_POINT_PROJECTION_CHANGED')
    require(point['pool_ref']==projection['pool_ref'] and point['prefix_ref']==projection['prefix_ref'],
            'B2_POINT_SAVED_REFS_CHANGED')
    require(point['raw_sha256']==projection['probability_evidence']['raw_sha256'],'B2_POINT_RAW_CHANGED')
    stage='NONEMPTY' if projection['public_state']['placed_objects'] else 'OPENING'
    require(point['stage']==stage,'B2_STAGE_CHANGED')
    facts=_probability_facts(projection)
    require(point['raw_sha256']==facts['native']['raw_sha256'],'B2_POINT_RAW_CHANGED')
    require(point['stratum'] in ('OBSERVED_EXACT_TOP_TIE','RELATIVE_NEAR_TOP') and
            point['stratum']==facts['stratum'],'B2_STRATUM_CHANGED')
    branches=point['branches'];kinds=[b['kind'] for b in branches]
    require(2<=len(branches)<=3 and kinds[0]=='ORIGINAL_ACTION_REFERENCE' and
            len(set(kinds))==len(kinds) and set(kinds)<={'ORIGINAL_ACTION_REFERENCE','SAME_BOX_DIFFERENT_POSE','CROSS_BOX_SELECTION'},
            'B2_BRANCH_CLASSES')
    require(len({b['exact_action_digest'] for b in branches})==len(branches),'B2_DUPLICATE_EXACT_ACTION')
    pool={c['candidate_id']:c for c in projection['pool']}
    original=projection['original'];original_item=pool[original['candidate_id']]['pick_item_id']
    for b in branches:
        base={'kind','label','candidate_id','candidate_digest','native_lexeme','exact_action_digest',
              'action','members','group_score','relative_gap','layer'}
        extra=({'position_changed','orientation_changed'} if b['kind']=='SAME_BOX_DIFFERENT_POSE' else
               {'public_attribute_contrast'} if b['kind']=='CROSS_BOX_SELECTION' else set())
        require(set(b)==base|extra,'B2_BRANCH_CLOSED_FIELDS')
        require(all(set(m)=={'label','candidate_id','candidate_digest','native_lexeme'} for m in b['members']),
                'B2_MEMBER_CLOSED_FIELDS')
        require(b['candidate_id'] in pool,'B2_ACTION_NOT_IN_POOL');c=pool[b['candidate_id']]
        require(b['candidate_digest']==c['candidate_digest'] and b['exact_action_digest']==public.exact_digest(c) and
                b['action']==public.exact_action(c),'B2_EXACT_ACTION_CHANGED')
        require(any(m['label']==b['label'] and m['candidate_id']==b['candidate_id'] for m in projection['display_mapping']),
                'B2_BRANCH_MAP_CHANGED')
        if b['kind']=='ORIGINAL_ACTION_REFERENCE':
            require(all(b[k]==original[k] for k in ('label','candidate_id','exact_action_digest')),'B2_ORIGINAL_CHANGED')
        else:
            require((c['pick_item_id']==original_item)==(b['kind']=='SAME_BOX_DIFFERENT_POSE'),'B2_INTERVENTION_CHANGED')
        group=facts['groups'][b['exact_action_digest']]
        _same_fact(b['native_lexeme'],facts['native']['lexemes'][b['label']],'B2_NATIVE_LEXEME_CHANGED')
        _same_fact(b['members'],group['members'],'B2_GROUP_MEMBERS_CHANGED')
        _same_fact(b['group_score'],public._ratio(group['score']),'B2_GROUP_SCORE_CHANGED')
        gap=facts['gaps'][b['exact_action_digest']]
        _same_fact(b['relative_gap'],public._ratio(gap),'B2_RELATIVE_GAP_CHANGED')
        require(b['layer']==('EXACT_TOP' if gap==0 else 'RELATIVE_NEAR_TOP'),'B2_BRANCH_LAYER_CHANGED')
        if b['kind']=='SAME_BOX_DIFFERENT_POSE':
            original_pose=pool[original['candidate_id']]['pose'];alternative_pose=c['pose']
            _same_fact(b['position_changed'],any(original_pose[k]!=alternative_pose[k]
                       for k in ('x_mm','y_mm','z_base_mm')),'B2_POSITION_FLAG_CHANGED')
            _same_fact(b['orientation_changed'],original_pose['yaw_deg']!=alternative_pose['yaw_deg'],
                       'B2_ORIENTATION_FLAG_CHANGED')
        elif b['kind']=='CROSS_BOX_SELECTION':
            attributes={item['item_id']:item for item in projection['public_state']['buffer']}
            _same_fact(b['public_attribute_contrast'],{'original':attributes[original_item],
                       'alternative':attributes[c['pick_item_id']]},'B2_PUBLIC_ATTRIBUTE_CONTRAST_CHANGED')
    return stage,branches,facts


def validate_template(template, *, root):
    """Validate saved constructed facts only, never call B1.sample or an engine."""
    schema(template,'jm_training_template_v1')
    policy=read_saved(template['policy_ref'],root=root)
    require(template['policy_ref']['sha256']==public.POLICY_SHA256 and
            policy['version']=='jm0_b_sampling_policy_v1','B2_POLICY_CHANGED')
    read_saved(template['source_candidates_ref'],root=root)
    slots=template['slots']
    require([s['ordinal'] for s in slots]==list(range(1,len(slots)+1)),'B2_SLOT_ORDER')
    require(len({s['slot_id'] for s in slots})==len(slots),'B2_DUPLICATE_SLOT')
    require(all(s['wave']==1+i//3 for i,s in enumerate(slots)),'B2_WAVES_3_PLUS_3')
    metadata=[];unbound=[]
    for slot in slots:
        assignment=slot['assignment']
        if assignment is None:
            unbound.append(slot['slot_id']);continue
        require(template['evidence_kind']=='CONSTRUCTED_ONLY','B2_REAL_TASK_BINDING_NOT_IMPLEMENTED')
        m=read_saved(assignment['metadata_ref'],root=root);schema(m,'jm_constructed_budget_metadata_v1')
        require(assignment['task_id']==m['task_id'],'B2_TASK_METADATA_CHANGED')
        metadata.append(m)
    order=[m['task_id'] for m in metadata]
    require(len(order)==len(set(order)),'B2_DUPLICATE_TASK')
    # Unbound capacity slots are never silently replaced or counted as real jobs.
    require(not (unbound and template['points']),'B2_POINTS_WITH_UNBOUND_TASKS')
    components=relation_components(metadata)
    component_by_task={task:public.digest(c) for c in components['material_components'] for task in c['tasks']}
    tasks={m['task_id']:m for m in metadata};point_keys=set();point_ids=set();facts=[]
    for binding in template['points']:
        require(template['evidence_kind']=='CONSTRUCTED_ONLY','B2_REAL_POINT_BINDING_NOT_IMPLEMENTED')
        require(binding['task_id'] in tasks,'B2_POINT_UNKNOWN_TASK')
        p=read_saved(binding['projection_ref'],root=root)
        require(p['evidence_scope']=='CONSTRUCTED_ONLY','B2_REAL_PROJECTION_NOT_ADMITTED')
        public.validate_saved_evidence(p,root=root)
        require(p['probability_evidence'] is not None,'MISSING_NATIVE_PROBABILITIES')
        require(p['probability_evidence']['origin']=='CONSTRUCTED_ONLY','B2_CONSTRUCTED_RAW_REQUIRED')
        selected=read_saved(binding['selected_point_ref'],root=root)
        # Closed binding: the saved point must have exactly the existing B1 shape.
        require(set(selected)=={'task_id','decision_id','projection_digest','stage','stratum','pool_ref','prefix_ref','raw_sha256','branches'},
                'B2_SELECTED_POINT_SHAPE')
        stage,branches,probability_facts=_branch_facts(p,selected)
        _validate_point_diagnostic(binding['selected_point_ref'],p,selected,probability_facts,root=root)
        require(binding['point_id']==public.digest({'projection':public.digest(p),'decision_id':p['decision_id']}) and
                binding['stage']==stage and binding['task_id']==p['task_id'],'B2_POINT_ID_CHANGED')
        key=(p['task_id'],stage)
        require(key not in point_keys and binding['point_id'] not in point_ids,'B2_DUPLICATE_STAGE')
        point_keys.add(key);point_ids.add(binding['point_id'])
        m=tasks[p['task_id']]
        require(m['source_group']==p['source_group'],'B2_SOURCE_GROUP_CHANGED')
        placed=len(p['public_state']['placed_objects'])
        require(m['full_item_count']>placed and m['full_item_count']>=placed+len(p['public_state']['buffer']),
                'B2_IMPOSSIBLE_ITEM_DENOMINATOR')
        facts.append({'point_id':binding['point_id'],'task_id':p['task_id'],'stage':stage,
                      'source_component':component_by_task[p['task_id']],
                      'decision_digest':public.digest(p['decision_id']),
                      'branches':branches,'placed_before':placed})
    repeat_meta=[{k:f[k] for k in ('point_id','task_id','stage','source_component','decision_digest')} for f in facts]
    expected=repeat_priority(repeat_meta,task_order=order)
    require(template['repeat_point_ids']==expected,'B2_REPEAT_PREREGISTRATION_CHANGED')
    jobs=[]
    for m in metadata:
        jobs.append({'job_id':'BASELINE:'+m['task_id'],'allocation':'TRAIN_BASELINE','task_id':m['task_id'],
                     'point_id':None,'candidate_id':None,'repeat_slot':0,'full_items':m['full_item_count'],
                     'placed_before':0,'forced_first':0,'send_upper':m['full_item_count']})
    initial=0;repeated=0
    for f in facts:
        for repeat in range(2 if f['point_id'] in expected else 1):
            for b in f['branches']:
                n=tasks[f['task_id']]['full_item_count']
                jobs.append({'job_id':public.digest([f['point_id'],b['exact_action_digest'],repeat]),
                             'allocation':'TRAIN_SUFFIX','task_id':f['task_id'],'point_id':f['point_id'],
                             'candidate_id':b['candidate_id'],'repeat_slot':repeat,'full_items':n,
                             'placed_before':f['placed_before'],'forced_first':1,
                             'send_upper':max(0,n-f['placed_before']-1)})
                if repeat:repeated+=1
                else:initial+=1
    require(initial<=36 and repeated<=12 and initial+repeated<=48,'B2_SUFFIX_CAP')
    require(len({j['job_id'] for j in jobs})==len(jobs),'B2_DUPLICATE_JOB')
    baseline=sum(j['send_upper'] for j in jobs if j['allocation']=='TRAIN_BASELINE')
    suffix=sum(j['send_upper'] for j in jobs if j['allocation']=='TRAIN_SUFFIX')
    complete=not unbound and template['evidence_kind']=='CONSTRUCTED_ONLY'
    return {'version':'jev_jm_training_template_check_v2','state':'TEMPLATE_ONLY','execution_state':'NOT_EXECUTABLE',
            'execution_authorized':False,'evidence_kind':template['evidence_kind'],'status':'PASS_TEMPLATE_ONLY',
            'task_order':order,'unbound_slots':unbound,'points':len(facts),'initial_suffixes':initial,
            'repeat_points':expected,'repeat_suffixes':repeated,'total_suffixes':initial+repeated,
            'source_components':components,'jobs':jobs,
            'budget_status':'CONSTRUCTED_ONLY' if complete else 'NOT_MATERIALIZED',
            'baseline_send_upper':baseline if complete else None,'suffix_send_upper':suffix if complete else None,
            'global_send_upper':baseline+suffix if complete else None,
            'future_points_not_materialized':not facts,'budget_scope':'saved supplied points only; no future point budget invented',
            'actual_calls':0,'dispatches':0,'stop':True}


def formal_freeze_readiness(template, *, root):
    """Refusal receipt only. This module deliberately cannot issue formal plans."""
    checked=validate_template(template,root=root)
    return {'version':'jev_jm_training_formal_gate_v1','status':'REFUSED','formal_frozen':False,
            'execution_authorized':False,'reasons':['TEMPLATE_ONLY_NOT_FORMAL_PLAN',
                'REAL_V3_EXECUTION_AND_RECOVERY_NOT_IMPLEMENTED','REAL_IDENTITIES_NOT_BOUND',
                'FORMAL_TASK_AND_SOURCE_ADMISSION_NOT_IMPLEMENTED','SEPARATE_USER_SEND_AUTHORIZATION_REQUIRED']+
                (['UNBOUND_TASK_SLOTS'] if checked['unbound_slots'] else [])+
                (['CONSTRUCTED_DATA_NOT_REAL_EVIDENCE'] if template['evidence_kind']=='CONSTRUCTED_ONLY' else []),
            'dispatches':0}


def validate_saved_audit(capsule, *, root):
    """HEAD-independent pure bytes check (also usable for the B1 QA finding).

    entry_head is pinned provenance, never resolved against mutable Git HEAD.
    EXACT checks whole bytes; ENTRY_PREFIX is solely for inert append-only
    packaging_versions registrations in B1 supplement scope. No resealing.
    """
    schema(capsule,'jm_saved_bytes_audit_v1');root=Path(root).resolve();seen=set()
    for row in capsule['files']:
        path=(root/row['path']).resolve()
        require(not Path(row['path']).is_absolute() and path.is_relative_to(root),'B2_PATH_ESCAPE')
        require(path not in seen,'B2_DUPLICATE_AUDIT_FILE');seen.add(path)
        require(path.is_file(),'B2_MISSING_SAVED_FILE');raw=path.read_bytes()
        if row['comparison']=='ENTRY_PREFIX':
            require(capsule['scope']=='B1_SUPPLEMENT_ONLY' and
                    row['path']=='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py',
                    'B2_PREFIX_SCOPE_FORBIDDEN')
            require(len(raw)>=row['bytes'] and row['extension_sha256'] is not None and
                    public.sha(raw[row['bytes']:])==row['extension_sha256'],'B2_SOURCE_DRIFT')
            raw=raw[:row['bytes']]
        else:require(len(raw)==row['bytes'] and row['extension_sha256'] is None,'B2_SOURCE_DRIFT')
        require(public.sha(raw)==row['sha256'],'B2_SOURCE_DRIFT')
    return {'version':'jev_jm_saved_bytes_check_v1','entry_head':capsule['entry_head'],
            'scope':capsule['scope'],'status':'PASS_SAVED_BYTES_ONLY','files':len(seen),
            'git_head_dependency':False,'dispatches':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['template','audit','formal-gate'])
    parser.add_argument('input');parser.add_argument('--root',default='.')
    args=parser.parse_args();value=public.strict_load(Path(args.input).read_bytes())
    function={'template':validate_template,'audit':validate_saved_audit,'formal-gate':formal_freeze_readiness}[args.mode]
    print(json.dumps(function(value,root=args.root),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
