"""Explicit operator-only preflight and pilot; no call occurs during preparation or verify."""
import base64
import copy
import json
from pathlib import Path
from .common import O5Error, atomic, digest, read, sha, exclusive, new_directory, canonical
from .remote_config import require_cost, charge, money
from .remote_transport import ChatHTTPTransport, HTTPWire, prepare_body
from .remote_budget import Budget
from .remote_runtime import Runtime
from .remote_experiment import validate_plan, budget_jobs, verify_job, validate_run
from .public_request import parse_response
from .episode import run_episode

AUTH_KEYS={'schema_version','plan_digest','campaign_path','profile_digest','account_id','currency',
           'stage','stage_amount','total_amount','instruction_reference'}


def validate_preflight(state):
    keys={'schema_version','identity','plan','auth_digest','campaign','status','results','error','test_double'}
    if (set(state)!=keys or state['schema_version']!='o5_s2_preflight_v1' or state['test_double'] is not False
            or state['status'] not in ('IN_PROGRESS','PASS','HOLD_ENGINEERING') or not isinstance(state['results'],list)):
        raise O5Error('PREFLIGHT_SCHEMA_ERROR')
    for row in state['results']:
        if set(row)!={'task_id','attempt_ids','pass','error'} or type(row['pass']) is not bool:
            raise O5Error('PREFLIGHT_SCHEMA_ERROR')
    return state


def campaign_identity(plan):
    return digest([plan['dataset_digest'],plan['profile'],plan['physical'],plan['source_files']])


def jobs_for(plan):
    return {**budget_jobs(plan), **{'P_'+t['task_id']:{'phase':'preflight','attempt_limit':t['attempt_limit']}
                                  for t in plan['preflight_tasks']}}


def authorization(plan,auth_path,stage):
    auth=read(auth_path)
    if (set(auth)!=AUTH_KEYS or auth['schema_version']!='o5_s2_operator_authorization_v1'
            or auth['plan_digest']!=digest(plan) or auth['profile_digest']!=digest(plan['profile'])
            or auth['account_id']!=plan['profile']['account_id'] or auth['currency']!=plan['profile']['pricing']['currency']
            or auth['stage']!=stage or not isinstance(auth['instruction_reference'],str) or not auth['instruction_reference'].strip()
            or not isinstance(auth['campaign_path'],str) or not auth['campaign_path']
            or not Path(auth['campaign_path']).is_absolute()):
        raise O5Error('AUTHORIZATION_MISMATCH')
    if (money(auth['stage_amount'])!=money(plan['profile']['limits'][stage+'_amount'])
            or money(auth['total_amount'])!=money(plan['profile']['limits']['total_amount'])):
        raise O5Error('AUTHORIZATION_AMOUNT_MISMATCH')
    return auth


def saved_authorization(plan,root,state,stage):
    auth=authorization(plan,Path(root)/'authorization.json',stage)
    if state['auth_digest']!=digest(auth) or Path(state['campaign']).resolve()!=Path(auth['campaign_path']).resolve():
        raise O5Error('SAVED_AUTHORIZATION_CHANGED')
    return auth


def campaign(root,plan,auth,*,create=False):
    path=Path(auth['campaign_path']).resolve()
    if path==root or path.is_relative_to(root):
        raise O5Error('CAMPAIGN_MUST_BE_SHARED_OUTSIDE_RUN')
    # A campaign is created for preflight only. Pilot can never reset it.
    if create:
        new_directory(path)
    return Budget(path,plan['profile'],campaign_identity(plan),jobs_for(plan),False,create=create)


def visual_body(task,plan_root,profile):
    content=[{'type':'text','text':task['prompt']}]
    for image in task['images']:
        path=Path(plan_root)/image['path']
        if sha(path)!=image['sha256']:raise O5Error('PREFLIGHT_IMAGE_CHANGED')
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+
            base64.b64encode(path.read_bytes()).decode(),'detail':'high'}})
    body={'model':profile['model'],'messages':[{'role':'user','content':content}],
          'max_tokens':256,'temperature':0,'stream':False}
    if profile['seed'] is not None:body['seed']=profile['seed']
    bound=len(task['prompt'].encode())+profile['token_bound']['framing_tokens']+2*profile['token_bound']['per_image_tokens']
    if bound>12000 or len(canonical(body).encode())>profile['max_request_bytes']:raise O5Error('INPUT_BOUND_EXCEEDED')
    return body,{'input_upper':bound,'output_upper':256,'image_sha256':[a['sha256'] for a in task['images']],
                 'algorithm':profile['token_bound']['algorithm'],'bound_evidence':profile['token_bound']['evidence'],
                 'body_digest':digest(body),'maximum_amount':charge(profile,bound,256)}


def preflight(plan_root,output,auth_path,*,resume=False):
    plan_root=Path(plan_root).resolve();plan,_=validate_plan(plan_root)
    require_cost(plan['profile'])
    if plan['stage']!='preflight' or plan['mode']!='REMOTE_DRAFT':raise O5Error('WRONG_PREFLIGHT_PLAN')
    auth=authorization(plan,auth_path,'preflight')
    # Verify credentials before allocating any run/campaign directory.
    transport=ChatHTTPTransport(plan['profile']);transport.precheck()
    root=Path(output).resolve() if resume else new_directory(output)
    identity=digest([digest(plan),str(root),digest(auth)])
    with exclusive(root/'run.lock'):
        if resume:
            state=read(root/'preflight.json')
            validate_preflight(state)
            saved_authorization(plan,root,state,'preflight')
            if state['identity']!=identity:raise O5Error('PREFLIGHT_IDENTITY_CHANGED')
            if state['status']!='IN_PROGRESS':
                return {'status':state['status'],'error':state['error'],'new_api_attempts':0}
        else:
            state={'schema_version':'o5_s2_preflight_v1','identity':identity,'plan':str(plan_root),'auth_digest':digest(auth),
                   'campaign':auth['campaign_path'],'status':'IN_PROGRESS','results':[],'error':None,
                   'test_double':False}
            atomic(root/'authorization.json',auth)
            atomic(root/'preflight.json',state)
        budget=campaign(root,plan,auth,create=not resume)
        if budget.load()['halt']:raise O5Error(budget.state['halt'])
        try:
            for task in plan['preflight_tasks']:
                if any(r['task_id']==task['task_id'] for r in state['results']):continue
                job='P_'+task['task_id']
                if task['task_id']=='probe_contract':
                    req=read(plan_root/'contract/request.json');ids=[];diagnostic=None;valid=False
                    for index in range(2):
                        body,bound=prepare_body(req,plan_root/'contract',plan['physical'],plan['profile'],diagnostic)
                        receipt,i,error=budget.attempt(job,req,body,bound,bool(index),transport);ids.append(i)
                        if error:break
                        try:parse_response(receipt['text'],req);valid=True;break
                        except O5Error as e:diagnostic=e.code
                else:
                    body,bound=visual_body(task,plan_root,plan['profile'])
                    receipt,i,error=budget.attempt(job,task,body,bound,False,transport);ids=[i]
                    expected={a['asset_id']:a['expected_fact'] for a in task['images']}
                    try:valid=not error and json.loads(receipt['text'])==expected
                    except (ValueError,TypeError):valid=False
                state['results'].append({'task_id':task['task_id'],'attempt_ids':ids,'pass':bool(valid),'error':error})
                atomic(root/'preflight.json',state)
                if not valid:raise O5Error(error or 'PREFLIGHT_CAPABILITY_FAILED')
            state['status']='PASS'
        except O5Error as error:
            state['status']='HOLD_ENGINEERING';state['error']=error.code
        atomic(root/'preflight.json',state)
        atomic(root/'receipt_seal.json',{'files':{str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and p.name not in ('receipt_seal.json','run.lock')}})
        return {'status':state['status'],'completed_probes':len(state['results']),'error':state['error'],
                'real_api_attempts':len(budget.load()['attempts']),'cost':budget.totals()}


def verify_preflight(root):
    root=Path(root).resolve();state=read(root/'preflight.json');plan,_=validate_plan(state['plan'])
    validate_preflight(state)
    auth=saved_authorization(plan,root,state,'preflight')
    if state['identity']!=digest([digest(plan),str(root),digest(auth)]):
        raise O5Error('PREFLIGHT_IDENTITY_CHANGED')
    if state['schema_version']!='o5_s2_preflight_v1' or state['test_double'] is not False:
        raise O5Error('PREFLIGHT_NOT_REAL')
    seal=read(root/'receipt_seal.json')
    if any(sha(root/f)!=h for f,h in seal['files'].items()):raise O5Error('PREFLIGHT_RECEIPT_CHANGED')
    budget=Budget(state['campaign'],plan['profile'],campaign_identity(plan),jobs_for(plan),False)
    tasks={t['task_id']:t for t in plan['preflight_tasks']};seen=[]
    for record in state['results']:
        if record['task_id'] in seen or record['task_id'] not in tasks:raise O5Error('PREFLIGHT_TASK_CHANGED')
        seen.append(record['task_id']);task=tasks[record['task_id']]
        rows=budget.rows('P_'+task['task_id'])
        if record['attempt_ids']!=[r['attempt_id'] for r in rows]:raise O5Error('PREFLIGHT_ATTEMPT_CHANGED')
        diagnostic=None;valid=False;error=None;done=False
        for index,row in enumerate(rows):
            if done:raise O5Error('UNEXPECTED_REPAIR_ATTEMPT')
            if task['task_id']=='probe_contract':
                req=read(Path(state['plan'])/'contract/request.json')
                body,bound=prepare_body(req,Path(state['plan'])/'contract',plan['physical'],plan['profile'],diagnostic)
            else:
                body,bound=visual_body(task,state['plan'],plan['profile'])
            if row['body_digest']!=digest(body) or row['bound']!=bound:raise O5Error('PREFLIGHT_BODY_CHANGED')
            receipt=read(budget.root/'attempts'/row['attempt_id']/'receipt.json');error=row['error']
            if error:done=True;break
            try:
                if task['task_id']=='probe_contract':parse_response(receipt['text'],req);valid=True
                else:valid=json.loads(receipt['text'])=={a['asset_id']:a['expected_fact'] for a in task['images']}
            except (O5Error,ValueError,TypeError) as e:
                diagnostic=e.code if isinstance(e,O5Error) else 'INVALID_JSON'
            done=valid or task['task_id']!='probe_contract'
        if record['pass']!=valid or record['error']!=error:raise O5Error('PREFLIGHT_RESULT_CHANGED')
    preflight_rows=[r for r in budget.state['attempts'] if r['phase']=='preflight']
    passed=(seen==list(tasks) and all(r['pass'] for r in state['results'])
            and all(r['status'] in ('completed','failed') for r in preflight_rows))
    if state['status']=='PASS' and not passed:raise O5Error('PREMATURE_PREFLIGHT_SUCCESS')
    return {'status':'PASS' if passed else 'HOLD_ENGINEERING','real_api_attempts':len([r for r in budget.state['attempts'] if r['phase']=='preflight']),
            'plan':plan,'campaign':str(budget.root),'source_preflight':str(root),'test_double':False}


def prepare_pilot_from_preflight(preflight_root,output):
    evidence=verify_preflight(preflight_root)
    if evidence['status']!='PASS':raise O5Error('PREFLIGHT_NOT_PASSED')
    from .remote_experiment import prepare
    source=evidence['plan']
    result=prepare(source['dataset_path'],output,source['profile'],stage='pilot')
    root=Path(output);plan=read(root/'plan.json');plan['status']='READY_FOR_OPERATOR_AUTHORIZATION'
    plan['gaps']=[]
    # Keep prerequisite binding external to public decision requests.
    atomic(root/'preflight_binding.json',{'preflight':evidence['source_preflight'],'campaign':evidence['campaign'],
            'preflight_file_sha256':sha(Path(preflight_root)/'preflight.json'),
            'profile_digest':digest(source['profile'])})
    atomic(root/'plan.json',plan)
    files={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and p.name!='seal.json'}
    atomic(root/'seal.json',{'schema_version':'o5_s2_plan_seal_v1','plan_digest':digest(plan),'files':files})
    return {**result,'status':plan['status'],'gaps':[]}


def run_pilot(plan_root,output,auth_path,*,resume=False):
    plan_root=Path(plan_root).resolve();plan,tasks=validate_plan(plan_root)
    require_cost(plan['profile'])
    if plan['status']!='READY_FOR_OPERATOR_AUTHORIZATION' or plan['mode']!='REMOTE_DRAFT' or plan['stage']!='pilot':
        raise O5Error('PILOT_PLAN_NOT_READY')
    binding=read(plan_root/'preflight_binding.json');evidence=verify_preflight(binding['preflight'])
    if (evidence['status']!='PASS' or digest(evidence['plan']['profile'])!=digest(plan['profile'])
            or sha(Path(binding['preflight'])/'preflight.json')!=binding['preflight_file_sha256']):
        raise O5Error('PREFLIGHT_BINDING_CHANGED')
    auth=authorization(plan,auth_path,'pilot')
    if Path(auth['campaign_path']).resolve()!=Path(evidence['campaign']).resolve():raise O5Error('CAMPAIGN_CHANGED')
    transport=ChatHTTPTransport(plan['profile']);transport.precheck()
    root=Path(output).resolve() if resume else new_directory(output);identity=campaign_identity(plan)
    with exclusive(root/'run.lock'):
        if resume:
            state=read(root/'run.json')
            validate_run(state,plan)
            saved_authorization(plan,root,state,'pilot')
            if state['identity']!=identity or state['plan']!=str(plan_root) or state['auth_digest']!=digest(auth):
                raise O5Error('RUN_IDENTITY_CHANGED')
        else:
            state={'schema_version':'o5_s2_run_v1','identity':identity,'plan':str(plan_root),'mode':'REAL_D0_PILOT',
                   'campaign':evidence['campaign'],'auth_digest':digest(auth),
                   'jobs':[{**j,'status':'NOT_RUN','error':None} for j in plan['jobs']]}
            atomic(root/'authorization.json',auth)
            atomic(root/'run.json',state)
        budget=campaign(root,plan,auth)
        if budget.load()['halt']:raise O5Error(budget.state['halt'])
        if len(state['jobs'])!=len(plan['jobs']) or any({k:j.get(k) for k in e}!=e for j,e in zip(state['jobs'],plan['jobs'])):
            raise O5Error('JOB_REGISTRY_CHANGED')
        by_id={t['task_id']:t for t in tasks}
        for job in state['jobs']:
            if job['status']=='COMPLETE':verify_job(root,plan,by_id[job['task_id']],job,budget);continue
            directory=root/'jobs'/job['job_id'];rt=Runtime(budget,job['job_id'],plan['profile'],plan['physical'],directory,transport)
            job['status']='IN_PROGRESS';atomic(root/'run.json',state)
            try:
                result=run_episode(by_id[job['task_id']],job['method'],plan['physical'],directory,job['job_id'],identity,
                    attempt_limit=job['attempt_limit'],resume=(directory/'checkpoint.json').exists(),_runtime=rt)
                job['status']='COMPLETE'
                reason=result['summary']['termination_reason']
                if budget.load()['halt']:raise O5Error(budget.state['halt'])
                if reason in ('AMOUNT_BUDGET_EXHAUSTED','ATTEMPT_BUDGET_EXHAUSTED','MISSING_CREDENTIAL','INPUT_BOUND_EXCEEDED'):
                    raise O5Error(reason)
            except O5Error as error:
                job['status']='STOPPED';job['error']=error.code;atomic(root/'run.json',state)
                return {'status':'INVALID_OR_PARTIAL','error':error.code,'completed_jobs':sum(j['status']=='COMPLETE' for j in state['jobs'])}
            atomic(root/'run.json',state)
        return {'status':'EXECUTION_COMPLETE_REQUIRES_VERIFICATION','completed_jobs':len(state['jobs']),
                'real_api_attempts':len([r for r in budget.load()['attempts'] if r['phase']=='pilot'])}
