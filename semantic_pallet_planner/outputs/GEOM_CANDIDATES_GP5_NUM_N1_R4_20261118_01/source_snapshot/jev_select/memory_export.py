"""Training-only, completed-episode whitelist export. No private task suffix/AST."""
from __future__ import annotations

from .contracts import JevSelectError, canonical, digest, validate_schema

FORBIDDEN_KEYS = {'reference_policy', 'policy_ast', 'source_article_ids', 'provenance',
                  'task', 'all_tasks', 'future_items', 'display_mapping', 'local_binding',
                  'candidate_business_score', 'allowed_ids', 'Authorization', 'api_key'}


def validate_export(value):
    validate_schema('memory_episode_export', value)
    def walk(x):
        if isinstance(x, dict):
            if FORBIDDEN_KEYS.intersection(x):
                raise JevSelectError('private_field_in_training_export')
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(value)
    return value


def export_completed_episode(episode, training_manifest, *, version='jev_episode_export_v1'):
    """Manifest binds exact episode and source-code identity, not just a split label."""
    if version not in ('jev_episode_export_v1', 'jev_episode_export_v2'):
        raise JevSelectError('unknown_export_version')
    bindings = {}
    summary = episode.get('summary')
    cp = episode.get('checkpoint', {})
    if (not summary or not summary.get('termination_reason') or cp.get('reason') is None
            or cp.get('phase', 'READY') != 'READY' or cp.get('pending_event') is not None):
        raise JevSelectError('episode_not_terminal_or_evaluated')
    group = summary['source_order_key']
    identity = episode['job_id']
    if summary.get('partition') != 'train' or group not in training_manifest.get('source_groups', []):
        raise JevSelectError('nontraining_episode_export')
    entry = training_manifest.get('episodes', {}).get(identity)
    if not entry or entry.get('episode_digest') != digest(episode):
        raise JevSelectError('training_episode_not_bound')
    if entry.get('fixture_only', False):
        raise JevSelectError('fixture_training_export')
    code_digest = training_manifest.get('source_code_digest')
    if not code_digest or entry.get('source_code_digest') != code_digest:
        raise JevSelectError('training_source_code_mismatch')
    if summary.get('selector_backend') not in ('jev_no_memory', 'jev_choice'):
        raise JevSelectError('teacher_method_not_allowed')
    events = []
    previous_instances = set()
    for event in episode['events']:
        if event['event'] != 'PLACE': continue
        if event.get('business_after') is None:
            raise JevSelectError('unevaluated_training_action')
        ctx = event['context']
        if ctx['model_state'].get('memories'):
            raise JevSelectError('memory_assisted_training_not_allowed')
        if event['selection']['source'] not in ('jev', 'singleton'):
            raise JevSelectError('test_double_training_not_allowed')
        label = event['selection']['selected_display_id']
        criterion = ctx['criteria'][label]
        # Projection from already-sent public facts, not the environment task/reference.
        state = {k: ctx['model_state'][k] for k in ('units','container','placed_objects',
            'available_objects','regions','buffer','business_requirements','objective')}
        candidates = {key: {k: c[k] for k in ('pick_object','pose','oriented_size_mm','features','load_changes')}
                      for key,c in ctx['criteria'].items()}
        # Resolve feedback against the same public parser used by the request.
        # No reference policy or private task AST is consulted.
        from .candidates import PublicBusinessGuard
        observation = event['observation']
        public_ast = PublicBusinessGuard().resolve(observation).data['response']['policy_ast']
        rule_aliases = {r['rule_id']: f'R{i:02d}' for i,r in enumerate(public_ast['rules'],1)}
        object_aliases = {o['object_id']: f'B{i:03d}' for i,o in enumerate(
            observation['placed_objects']+observation['available_objects'],1)}
        bindings[event['decision_id']] = {alias: identity for identity, alias in object_aliases.items()}
        if len(bindings[event['decision_id']]) != len(object_aliases):
            raise JevSelectError('ambiguous_public_object_identity')
        def public_instance(instance):
            return {'kind':instance['kind'], 'rule_id':rule_aliases[instance['rule_id']],
                    'object_ids':[object_aliases[o] for o in instance['object_ids']],
                    'severity':instance['severity']}
        from .context import business_text
        if business_text(public_ast, object_aliases) != state['business_requirements']['english_descriptions']:
            raise JevSelectError('public_export_policy_semantics_changed')
        instances = event['business_after']['instances']
        public_feedback = {
            'instances':[public_instance(i) for i in instances],
            'new_instances':[public_instance(i) for i in instances if i['identity'] not in previous_instances],
            'coverage':[{**r,'rule_id':rule_aliases[r['rule_id']]} for r in event['business_after']['coverage']]}
        previous_instances = {i['identity'] for i in instances}
        events.append({'decision_id': event['decision_id'], 'public_state': state,
                       'public_feedback': public_feedback,
                       'candidate_facts': candidates, 'selected_action': criterion,
                       'feedback': {k:event['business_after'][k] for k in ('instances','coverage')}})
    reason = summary['termination_reason']
    value = {'version':'jev_episode_export_v1','episode_id':training_manifest.get('experiment_id', 'local') + ':' + identity,'source_group_id':group,
             'partition':'train','protocol_version':summary['version'],'source_code_digest':code_digest,
             'events':events,'terminal_feedback':{
                 'termination_reason':reason, **{k:summary[k] for k in ('planned_items','placed_items','placed_item_ratio','placed_volume_ratio')},
                 'truncated_by_service_failure':reason in ('UNKNOWN_IN_FLIGHT','PROVIDER_FAILURE','INVALID_RESPONSE')}}
    if version == 'jev_episode_export_v2':
        value.update(version=version, object_bindings=bindings)
    return validate_export(value)


def export_experiment(experiment, output, *, version='jev_episode_export_v1'):
    """Derive training whitelist from a verified sealed run, excluding baselines/test splits."""
    from pathlib import Path
    from .dataset_j4 import verify_seal
    from .ledger import read,write
    from .experiment import _new_output
    from .memory_store import MemoryStore
    root=Path(experiment)
    if verify_seal(root)['status']!='PASS':raise JevSelectError('training_source_not_sealed')
    source=read(root/'plan/source_manifest.json')
    code_digest=digest(source)
    exports=[];entries={};groups=set();skipped=[]
    episodes=[read(p) for p in sorted((root/'episodes').glob('*.json'))]
    for e in episodes:
        s=e['summary']
        if s.get('partition')!='train' or s.get('selector_backend') not in ('jev_choice','jev_no_memory'):
            skipped.append({'job_id':e['job_id'],'reason':'not_training_D0'});continue
        groups.add(s['source_order_key'])
        entries[e['job_id']]={'episode_digest':digest(e),'source_code_digest':code_digest,'fixture_only':False}
    manifest={'experiment_id':root.name,'source_code_digest':code_digest,'source_groups':sorted(groups),'episodes':entries}
    for e in episodes:
        if e['job_id'] in entries:exports.append(export_completed_episode(e,manifest,version=version))
    if not exports:raise JevSelectError('no_real_training_episodes')
    out=_new_output(output);out.mkdir(parents=True)
    write(out/'training_manifest.json',manifest)
    store=MemoryStore(out/'store')
    for value in exports:store.ingest(value)
    report={'status':'PASS','exported_episodes':len(exports),'skipped':skipped,'model_api_calls':0,
            'scope':'WHITELIST_ONLY_NO_SUMMARIZATION'}
    write(out/'export_report.json',report)
    return report


HISTORY_PROJECTION_VERSION = 'decision_event_self_contained_v1'
HISTORY_OMISSIONS = [
    'unexecuted candidate poses and candidate scores',
    'original-language policy duplicate (full English semantics retained)',
    'objective boilerplate and buffer arrival indices',
    'unrelated available boxes (all placed resource objects retained)',
    'geometry score components and heavy-box preference features',
    'local source identifiers (retained only in provenance)',
]


def build_raw_history(exports, *, projection='v1'):
    """Complete event or exclusion, never feedback truncation or outcome filtering.

    Legacy B0 feedback has unresolved private instance/rule handles: fail closed.
    New exports carry public_feedback with rule/object aliases resolved at export.
    All placed resource objects and public region definitions are kept, avoiding
    an unsupported guess about which spatial facts might matter.
    """
    from collections import Counter
    from .memory_query import build_query
    if projection not in ('v1','v2'): raise JevSelectError('unknown_history_projection')
    projection_version = HISTORY_PROJECTION_VERSION if projection == 'v1' else 'decision_event_columnar_v2'
    histories=[]; excluded=[]; total=0
    for export in sorted(exports, key=digest):
        validate_export(export)
        for event in export['events']:
            total+=1
            provenance={k:export[k] for k in ('source_group_id','episode_id')}
            provenance.update(decision_id=event['decision_id'],export_digest=digest(export))
            state=event['public_state']; action=event['selected_action']
            if 'public_feedback' not in event:
                excluded.append({**provenance,'reason':'PUBLIC_FEEDBACK_UNRESOLVED'});continue
            selected=next((o for o in state['available_objects'] if o['object_id']==action['pick_object']),None)
            if selected is None:
                excluded.append({**provenance,'reason':'SELECTED_OBJECT_UNRESOLVED'});continue
            # Source aliases are local to this historical event, explicitly defined here.
            body={'historical_event_local_aliases':True, 'units':{'length':'mm','mass':'kg','angle':'deg'},
                'container':state['container'], 'selected_box':selected,
                'actual_action':{k:action[k] for k in ('pick_object','pose','oriented_size_mm','load_changes')},
                'actual_geometry_support':{k:action['features'][k] for k in ('support_ratio','com_margin_mm','supported_by','resulting_max_height_mm','resulting_volume_utilization') if k in action['features']},
                'placed_resources':state['placed_objects'], 'regions':state['regions'],
                'public_business_semantics':state['business_requirements']['english_descriptions'],
                'actual_feedback':event['public_feedback'], 'terminal':export['terminal_feedback']}
            # A policy can refer to an available alias not selected in this event.
            import re
            rule_definitions = {m for text in body['public_business_semantics'] for m in re.findall(r'^(R\d+):',text)}
            if set(re.findall(r'\bR\d+\b',canonical(body))) - rule_definitions:
                excluded.append({**provenance,'reason':'PUBLIC_RULE_UNRESOLVED'});continue
            aliases=set(re.findall(r'\bB\d+\b',canonical(body)))
            defined={selected['object_id'],*(o['object_id'] for o in state['placed_objects'])}
            body['other_referenced_boxes']=[o for o in state['available_objects'] if o['object_id'] in aliases-defined]
            defined.update(o['object_id'] for o in body['other_referenced_boxes'])
            if aliases-defined:
                excluded.append({**provenance,'reason':'PUBLIC_OBJECT_UNRESOLVED'});continue
            if projection == 'v2':
                body = compact_history_event_v2(body)
            text=canonical(body); size=len(text.encode('utf-8'))
            if size>1600:
                excluded.append({**provenance,'reason':'EVENT_TOO_LARGE','utf8_bytes':size,'content_digest':digest(text)});continue
            query=build_query(state,{'english_descriptions':state['business_requirements']['english_descriptions']},event['candidate_facts'])
            gates=[{'field':'container_'+k,'op':'eq','value':v} for k,v in sorted(state['container'].items())]
            # Only finite public facts; same evaluator as cards. English constraints
            # remain in text, and are not represented as automatically satisfied.
            histories.append({**provenance,'history_id':digest(provenance),'text':text,
                'content_digest':digest(text),'utf8_bytes':size,'gates':gates,
                'projection_version':projection_version,'query_digest':query['query_digest']})
    reasons=Counter(e['reason'] for e in excluded)
    report={'version':projection_version,'total_events':total,'injectable_events':len(histories),
        'injectable_ratio':len(histories)/total if total else (None if projection == 'v2' else 0),'excluded_events':len(excluded),
        'exclusion_reasons':dict(sorted(reasons.items())),'exclusions':excluded,
        'omitted_fields':HISTORY_OMISSIONS,'source_groups':sorted({e['source_group_id'] for e in exports}),
        'selection_policy':'every actual decision; no outcome filtering','model_api_calls':0}
    return histories,report


def compact_history_event_v2(body):
    """Lossless shared column names for homogeneous object arrays; no field removal."""
    def encode(value):
        if isinstance(value,dict):
            if '$columns' in value or '$rows' in value: raise JevSelectError('reserved_history_encoding_key')
            return {k:encode(v) for k,v in value.items()}
        if isinstance(value,list):
            if len(value)>1 and all(isinstance(v,dict) for v in value):
                keys=sorted(value[0])
                if all(sorted(v)==keys for v in value):
                    encoded={'$columns':keys,'$rows':[[encode(v[k]) for k in keys] for v in value]}
                    ordinary=[encode(v) for v in value]
                    if len(canonical(encoded))<len(canonical(ordinary)): return encoded
            return [encode(v) for v in value]
        return value
    return {'encoding':'decision_event_columnar_v2',
            'semantics':'$columns lists object keys; each $rows row reconstructs one object in original list order. No field/value omitted.',
            'event':encode(body)}


def expand_history_event_v2(encoded):
    if encoded.get('encoding') != 'decision_event_columnar_v2':
        raise JevSelectError('unknown_history_projection')
    def decode(value):
        if isinstance(value,dict):
            if '$columns' in value:
                keys=value['$columns']
                if set(value)!={'$columns','$rows'} or len(set(keys))!=len(keys) or any(len(r)!=len(keys) for r in value['$rows']):
                    raise JevSelectError('invalid_history_columnar_table')
                return [{k:decode(v) for k,v in zip(keys,row)} for row in value['$rows']]
            return {k:decode(v) for k,v in value.items()}
        if isinstance(value,list):return [decode(v) for v in value]
        return value
    return decode(encoded['event'])
