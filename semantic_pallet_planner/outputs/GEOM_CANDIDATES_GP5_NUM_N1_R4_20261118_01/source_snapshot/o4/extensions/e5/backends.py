"""Compilation backends with durable cross-job budgets; no planner/reference input."""
import copy
import time
from pathlib import Path
from ...common import read,digest,O4Error
from ..e2.compiler import compile_policy
from ..e2.protocol import response_for,validate_observation,rebind,validate_response
from ..e2.remote import parse_response,prompt,PROMPT_VERSION
from ..e2.visual import render,facts
from ..e2.visual_verify import verify as verify_image
from .storage import atomic,exclusive
from .capability import check_instruction


class Ledger:
    def __init__(self,root,budget,job_limits,*,test_double=False,resume=False):
        self.root=Path(root);self.path=self.root/'audit/ledger.json'
        if type(budget)is not int or budget<0 or any(type(v)is not int or v<0 for v in job_limits.values()):raise O4Error('invalid_api_budget')
        self.budget=budget;self.limits=job_limits;self.test_double=test_double
        with exclusive(self.root/'audit/ledger.lock'):
            if self.path.exists():
                if not resume:raise O4Error('ledger_exists')
                d=read(self.path)
                if d['budget']!=budget or d['job_limits']!=job_limits or d['test_double']!=test_double:raise O4Error('ledger_configuration_changed')
                self._validate_resume(d)
            else:
                if resume:raise O4Error('missing_ledger')
                atomic(self.path,{'budget':budget,'job_limits':job_limits,'test_double':test_double,'attempts':[]})

    def _validate_resume(self,data):
        rows=data.get('attempts')
        if not isinstance(rows,list) or len(rows)>self.budget or [a.get('attempt_id') for a in rows]!=list(range(1,len(rows)+1)):
            raise O4Error('ledger_record_disagreement','attempt identity/count changed')
        if any(a.get('job_id') not in self.limits for a in rows) or any(sum(a['job_id']==j for a in rows)>limit for j,limit in self.limits.items()):
            raise O4Error('ledger_record_disagreement','per-job attempt count changed')
        known=set()
        for path in sorted((self.root/'responses').glob('*/*.json')):
            record=read(path);identifier=record['compilation_id'];known.add(identifier)
            matching=[a for a in rows if a['compilation_id']==identifier]
            # A process may die after reserving an attempt but before appending
            # its ID to the compilation record. Only an intact known prefix is
            # allowed; dropping previously saved IDs is never a budget reset.
            expected=[a['attempt_id'] for a in matching];saved=record['attempt_ids']
            if saved!=expected[:len(saved)] or len(matching)>2:
                raise O4Error('ledger_record_disagreement','saved compilation attempts missing or renumbered')
            if record['response'] is not None:
                if not matching or matching[-1]['status']!='valid':raise O4Error('ledger_record_disagreement','valid response has no debited attempt')
                try:response=parse_response(matching[-1]['payload'],record['compiled_request'])
                except O4Error as exc:raise O4Error('ledger_record_disagreement','saved valid payload changed') from exc
                if response!=record['response']:raise O4Error('ledger_record_disagreement','saved response differs from HTTP payload')
        if any(a['compilation_id'] not in known for a in rows):raise O4Error('ledger_record_disagreement','attempt without compilation record')


    def rows(self):return read(self.path)['attempts']

    def start(self,job_id,compilation_id,body_digest,repair):
        with exclusive(self.root/'audit/ledger.lock'):
            d=read(self.path);rows=d['attempts']
            if job_id not in self.limits:raise O4Error('unplanned_job')
            if len(rows)>=self.budget or sum(a['job_id']==job_id for a in rows)>=self.limits[job_id]:raise O4Error('budget_exhausted')
            previous=[a for a in rows if a['compilation_id']==compilation_id]
            if len(previous)>=2 or repair!=(len(previous)==1) or (previous and previous[0]['status'] not in ('invalid_ast','invalid_binding')):
                raise O4Error('invalid_attempt_transition')
            attempt={'attempt_id':len(rows)+1,'job_id':job_id,'compilation_id':compilation_id,'body_digest':body_digest,
                     'repair':repair,'status':'in_flight','payload':None,'raw_text':None,'repair_diagnostic':None,
                     'usage':None,'cost':None,'latency_s':None}
            rows.append(attempt);atomic(self.path,d);return copy.deepcopy(attempt)

    def finish(self,attempt_id,**result):
        with exclusive(self.root/'audit/ledger.lock'):
            d=read(self.path);row=d['attempts'][attempt_id-1]
            if row['attempt_id']!=attempt_id or row['status']!='in_flight':raise O4Error('invalid_attempt_finish')
            row.update(result);atomic(self.path,d);return copy.deepcopy(row)

    def report(self):
        rows=self.rows();return {'authorized_budget':self.budget,'used_attempts':len(rows),'remaining_attempts':self.budget-len(rows),
             'real_api_attempts':0 if self.test_double else len(rows),'test_double':self.test_double,
             'unknown_in_flight':sum(a['status']=='in_flight' for a in rows),
             'per_job':{j:{'limit':limit,'used':sum(a['job_id']==j for a in rows)} for j,limit in self.limits.items()}}


class LocalCompiler:
    def __init__(self,backend,oracle_policy=None,*,transform=None):
        if backend not in ('public_parser','oracle_ast'):raise O4Error('unsupported_backend')
        if (backend=='oracle_ast')!=(oracle_policy is not None):raise O4Error('oracle_privilege_mismatch')
        self.backend=backend;self.oracle=oracle_policy;self.transform=transform

    def compile(self,req,job_id,decision):
        validate_observation(req);check_instruction(req['instruction_text'])
        response=compile_policy(req) if self.backend=='public_parser' else response_for(req,self.oracle)
        if self.transform:response=response_for(req,self.transform(copy.deepcopy(response['policy_ast'])))
        return {'compiled_request':copy.deepcopy(req),'response':response,'status':'valid',
                'compilation_id':f'{job_id}_D{decision:04d}','backend':self.backend,'source_digest':digest(req),
                'first_valid':True,'repaired_valid':False,'attempt_ids':[],'test_double':False}


class RemoteCompiler:
    """One shared transport/ledger; stable IDs recover only interrupted decisions."""
    def __init__(self,root,transport,ledger,*,recover=False):
        if transport.test_double!=ledger.test_double:raise O4Error('transport_ledger_mismatch')
        self.root=Path(root);self.transport=transport;self.ledger=ledger;self.recover=recover

    def compile(self,req,job_id,decision,condition=None):
        # condition is set by a per-job public wrapper; no private task is accepted.
        validate_observation(req);check_instruction(req['instruction_text'])
        if req['images'] or condition not in ('text','image'):raise O4Error('invalid_remote_source')
        if job_id not in self.ledger.limits or not job_id.replace('_','').isalnum() or type(decision)is not int or not 0<=decision<self.ledger.limits[job_id]//2:raise O4Error('unplanned_decision')
        identifier=f'{job_id}_D{decision:04d}';path=self.root/f'responses/{job_id}/D{decision:04d}.json'
        if path.exists():
            if not self.recover:raise O4Error('duplicate_compilation')
            record=read(path)
            if record['source_digest']!=digest(req) or record['backend']!='remote_'+condition:raise O4Error('compilation_source_changed')
        else:
            asset=render(req,self.root,f'public/images/{identifier}.png');verify_image(req,self.root,asset)
            attached=copy.deepcopy(req);attached['images']=[asset] if condition=='image' else [];attached=rebind(attached)
            envelope={'schema_version':'o4_e2_visual_input_v1','condition':condition,'public_request':attached,'visual_facts':facts(req),'images':attached['images']}
            record={'compilation_id':identifier,'backend':'remote_'+condition,'source_digest':digest(req),'source_request':req,
                    'compiled_request':attached,'envelope':envelope,'prompt_version':PROMPT_VERSION,'prompt_digest':digest(prompt()),
                    'status':'in_flight','response':None,'first_valid':False,'repaired_valid':False,'attempt_ids':[],
                    'test_double':self.transport.test_double}
            atomic(path,record)
        attached=record['compiled_request'];diagnostic=None
        # Ledger is authoritative even if interrupted between finishing an HTTP
        # attempt and writing the compilation record.
        previous=[a for a in self.ledger.rows() if a['compilation_id']==identifier]
        record['attempt_ids']=[a['attempt_id'] for a in previous]
        if previous:record['status']=previous[-1]['status']
        for a in previous:
            if digest(self.transport.body(record['envelope'],self.root,prompt(),diagnostic))!=a['body_digest']:
                raise O4Error('saved_request_body_changed')
            if a['status']=='in_flight':
                record.update(status='unknown_in_flight',response=None,attempt_ids=[x['attempt_id'] for x in previous]);atomic(path,record);return record
            if a['status']=='valid':
                response=parse_response(a['payload'],attached)
                record.update(response=response,status='valid',first_valid=not a['repair'],repaired_valid=a['repair'],attempt_ids=[x['attempt_id'] for x in previous]);atomic(path,record);return record
            diagnostic=a['repair_diagnostic']
        if previous and previous[-1]['status'] not in ('invalid_ast','invalid_binding'):
            record.update(status=previous[-1]['status'],attempt_ids=[x['attempt_id'] for x in previous]);atomic(path,record);return record
        for index in range(len(previous),2):
            body=self.transport.body(record['envelope'],self.root,prompt(),diagnostic)
            try:attempt=self.ledger.start(job_id,identifier,digest(body),index==1)
            except O4Error as exc:
                if exc.code!='budget_exhausted':raise
                record['status']=exc.code;atomic(path,record);return record
            record['attempt_ids'].append(attempt['attempt_id']);atomic(path,record)
            payload=raw=None;response=None;started=time.perf_counter()
            try:
                output=self.transport.complete(body);payload=output['payload'];raw=output.get('raw_text')
                response=parse_response(payload,attached);status='valid';diagnostic=None
            except O4Error as exc:
                status=exc.code;diagnostic={'code':exc.code,'detail':str(exc),'repair_scope':'format/bindings only; no reference answer'}
            self.ledger.finish(attempt['attempt_id'],status=status,payload=payload,raw_text=raw,repair_diagnostic=diagnostic,
                               usage=payload.get('usage') if isinstance(payload,dict) else None,cost=None,latency_s=time.perf_counter()-started)
            record['status']=status
            if response is not None:
                record.update(response=response,first_valid=index==0,repaired_valid=index==1);break
            if status not in ('invalid_ast','invalid_binding'):break
        atomic(path,record);return record

    def bound(self,condition):
        owner=self
        class Bound:
            def compile(self,req,job_id,decision):return owner.compile(req,job_id,decision,condition)
        return Bound()
