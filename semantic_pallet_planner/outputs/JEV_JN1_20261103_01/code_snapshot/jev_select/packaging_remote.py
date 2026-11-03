"""JN1-A registered packaging Choice protocol and durable single-send dependency.

This module has no credentials or implicit network transport. Callers inject both
transport and ledger; credential loading remains exclusively in JevTransport.
"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from .contracts import DecisionContext, JevSelectError, digest, validate_schema
from .ledger import read, write, exclusive
from .selector import parse_response, result, SelectionResult
from .transport import outcome, validate_transport

VERSION = 'jev_packaging_remote_v6'
MODEL = 'jev-1.14.0'
REGISTRY = {
    'jev_no_memory': {'origin': 'jev', 'model': MODEL},
    'local_geometry_test_double': {'origin': 'LOCAL_TEST_DOUBLE_NOT_JEV', 'model': 'LOCAL_TEST_DOUBLE_NOT_JEV'},
    'local_first_test_double': {'origin': 'LOCAL_TEST_DOUBLE_NOT_JEV', 'model': 'LOCAL_TEST_DOUBLE_NOT_JEV'},
}
VERSIONS = {'execution': VERSION, 'config': VERSION, 'context': 'jev_decision_context_v6',
            'candidate_bundle': 'jev_candidate_bundle_v6', 'selection': 'jev_selection_result_v6',
            'checkpoint': 'jev_checkpoint_v6', 'metrics': 'jev_packaging_remote_metrics_v1',
            'request_ledger': 'jev_packaging_requests_v2', 'decision_record': 'jev_packaging_decision_v1',
            'plan': 'JN1-A_preregistration_v1', 'run': 'JN1-A_single_decision_v1'}


def load_remote_config(*, data_identity, task_digest, method='jev_no_memory', enabled=False):
    from .stability.monitor import load_monitor_config
    from .experiment import source_manifest
    if method not in REGISTRY:
        raise JevSelectError('remote_unregistered_method')
    c = load_monitor_config(data_identity=data_identity, task_digest=task_digest,
                            method='local_geometry_test_double' if method=='jev_no_memory' else method, enabled=enabled)
    c.update(version=VERSION, selector=method, model=REGISTRY[method]['model'],
             endpoint='https://api.typesafe.ai/v1/systemone', api_key_env='TYPESAFE_API_KEY',
             timeout_s=30., max_retries=0, response_max_bytes=1000000,
             probability_tolerance=1e-5, probability_sum_validation='strict_or_2dp_rounding_interval_v1')
    c['runtime_identity']['strategy_identity'] = digest({'config': {k:v for k,v in c.items() if k!='runtime_identity'},
                                                       'source': source_manifest(), 'versions': VERSIONS})
    validate_schema('config', c)
    return c


def preflight_remote(config):
    ids = config['runtime_identity']
    expected = load_remote_config(data_identity=ids['data_identity'], task_digest=ids['task_identity'],
                                  method=config['selector'], enabled=config['stability_monitor']['enabled'])
    if config != expected:
        raise JevSelectError('remote_frozen_identity_changed')


class RequestLedger:
    """INTENT is safely unsent; SENDING after interruption is UNKNOWN_SEND.

    A caller must keep the same stage root across restarts. Attempts are never
    removed or retried, including explicit failures. Disk is reloaded under an
    exclusive writer lock, so stale instances cannot spend the same slot twice.
    """
    def __init__(self, root, *, max_sends=1, hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/'requests.json'
        self.max_sends, self.hook = max_sends, hook
        with exclusive(self.root):
            if not self.path.exists():
                self._save({'version': VERSIONS['request_ledger'], 'max_sends': max_sends, 'requests': []})
            self._load()

    def _save(self, data):
        data['record_digest'] = digest({k:v for k,v in data.items() if k!='record_digest'})
        write(self.path, data)

    def _load(self):
        d = read(self.path)
        if (d['version'] != VERSIONS['request_ledger'] or d['max_sends'] != self.max_sends or
            d['record_digest'] != digest({k:v for k,v in d.items() if k!='record_digest'})):
            raise JevSelectError('request_ledger_changed')
        keys=set()
        for i,r in enumerate(d['requests'],1):
            key=(r['job_id'],r['decision_id'])
            if key in keys or r['attempt_id']!=f'A{i:06d}' or r['state'] not in ('INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED','UNKNOWN_SEND','FAILED'):
                raise JevSelectError('invalid_request_ledger')
            keys.add(key)
            if r['transport'] is not None:
                validate_transport(r['transport'])
                if r['transport_digest'] != digest(r['transport']):raise JevSelectError('request_response_changed')
            if r['selection'] is not None:
                validate_schema('selection_result', r['selection'])
                if r['selection_digest'] != digest(r['selection']):raise JevSelectError('request_selection_changed')
        if sum(r['send_started'] for r in d['requests'])>self.max_sends:
            raise JevSelectError('request_budget_exceeded')
        self.data=d
        return d

    def _transition(self, row, state):
        row['state']=state
        row['history'].append({'state':state,'at':time.time()})
        self._save(self.data)
        if self.hook:self.hook(state, copy.deepcopy(row))

    @staticmethod
    def identity(context, job_id, decision_id):
        from .context import validate_context
        validate_context(context)
        v=context.data;b=v['local_binding']
        if v['version']!=VERSIONS['context'] or b.get('job_id')!=job_id or b.get('decision_id')!=decision_id or v['route']!='CHOICE_REQUIRED':
            raise JevSelectError('request_identity_mismatch')
        return {'context_digest':digest(v),'body_digest':digest(v['request_body']),
                'binding_digest':digest(b),'state_digest':digest(v['model_state']),
                'mapping_digest':digest(v['display_mapping'])}

    def request(self, context, job_id, decision_id, transport):
        identity=self.identity(context,job_id,decision_id)
        with exclusive(self.root):
            self._load()
            matches=[r for r in self.data['requests'] if (r['job_id'],r['decision_id'])==(job_id,decision_id)]
            if matches:
                row=matches[0]
                if any(row[k]!=v for k,v in identity.items()):raise JevSelectError('stale_request')
                if row['state']=='SENDING':
                    row['transport']=outcome('UNKNOWN_IN_FLIGHT',error='UNKNOWN_SEND',network_attempted=None)
                    row['transport_digest']=digest(row['transport'])
                    self._transition(row,'UNKNOWN_SEND')
                if row['state']!='INTENT':return copy.deepcopy(row)
            else:
                if transport is None:raise JevSelectError('missing_transport')
                if transport.origin not in ('jev','test_double'):raise JevSelectError('invalid_remote_origin')
                if sum(r['send_started'] for r in self.data['requests'])>=self.max_sends:raise JevSelectError('request_budget_exhausted')
                row={'attempt_id':f"A{len(self.data['requests'])+1:06d}",'job_id':job_id,'decision_id':decision_id,
                     **identity, 'origin':transport.origin,'model':context.data['request_body']['model'],
                     'send_started':False,'state':'INTENT','history':[], 'transport':None,'transport_digest':None,
                     'selection':None,'selection_digest':None}
                self.data['requests'].append(row);self._transition(row,'INTENT')
            if transport is None:raise JevSelectError('missing_transport')
            if transport.origin!=row['origin']:raise JevSelectError('transport_origin_changed')
            if sum(r['send_started'] for r in self.data['requests'])>=self.max_sends:raise JevSelectError('request_budget_exhausted')
            row['send_started']=True;self._transition(row,'SENDING')
            try:
                saved=transport.complete(context.data['request_body'])
                validate_transport(saved)
            except Exception:
                # Delivery cannot be inferred from an exception, including local wrappers.
                saved=outcome('UNKNOWN_IN_FLIGHT',error='UNKNOWN_SEND',network_attempted=None)
            row['transport']=saved;row['transport_digest']=digest(saved)
            state='UNKNOWN_SEND' if saved['status']=='UNKNOWN_IN_FLIGHT' else 'RESPONSE_SAVED' if saved['status']=='OK' else 'FAILED'
            self._transition(row,state)
            return copy.deepcopy(row)

    def save_selection(self, attempt, selection):
        with exclusive(self.root):
            self._load();row=self.data['requests'][int(attempt['attempt_id'][1:])-1]
            if any(row[k]!=attempt[k] for k in ('context_digest','transport_digest','job_id','decision_id')):
                raise JevSelectError('stale_selection_save')
            if row['selection'] is not None:
                if row['selection']!=selection.data:raise JevSelectError('selection_overwrite')
                return
            row['selection']=selection.data;row['selection_digest']=digest(selection.data)
            self._transition(row,'SELECTION_SAVED' if selection.data['status']=='selected' else row['state'])

    def statistics(self):
        rows=self._load()['requests']
        sent=[r for r in rows if r['send_started'] and r['origin']=='jev']
        return {'send_reservations':len(sent),
                'model_calls':sum(r['transport'] is not None and r['transport']['network_attempted'] is True for r in sent),
                'unknown_sends':sum(r['state']=='UNKNOWN_SEND' for r in sent),
                'failed_requests':sum(r['state']=='FAILED' or (r['selection'] is not None and r['selection']['status']=='invalid_response') for r in sent),
                'model_cost_usd':'UNKNOWN' if sent else 0,
                'usage':[r['selection']['usage'] for r in sent if r['selection'] is not None],
                'request_latency_s':[r['transport']['latency_s'] for r in sent if r['transport'] is not None]}


class PackagingRemoteSelector:
    def __init__(self, config, ledger, job_id, transport):
        self.config,self.ledger,self.job_id,self.transport=config,ledger,job_id,transport

    def select(self, context, *, decision_id):
        from .context import validate_context
        validate_context(context,config=self.config)
        b=context.data['local_binding']
        if b.get('job_id')!=self.job_id or b.get('decision_id')!=decision_id:
            raise JevSelectError('selector_identity_mismatch')
        if context.data['route']=='SINGLETON_BYPASS':
            return result(context,status='singleton',source='singleton',label='C01')
        if context.data['model_state']['memories']!=[]:raise JevSelectError('remote_memories_not_empty')
        attempt=self.ledger.request(context,self.job_id,decision_id,self.transport)
        if attempt['selection'] is not None:return SelectionResult.from_dict(attempt['selection'])
        selected=parse_response(context,attempt,self.config)
        self.ledger.save_selection(attempt,selected)
        return selected


def remote_selector_factory(method, *, config, transport, ledger, job_id):
    if config is None or config.get('version')!=VERSION or method not in REGISTRY or config['selector']!=method:
        raise JevSelectError('remote_unregistered_method_or_protocol')
    validate_schema('config',config)
    if method!='jev_no_memory':
        from .packaging_runtime import LocalPackagingDouble
        if transport is not None or ledger is not None:raise JevSelectError('local_method_remote_dependencies')
        return LocalPackagingDouble(method)
    if not isinstance(ledger,RequestLedger) or not job_id:
        raise JevSelectError('remote_dependencies_required')
    return PackagingRemoteSelector(config,ledger,job_id,transport)


def event_cost(events):
    """Event-only estimate; ledger statistics are authoritative, including failures."""
    rows=[e['selection'] for e in events if e.get('selection') and e['selection']['source']=='jev']
    return {'model_calls':sum(s['network_attempted'] is True for s in rows), 'model_cost_usd':'UNKNOWN' if rows else 0}


def decision_record(event):
    """Bind all saved inputs and downstream results without inventing a reason."""
    c=event['context'];s=event['selection']
    row={'version':VERSIONS['decision_record'],'decision_id':event['decision_id'],
         'state_digest':digest(event['before']),'candidate_pool_digest':digest(event['bundle']),
         'available_candidate_ids':[v['candidate_id'] for v in c['display_mapping'].values()],
         'display_mapping':c['display_mapping'],'context_digest':digest(c),
         'selected_candidate_id':s['selected_candidate_id'] if s else None,
         'selection':s,'exact_action':event['proposed_action'],
         'request_digest':digest(c['request_body']), 'response_digest':s['raw_response_digest'] if s else None,
         'probability_semantics':'native service values, not physical confidence; raw bytes preserved',
         'ranking_availability':'NATIVE_PROBABILITIES_ONLY' if s and s['probabilities'] else 'UNAVAILABLE',
         'provider_tie_rule':'UNKNOWN','generated_explanation':None,
         'monitor':event['monitor'],'execution':{'event':event['event'],'reason':event['reason'],
                     'action':event['action'],'before_digest':digest(event['before']),'after_digest':digest(event['after'])}}
    row['record_digest']=digest(row)
    return row
