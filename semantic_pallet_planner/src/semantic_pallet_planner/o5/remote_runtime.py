"""S2 choice/accounting hook; shared physical episode transitions remain authoritative."""
from .common import O5Error, atomic, digest, read
from .public_request import parse_response
from .remote_transport import prepare_body
from .selectors import geometry_choice
from .remote_config import request_version

DENIALS = {'AMOUNT_BUDGET_EXHAUSTED','ATTEMPT_BUDGET_EXHAUSTED','INPUT_BOUND_EXCEEDED',
           'REQUEST_TOO_LARGE','TEXT_TOKEN_UPPER_BOUND_EXCEEDED','MISSING_CREDENTIAL'}


class JobLedgerView:
    def __init__(self, budget, job_id):
        self.budget,self.job_id=budget,job_id

    @property
    def data(self):
        return {'attempts':self.budget.rows(self.job_id)}


class Runtime:
    def __init__(self, budget, job_id, profile, physical, directory, transport=None):
        self.budget,self.job_id,self.profile,self.physical=budget,job_id,profile,physical
        self.request_version=request_version(profile)
        self.transport=transport
        self.test_double=budget.test_double
        self.result_scope='OFFLINE_HTTP_ENGINEERING_NOT_MODEL_PERFORMANCE' if self.test_double else 'REAL_D0_PILOT'
        self.ledger=JobLedgerView(budget,job_id)
        directory.mkdir(parents=True,exist_ok=True)
        requests=list(directory.glob('decisions/*/request.json'))
        if requests and not (directory/'checkpoint.json').is_file():
            raise O5Error('MISSING_CHECKPOINT')
        if any(not (request.parent/'mapping.private.json').is_file() for request in requests):
            raise O5Error('MISSING_MAPPING')
        path=directory/'ledger.json'
        expected={'schema_version':'o5_s2_job_ledger_ref_v1','campaign_identity':budget.identity,'job_id':job_id}
        if path.exists():
            if read(path)!=expected:
                raise O5Error('JOB_LEDGER_REFERENCE_CHANGED')
        elif (directory/'checkpoint.json').exists():
            raise O5Error('MISSING_LEDGER')
        else:
            atomic(path,expected)

    def choose(self, req, directory):
        diagnostic=None;ids=[];response=None;failure=None
        for index in range(2):
            try:
                body,bound=prepare_body(req,directory,self.physical,self.profile,diagnostic)
                receipt,identity,error=self.budget.attempt(self.job_id,req,body,bound,bool(index),self.transport)
                ids.append(identity)
                if error:
                    failure=error;break
                response=parse_response(receipt['text'],req)
                break
            except O5Error as error:
                if error.code=='UNKNOWN_IN_FLIGHT' or error.code.startswith('SYSTEM_'):
                    raise
                if error.code in DENIALS:
                    failure=error.code
                    atomic(directory/'denial.json',{'request_digest':digest(req),'repair':bool(index),'error':failure})
                    break
                if error.code not in ('INVALID_JSON','SCHEMA_ERROR','STALE_BINDING','INVALID_STOP','UNKNOWN_CANDIDATE'):
                    raise
                diagnostic=error.code
                if index:
                    failure=error.code
        return response,ids,failure

    def verify(self, journal, method, directory):
        req=journal['request']
        if not req['candidates']:
            if journal['response'] is not None or journal['attempt_ids'] or journal['reason']!='NO_PHYSICAL_CANDIDATE':
                raise O5Error('EMPTY_POOL_ACCOUNTING_MISMATCH')
            return
        if method=='G0':
            if journal['attempt_ids'] or journal['response']!=geometry_choice(req,journal['private_mapping']):
                raise O5Error('G0_DECISION_CHANGED')
            return
        rows=[r for r in self.budget.rows(self.job_id) if r['request_digest']==digest(req)]
        if len(rows)>2 or [r['attempt_id'] for r in rows]!=journal['attempt_ids']:
            raise O5Error('REMOTE_ATTEMPT_JOURNAL_MISMATCH')
        diagnostic=None;response=None;failure=None;done=False
        for index,row in enumerate(rows):
            if done or row['repair']!=bool(index):
                raise O5Error('UNEXPECTED_REPAIR_ATTEMPT')
            body,bound=prepare_body(req,directory,self.physical,self.profile,diagnostic)
            if digest(body)!=row['body_digest'] or bound!=row['bound']:
                raise O5Error('REMOTE_BODY_REBUILD_MISMATCH')
            if row['status'] not in ('completed','failed'):
                raise O5Error('UNKNOWN_IN_FLIGHT')
            receipt=read(self.budget.root/'attempts'/row['attempt_id']/'receipt.json')
            if row['error']:
                failure=row['error'];done=True
            else:
                try:
                    response=parse_response(receipt['text'],req);done=True
                except O5Error as error:
                    diagnostic=error.code
                    if index:
                        failure=error.code;done=True
        if not done:
            if not (directory/'denial.json').is_file():
                raise O5Error('MISSING_REMOTE_DECISION')
            denial=read(directory/'denial.json')
            if (denial.get('request_digest')!=digest(req) or denial.get('repair')!=bool(len(rows))
                    or denial.get('error') not in DENIALS):
                raise O5Error('INVALID_REMOTE_DENIAL')
            failure=denial['error']
            if failure in ('INPUT_BOUND_EXCEEDED','REQUEST_TOO_LARGE','TEXT_TOKEN_UPPER_BOUND_EXCEEDED'):
                try:
                    prepare_body(req,directory,self.physical,self.profile,diagnostic)
                except O5Error as error:
                    if error.code!=failure:
                        raise O5Error('REMOTE_DENIAL_CHANGED') from None
                else:
                    raise O5Error('REMOTE_DENIAL_CHANGED')
        expected=failure or ('MODEL_STOP' if response['action']=='STOP' else
                             'PHYSICAL_REJECTION' if journal['physical_errors'] else 'PLACED')
        if response!=journal['response'] or expected!=journal['reason']:
            raise O5Error('REMOTE_DECISION_RECOMPUTATION_MISMATCH')
