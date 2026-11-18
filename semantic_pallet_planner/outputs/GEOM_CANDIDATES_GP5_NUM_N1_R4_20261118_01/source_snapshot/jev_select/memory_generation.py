"""B2 explicit text generation, deterministic inputs and durable one-send accounting.

No import, prepare, validate, review or freeze path reads credentials or opens sockets.
Formal accounting is shared across B2-A/B2-B at a fixed repository location.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import re
import time

from .contracts import JevSelectError, canonical, digest, validate_schema
from .ledger import exclusive, read, write
from .memory_export import validate_export, build_raw_history, export_completed_episode

ACCOUNT_DIRECTORY = 'semantic_pallet_planner/outputs/JEV_J4_GENERATION_ACCOUNTING_V1'


def resource(name):
    return json.loads(files('semantic_pallet_planner.jev_select').joinpath('configs', name).read_text())


def generator_config():
    value = resource('memory_generation_v1.json')
    validate_schema('memory_generator_config', value)
    return value


def pointer(value, path):
    if not path.startswith('/'):
        raise JevSelectError('invalid_evidence_pointer')
    try:
        for part in path[1:].split('/'):
            key = part.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise JevSelectError('unresolved_evidence_pointer') from exc
    return value


def summary_input(export):
    """Lossless public subtree projection; floats use canonical Python JSON precision.

    Keep all current visible and placed resources and full English rule semantics.
    Exclude unexecuted candidates, legacy private feedback handles and duplicate
    language/objective/buffer arrival metadata. Event order is actual export order.
    """
    validate_export(export)
    events = []
    for event in export['events']:
        if 'public_feedback' not in event:
            raise JevSelectError('PUBLIC_FEEDBACK_UNRESOLVED')
        state = event['public_state']
        selected = event['selected_action']
        if selected['pick_object'] not in {o['object_id'] for o in state['available_objects']}:
            raise JevSelectError('SELECTED_OBJECT_UNRESOLVED')
        public = {k: deepcopy(state[k]) for k in ('units', 'container', 'placed_objects', 'available_objects', 'regions')}
        public['business_requirements'] = {'english_descriptions': state['business_requirements']['english_descriptions']}
        events.append({'decision_id': event['decision_id'], 'public_state': public,
                       'selected_action': deepcopy(selected), 'public_feedback': deepcopy(event['public_feedback'])})
    if len({e['decision_id'] for e in events}) != len(events):
        raise JevSelectError('duplicate_training_decision')
    payload = {'projection_version': 'training_summary_public_v1', 'episode_id': export['episode_id'],
               'source_group_id': export['source_group_id'], 'export_digest': digest(export),
               'source_code_digest': export['source_code_digest'], 'fixture_only': export.get('fixture_only', False),
               'events': events, 'terminal_feedback': deepcopy(export['terminal_feedback'])}
    # Subtree coverage is exact, compact and includes every descendant field.
    coverage = [{'decision_id': event['decision_id'], 'path': f'/events/{i}/{key}',
                 'subtree_digest': digest(value)} for i, event in enumerate(events)
                for key, value in sorted(event.items()) if key != 'decision_id']
    coverage.append({'decision_id': events[-1]['decision_id'] if events else '',
                     'path': '/terminal_feedback', 'subtree_digest': digest(payload['terminal_feedback'])})
    return {'payload': payload, 'coverage': coverage}


def budget_preflight(request, config):
    validate_schema('memory_generator_config', config)
    # Upper bound, deliberately not a provider tokenizer or billed usage estimate.
    upper = len(canonical(request['body']['messages']).encode('utf-8')) + 1024
    allowed = (upper <= config['input_upper_bound_tokens'] and
               upper + config['max_tokens'] + config['safety_margin_tokens'] <= config['context_tokens'])
    return {'status': 'PASS' if allowed else 'GENERATION_INPUT_TOO_LARGE',
            'input_token_upper_bound': upper, 'bound_method': config['token_bound_method'],
            'output_max_tokens': config['max_tokens'], 'context_tokens': config['context_tokens'],
            'safety_margin_tokens': config['safety_margin_tokens'],
            'covered_events': [e.get('decision_id',e.get('event_alias')) for e in request['input']['payload']['events']] if allowed else [],
            'uncovered_events': [] if allowed else [e.get('decision_id',e.get('event_alias')) for e in request['input']['payload']['events']],
            'billed_input_tokens': None}


def make_request(export, *, operation='generate', parents=(), context_requests=None, protocol='v1', merge_compatibility=None):
    if operation not in ('generate', 'merge'):
        raise JevSelectError('invalid_generation_operation')
    if protocol not in ('v1','v2','v3','v4'): raise JevSelectError('unknown_generation_protocol')
    config = generator_config(); prompt = resource(f'memory_generation_prompt_{protocol}.json')
    inputs = summary_input(export) if protocol == 'v1' else summary_input_v2(export) if protocol == 'v2' else summary_input_v3(export)
    context_requests = context_requests or {}
    binding = {'version': 'jev_generation_request_'+protocol, 'input': inputs, 'config': config, 'prompt': prompt,
               'operation': operation, 'parents': list(parents),
               'context_requests': context_requests}
    if merge_compatibility is not None:
        binding['merge_compatibility'] = deepcopy(merge_compatibility)
    request_id = digest(binding)
    contracts = json.loads(files('semantic_pallet_planner.jev_select').joinpath(
        'schemas/memory_generation_result.schema.json').read_text())['oneOf']
    user = ({'request_digest': request_id, **inputs} if protocol == 'v1' else public_input_v2(inputs))
    user['output_contract'] = contracts[0 if protocol == 'v1' else 1]
    if operation == 'merge':
        if protocol == 'v1':
            user.update(parents=list(parents), parent_requests=context_requests)
        else:
            aliases = {key:f'P{i+1:04d}' for i,key in enumerate(sorted(context_requests))}
            user['parent_requests'] = [{
                'request_alias':aliases[key], **public_input_v2(context_requests[key]['input'])
            } for key in sorted(context_requests)]
            user['parents'] = [{**{k:p[k] for k in ('card_id','applicability','advice','observed_evidence',
                'comparison_basis','limitations_counterexamples','knowledge_role','knowledge_role_basis','expected_effect_hypothesis')},
                'fact_links':[{**link,'request_alias':aliases[p['generator_digest']]} for link in p['fact_links']]} for p in parents]
    body = {k: config[k] for k in ('model', 'thinking', 'temperature', 'top_p', 'max_tokens')}
    body.update(stream=False, response_format={'type': 'json_object'}, messages=[
        {'role': 'system', 'content': prompt['system'] + ('\n' + prompt['merge'] if operation == 'merge' else '')},
        {'role': 'user', 'content': canonical(user)}])
    request = {**binding, 'request_digest': request_id, 'body': body, 'wire_digest': digest(body)}
    request['preflight'] = budget_preflight(request, config)
    return request


def validate_request(request):
    binding = {k: request[k] for k in ('version', 'input', 'config', 'prompt', 'operation', 'parents', 'context_requests')}
    if 'merge_compatibility' in request: binding['merge_compatibility'] = request['merge_compatibility']
    if request['version'] not in ('jev_generation_request_v1','jev_generation_request_v2','jev_generation_request_v3','jev_generation_request_v4') or digest(binding) != request['request_digest']:
        raise JevSelectError('generation_request_changed')
    if request['wire_digest'] != digest(request['body']) or request['preflight'] != budget_preflight(request, request['config']):
        raise JevSelectError('generation_wire_or_budget_changed')
    # Rebuild from immutable exports in validate_prepared; here bind prompt and config resources too.
    if request['prompt'] != resource('memory_generation_prompt_'+request['version'].rsplit('_',1)[1]+'.json') or request['config'] != generator_config():
        raise JevSelectError('generation_contract_changed')
    return request


def verify_training(exports, experiment):
    """Re-resolve exact exports from sealed real source, not a claimed train label."""
    from .dataset_j4 import verify_seal
    root = Path(experiment)
    if verify_seal(root)['status'] != 'PASS':
        raise JevSelectError('training_source_not_sealed')
    code = digest(read(root/'plan/source_manifest.json'))
    episodes = [read(p) for p in sorted((root/'episodes').glob('*.json'))]
    allowed = [e for e in episodes if e['summary'].get('partition') == 'train' and
               e['summary'].get('selector_backend') in ('jev_choice', 'jev_no_memory')]
    manifest = {'experiment_id': root.name, 'source_code_digest': code,
                'source_groups': sorted({e['summary']['source_order_key'] for e in allowed}),
                'episodes': {e['job_id']: {'episode_digest': digest(e), 'source_code_digest': code} for e in allowed}}
    actual = {digest(export_completed_episode(e, manifest, version=v)) for e in allowed
              for v in ('jev_episode_export_v1','jev_episode_export_v2')}
    if not exports or any(e.get('fixture_only') or digest(e) not in actual for e in exports):
        raise JevSelectError('training_export_not_verified')
    return {'status': 'PASS', 'source_experiment': root.name, 'source_code_digest': code,
            'source_seal_digest': digest(read(root/'delivery_manifest.json')),
            'export_digests': sorted(digest(e) for e in exports),
            'episode_identities': {e['episode_id']: manifest['episodes'][e['episode_id'].rsplit(':',1)[1]]['episode_digest'] for e in exports},
            'source_groups': sorted({e['source_group_id'] for e in exports}), 'events': sum(len(e['events']) for e in exports)}


def prepare_generation(store, output, *, experiment=None, mode='remote_text', protocol='v1'):
    from .experiment import _new_output
    exports = [validate_export(read(p)) for p in sorted((Path(store)/'exports').glob('*.json'))]
    if mode not in ('remote_text', 'offline_fixture') or not exports:
        raise JevSelectError('invalid_generation_mode_or_empty_corpus')
    if mode == 'remote_text':
        if experiment is None: raise JevSelectError('verified_training_experiment_required')
        readiness = verify_training(exports, experiment)
    else:
        if not all(e.get('fixture_only') for e in exports):
            raise JevSelectError('offline_generation_requires_fixture_exports')
        readiness = {'status': 'FIXTURE_ONLY', 'export_digests': sorted(digest(e) for e in exports)}
    root = _new_output(output); root.mkdir(parents=True)
    for export in exports:
        write(root/'exports'/f'{digest(export)}.json', export)
        request = make_request(export, protocol=protocol)
        write(root/'requests'/f'{request["request_digest"]}.json', request)
    _, r0 = build_raw_history(exports,projection='v1' if protocol=='v1' else 'v2')
    report = {'version': 'jev_generation_prepared_v1', 'status': 'PASS', 'mode': mode,
              'readiness': readiness, 'r0': r0,
              'r0_limits': {'item_max_utf8_bytes':1600,'canonical_array_max_utf8_bytes':4800,'top_k':3},
              'model_api_calls': 0,
              'summary': {p.stem: read(p)['preflight'] for p in sorted((root/'requests').glob('*.json'))},
              'projection': {'version': 'training_summary_public_'+('v3' if protocol=='v4' else protocol), 'precision': 'canonical JSON preserves source float precision',
                             'order': 'export actual event order; fields canonical sorted',
                             'omissions': ['unexecuted candidate facts', 'legacy feedback private handles', 'original-language rule duplicate', 'objective and buffer arrival metadata'],
                             'coverage': 'every event: public_state, selected_action, public_feedback; full terminal feedback; subtree paths include all descendants'}}
    write(root/'prepared.json', report)
    write(root/'prepared_digest.json', {'digest': digest(report), 'requests': {p.stem: digest(read(p)) for p in sorted((root/'requests').glob('*.json'))}})
    return report


def validate_prepared(prepared):
    root = Path(prepared); report = read(root/'prepared.json'); seal = read(root/'prepared_digest.json')
    if seal['digest'] != digest(report): raise JevSelectError('prepared_changed')
    exports = {digest(read(p)): validate_export(read(p)) for p in (root/'exports').glob('*.json')}
    if sorted(exports) != report['readiness']['export_digests']: raise JevSelectError('prepared_exports_changed')
    requests = {p.stem: read(p) for p in (root/'requests').glob('*.json')}
    if seal['requests'] != {k:digest(v) for k,v in requests.items()}: raise JevSelectError('prepared_requests_changed')
    for request in requests.values():
        validate_request(request)
        export = exports[request['input']['payload']['export_digest']]
        expected = make_request(export, operation=request['operation'], parents=request['parents'], context_requests=request['context_requests'], protocol=request['version'].rsplit('_',1)[1], merge_compatibility=request.get('merge_compatibility'))
        if request != expected: raise JevSelectError('prepared_projection_changed')
    return report, exports, requests


def _credential(repo):
    # This is called only by the explicit remote transport after reserving an attempt.
    text = (Path(repo)/'deepseek_api.md').read_text(encoding='utf-8')
    keys = set(re.findall(r'(?<![\w-])sk-[A-Za-z0-9_-]{16,}', text))
    if len(keys) != 1: raise JevSelectError('missing_or_ambiguous_deepseek_key')
    return keys.pop()


def remote_complete(body, repo, config):
    import urllib.request
    import urllib.error
    from .transport import NoRedirect
    started = time.monotonic()
    try:
        key = _credential(repo)
    except (OSError, ValueError):
        return {'status': 'NOT_SENT', 'raw_body_b64': '', 'http_status': None,
                'latency_s': time.monotonic()-started, 'error': 'credential_unavailable', 'headers': {}}
    req = urllib.request.Request(config['endpoint'], canonical(body).encode('utf-8'),
              {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=config['timeout_s']) as response:
            raw = response.read(); status = response.status
            headers = {k:response.headers[k] for k in ('x-request-id', 'date', 'content-type') if k in response.headers}
    except urllib.error.HTTPError as exc:
        raw = exc.read(); status = exc.code
        headers = {k:exc.headers[k] for k in ('x-request-id', 'date', 'content-type') if k in exc.headers}
    except Exception as exc:
        # Never persist exception strings: a transport exception could include credentials.
        return {'status': 'UNKNOWN_IN_FLIGHT', 'raw_body_b64': '', 'http_status': None,
                'latency_s': time.monotonic()-started, 'error': type(exc).__name__, 'headers': {}}
    # Normally no service echoes credentials, but redact before persistence if it does.
    raw = raw.replace(key.encode(), b'[REDACTED_CREDENTIAL]')
    return {'status': 'OK' if 200 <= status < 300 else 'HTTP_FAILURE',
            'raw_body_b64': base64.b64encode(raw).decode('ascii'), 'http_status': status,
            'latency_s': time.monotonic()-started, 'error': None, 'headers': headers}


def _fixture_complete(body, fixture):
    value = read(fixture)
    return {'status': 'OK', 'raw_body_b64': base64.b64encode(canonical(value).encode()).decode(),
            'http_status': 200, 'latency_s': 0., 'error': None, 'headers': {}}


def _account_root(mode, store, repo):
    if mode == 'offline_fixture': return Path(store)/'generation_accounting_fixture'
    root = Path(repo).resolve()
    if not (root/'semantic_pallet_planner/pyproject.toml').is_file():
        raise JevSelectError('generation_repository_required')
    return root/ACCOUNT_DIRECTORY


def _send(account, identity, request, body, mode, repo, fixture, hook, *, operation):
    """Journal raw response first; a crash before journal completion is UNKNOWN.

    All calls hold the shared account lock. A saved raw response recovers even if
    its ledger checkpoint was not completed. There is never an automatic resend.
    """
    path = account/'attempts'/f'{identity}.json'
    rawpath = account/'responses'/f'{identity}.json'
    if path.exists():
        row = read(path)
        if row['request_digest'] != request['request_digest'] or row['wire_digest'] != digest(body):
            raise JevSelectError('generation_attempt_binding_changed')
        if rawpath.exists():
            result = read(rawpath)
            if row.get('response_digest') not in (None, digest(result)):
                raise JevSelectError('generation_response_changed')
            row.update(state='NOT_SENT' if result['status']=='NOT_SENT' else 'RESPONSE_SAVED', response_digest=digest(result))
            _response_metadata(row, result)
            write(path, row)
            return result
        if row['state'] == 'NOT_SENT': return row['result']
        row['state'] = 'UNKNOWN_IN_FLIGHT'; write(path, row)
        return {'status': 'UNKNOWN_IN_FLIGHT'}
    row = {'version': 'jev_generation_attempt_v1', 'request_digest': request['request_digest'],
           'wire_digest': digest(body), 'mode': mode, 'operation': operation,
           'state': 'RESERVED_POSSIBLY_SENT', 'started_at': time.time(), 'response_digest': None,
           'requested_model': request['config']['model'],
           'usage': None, 'served_model': None, 'service_id': None, 'actual_cost': None, 'estimated_cost': None,
           'cost_status': 'NO_BILLING_RECEIPT_ESTIMATE_NOT_COMPUTED'}
    write(account/'wire_requests'/f'{identity}.json', {'operation':operation,'request_digest':request['request_digest'],'body':body})
    write(path, row)
    if hook: hook('after_reserve')
    result = remote_complete(body, repo, request['config']) if mode == 'remote_text' else _fixture_complete(body, fixture)
    if hook: hook('after_transport')
    # Durable transport envelope includes the original bytes before any JSON parsing.
    result['raw_digest'] = digest(result.get('raw_body_b64', ''))
    result['raw_sha256'] = __import__('hashlib').sha256(base64.b64decode(result.get('raw_body_b64',''))).hexdigest()
    write(rawpath, result)
    if hook: hook('after_raw_response')
    row.update(state='NOT_SENT' if result['status'] == 'NOT_SENT' else 'RESPONSE_SAVED',
               response_digest=digest(result), finished_at=time.time(), latency_s=result['latency_s'])
    _response_metadata(row, result)
    if result['status'] == 'NOT_SENT': row['result'] = result
    write(path, row)
    if hook: hook('after_response')
    return result


def _response_metadata(row, result):
    row['latency_s'] = result.get('latency_s')
    row['transport_status'] = result['status']
    row['http_status'] = result.get('http_status')
    try:
        from .transport import strict_json
        value = strict_json(base64.b64decode(result['raw_body_b64']))
        row.update(usage=value.get('usage'), served_model=value.get('model'), service_id=value.get('id'),
                   system_fingerprint=value.get('system_fingerprint'))
    except (ValueError, KeyError, TypeError, AttributeError): pass


def _parse_response(result, requested_model, *, fixture=False):
    if result['status'] != 'OK': return None, ['transport_'+result['status']], False
    from .transport import strict_json
    try:
        response = strict_json(base64.b64decode(result['raw_body_b64']))
        if not fixture and response.get('model') != requested_model:
            return None, ['served_model_mismatch'], False
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop': return None, ['incomplete_output'], True
        output = strict_json(choice['message']['content'].encode('utf-8'))
        validate_schema('memory_generation_result', output)
        return output, [], False
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        # No offending values or semantic hints go into the repair request.
        return None, ['invalid_json_or_output_schema'], True


def generate_candidates(prepared, request_id, store, *, mode, repo=None, fixture=None, repair_fixture=None, hook=None):
    report, exports, requests = validate_prepared(prepared)
    if mode != report['mode'] or mode not in ('remote_text','offline_fixture'):
        raise JevSelectError('generation_mode_changed')
    if mode == 'offline_fixture' and fixture is None: raise JevSelectError('fixture_response_required')
    request = requests[request_id]
    if request['preflight']['status'] != 'PASS':
        return {'status': 'GENERATION_INPUT_TOO_LARGE', 'request_digest': request_id, 'model_api_calls': 0}
    if mode == 'remote_text' and any(e.get('fixture_only') for e in exports.values()):
        raise JevSelectError('fixture_generation_in_remote')
    root = Path(store); root.mkdir(parents=True, exist_ok=True)
    if (root/'memory_manifest.json').exists(): raise JevSelectError('frozen_memory_is_readonly')
    if request['operation']=='merge' and any(p['semantic_review'].get('reviewer_kind')=='developer_agent' for p in request['parents']):
        if 'merge_compatibility' not in request:raise JevSelectError('pairwise_merge_compatibility_required')
        validate_merge_compatibility(request['merge_compatibility'],request['parents'],root)
        if any(p['semantic_review']['status']!='accepted' for p in request['parents']):
            raise JevSelectError('reviewed_merge_parents_required')
    account = _account_root(mode, root, repo); account.mkdir(parents=True, exist_ok=True)
    # Formal source seal is rechecked at the execution boundary, using the named
    # source under this repository, before reading any credentials.
    if mode == 'remote_text':
        if 'sources' in report['readiness']:
            checked_sources = [verify_training([exports[k] for k in att['export_digests']],
                Path(repo)/'semantic_pallet_planner/outputs'/att['source_experiment']) for att in report['readiness']['sources']]
            checked = combined_readiness(checked_sources)
        else:
            checked = verify_training(list(exports.values()), Path(repo)/'semantic_pallet_planner/outputs'/report['readiness']['source_experiment'])
        if checked != report['readiness']: raise JevSelectError('training_attestation_changed')
    with exclusive(account), exclusive(root):
        claims_path = account/'episode_claims.json'
        claims = read(claims_path) if claims_path.exists() else {}
        payload = request['input']['payload']
        episode_key = digest({'source_code_digest':payload['source_code_digest'],
                              'source_episode_digest': report['readiness'].get('episode_identities',{}).get(payload['episode_id'],payload['episode_id'])})
        op = request['operation']
        if op == 'generate':
            if episode_key in claims and claims[episode_key] != request_id:
                raise JevSelectError('episode_generation_already_reserved')
            claims[episode_key] = request_id
            write(claims_path, claims)
        else:
            for parent in request['parents']:
                if read(root/'cards'/f"{parent['card_id']}.json") != parent:
                    raise JevSelectError('merge_parent_history_changed')
            merge_claims = account/'merge_claims.json'
            merges = read(merge_claims) if merge_claims.exists() else []
            if request_id not in merges:
                if len(merges)+1 > len(claims)//4: raise JevSelectError('merge_frequency_not_reached')
                merges.append(request_id); write(merge_claims, merges)
        from .memory_store import MemoryStore
        # Ingest before send; interruption later only leaves verified exports.
        # Already holding root lock, so use atomic exact-content append directly.
        for identity, export in exports.items():
            path = root/'exports'/f'{identity}.json'
            if path.exists() and read(path) != export: raise JevSelectError('training_export_changed')
            write(path, export)
        dest = account/'requests'/f'{request_id}.json'
        if dest.exists() and read(dest) != request: raise JevSelectError('generation_request_changed')
        write(dest, request)
        result = _send(account, request_id, request, request['body'], mode, repo, fixture, hook, operation=op)
        output, errors, repairable = _parse_response(result, request['config']['model'], fixture=mode=='offline_fixture')
        attempts = [request_id]
        if repairable:
            repair_body = deepcopy(request['body'])
            # Original request and raw assistant output, then structure errors only.
            try:
                raw = json.loads(base64.b64decode(result['raw_body_b64']))['choices'][0]['message']['content']
            except (ValueError, KeyError, IndexError, TypeError): raw = ''
            repair_body['messages'] += [{'role':'assistant','content':raw},
                {'role':'user','content':canonical({'instruction':request['prompt']['repair'], 'structure_errors':errors})}]
            repair_id = digest({'request':request_id,'operation':'format_repair','body':repair_body})
            check = deepcopy(request); check['body'] = repair_body
            if budget_preflight(check, request['config'])['status'] != 'PASS':
                errors = ['GENERATION_INPUT_TOO_LARGE_REPAIR']
            elif mode == 'remote_text' or repair_fixture is not None:
                result2 = _send(account, repair_id, request, repair_body, mode, repo, repair_fixture, hook, operation='format_repair')
                attempts.append(repair_id)
                output, errors, _ = _parse_response(result2, request['config']['model'], fixture=mode=='offline_fixture')
        if output is not None and output['version'] != ('jev_generation_output_v1' if request['version']=='jev_generation_request_v1' else 'jev_generation_output_v2'):
            output = None; errors = ['output_contract_version_mismatch']
        record = {'version':'jev_generation_processed_v1','request_digest':request_id,'operation':op,
                  'status':'PARSED' if output is not None else 'FAILED', 'errors':errors,
                  'attempts':attempts, 'output':output, 'fixture_only': mode=='offline_fixture'}
        # Reuse official responses, but materialize local cards idempotently after crashes.
        write(account/'processed'/f'{request_id}.json', record)
        for sub in ('requests','responses','attempts','processed','wire_requests'):
            for identity in ([request_id] if sub in ('requests','processed') else attempts):
                src = account/sub/f'{identity}.json'
                if src.exists(): write(root/'generation'/sub/src.name, read(src))
        if output is not None:
            from .memory_validation import materialize_candidates
            materialize_candidates(root, request, output, hook=hook)
        return {k:v for k,v in record.items() if k != 'output'}


def prepare_merge(prepared, store, parent_ids, output, *, additional_prepared=(), compatibility_file=None):
    """Prepare without network; frequency enforced against the same formal ledger.

    No automatic compatibility classifier: the generated merge stays candidate
    until an independent reviewer accepts both scope and advice compatibility.
    """
    from .memory_validation import validate_store
    from .experiment import _new_output
    report, exports, requests = validate_prepared(prepared)
    attestations = [report['readiness']]
    for extra in additional_prepared:
        extra_report, extra_exports, extra_requests = validate_prepared(extra)
        if extra_report['mode'] != report['mode']: raise JevSelectError('mixed_prepared_modes')
        for key,value in extra_exports.items():
            if key in exports and exports[key]!=value: raise JevSelectError('prepared_export_conflict')
            exports[key]=value
        requests.update(extra_requests);attestations.append(extra_report['readiness'])
    if additional_prepared:
        report = dict(report,readiness=combined_readiness(attestations))
    validate_store(store)
    parents = [read(Path(store)/'cards'/f'{identity}.json') for identity in sorted(set(parent_ids))]
    if len(parents)<2 or any(p['status'] in ('rejected','retired') for p in parents):
        raise JevSelectError('merge_eligible_parents_required')
    contexts = {p.stem:read(p) for p in (Path(store)/'generation/requests').glob('*.json')}
    evidence_ids = {link['request_digest'] for parent in parents for link in parent['evidence_links']}
    contexts = {k:contexts[k] for k in sorted(evidence_ids)}
    export = sorted(exports.values(),key=digest)[-1]
    modern = ('jev_memory_card_v3','jev_memory_card_v4')
    if any(p['version'] in modern for p in parents) and not all(p['version'] in modern for p in parents):
        raise JevSelectError('mixed_parent_contract_versions')
    protocol = 'v2' if all(p['version'] in modern for p in parents) else 'v1'
    if protocol == 'v2' and any(p['semantic_review']['status']!='accepted' or
            not p['semantic_review']['scope_and_advice_compatible'] for p in parents):
        raise JevSelectError('independently_reviewed_compatible_parents_required')
    if protocol == 'v2' and (any(p['version']=='jev_memory_card_v4' for p in parents) or all(contexts[p['generator_digest']]['version']=='jev_generation_request_v3' for p in parents)):
        protocol = 'v3'
    if all(p['version'] in modern for p in parents) and any(contexts[p['generator_digest']]['version']=='jev_generation_request_v4' for p in parents):
        protocol = 'v4'
    compatibility = None
    if any(p['semantic_review'].get('reviewer_kind')=='developer_agent' for p in parents):
        if compatibility_file is None: raise JevSelectError('pairwise_merge_compatibility_required')
        compatibility = read(compatibility_file)
        validate_merge_compatibility(compatibility,parents,store)
    request = make_request(export,operation='merge',parents=parents,context_requests=contexts,protocol=protocol,merge_compatibility=compatibility)
    root = _new_output(output); root.mkdir(parents=True)
    for identity, e in exports.items(): write(root/'exports'/f'{identity}.json',e)
    write(root/'requests'/f'{request["request_digest"]}.json',request)
    report = dict(report, summary={request['request_digest']:request['preflight']})
    write(root/'prepared.json',report)
    write(root/'prepared_digest.json',{'digest':digest(report),'requests':{request['request_digest']:digest(request)}})
    return {'status':'PASS','request_digest':request['request_digest'],'preflight':request['preflight'],'model_api_calls':0}


FIELD_SEMANTICS_V2 = {
    'version': 'public_feedback_semantics_v2',
    'instances': 'Violations present after the actual action; absence alone is not proof of all-rule compliance.',
    'new_instances': 'After-action violation identities absent from the preceding committed action.',
    'checked': 'Number of evaluated rule instances, including violations; never a satisfied count.',
    'deferred': 'Known pending targets/pairs or unresolved relation pairs; may coexist with checked > 0. Never evidence of compliance or benefit.',
    'labels.max_top_load_kg': 'Public business label in kg, distinct from the physical limit.',
    'physical_top_load_limit_kg': 'Physical feasibility capacity in kg; business labels do not replace it.',
    'terminal': 'Post-episode observation; unexecuted alternatives and causal effects are unknown.',
    'units': 'Suffix _mm: mm; _kg: kg; _deg: deg; _ratio and utilization: ratio; counts: count; structured or categorical values: context.',
}


def value_type(value):
    if value is None: return 'null'
    if type(value) is bool: return 'boolean'
    if type(value) is int: return 'integer'
    if type(value) is float: return 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'array'
    if isinstance(value, dict): return 'object'
    raise JevSelectError('unsupported_fact_type')


def fact_unit(path, value):
    if isinstance(value, (dict, list, str, bool)) or value is None: return 'context'
    # Inspect the leaf first, then its container (e.g. dimensions_mm/length).
    for part in reversed(path.split('/')):
        if part.endswith('_mm'): return 'mm'
        if part.endswith('_kg'): return 'kg'
        if part.endswith('_deg'): return 'deg'
        if part.endswith('_ratio') or 'utilization' in part: return 'ratio'
    return 'count' if type(value) is int else 'context'


def summary_input_v2(export):
    """Stable aliases from sealed public identities, allocated only on first visibility.

    Global identities and event-local B aliases remain in local mapping. No future
    task sequence or size-based identity inference participates in this projection.
    """
    validate_export(export)
    if export['version'] != 'jev_episode_export_v2':
        raise JevSelectError('stable_object_bindings_required')
    old = summary_input(export)
    stable = {}; mappings = []; facts = []; events = []
    for i, event in enumerate(old['payload']['events']):
        bindings = export['object_bindings'].get(event['decision_id'], {})
        state = event['public_state']
        visible = state['placed_objects'] + state['available_objects']
        local_ids = [o['object_id'] for o in visible]
        if set(local_ids) != set(bindings) or len(set(bindings.values())) != len(bindings):
            raise JevSelectError('object_identity_unresolved')
        aliases = {}
        for local in local_ids:
            real = bindings[local]
            if real not in stable: stable[real] = f'O{len(stable)+1:04d}'
            aliases[local] = stable[real]
        def replace(value):
            if isinstance(value, dict): return {k:replace(v) for k,v in value.items()}
            if isinstance(value, list): return [replace(v) for v in value]
            if isinstance(value, str):
                def resolve(m):
                    if m[0] not in aliases: raise JevSelectError('cross_step_object_unresolved')
                    return aliases[m[0]]
                return re.sub(r'\bB\d{3,}\b', resolve, value)
            return value
        event_alias = f'E{i+1:04d}'
        public = {'event_alias':event_alias}
        for key in ('public_state','selected_action','public_feedback'):
            ident = f'F{len(facts)+1:04d}'
            value = replace(event[key])
            facts.append({'fact_id':ident,'event_alias':event_alias,'context':key,
                          'units':{'length':'mm','mass':'kg','angle':'deg'},'value':value})
            mappings.append({'fact_id':ident,'decision_id':event['decision_id'],
                             'export_path':f'/events/{i}/{key}', 'event_alias':event_alias})
            public[key] = ident
        events.append(public)
    terminal = f'F{len(facts)+1:04d}'
    facts.append({'fact_id':terminal,'event_alias':events[-1]['event_alias'] if events else '',
                  'context':'terminal_feedback','units':{'length':'mm','mass':'kg','angle':'deg'},
                  'value':deepcopy(export['terminal_feedback'])})
    mappings.append({'fact_id':terminal,'decision_id':export['events'][-1]['decision_id'] if events else '',
                     'export_path':'/terminal_feedback','event_alias':events[-1]['event_alias'] if events else ''})
    public = {'projection_version':'training_summary_public_v2','events':events,'facts':facts,
              'field_semantics':FIELD_SEMANTICS_V2,'object_association':'stable sealed identity; first public appearance only'}
    return {'payload':{**{k:v for k,v in old['payload'].items() if k not in ('events','terminal_feedback','projection_version')},
                       **public}, 'coverage':mappings,
            'local_mapping':{'version':'generation_fact_mapping_v2','objects':stable,
                             'event_object_bindings':deepcopy(export['object_bindings'])}}


def public_input_v2(inputs):
    keys = ['projection_version','events','facts','field_semantics','object_association']
    if 'unit_resolution' in inputs['payload']: keys.append('unit_resolution')
    return {k:inputs['payload'][k] for k in keys}


def summary_input_v3(export):
    inputs = summary_input_v2(export)
    inputs['payload']['projection_version'] = 'training_summary_public_v3'
    inputs['payload']['field_semantics'] = dict(FIELD_SEMANTICS_V2,version='public_feedback_semantics_v3')
    inputs['payload']['unit_resolution'] = 'context_units_v2: numeric severity/value uses actual sibling severity/unit; nearest unit-bearing path otherwise; whole structure uses context'
    return inputs


def summary_for_request(request, export):
    routes = {'jev_generation_request_v1':summary_input,'jev_generation_request_v2':summary_input_v2,
              'jev_generation_request_v3':summary_input_v3,'jev_generation_request_v4':summary_input_v3}
    if request['version'] not in routes: raise JevSelectError('unknown_generation_protocol')
    return routes[request['version']](export)


def context_fact_unit(root, path, value):
    """New resolver contract; v2 requests continue using the original suffix resolver."""
    if path.endswith('/value'):
        parent = pointer(root,path.rsplit('/',1)[0])
        if isinstance(parent,dict) and parent.get('unit') in ('kg','mm','deg') and type(value) in (int,float):
            return parent['unit']
    return fact_unit(path,value)


def combined_readiness(attestations):
    sources = {}
    for att in attestations:
        for source in att.get('sources',[att]): sources[digest(source)] = source
    ordered = sorted(sources.values(),key=lambda a:(a.get('source_experiment',''),digest(a)))
    identities = {}
    for att in ordered:
        for key,value in att.get('episode_identities',{}).items():
            if key in identities and identities[key]!=value: raise JevSelectError('source_episode_identity_conflict')
            identities[key]=value
    return {'status':'PASS' if all(a['status']=='PASS' for a in ordered) else 'FIXTURE_ONLY',
            'sources':ordered,'export_digests':sorted({d for a in ordered for d in a['export_digests']}),
            'episode_identities':identities,'source_groups':sorted({g for a in ordered for g in a.get('source_groups',[])}),
            'events':sum(a.get('events',0) for a in ordered)}


def generation_gate(store, request_id):
    """Read-only gate for expansion; parsed JSON alone never means technical success.

    Original proposals must be exhaustively accounted for as either an unchanged
    legal card or a recorded rejection. Empty output is legal, not a zero-denominator
    success-rate claim. This function never reads credentials or opens a connection.
    """
    from .memory_validation import validate_store
    root = Path(store)
    result = {'version':'jev_generation_expansion_gate_v1','request_digest':request_id,
              'status':'STOP_VALIDATION_INCOMPLETE','original_proposals':None,
              'legal_candidates':0,'technical_rejections':None,'allow_next':False,
              'new_model_calls':0,'semantic_review':'NOT_IMPLIED'}
    path = root/'generation/processed'/f'{request_id}.json'
    if not path.is_file(): return result
    processed = read(path)
    result['processed_digest'] = digest(processed)
    if processed['request_digest'] != request_id:
        raise JevSelectError('generation_gate_request_changed')
    if processed['status'] != 'PARSED' or processed['output'] is None:
        return dict(result,status='STOP_GENERATION_FAILURE')
    rejection_path = root/'generation/rejections'/f'{request_id}.json'
    if not rejection_path.is_file(): return result
    validate_store(root)
    proposals = processed['output']['cards']
    rejects = read(rejection_path)
    expected = {digest({'request':request_id,'index':i}):p for i,p in enumerate(proposals)}
    rejected_ids = [entry['card_id'] for entry in rejects['rejected']]
    if len(set(rejected_ids)) != len(rejected_ids) or not set(rejected_ids).issubset(expected):
        raise JevSelectError('generation_gate_rejection_accounting_changed')
    legal = set()
    for identity, proposal in expected.items():
        original = read(root/'originals'/f'{identity}.json')
        if original != {'proposal':proposal,'request_digest':request_id}:
            raise JevSelectError('generation_gate_original_changed')
        card_path=root/'cards'/f'{identity}.json'
        if card_path.is_file():
            # Corrective admission is a later explicit validation stage; the
            # original generation gate must keep its historical refusal.
            if not (identity in rejected_ids and read(card_path)['version']=='jev_memory_card_v4'):
                legal.add(identity)
    if legal.intersection(rejected_ids) or legal.union(rejected_ids) != set(expected):
        raise JevSelectError('generation_gate_proposal_accounting_incomplete')
    return dict(result, status='STOP_TECHNICAL_REJECTION' if rejected_ids else 'PASS',
                original_proposals=len(proposals),legal_candidates=len(legal),
                technical_rejections=len(rejected_ids),allow_next=not rejected_ids,
                rejections_digest=digest(rejects),originals_digest=digest(expected))


def run_generation_batch(prepared, request_ids, store, output, *, mode, repo=None,
                         fixtures=None, resume=False, hook=None):
    """Run a frozen ordered prefix; stop durably at the first failed technical gate.

    Reuses the existing one-send generator and formal ledger. No new frequency
    identity or independent accounting is introduced by this orchestration.
    """
    from .experiment import _new_output
    report, _, requests = validate_prepared(prepared)
    ids = list(request_ids)
    if mode != report['mode'] or not ids or len(set(ids)) != len(ids) or not set(ids).issubset(requests):
        raise JevSelectError('invalid_generation_batch_scope')
    if any(requests[key]['operation']!='generate' for key in ids):
        raise JevSelectError('generation_batch_requires_episode_generations')
    fixtures = fixtures or {}
    if mode == 'remote_text' and fixtures:
        raise JevSelectError('fixture_generation_in_remote')
    if mode == 'offline_fixture' and set(fixtures) != set(ids):
        raise JevSelectError('batch_fixture_bindings_required')
    binding = {'version':'jev_generation_batch_v1','request_ids':ids,'mode':mode,
               'requests':{key:digest(requests[key]) for key in ids},
               'store':str(Path(store).resolve()),'repo':str(Path(repo).resolve()) if repo else None,
               'fixture_digests':{key:digest(read(fixtures[key])) for key in sorted(fixtures)}}
    root = Path(output).resolve()
    if not resume:
        root = _new_output(root);root.mkdir(parents=True)
        write(root/'binding.json',binding)
        write(root/'state.json',{'version':'jev_generation_batch_state_v1','binding_digest':digest(binding),
              'status':'RUNNING','completed':[],'pending_request':None,'remaining_requests':ids})
    with exclusive(root):
        if read(root/'binding.json') != binding: raise JevSelectError('generation_batch_binding_changed')
        state = read(root/'state.json')
        if state['binding_digest'] != digest(binding): raise JevSelectError('generation_batch_binding_changed')
        completed_ids = [row['request_digest'] for row in state['completed']]
        if completed_ids != ids[:len(completed_ids)]: raise JevSelectError('generation_batch_order_changed')
        for row in state['completed']:
            if generation_gate(store,row['request_digest']) != row['gate']:
                raise JevSelectError('generation_batch_saved_gate_changed')
        remaining = ids[len(completed_ids):]
        if state['remaining_requests'] != remaining or state['pending_request'] not in ([None,remaining[0]] if remaining else [None]):
            raise JevSelectError('generation_batch_state_changed')
        expected_status = (state['completed'][-1]['gate']['status'] if state['completed'] and not state['completed'][-1]['gate']['allow_next']
                           else 'PASS' if not remaining else 'RUNNING')
        if state['status'] != expected_status and not (state['status']=='STOP_EXECUTION_ERROR' and expected_status=='RUNNING' and state.get('error')):
            raise JevSelectError('generation_batch_state_changed')
        if state['status'] != 'RUNNING': return state
        for key in ids[len(completed_ids):]:
            state.update(pending_request=key,remaining_requests=ids[len(state['completed']):])
            write(root/'state.json',state)
            if hook: hook('before_generate',key)
            try:
                processed = generate_candidates(prepared,key,store,mode=mode,repo=repo,fixture=fixtures.get(key))
                if hook: hook('after_generate',key)
                gate = generation_gate(store,key)
            except (JevSelectError,OSError,KeyError,TypeError) as exc:
                state.update(status='STOP_EXECUTION_ERROR',error=exc.code if isinstance(exc,JevSelectError) else type(exc).__name__)
                write(root/'state.json',state)
                return state
            state['completed'].append({'request_digest':key,'processing_status':processed['status'],'gate':gate})
            state.update(pending_request=None,remaining_requests=ids[len(state['completed']):])
            if not gate['allow_next']: state['status']=gate['status']
            elif not state['remaining_requests']: state['status']='PASS'
            write(root/'state.json',state)
            if state['status'] != 'RUNNING': return state
        return state


def validate_merge_compatibility(review, parents, store):
    from .memory_validation import validate_developer_authorization
    fields={'version','reviewer_kind','authorization_digest','parent_content_digests','compatible',
            'scope_intersection','advice_compatibility','counterexamples_unknowns_preserved','reason','reviewed_at'}
    if set(review)!=fields or review['version']!='jev_merge_compatibility_v1' or review['reviewer_kind']!='developer_agent':
        raise JevSelectError('invalid_merge_compatibility_contract')
    validate_developer_authorization(store,review['authorization_digest'])
    if review['parent_content_digests']!={p['card_id']:p['content_digest'] for p in parents}:
        raise JevSelectError('merge_compatibility_parent_changed')
    if any(p['semantic_review'].get('authorization_digest')!=review['authorization_digest'] for p in parents):
        raise JevSelectError('merge_compatibility_authorization_changed')
    if any(not isinstance(review[k],str) or not review[k].strip() for k in ('scope_intersection','advice_compatibility','reason','reviewed_at')):
        raise JevSelectError('merge_compatibility_incomplete')
    from datetime import datetime
    try:
        if datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except ValueError as exc:raise JevSelectError('merge_compatibility_timestamp_invalid') from exc
    if review['compatible'] is not True or review['counterexamples_unknowns_preserved'] is not True:
        raise JevSelectError('merge_parents_semantically_incompatible')
    return review
