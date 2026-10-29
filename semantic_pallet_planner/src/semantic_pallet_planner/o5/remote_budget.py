"""Campaign-wide decimal reservations and durable single-send remote attempts."""
import copy
from pathlib import Path
from .common import O5Error, atomic, digest, read, exclusive
from .remote_config import closed, require_cost, money, charge, amount_policy

STATE = {'schema_version':None,'identity':None,'profile_digest':None,'test_double':None,
         'halt':None,'attempts':None,'jobs':None}
ROW = {'attempt_id':None,'job_id':None,'phase':None,'request_digest':None,'body_digest':None,
       'repair':None,'bound':None,'status':None,'reserved_amount':None,'accounted_amount':None,
       'cost_basis':None,'receipt_digest':None,'error':None}
BOUND = {'input_upper':None,'output_upper':None,'image_sha256':None,'algorithm':None,
         'bound_evidence':None,'body_digest':None,'maximum_amount':None}
RECEIPT = {'schema_version':None,'http_status':None,'provider_request_id':None,'raw_body':None,
           'model':None,'finish_reason':None,'text':None,'usage':None,'error':None,'latency_seconds':None}


class Budget:
    def __init__(self, directory, profile, identity, jobs, test_double, *, create=False):
        profile=require_cost(profile)
        self.root = Path(directory)
        self.path = self.root/'budget.json'
        self.profile, self.identity = copy.deepcopy(profile), identity
        self.jobs, self.test_double = copy.deepcopy(jobs), test_double
        self.capped=amount_policy(profile)=='capped'
        self.version=('o5_s2_attempt_ledger_v1' if profile['schema_version']=='o5_s2_provider_profile_v1'
                      else 'o5_s2_attempt_ledger_v2')
        if create:
            self.root.mkdir(parents=True,exist_ok=True)
            with exclusive(self.root/'budget.lock'):
                if self.path.exists():
                    raise O5Error('BUDGET_EXISTS')
                atomic(self.path, {'schema_version':self.version,'identity':identity,
                    'profile_digest':digest(profile),'test_double':test_double,'halt':None,'attempts':[], 'jobs':jobs})
        self.load()

    def load(self):
        if not self.path.is_file():
            raise O5Error('MISSING_REMOTE_LEDGER')
        state = read(self.path)
        closed(state,STATE)
        if (state['schema_version'] != self.version or state['identity'] != self.identity
                or state['profile_digest'] != digest(self.profile) or state['jobs'] != self.jobs
                or state['test_double'] is not self.test_double or not isinstance(state['attempts'],list)):
            raise O5Error('REMOTE_LEDGER_IDENTITY_CHANGED')
        ids = []
        for r in state['attempts']:
            closed(r,ROW)
            closed(r['bound'],BOUND)
            if (r['job_id'] not in self.jobs or r['phase'] != self.jobs[r['job_id']]['phase']
                    or r['status'] not in ('reserved','sent','completed','failed','unknown')
                    or r['attempt_id'] in ids or type(r['repair']) is not bool
                    or r['attempt_id'] != digest([r['job_id'],r['request_digest'],r['repair']])):
                raise O5Error('REMOTE_LEDGER_CORRUPTED')
            ids.append(r['attempt_id'])
            for value in (r['reserved_amount'],r['accounted_amount']):
                if value is not None or self.capped:money(value)
            body = read(self.root/'attempts'/r['attempt_id']/'body.json')
            if digest(body) != r['body_digest'] or r['bound']['body_digest'] != r['body_digest']:
                raise O5Error('SAVED_REMOTE_BODY_CHANGED')
            b = r['bound']
            if (b['input_upper'] > self.profile['input_limit'] or b['output_upper'] != 256
                    or r['reserved_amount'] != charge(self.profile,b['input_upper'],256)):
                raise O5Error('REMOTE_RESERVATION_CHANGED')
            if r['status'] in ('completed','failed'):
                receipt = read(self.root/'attempts'/r['attempt_id']/'receipt.json')
                closed(receipt,RECEIPT)
                if digest(receipt) != r['receipt_digest']:
                    raise O5Error('REMOTE_RECEIPT_CHANGED')
                amount,basis,error = self.cost(receipt,r)
                if (amount,basis,error) != (r['accounted_amount'],r['cost_basis'],r['error']):
                    raise O5Error('REMOTE_COST_CHANGED')
            elif r['accounted_amount'] != r['reserved_amount'] or r['receipt_digest'] is not None:
                raise O5Error('REMOTE_UNSETTLED_CHANGED')
            if r['status']=='unknown' and state['halt']!='UNKNOWN_IN_FLIGHT':
                raise O5Error('UNKNOWN_HALT_CHANGED')
        for job_id, job in self.jobs.items():
            if sum(r['job_id']==job_id for r in state['attempts']) > job['attempt_limit']:
                raise O5Error('JOB_ATTEMPT_LIMIT_CHANGED')
        for phase in ('preflight','pilot'):
            if sum(r['phase']==phase for r in state['attempts']) > self.profile['limits'][phase+'_attempts']:
                raise O5Error('STAGE_ATTEMPT_LIMIT_CHANGED')
        self.state = state
        return state

    def totals(self):
        self.load()
        if not self.capped:
            groups={phase:[r for r in self.state['attempts'] if r['phase']==phase] for phase in ('preflight','pilot')}
            groups['total']=self.state['attempts']
            known={phase:str(sum((money(r['accounted_amount']) for r in rows if r['accounted_amount'] is not None),money('0')))
                   for phase,rows in groups.items()}
            unknown={phase:sum(r['accounted_amount'] is None for r in rows) for phase,rows in groups.items()}
            return {**{phase:None if unknown[phase] else known[phase] for phase in groups},
                    'known_subtotal':known,'unknown_attempts':unknown,'currency':self.profile['pricing']['currency'],
                    'amount_policy':'unlimited','basis':'usage_based_estimate_or_unknown_not_provider_invoice'}
        return {**{phase:str(sum((money(r['accounted_amount']) for r in self.state['attempts'] if r['phase']==phase), money('0')))
                    for phase in ('preflight','pilot')},
                'total':str(sum((money(r['accounted_amount']) for r in self.state['attempts']),money('0'))),
                'basis':'usage_based_estimate_or_reserved_upper_bound_not_provider_invoice'}

    def cost(self, receipt, row):
        usage = receipt.get('usage')
        if (not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens'))):
            return row['reserved_amount'],('RESERVED_ESTIMATE' if row['reserved_amount'] is not None else 'UNKNOWN'),receipt.get('error')
        amount = charge(self.profile,usage['prompt_tokens'],usage['completion_tokens'])
        error = receipt.get('error')
        if usage['prompt_tokens']>row['bound']['input_upper'] or usage['completion_tokens']>256:
            error = 'SYSTEM_USAGE_BOUND_EXCEEDED'
        return amount,('USAGE_BASED_ESTIMATE' if amount is not None else 'UNKNOWN'),error

    def _settle(self, row, receipt):
        closed(receipt,RECEIPT)
        if receipt['schema_version']!='o5_s2_transport_result_v1':
            raise O5Error('INVALID_REMOTE_RECEIPT')
        row['receipt_digest'] = digest(receipt)
        row['accounted_amount'],row['cost_basis'],row['error'] = self.cost(receipt,row)
        row['status'] = 'failed' if row['error'] else 'completed'
        if row['error'] and row['error'].startswith('SYSTEM_'):
            self.state['halt'] = row['error']
        last=self.state['attempts'][-2:]
        if len(last)==2 and all((r['error'] or '').startswith('HTTP_5') for r in last):
            self.state['halt']='SYSTEM_REPEATED_HTTP_5XX'
        atomic(self.path,self.state)

    def rows(self, job_id):
        return [copy.deepcopy(r) for r in self.load()['attempts'] if r['job_id']==job_id]

    def attempt(self, job_id, req, body, bound, repair, transport):
        if transport.test_double is not self.test_double:
            raise O5Error('REMOTE_TEST_DOUBLE_MISMATCH')
        identity = digest([job_id,digest(req),bool(repair)])
        with exclusive(self.root/'budget.lock'):
            self.load()
            existing = next((r for r in self.state['attempts'] if r['attempt_id']==identity),None)
            if existing and (existing['body_digest']!=digest(body) or existing['bound']!=bound):
                raise O5Error('SAVED_REQUEST_CHANGED')
            # Reconcile a durable receipt before marking a sent request unknown.
            for r in self.state['attempts']:
                if r['status']=='sent':
                    path = self.root/'attempts'/r['attempt_id']/'receipt.json'
                    if path.is_file():
                        self._settle(r,read(path))
                    else:
                        r['status']='unknown';r['error']='UNKNOWN_IN_FLIGHT'
                        self.state['halt']='UNKNOWN_IN_FLIGHT';atomic(self.path,self.state)
            if existing and existing['status'] in ('completed','failed'):
                return read(self.root/'attempts'/identity/'receipt.json'),identity,existing['error']
            if self.state['halt']:
                raise O5Error(self.state['halt'])
            transport.precheck()  # Cached responses do not need credentials or a new call.
            if existing is None:
                if job_id not in self.jobs:
                    raise O5Error('UNPLANNED_JOB')
                job = self.jobs[job_id];phase=job['phase']
                rows=self.state['attempts']
                if (sum(r['job_id']==job_id for r in rows)>=job['attempt_limit']
                        or sum(r['phase']==phase for r in rows)>=self.profile['limits'][phase+'_attempts']):
                    raise O5Error('ATTEMPT_BUDGET_EXHAUSTED')
                reservation=bound['maximum_amount']
                if bound['body_digest']!=digest(body) or reservation!=charge(self.profile,bound['input_upper'],256):
                    raise O5Error('INVALID_RESERVATION')
                if self.capped:
                    phase_amount=sum((money(r['accounted_amount']) for r in rows if r['phase']==phase),money('0'))
                    total=sum((money(r['accounted_amount']) for r in rows),money('0'))
                    if (phase_amount+money(reservation)>money(self.profile['limits'][phase+'_amount'])
                            or total+money(reservation)>money(self.profile['limits']['total_amount'])):
                        raise O5Error('AMOUNT_BUDGET_EXHAUSTED')
                atomic(self.root/'attempts'/identity/'body.json',body)
                existing={'attempt_id':identity,'job_id':job_id,'phase':phase,'request_digest':digest(req),
                    'body_digest':digest(body),'repair':bool(repair),'bound':bound,'status':'reserved',
                    'reserved_amount':reservation,'accounted_amount':reservation,
                    'cost_basis':'RESERVED_ESTIMATE' if reservation is not None else 'UNKNOWN',
                    'receipt_digest':None,'error':None}
                rows.append(existing);atomic(self.path,self.state)
            existing['status']='sent';atomic(self.path,self.state)
            try:
                receipt=transport.complete(copy.deepcopy(body))
            except Exception:
                existing['status']='unknown';existing['error']='UNKNOWN_IN_FLIGHT'
                self.state['halt']='UNKNOWN_IN_FLIGHT';atomic(self.path,self.state)
                raise O5Error('UNKNOWN_IN_FLIGHT') from None
            atomic(self.root/'attempts'/identity/'receipt.json',receipt)
            self._settle(existing,receipt)
            return receipt,identity,existing['error']
