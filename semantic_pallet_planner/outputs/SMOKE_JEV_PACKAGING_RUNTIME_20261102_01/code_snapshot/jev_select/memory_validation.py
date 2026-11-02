"""B2 field-level facts, independent review import and append-only card lifecycle.

Advice semantic support is never inferred by schema validation or this agent.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from .contracts import JevSelectError, canonical, digest, validate_schema
from .ledger import exclusive, read, write
from .memory_generation import pointer, validate_request

CONTENT_FIELDS_V1 = ('applicability','advice','observed_evidence','limitations_counterexamples','evidence_refs','knowledge_role')
CONTENT_FIELDS_V2 = CONTENT_FIELDS_V1 + ('comparison_basis','evidence_links','expected_effect_hypothesis','knowledge_role_basis','parent_card_ids','generator_digest','created_after_episode','card_version')


def card_content(card):
    fields = (CONTENT_FIELDS_V2 + ('fact_links','render_version','admission') if card['version']=='jev_memory_card_v4'
              else CONTENT_FIELDS_V2 + ('fact_links','render_version') if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4')
              else CONTENT_FIELDS_V2 if card['version'] == 'jev_memory_card_v2' else CONTENT_FIELDS_V1)
    content = {k:card[k] for k in fields}
    content.update({k:card[k] for k in ('gates','fixture_only') if k in card})
    return content


def validate_facts(card, requests, exports):
    validate_schema('memory_card', card)
    if card['content_digest'] != digest(card_content(card)):
        raise JevSelectError('memory_card_content_changed')
    prose = {k:card[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples','comparison_basis','expected_effect_hypothesis','knowledge_role_basis')}
    if re.search(r'\b(?:C\d{2}|SCN_\d+|item_\d+|SG_[a-f0-9]+|J\d+_D\d+)\b|reference_policy|policy_ast|future_items', canonical(prose)):
        raise JevSelectError('memory_card_identifier_leak')
    if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4'):
        validate_v3_links(card, requests, exports)
    refs = []; support = set(); used = set()
    for link in card['evidence_links']:
        req = requests.get(link['request_digest'])
        if req is None: raise JevSelectError('evidence_request_unavailable')
        validate_request(req)
        payload = req['input']['payload']; export = exports.get(payload['export_digest'])
        if export is None or payload['episode_id'] != link['episode_id'] or export['episode_id'] != link['episode_id']:
            raise JevSelectError('evidence_episode_unresolved')
        from .memory_generation import summary_for_request
        if req['input'] != summary_for_request(req,export): raise JevSelectError('evidence_input_changed')
        if req['version'] in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4'):
            if link not in resolve_fact_links(requests[card['generator_digest']], card['fact_links'], unit_resolution='context_units_v2' if card['version']=='jev_memory_card_v4' else None):
                raise JevSelectError('fact_link_resolution_changed')
            covered = []
        else:
            covered = [c for c in req['input']['coverage'] if c['decision_id'] == link['decision_id'] and
                   (link['path'] == c['path'] or link['path'].startswith(c['path']+'/'))]
        if not covered and req['version'] == 'jev_generation_request_v1': raise JevSelectError('evidence_not_in_actual_request')
        actual = pointer(payload, link['path'])
        if canonical(actual) != canonical(link['value']): raise JevSelectError('evidence_value_mismatch')
        for subtree in covered:
            if digest(pointer(payload, subtree['path'])) != subtree['subtree_digest']:
                raise JevSelectError('evidence_coverage_changed')
        if export.get('fixture_only') and not card.get('fixture_only'):
            raise JevSelectError('fixture_evidence_in_production_card')
        ref = {'episode_id':export['episode_id'],'source_group_id':export['source_group_id'],
               'export_digest':digest(export),'decision_id':link['decision_id']}
        if ref not in refs: refs.append(ref)
        if link['relation'] == 'support': support.add(export['source_group_id'])
        used.add(link['request_digest'])
    refs.sort(key=canonical)
    if refs != card['evidence_refs']: raise JevSelectError('evidence_refs_mismatch')
    expected = {'version':'jev_card_fact_validation_v2' if card['version']=='jev_memory_card_v4' else 'jev_card_fact_validation_v1','status':'PASS','request_digests':sorted(used),
                'support_source_groups':sorted(support), 'conflict':card['validation']['conflict'],
                'semantic_support':'REQUIRES_VERSIONED_SEMANTIC_REVIEW' if card['version']=='jev_memory_card_v4' else 'REQUIRES_INDEPENDENT_REVIEW'}
    if card['validation'] != expected: raise JevSelectError('card_validation_changed')
    review = card['semantic_review']
    if review['content_digest'] != card['content_digest'] or review['card_id'] != card['card_id']:
        raise JevSelectError('review_content_binding_changed')
    if not set(review['supported_source_groups']).issubset(support):
        raise JevSelectError('review_fabricated_source_support')
    if card['status'] == 'active' and not eligible(card):
        raise JevSelectError('memory_card_not_eligible_for_activation')
    return expected


def eligible(card):
    review = card['semantic_review']
    return (len(set(review['supported_source_groups'])) >= 2 and
            set(review['supported_source_groups']).issubset(card['validation']['support_source_groups']) and
            review['status'] == 'accepted' and review['conflicts_resolved'] and
            review['scope_and_advice_compatible'] and not card['validation']['conflict'] and
            review.get('assessed_knowledge_role',card['knowledge_role']) != 'rule_restatement')


def _maps(root):
    root = Path(root)
    return ({p.stem:read(p) for p in (root/'generation/requests').glob('*.json')},
            {p.stem:read(p) for p in (root/'exports').glob('*.json')})


def materialize_candidates(root, request, output, *, hook=None):
    root = Path(root); validate_schema('memory_generation_result', output)
    requests, exports = _maps(root)
    requests.update(request['context_requests'])
    rejects = []
    for index, proposal in enumerate(output['cards']):
        identity = digest({'request':request['request_digest'], 'index':index})
        path = root/'cards'/f'{identity}.json'
        if path.exists():
            old = read(path)
            # Reviews may change status; generated original never changes.
            if read(root/'originals'/f'{identity}.json')['proposal'] != proposal:
                raise JevSelectError('candidate_original_changed')
            _created_event(root, old)
            if old['version']=='jev_memory_card_v4':
                validate_corrective_admission(root,old)
                rejects.append({'card_id':identity,'reason':'fact_unit_mismatch'})
            continue
        # Keep every original, including rejected proposals.
        write(root/'originals'/f'{identity}.json', {'proposal':proposal,'request_digest':request['request_digest']})
        try:
            proposal = deepcopy(proposal)
            if request['version'] in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4'):
                proposal['evidence_links'] = resolve_fact_links(request, proposal['fact_links'])
            refs = []; used = set(); support = set()
            for link in proposal['evidence_links']:
                req = requests[link['request_digest']]; p = req['input']['payload']
                ref = {'episode_id':p['episode_id'],'source_group_id':p['source_group_id'],
                       'export_digest':p['export_digest'],'decision_id':link['decision_id']}
                if ref not in refs: refs.append(ref)
                if link['relation'] == 'support': support.add(p['source_group_id'])
                used.add(link['request_digest'])
            parents = {p['card_id']:p for p in request['parents']}
            if request['operation'] == 'generate' and (proposal['parent_card_ids'] or used != {request['request_digest']}):
                raise JevSelectError('generation_evidence_outside_request')
            if request['operation'] == 'merge':
                if set(proposal['parent_card_ids']) != set(parents): raise JevSelectError('merge_parent_changed')
                required_links = {canonical(link) for parent in parents.values() for link in parent['evidence_links']}
                actual_links = {canonical(link) for link in proposal['evidence_links']}
                if not required_links.issubset(actual_links):
                    raise JevSelectError('merge_dropped_evidence')
                if request['version'] in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4') and actual_links != required_links:
                    raise JevSelectError('merge_evidence_outside_parents')
            card = {'version':'jev_memory_card_v2', 'card_id':identity,'card_version':1,'content_digest':'0'*64,
                    'status':'candidate', **deepcopy(proposal), 'evidence_refs':sorted(refs,key=canonical),
                    'evidence_level':'observational','created_after_episode':request['input']['payload']['episode_id'],
                    'generator_digest':request['request_digest'], 'fixture_only':request['input']['payload']['fixture_only'],
                    'validation':{'version':'jev_card_fact_validation_v1','status':'PASS',
                                  'request_digests':sorted(used),'support_source_groups':sorted(support),
                                  # Consolidation needs explicit human scope/advice compatibility.
                                  'conflict':False,'semantic_support':'REQUIRES_INDEPENDENT_REVIEW'}}
            if request['version'] in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4'):
                card.update(version='jev_memory_card_v3',render_version='memory_prose_v2')
            if parents: card['card_version'] = max(p['card_version'] for p in parents.values())+1
            card['content_digest'] = digest(card_content(card))
            card['semantic_review'] = {'version':'jev_semantic_review_v1','card_id':identity,
                    'content_digest':card['content_digest'], 'reviewer':'unassigned',
                    'reviewer_kind':'independent_human','protocol_version':'observational_support_review_v1',
                    'status':'pending','reason':'Awaiting independent human semantic support review',
                    'supported_source_groups':[], 'conflicts_resolved':False,'scope_and_advice_compatible':False}
            if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4'):
                card['semantic_review'].update(version='jev_semantic_review_v2',
                    protocol_version='observational_support_review_v2',reviewed_at=None,
                    independence_declaration='',audit_binding_digest=review_binding(root,card),
                    source_assessments=[],checks={k:'unknown' for k in REVIEW_CHECKS_V2})
            validate_facts(card, requests, exports)
            write(path, card)
            _created_event(root, card)
            if hook: hook('after_card')
        except (JevSelectError, KeyError) as exc:
            rejects.append({'card_id':identity,'reason':exc.code if isinstance(exc,JevSelectError) else 'evidence_request_unavailable'})
    write(root/'generation/rejections'/f'{request["request_digest"]}.json', {'rejected':rejects})


def _created_event(root, card):
    value = {'card_id':card['card_id'],'content_digest':card['content_digest'],
             'from':None,'to':'candidate','reason':'corrective admission; historical refusal preserved; pending review' if card['version']=='jev_memory_card_v4' else 'generated; fact checked; pending independent review',
             'parent_card_ids':card['parent_card_ids']}
    path = root/'lifecycle'/f"{card['card_id']}_created.json"
    if path.exists() and read(path) != value: raise JevSelectError('lifecycle_changed')
    if not path.exists(): write(path,value)


def review_materials(store, output, *, reviewer_mode='independent_human', authorization_digest=None):
    from .experiment import _new_output
    root = Path(store); requests, exports = _maps(root)
    if reviewer_mode not in ('independent_human','developer_agent'): raise JevSelectError('unknown_reviewer_mode')
    if reviewer_mode == 'developer_agent': validate_developer_authorization(root,authorization_digest)
    out = _new_output(output); out.mkdir(parents=True)
    cards = [read(p) for p in sorted((root/'cards').glob('*.json'))]
    for card in cards:
        validate_facts(card, requests, exports)
        write(out/'cards'/f'{card["card_id"]}.json', card)
        template = developer_review_template(root,card,authorization_digest) if reviewer_mode=='developer_agent' else card['semantic_review']
        write(out/'templates'/f'{card["card_id"]}.json', template)
        if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4'):
            write(out/'source_worksheets'/f'{card["card_id"]}.json', {
                'claim':card['advice'],'scope':card['applicability'],
                'binding':review_binding(root,card),'source_groups':sorted({r['source_group_id'] for r in card['evidence_refs']}),
                'fact_links':card['fact_links'],'resolved_evidence_links':card['evidence_links'],
                'comparison':card['comparison_basis'],'counterexamples_unknowns':card['limitations_counterexamples'],
                'review_checks':list(REVIEW_CHECKS_V2)})
    protocol = {'version':'observational_support_review_v1',
                'reviewer_requirement':'Independent human; agent self-score and generation authorization are not acceptance.',
                'instructions':['Read every claim/advice, comparison basis, exact facts and original response.',
                   'Check applicability and advice are supported by each claimed independent source group; terminal correlation is not causation.',
                   'Preserve counterexamples and unknown scope. Resolve conflicts explicitly; do not rewrite card prose.',
                   'Accept, reject or keep pending. List only actually supporting source groups. Bind card_id/content_digest.',
                   'A text reviewer requires a separate authorized protocol and accounting; it is not enabled here.']}
    if any(r['version'] in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4') for r in requests.values()):
        protocol.update(version='observational_support_review_v2',
            identity_scope='Named reviewer declaration, not authenticated identity or digital signature',
            checks=list(REVIEW_CHECKS_V2),
            required_declaration='Actual independent reviewer name, timezone-aware reviewed_at, independence_declaration, per-source exact claim/scope and reason; all checks confirmed before acceptance')
    if reviewer_mode == 'developer_agent':
        protocol.update(version='developer_support_review_v1',reviewer_requirement='User-authorized development agent; explicitly not independent review',
            identity_scope='Development-agent assessment under a preserved user policy change',
            required_declaration='Developer identity and non-independence, actual reviewed_at, source assessments, assessed role and claim checks',
            authorization_digest=authorization_digest)
        protocol['instructions']=[text.replace('Independent human','User-authorized development agent').replace('independent human','development agent') for text in protocol['instructions']]
        for auth in (root/'review_authorizations').glob('*.json'):write(out/'review_authorizations'/auth.name,read(auth))
    write(out/'protocol.json', protocol)
    write(out/'requests.json', requests)
    write(out/'exports.json', exports)
    for sub in ('originals','generation/responses','generation/rejections','reviews','lifecycle','admissions'):
        for p in (root/sub).glob('*.json'): write(out/sub/p.name, read(p))
    report = {'status':'PASS','cards':len(cards),'pending':sum(c['semantic_review']['status']=='pending' for c in cards),'model_api_calls':0}
    write(out/'review_todo.json', report)
    return report


def import_review(store, review_file):
    root = Path(store); review = read(review_file); validate_schema('memory_review', review)
    if review['reviewer_kind'] != 'developer_agent' and review['reviewer'].lower() in ('unassigned','agent','codex','deepseek','self'):
        raise JevSelectError('independent_human_reviewer_required')
    if (root/'memory_manifest.json').exists(): raise JevSelectError('frozen_memory_is_readonly')
    with exclusive(root):
        path = root/'cards'/f'{review["card_id"]}.json'; card = read(path)
        requests, exports = _maps(root)
        if review['card_id'] != card['card_id'] or review['content_digest'] != card['content_digest']:
            raise JevSelectError('review_content_binding_changed')
        if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4'):
            validate_review_v2(review,card,root)
        card['semantic_review'] = review
        old = card['status']
        card['status'] = 'rejected' if review['status']=='rejected' else 'candidate'
        validate_facts(card, requests, exports)
        if eligible(card): card['status'] = 'active'
        write(root/'reviews'/f'{digest(review)}.json', review)
        write(root/'lifecycle'/f'{digest(review)}.json', {'card_id':card['card_id'],'from':old,'to':card['status'],
                    'reason':review['reason'],'review_digest':digest(review)})
        write(path, card)
        # Deterministic active cap, with original and review history retained.
        active = [read(p) for p in (root/'cards').glob('*.json') if read(p)['status']=='active']
        active.sort(key=lambda c:(-len(set(c['semantic_review']['supported_source_groups'])),c['content_digest']))
        for excess in active[64:]:
            excess['status']='retired'
            write(root/'cards'/f'{excess["card_id"]}.json',excess)
            write(root/'lifecycle'/f'{excess["card_id"]}_retired.json',{'card_id':excess['card_id'],'from':'active','to':'retired','reason':'deterministic active cap'})
        return {'status':'PASS','card_id':card['card_id'],'card_status':read(path)['status'],'model_api_calls':0}


def _validate_artifacts(artifacts, cards, exports):
    from .memory_generation import make_request, _parse_response
    import base64
    import hashlib
    requests = {p.stem:read(p) for p in (artifacts/'generation/requests').glob('*.json')}
    for request in requests.values():
        validate_request(request)
        expected = make_request(exports[request['input']['payload']['export_digest']], operation=request['operation'],
                                parents=request['parents'], context_requests=request['context_requests'], protocol=request['version'].rsplit('_',1)[1], merge_compatibility=request.get('merge_compatibility'))
        if request != expected: raise JevSelectError('generation_request_changed')
        if 'merge_compatibility' in request:
            from .memory_generation import validate_merge_compatibility
            validate_merge_compatibility(request['merge_compatibility'],request['parents'],artifacts)
    for path in (artifacts/'generation/attempts').glob('*.json'):
        row = read(path)
        wire = read(artifacts/'generation/wire_requests'/path.name)
        if digest(wire['body']) != row['wire_digest'] or wire['request_digest'] != row['request_digest'] or wire['operation'] != row['operation']:
            raise JevSelectError('generation_wire_changed')
        response_path = artifacts/'generation/responses'/path.name
        if response_path.exists():
            response = read(response_path)
            if (response.get('raw_digest') != digest(response['raw_body_b64']) or
                response.get('raw_sha256') != hashlib.sha256(base64.b64decode(response['raw_body_b64'])).hexdigest() or
                row.get('response_digest') != digest(response)):
                raise JevSelectError('generation_response_changed')
    for path in (artifacts/'generation/processed').glob('*.json'):
        processed = read(path); req = requests[processed['request_digest']]
        response_path = artifacts/'generation/responses'/f"{processed['attempts'][-1]}.json"
        if response_path.exists():
            output, _, _ = _parse_response(read(response_path),req['config']['model'],fixture=processed['fixture_only'])
            if output != processed['output']: raise JevSelectError('processed_response_changed')
    for card in cards:
        validate_facts(card,requests,exports)
        if card['version']=='jev_memory_card_v4':
            validate_corrective_admission(artifacts,card)
        if card['version'] in ('jev_memory_card_v3','jev_memory_card_v4'):
            validate_review_v2(card['semantic_review'],card,artifacts)
        processed = read(artifacts/'generation/processed'/f"{card['generator_digest']}.json")
        original = read(artifacts/'originals'/f"{card['card_id']}.json")
        proposal = original['proposal']
        if original['request_digest'] != card['generator_digest'] or proposal not in processed['output']['cards']:
            raise JevSelectError('candidate_original_changed')
        if any(card[k] != proposal[k] for k in proposal): raise JevSelectError('candidate_prose_changed')
        review = card['semantic_review']
        if review['status'] != 'pending' and read(artifacts/'reviews'/f"{digest(review)}.json") != review:
            raise JevSelectError('review_history_changed')
        created = read(artifacts/'lifecycle'/f"{card['card_id']}_created.json")
        if (created['content_digest'] != card['content_digest'] or created['parent_card_ids'] != card['parent_card_ids']
                or created['to'] != 'candidate' or created['from'] is not None):
            raise JevSelectError('lifecycle_changed')
        for parent in card['parent_card_ids']:
            if parent not in {c['card_id'] for c in cards}: raise JevSelectError('parent_card_missing')


def validate_store(store):
    root = Path(store); _, exports = _maps(root)
    cards = [read(p) for p in sorted((root/'cards').glob('*.json'))]
    _validate_artifacts(root,cards,exports)
    return {'status':'PASS','cards':len(cards),'candidate':sum(c['status']=='candidate' for c in cards),
            'active':sum(c['status']=='active' for c in cards),'rejected':sum(c['status']=='rejected' for c in cards),
            'retired':sum(c['status']=='retired' for c in cards),
            'requests':len(list((root/'generation/requests').glob('*.json'))),'model_api_calls':0}


def freeze_generation(store, output):
    from .memory_store import indexed_snapshot, freeze_snapshot
    root = Path(store); report = validate_store(root)
    requests, exports = _maps(root)
    cards = [read(p) for p in sorted((root/'cards').glob('*.json'))]
    artifacts = {str(p.relative_to(root)):read(p) for sub in ('generation','originals','reviews','lifecycle','review_authorizations','admissions')
                 for p in (root/sub).rglob('*.json')}
    # Includes rejected raw proposals, all saved responses, attempts and configuration.
    snapshot = indexed_snapshot(list(exports.values()), cards=cards)
    manifest = freeze_snapshot(snapshot, output, evidence_exports=list(exports.values()), artifacts=artifacts)
    # Read-only is an operational guard; digest verification is the integrity guard.
    for p in Path(output).rglob('*'):
        if p.is_file(): p.chmod(0o444)
    return {**report,'snapshot_digest':manifest['snapshot_digest']}


def validate_frozen_artifacts(root, snapshot, exports):
    """Read-only B2 artifact verification; no temporary store or mutation."""
    artifacts = Path(root)/'artifacts'
    cards = [c for c in snapshot['cards'] if c['version'] in ('jev_memory_card_v2','jev_memory_card_v3','jev_memory_card_v4')]
    _validate_artifacts(artifacts,cards,{digest(e):e for e in exports})


def resolve_fact_links(request, links, *, unit_resolution=None):
    """Resolve only against public fact slots in this wire, including merge parents."""
    from .memory_generation import public_input_v2, value_type, fact_unit
    import json
    if unit_resolution not in (None,'context_units_v2'):raise JevSelectError('unknown_unit_resolution')
    validate_request(request)
    if request['version'] not in ('jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4'):
        raise JevSelectError('fact_links_require_v2_request')
    user = json.loads(request['body']['messages'][1]['content'])
    public = public_input_v2(request['input'])
    if any(user.get(k) != v for k,v in public.items()):
        raise JevSelectError('fact_not_in_actual_request')
    parent_requests = {f'P{i+1:04d}':r for i,(_,r) in enumerate(sorted(request['context_requests'].items()))}
    result = []
    for link in links:
        target = request
        sent = user
        if 'request_alias' in link:
            if request['operation'] != 'merge' or link['request_alias'] not in parent_requests:
                raise JevSelectError('fact_request_alias_unresolved')
            target = parent_requests[link['request_alias']]
            sent = next((p for p in user.get('parent_requests',[]) if p['request_alias']==link['request_alias']),{})
            if any(sent.get(k)!=v for k,v in public_input_v2(target['input']).items()):
                raise JevSelectError('fact_not_in_actual_request')
        payload = target['input']['payload']
        facts = {f['fact_id']:(i,f) for i,f in enumerate(sent['facts'])}
        mapping = {c['fact_id']:c for c in target['input']['coverage']}
        if link['fact_id'] not in facts or link['fact_id'] not in mapping:
            raise JevSelectError('fact_not_in_actual_request')
        i, fact = facts[link['fact_id']]
        path = link['path']
        actual = fact['value'] if path == '/' else pointer(fact['value'],path)
        if canonical(actual) != canonical(link['value']) or value_type(actual) != link['value_type']:
            raise JevSelectError('fact_type_or_value_mismatch')
        from .memory_generation import context_fact_unit
        unit = context_fact_unit(fact['value'],path,actual) if request['version'] in ('jev_generation_request_v3','jev_generation_request_v4') or target['version'] in ('jev_generation_request_v3','jev_generation_request_v4') or unit_resolution=='context_units_v2' else fact_unit(path,actual)
        if unit != link['unit']:
            raise JevSelectError('fact_unit_mismatch')
        result.append({'request_digest':target['request_digest'],'episode_id':payload['episode_id'],
                       'decision_id':mapping[link['fact_id']]['decision_id'],
                       'path':f'/facts/{i}/value'+('' if path=='/' else path),
                       'value':actual,'relation':link['relation']})
    return result


def validate_v3_links(card, requests, exports):
    prose = {k:card[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples',
                                'comparison_basis','expected_effect_hypothesis','knowledge_role_basis')}
    if re.search(r'\b(?:[EOFB]\d+|R\d+|C\d+|J\d+(?:_D\d+)?|SG_\w+|EXP_\w+|SCN_\w+|item_\w+)\b',canonical(prose),re.IGNORECASE):
        raise JevSelectError('memory_card_identifier_leak')
    req = requests.get(card['generator_digest'])
    if req is None or card['evidence_links'] != resolve_fact_links(req, card['fact_links'], unit_resolution='context_units_v2' if card['version']=='jev_memory_card_v4' else None):
        raise JevSelectError('fact_link_resolution_changed')
    from .memory_retrieval import card_text
    if len(card_text(card).encode('utf-8')) > 1600:
        raise JevSelectError('memory_card_render_budget_exceeded')


REVIEW_CHECKS_V2 = ('field_truth','advice_support','scope','comparison','counterexamples_unknowns',
                    'observation_vs_causation','knowledge_role','incremental_content')


def review_binding(root, card):
    root = Path(root)
    req = read(root/'generation/requests'/f"{card['generator_digest']}.json")
    processed = read(root/'generation/processed'/f"{card['generator_digest']}.json")
    return digest({'content_digest':card['content_digest'],'request':req,
                   'original':read(root/'originals'/f"{card['card_id']}.json"),
                   'responses':[read(root/'generation/responses'/f'{a}.json') for a in processed['attempts']],
                   'export_digests':sorted({r['export_digest'] for r in card['evidence_refs']}),
                   'protocol':'observational_support_review_v2'})


def validate_review_v2(review, card, root):
    developer = review['version'] == 'jev_semantic_review_v3'
    if developer:
        validate_developer_authorization(root,review['authorization_digest'])
        expected_binding = developer_review_binding(root,card,review['authorization_digest'])
    elif review['version'] == 'jev_semantic_review_v2':
        expected_binding = review_binding(root,card)
    else:
        raise JevSelectError('unknown_semantic_review_version')
    if review['audit_binding_digest'] != expected_binding:
        raise JevSelectError('review_audit_binding_changed')
    groups = {r['source_group_id'] for r in card['evidence_refs']}
    rows = review['source_assessments']
    row_groups = [r['source_group_id'] for r in rows]
    if len(set(row_groups)) != len(row_groups) or not set(row_groups).issubset(groups):
        raise JevSelectError('review_source_assessment_changed')
    supported = {r['source_group_id'] for r in rows if r['decision']=='support'}
    if supported != set(review['supported_source_groups']):
        raise JevSelectError('review_source_support_mismatch')
    if review['status'] != 'pending':
        declaration = review['reviewer_declaration'] if developer else review['independence_declaration']
        if not review['reviewed_at'] or not declaration.strip():
            raise JevSelectError('independent_review_declaration_required')
        from datetime import datetime
        try:
            when = datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
            if when.tzinfo is None: raise ValueError()
        except ValueError as exc: raise JevSelectError('review_timestamp_invalid') from exc
        if set(row_groups) != groups:
            raise JevSelectError('review_source_assessment_incomplete')
    if review['status'] == 'accepted' and any(review['checks'][k]!='confirmed' for k in REVIEW_CHECKS_V2):
        raise JevSelectError('review_claim_checks_incomplete')


def validate_developer_authorization(root, authorization_digest):
    if not authorization_digest or not re.fullmatch(r'[a-f0-9]{64}',authorization_digest):
        raise JevSelectError('developer_review_authorization_required')
    path=Path(root)/'review_authorizations'/f'{authorization_digest}.json'
    if not path.is_file():raise JevSelectError('developer_review_authorization_required')
    authorization=read(path);validate_schema('memory_review_authorization',authorization)
    if digest(authorization)!=authorization_digest:raise JevSelectError('developer_review_authorization_changed')
    return authorization


def register_review_authorization(store, authorization_file):
    root=Path(store);authorization=read(authorization_file)
    validate_schema('memory_review_authorization',authorization)
    if (root/'memory_manifest.json').exists():raise JevSelectError('frozen_memory_is_readonly')
    identity=digest(authorization)
    with exclusive(root):
        path=root/'review_authorizations'/f'{identity}.json'
        if path.exists() and read(path)!=authorization:raise JevSelectError('developer_review_authorization_changed')
        write(path,authorization)
    return {'status':'PASS','authorization_digest':identity,'reviewer_mode':'developer_agent','independent_review':False,'model_api_calls':0}


def developer_review_binding(root, card, authorization_digest):
    return digest({'evidence_binding':review_binding(root,card),'protocol':'developer_support_review_v1',
                   'authorization_digest':authorization_digest})


def developer_review_template(root, card, authorization_digest):
    validate_developer_authorization(root,authorization_digest)
    if card['version'] not in ('jev_memory_card_v3','jev_memory_card_v4'):raise JevSelectError('developer_review_requires_v3_card')
    template=deepcopy(card['semantic_review'])
    template.pop('independence_declaration',None)
    template.update(card_id=card['card_id'],content_digest=card['content_digest'],version='jev_semantic_review_v3',reviewer='unassigned',reviewer_kind='developer_agent',
        protocol_version='developer_support_review_v1',independent_review=False,
        authorization_digest=authorization_digest,audit_binding_digest=developer_review_binding(root,card,authorization_digest),
        reviewer_declaration='User-authorized development-agent review; not an independent review.',
        reviewed_at=None,status='pending',reason='Pending user-authorized development-agent semantic assessment',
        supported_source_groups=[],source_assessments=[],conflicts_resolved=False,scope_and_advice_compatible=False,
        assessed_knowledge_role=card['knowledge_role'],checks={key:'unknown' for key in REVIEW_CHECKS_V2})
    validate_schema('memory_review',template)
    return template


def validate_corrective_admission(root, card):
    root=Path(root);admission=card['admission']
    rejection=read(root/'generation/rejections'/f"{card['generator_digest']}.json")
    if digest(rejection)!=admission['original_rejection_digest'] or not any(
            row['card_id']==card['card_id'] and row['reason']=='fact_unit_mismatch' for row in rejection['rejected']):
        raise JevSelectError('corrective_admission_history_changed')
    receipt=read(root/'admissions'/f"{card['card_id']}_context_v1.json")
    if receipt['status']!='PASS' or receipt['content_digest']!=card['content_digest'] or receipt['card_id']!=card['card_id']:
        raise JevSelectError('corrective_admission_receipt_changed')


def admit_unit_context_correction(store, proposal_id, authorization_digest):
    """Revalidate unchanged raw output with a new, explicit admission contract.

    Historical request, wire, raw response and technical refusal stay byte-identical.
    Only a v2 unit-context false negative is eligible. No model call or prose edit.
    """
    root=Path(store);validate_developer_authorization(root,authorization_digest)
    if (root/'memory_manifest.json').exists():raise JevSelectError('frozen_memory_is_readonly')
    with exclusive(root):
        original=read(root/'originals'/f'{proposal_id}.json');requests,exports=_maps(root)
        request=requests[original['request_digest']]
        if request['version']!='jev_generation_request_v2':raise JevSelectError('corrective_admission_requires_original_v2_request')
        rejection=read(root/'generation/rejections'/f"{request['request_digest']}.json")
        if not any(row['card_id']==proposal_id and row['reason']=='fact_unit_mismatch' for row in rejection['rejected']):
            raise JevSelectError('corrective_admission_requires_unit_false_negative')
        processed=read(root/'generation/processed'/f"{request['request_digest']}.json")
        if not any(digest({'request':request['request_digest'],'index':i})==proposal_id and proposal==original['proposal']
                   for i,proposal in enumerate(processed['output']['cards'])):
            raise JevSelectError('candidate_original_changed')
        path=root/'cards'/f'{proposal_id}.json';receipt_path=root/'admissions'/f'{proposal_id}_context_v1.json'
        if path.exists():
            card=read(path)
            if card['version']!='jev_memory_card_v4':raise JevSelectError('corrective_admission_existing_card')
            validate_corrective_admission(root,card);return read(receipt_path)
        proposal=deepcopy(original['proposal']);payload=request['input']['payload']
        receipt={'version':'jev_corrective_admission_receipt_v1','card_id':proposal_id,
                 'request_digest':request['request_digest'],'original_rejection_digest':digest(rejection),
                 'original_proposal_digest':digest(original['proposal']),'new_model_calls':0,
                 'historical_status':'TECHNICALLY_REJECTED_V2_PRESERVED','status':'REJECTED'}
        try:
            links=resolve_fact_links(request,proposal['fact_links'],unit_resolution='context_units_v2')
            refs=sorted({canonical({'episode_id':payload['episode_id'],'source_group_id':payload['source_group_id'],
                'export_digest':payload['export_digest'],'decision_id':link['decision_id']}) for link in links})
            import json
            refs=[json.loads(ref) for ref in refs]
            support=[payload['source_group_id']] if any(link['relation']=='support' for link in links) else []
            card={'version':'jev_memory_card_v4','card_id':proposal_id,'card_version':1,'content_digest':'0'*64,
                'status':'candidate',**proposal,'evidence_links':links,'evidence_refs':refs,
                'evidence_level':'observational','created_after_episode':payload['episode_id'],
                'generator_digest':request['request_digest'],'fixture_only':payload['fixture_only'],'render_version':'memory_prose_v2',
                'validation':{'version':'jev_card_fact_validation_v2','status':'PASS','request_digests':[request['request_digest']],
                    'support_source_groups':support,'conflict':False,'semantic_support':'REQUIRES_VERSIONED_SEMANTIC_REVIEW'},
                'admission':{'version':'jev_corrective_admission_v1','original_rejection_digest':digest(rejection),
                    'reason':'unit_context_resolver_correction','unit_resolution':'context_units_v2',
                    'historical_status':'TECHNICALLY_REJECTED_V2_PRESERVED','new_generation':False}}
            card['content_digest']=digest(card_content(card))
            card['semantic_review']={}
            card['semantic_review']=developer_review_template(root,card,authorization_digest)
            validate_facts(card,requests,exports)
            receipt.update(status='PASS',content_digest=card['content_digest'])
            write(receipt_path,receipt);write(path,card);_created_event(root,card)
        except JevSelectError as exc:
            receipt['reason']=exc.code;write(receipt_path,receipt)
        return receipt
