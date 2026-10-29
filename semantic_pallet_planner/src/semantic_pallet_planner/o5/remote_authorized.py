"""Explicit operator-only preflight and pilot; no call occurs during preparation or verify."""
import base64
import copy
import json
from pathlib import Path
from .common import O5Error, atomic, digest, read, sha, exclusive, new_directory, canonical
from .remote_config import require_cost, charge, money, amount_policy
from .remote_transport import ChatHTTPTransport, HTTPWire, prepare_body, provider_options
from .remote_budget import Budget
from .remote_runtime import Runtime
from .remote_experiment import validate_plan, budget_jobs, verify_job, validate_run
from .public_request import parse_response, TEXT_VERSION
from .episode import run_episode
from .visual_probe import evaluate as evaluate_visual

AUTH_KEYS={'schema_version','plan_digest','campaign_path','profile_digest','account_id','currency',
           'stage','stage_amount','total_amount','instruction_reference'}


def validate_selection(raw,req,plan_root,task):
    response=parse_response(raw,req)
    if req['schema_version'] == TEXT_VERSION and response['action']=='PLACE':
        from .candidates import case_for, state_for
        from ..evaluation.geometry_oracle import check_candidate
        directory=Path(plan_root)/Path(task['request_path']).parent
        mapping=read(directory/'mapping.private.json')
        # Recover evaluator-only support fractions from the frozen physical prefix.
        _,tasks=validate_plan(plan_root)
        from .selectors import geometry_choice
        from ..evaluation.state import apply_candidate
        placed=[];index=len(req['placed_items']);t=tasks[0]
        if index:
            first=read(Path(plan_root)/'text_states/0/request.json')
            first_map=read(Path(plan_root)/'text_states/0/mapping.private.json')
            proposal=first_map[geometry_choice(first,first_map)['candidate_id']]
            placed=apply_candidate(case_for(state_for(t['container'],[],t['items'][0],0)),proposal)
        case=case_for(state_for(t['container'],placed,t['items'][index],index))
        if check_candidate(case,{'container':t['container']},mapping[response['candidate_id']]):
            raise O5Error('PREFLIGHT_PHYSICAL_REJECTION')
    return response


def validate_preflight(state):
    keys={'schema_version','identity','plan','auth_digest','campaign','status','results','error','test_double'}
    if (set(state)!=keys or state['schema_version'] not in ('o5_s2_preflight_v1','o5_direct_text_preflight_v1')
            or type(state['test_double']) is not bool
            or (state['schema_version']=='o5_s2_preflight_v1' and state['test_double'] is not False)
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
    policy=amount_policy(plan['profile'])
    version=auth.get('schema_version')
    if version=='o5_s2_operator_authorization_v1':
        if set(auth)!=AUTH_KEYS or policy!='capped':raise O5Error('AUTHORIZATION_AMOUNT_POLICY_MISMATCH')
    elif version=='o5_s2_operator_authorization_v2':
        monetary={'currency','stage_amount','total_amount'}
        required=(AUTH_KEYS-monetary)|{'amount_policy'}
        if (not required<=set(auth) or not set(auth)<=required|monetary
                or auth['amount_policy']!=policy
                or (policy=='capped' and not monetary<=set(auth))):
            raise O5Error('AUTHORIZATION_AMOUNT_POLICY_MISMATCH')
        if policy=='unlimited' and any(auth.get(k) is not None for k in ('stage_amount','total_amount')):
            raise O5Error('AUTHORIZATION_AMOUNT_POLICY_MISMATCH')
    else:
        raise O5Error('AUTHORIZATION_MISMATCH')
    if (auth['plan_digest']!=digest(plan) or auth['profile_digest']!=digest(plan['profile'])
            or auth['account_id']!=plan['profile']['account_id']
            or ('currency' in auth and auth['currency']!=plan['profile']['pricing']['currency'])
            or auth['stage']!=stage or not isinstance(auth['instruction_reference'],str) or not auth['instruction_reference'].strip()
            or not isinstance(auth['campaign_path'],str) or not auth['campaign_path']
            or not Path(auth['campaign_path']).is_absolute()):
        raise O5Error('AUTHORIZATION_MISMATCH')
    if policy=='capped' and (money(auth['stage_amount'])!=money(plan['profile']['limits'][stage+'_amount'])
            or money(auth['total_amount'])!=money(plan['profile']['limits']['total_amount'])):
        raise O5Error('AUTHORIZATION_AMOUNT_MISMATCH')
    return auth


def saved_authorization(plan,root,state,stage):
    auth=authorization(plan,Path(root)/'authorization.json',stage)
    if state['auth_digest']!=digest(auth) or Path(state['campaign']).resolve()!=Path(auth['campaign_path']).resolve():
        raise O5Error('SAVED_AUTHORIZATION_CHANGED')
    return auth


def campaign(root,plan,auth,*,create=False,test_double=False):
    path=Path(auth['campaign_path']).resolve()
    if path==root or path.is_relative_to(root):
        raise O5Error('CAMPAIGN_MUST_BE_SHARED_OUTSIDE_RUN')
    # A campaign is created for preflight only. Pilot can never reset it.
    if create:
        new_directory(path)
    return Budget(path,plan['profile'],campaign_identity(plan),jobs_for(plan),test_double,create=create)


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
    provider_options(body,profile)
    bound=len(task['prompt'].encode())+profile['token_bound']['framing_tokens']+2*profile['token_bound']['per_image_tokens']
    if bound>12000 or len(canonical(body).encode())>profile['max_request_bytes']:raise O5Error('INPUT_BOUND_EXCEEDED')
    return body,{'input_upper':bound,'output_upper':256,'image_sha256':[a['sha256'] for a in task['images']],
                 'algorithm':profile['token_bound']['algorithm'],'bound_evidence':profile['token_bound']['evidence'],
                 'body_digest':digest(body),'maximum_amount':charge(profile,bound,256)}


def preflight(plan_root,output,auth_path,*,resume=False,_offline_wire=None):
    plan_root=Path(plan_root).resolve();plan,_=validate_plan(plan_root)
    require_cost(plan['profile'])
    if plan['stage']!='preflight' or plan['mode']!='REMOTE_DRAFT':raise O5Error('WRONG_PREFLIGHT_PLAN')
    auth=authorization(plan,auth_path,'preflight')
    # Verify credentials before allocating any run/campaign directory.
    text_only=plan['schema_version']=='o5_direct_text_plan_v1'
    if _offline_wire is not None and (not text_only or _offline_wire.test_double is not True):
        raise O5Error('TEXT_OFFLINE_WIRE_REQUIRED')
    transport=ChatHTTPTransport(plan['profile'],_offline_wire);transport.precheck()
    root=Path(output).resolve() if resume else new_directory(output)
    identity=digest([digest(plan),str(root),digest(auth)])
    with exclusive(root/'run.lock'):
        if resume:
            state=read(root/'preflight.json')
            validate_preflight(state)
            saved_authorization(plan,root,state,'preflight')
            if state['identity']!=identity or state['test_double'] != transport.test_double:raise O5Error('PREFLIGHT_IDENTITY_CHANGED')
            if state['status']!='IN_PROGRESS':
                checked=verify_preflight(root)
                return {'status':checked['status'],'error':state['error'],'new_api_attempts':0}
        else:
            state={'schema_version':'o5_direct_text_preflight_v1' if text_only else 'o5_s2_preflight_v1','identity':identity,'plan':str(plan_root),'auth_digest':digest(auth),
                   'campaign':auth['campaign_path'],'status':'IN_PROGRESS','results':[],'error':None,
                   'test_double':transport.test_double}
            atomic(root/'authorization.json',auth)
            atomic(root/'preflight.json',state)
        budget=campaign(root,plan,auth,create=not resume,test_double=transport.test_double)
        if budget.load()['halt']:raise O5Error(budget.state['halt'])
        if resume and text_only:
            # Check completed probes before any further transmission after an interruption.
            verify_preflight_records(state,plan,budget)
        try:
            for task in plan['preflight_tasks']:
                if any(r['task_id']==task['task_id'] for r in state['results']):continue
                job='P_'+task['task_id']
                if task['task_id']=='probe_contract' or 'request_path' in task:
                    req=read(plan_root/task.get('request_path','contract/request.json'));ids=[];diagnostic=None;valid=False
                    for index in range(2):
                        body,bound=prepare_body(req,plan_root/Path(task.get('request_path','contract/request.json')).parent,plan['physical'],plan['profile'],diagnostic)
                        receipt,i,error=budget.attempt(job,req,body,bound,bool(index),transport);ids.append(i)
                        if error:break
                        try:validate_selection(receipt['text'],req,plan_root,task);valid=True;break
                        except O5Error as e:
                            diagnostic=e.code
                            if text_only and (index or e.code=='PREFLIGHT_PHYSICAL_REJECTION'):
                                error=e.code
                                break
                else:
                    body,bound=visual_body(task,plan_root,plan['profile'])
                    receipt,i,error=budget.attempt(job,task,body,bound,False,transport);ids=[i]
                    valid=False
                    if not error:valid,error=evaluate_visual(task,receipt['text'])
                state['results'].append({'task_id':task['task_id'],'attempt_ids':ids,'pass':bool(valid),'error':error})
                atomic(root/'preflight.json',state)
                if not valid:raise O5Error(error or 'PREFLIGHT_CAPABILITY_FAILED')
            state['status']='PASS'
        except O5Error as error:
            state['status']='HOLD_ENGINEERING';state['error']=error.code
        atomic(root/'preflight.json',state)
        atomic(root/'receipt_seal.json',{'files':{str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and p.name not in ('receipt_seal.json','run.lock')}})
        return {'status':state['status'],'completed_probes':len(state['results']),'error':state['error'],
                'real_api_attempts':0 if transport.test_double else len(budget.load()['attempts']),
                'test_double':transport.test_double,'offline_http_attempts':len(budget.state['attempts']) if transport.test_double else 0,'cost':budget.totals()}


def verify_preflight_records(state,plan,budget):
    text_only=plan['schema_version']=='o5_direct_text_plan_v1'
    tasks={t['task_id']:t for t in plan['preflight_tasks']};seen=[]
    for record in state['results']:
        if record['task_id'] in seen or record['task_id'] not in tasks:raise O5Error('PREFLIGHT_TASK_CHANGED')
        seen.append(record['task_id']);task=tasks[record['task_id']]
        rows=budget.rows('P_'+task['task_id'])
        if record['attempt_ids']!=[r['attempt_id'] for r in rows]:raise O5Error('PREFLIGHT_ATTEMPT_CHANGED')
        diagnostic=None;valid=False;error=None;done=False
        for index,row in enumerate(rows):
            if done:raise O5Error('UNEXPECTED_REPAIR_ATTEMPT')
            if task['task_id']=='probe_contract' or 'request_path' in task:
                req=read(Path(state['plan'])/task.get('request_path','contract/request.json'))
                body,bound=prepare_body(req,Path(state['plan'])/Path(task.get('request_path','contract/request.json')).parent,plan['physical'],plan['profile'],diagnostic)
            else:
                body,bound=visual_body(task,state['plan'],plan['profile'])
            if (row['body_digest']!=digest(body) or row['bound']!=bound
                    or (text_only and (row['request_digest']!=digest(req) or row['repair']!=bool(index)))):
                raise O5Error('PREFLIGHT_BODY_CHANGED')
            receipt=read(budget.root/'attempts'/row['attempt_id']/'receipt.json');error=row['error']
            if error:done=True;break
            try:
                if task['task_id']=='probe_contract' or 'request_path' in task:validate_selection(receipt['text'],req,Path(state['plan']),task);valid=True
                else:valid,error=evaluate_visual(task,receipt['text'])
            except (O5Error,ValueError,TypeError) as e:
                diagnostic=e.code if isinstance(e,O5Error) else 'INVALID_JSON'
                if text_only and (index or diagnostic=='PREFLIGHT_PHYSICAL_REJECTION'):
                    error=diagnostic
            done=valid or bool(error) or (task['task_id']!='probe_contract' and 'request_path' not in task)
        if record['pass']!=valid or record['error']!=error:raise O5Error('PREFLIGHT_RESULT_CHANGED')
    return tasks,seen


def verify_preflight(root):
    root=Path(root).resolve();state=read(root/'preflight.json');plan,_=validate_plan(state['plan'])
    validate_preflight(state)
    auth=saved_authorization(plan,root,state,'preflight')
    if state['identity']!=digest([digest(plan),str(root),digest(auth)]):
        raise O5Error('PREFLIGHT_IDENTITY_CHANGED')
    text_only=plan['schema_version']=='o5_direct_text_plan_v1'
    if state['schema_version']!=('o5_direct_text_preflight_v1' if text_only else 'o5_s2_preflight_v1'):
        raise O5Error('PREFLIGHT_PROTOCOL_MISMATCH')
    seal=read(root/'receipt_seal.json')
    if any(sha(root/f)!=h for f,h in seal['files'].items()):raise O5Error('PREFLIGHT_RECEIPT_CHANGED')
    budget=Budget(state['campaign'],plan['profile'],campaign_identity(plan),jobs_for(plan),state['test_double'])
    tasks,seen=verify_preflight_records(state,plan,budget)
    preflight_rows=[r for r in budget.state['attempts'] if r['phase']=='preflight']
    passed=(seen==list(tasks) and all(r['pass'] for r in state['results'])
            and not budget.state['halt']
            and all(r['status'] in ('completed','failed') for r in preflight_rows))
    if state['status']=='PASS' and not passed:raise O5Error('PREMATURE_PREFLIGHT_SUCCESS')
    return {'status':'PASS' if passed else 'HOLD_ENGINEERING','real_api_attempts':0 if state['test_double'] else len([r for r in budget.state['attempts'] if r['phase']=='preflight']),
            'plan':plan,'campaign':str(budget.root),'source_preflight':str(root),'test_double':state['test_double'],
            'protocol_version':plan.get('protocol_version','o5_direct_memory_v1'),'cost':budget.totals()}


def prepare_pilot_from_preflight(preflight_root,output):
    evidence=verify_preflight(preflight_root)
    if evidence['status']!='PASS':raise O5Error('PREFLIGHT_NOT_PASSED')
    if evidence['test_double']:raise O5Error('PREFLIGHT_NOT_REAL')
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
    if (evidence['test_double'] or evidence['status']!='PASS' or evidence['plan']['schema_version']!=plan['schema_version']
            or digest(evidence['plan']['profile'])!=digest(plan['profile'])
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
