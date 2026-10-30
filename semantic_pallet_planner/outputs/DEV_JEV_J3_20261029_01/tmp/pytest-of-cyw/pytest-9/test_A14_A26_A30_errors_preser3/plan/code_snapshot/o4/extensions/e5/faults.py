"""Executable E5 fault evidence using injected HTTP, never real credentials/API."""
import copy
import io
import json
import os
import shutil
from pathlib import Path
from urllib.error import URLError
from ...common import read,write,O4Error,digest
from ..e2.faults import run_faults as shared_faults
from ..e2.compiler import compile_policy
from ..e2.protocol import rebind,validate_response
from ...remote.transport import ModelConfig,ChatTransport
from .backends import Ledger,LocalCompiler,RemoteCompiler
from .episode import episode,verify_episode,stable


def run_faults(data,config,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    rows=[{'scope':'shared_E2_contract',**r} for r in shared_faults(data['shared_contract_fixtures'],config,root/'shared')]
    task=data['constructs'][0];q=data['gold'][0]['request']
    def record(name,passed,**evidence):rows.append({'scope':'E5','purpose':name,'passed':bool(passed),**evidence})
    def reject(name,fn):
        try:fn()
        except O4Error as exc:record(name,True,error=str(exc))
        else:record(name,False)
    from unittest.mock import patch
    from .experiment import prepare
    failed_prepare=root/'failed_initialization'
    try:
        with patch('semantic_pallet_planner.o4.extensions.e5.experiment.source_tasks',side_effect=O4Error('injected_source_read_failure')):
            prepare(failed_prepare,root/'unused_protection.json')
    except O4Error as exc:
        saved=read(failed_prepare/'acceptance_report.json')
        record('initialization_failure_records_denominator',exc.code=='injected_source_read_failure' and saved['status']=='FAIL'
               and saved['not_run_jobs']==240 and saved['materialized_jobs']==saved['recorded_episodes']==0
               and saved['new_api_attempts']==0 and (failed_prepare/'audit/initialization_error.json').is_file(),
               report_path=str(failed_prepare/'acceptance_report.json'),planned_jobs=240)
    else:record('initialization_failure_records_denominator',False)
    empty=lambda a:{**a,'rules':[]}
    invert=lambda a:{**a,'rules':[{**r,'relation':{'left_of':'right_of','right_of':'left_of','front_of':'behind','behind':'front_of'}[r['relation']]} if r['type']=='relative_position' else r for r in a['rules']]}
    direction_task=copy.deepcopy(task)
    for r in direction_task['regions']:
        r.update(x_min_mm=-500,x_max_mm=500,y_min_mm=-500,y_max_mm=500)
    write(root/'wrong_ast_direction_task.json',direction_task)
    for name,t,transform in [('wrong_ast_drop',data['constructs'][4],empty),('wrong_ast_direction',direction_task,invert)]:
        result=episode(t,'public_parser','single',config,LocalCompiler('public_parser',transform=transform),name)
        verify_episode(result,t,config);result.pop('checkpoints');write(root/f'{name}.json',result)
        record(name,result['summary']['completed'] and bool(result['summary']['final_business_violations']),summary=result['summary'])
    altered=copy.deepcopy(task);altered['items'][3]['mass_kg']=99.
    a=episode(task,'public_parser','buffer_search',config,LocalCompiler('public_parser'),'future')
    b=episode(altered,'public_parser','buffer_search',config,LocalCompiler('public_parser'),'future')
    record('e5_hidden_future_invariance',stable(next(e for e in a['events'] if 'request'in e))==stable(next(e for e in b['events'] if 'request'in e)))
    corrupted=copy.deepcopy(a);corrupted['summary']['completed']=not corrupted['summary']['completed']
    reject('e5_summary_tamper',lambda:verify_episode(corrupted,task,config))
    from ..e2.protocol import validate_policy
    bad=copy.deepcopy(task['reference_policy']);bad['rules'].append({'rule_id':'yaw','type':'allowed_yaw','target':{'all':True},'angles':[0,90],'priority':20,'overrides':[]})
    reject('unsupported_allowed_yaw_ast',lambda:validate_policy(bad,q))
    changed=copy.deepcopy(q);changed['rendering_version']='unsupported_render'
    reject('changed_render_version',lambda:rebind(changed))
    corrupted=copy.deepcopy(a);corrupted['events'][0]['after']['end_of_stream']=True
    reject('e5_event_tamper',lambda:verify_episode(corrupted,task,config))
    unsupported=rebind({**q,'instruction_text':'要求箱体旋转180°。'})
    reject('explicit_unsupported_yaw_instruction',lambda:LocalCompiler('public_parser').compile(unsupported,'unsupported',0))
    original_key=os.environ.get('E5_FAULT_TEST_KEY');os.environ['E5_FAULT_TEST_KEY']='offline-test-double'
    try:
        def transport(reply=None):
            bodies=[]
            def opener(request,timeout):
                body=json.loads(request.data);bodies.append(body)
                envelope=json.loads(body['messages'][1]['content'][0]['text'])['public_input']
                response=reply(envelope['public_request'],len(bodies)) if reply else compile_policy(envelope['public_request'])
                payload={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(response)}}],'usage':{'total_tokens':1}}
                class Response(io.BytesIO):
                    def __enter__(self):return self
                    def __exit__(self,*args):self.close()
                return Response(json.dumps(payload).encode())
            model=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='e5-fault-double',api_key_env='E5_FAULT_TEST_KEY')
            return ChatTransport(model,opener=opener,test_double=True),bodies
        t,bodies=transport();path=root/'remote_image_commit';ledger=Ledger(path,10,{'image':10},test_double=True)
        image=episode(task,'remote_image','buffer_search',config,RemoteCompiler(path,t,ledger).bound('image'),'image')
        verify_episode(image,task,config);image.pop('checkpoints');write(path/'episode.json',image)
        record('remote_image_commit',image['summary']['clean_completed'] and len(bodies)==4 and all(e['request']['images'] and e['action']['observation_digest']==e['response']['observation_digest'] for e in image['events'] if e.get('action')),test_double=True,attempts=len(bodies))
        path=root/'fairness';t,bodies=transport();ledger=Ledger(path,4,{'txt':2,'img':2},test_double=True);remote=RemoteCompiler(path,t,ledger)
        text=remote.compile(q,'txt',0,'text');image=remote.compile(q,'img',0,'image')
        record('text_image_fairness',text['envelope']['visual_facts']==image['envelope']['visual_facts'] and
               {k:v for k,v in bodies[0].items() if k!='messages'}=={k:v for k,v in bodies[1].items() if k!='messages'} and
               len(bodies[0]['messages'][1]['content'])==1 and bodies[1]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'),test_double=True)
        changed=rebind({**q,'images':image['compiled_request']['images']})
        reject('image_response_into_plain_request',lambda:validate_response(image['response'],q))
        path=root/'budget';t,bodies=transport(lambda q,n:{'invalid':'format'} if n==1 else compile_policy(q))
        ledger=Ledger(path,3,{'a':4,'b':4},test_double=True);remote=RemoteCompiler(path,t,ledger)
        first=remote.compile(q,'a',0,'image');second=remote.compile(q,'b',0,'text');third=remote.compile(q,'b',1,'text')
        restored=Ledger(path,3,{'a':4,'b':4},test_double=True,resume=True)
        recovered=RemoteCompiler(path,t,restored,recover=True).compile(q,'a',0,'image')
        record('global_budget_repair_and_resume',len(bodies)==3 and first['repaired_valid'] and second['first_valid'] and third['status']=='budget_exhausted' and recovered['response']==first['response'] and restored.report()['used_attempts']==3,test_double=True,budget=restored.report())
        reject('budget_increase_on_resume',lambda:Ledger(path,4,{'a':4,'b':4},test_double=True,resume=True))
        reset_copy=root/'reset_attempts_copy';shutil.copytree(path,reset_copy)
        reset=read(reset_copy/'audit/ledger.json');reset['attempts']=[];write(reset_copy/'audit/ledger.json',reset)
        try:Ledger(reset_copy,3,{'a':4,'b':4},test_double=True,resume=True)
        except O4Error as exc:record('attempt_list_reset_rejected_before_http',exc.code=='ledger_record_disagreement',error=str(exc),test_double=True)
        else:record('attempt_list_reset_rejected_before_http',False,test_double=True)
        def stale(q,n):
            r=compile_policy(q);r['state_hash']='0'*64;return r
        path=root/'stale';t,bodies=transport(stale);ledger=Ledger(path,4,{'stale':4},test_double=True)
        failure=RemoteCompiler(path,t,ledger).compile(q,'stale',0,'text')
        record('repair_still_invalid_no_fallback',failure['response'] is None and failure['status']=='invalid_binding' and len(bodies)==2,test_double=True)
        path=root/'inflight';t,bodies=transport();ledger=Ledger(path,4,{'uncertain':4},test_double=True)
        def crash(body):raise KeyboardInterrupt('injected process interruption after budget reservation')
        t.complete=crash
        try:RemoteCompiler(path,t,ledger).compile(q,'uncertain',0,'text')
        except KeyboardInterrupt:pass
        unknown=RemoteCompiler(path,t,Ledger(path,4,{'uncertain':4},test_double=True,resume=True),recover=True).compile(q,'uncertain',0,'text')
        record('unknown_attempt_not_resent',unknown['status']=='unknown_in_flight' and len(ledger.rows())==1 and not bodies,test_double=True)
        path=root/'commit_crash';t,bodies=transport();ledger=Ledger(path,10,{'job':10},test_double=True);checkpoints=[]
        def checkpoint(cp,phase):
            checkpoints.append(cp)
            if phase=='before_commit':raise KeyboardInterrupt('injected crash before PLACE')
        try:episode(task,'remote_image','single',config,RemoteCompiler(path,t,ledger).bound('image'),'job',on_checkpoint=checkpoint)
        except KeyboardInterrupt:pass
        restored=episode(task,'remote_image','single',config,RemoteCompiler(path,t,ledger,recover=True).bound('image'),'job',resume=checkpoints[-1])
        verify_episode(restored,task,config);restored.pop('checkpoints');write(path/'resumed_episode.json',restored)
        record('http_saved_before_commit_resume',restored['summary']['clean_completed'] and len(bodies)==4 and restored['final_state']['placed_count']==4,test_double=True)
        path=root/'provider';model=ModelConfig(endpoint='https://offline.invalid/chat/completions',model='fault',api_key_env='E5_FAULT_TEST_KEY')
        def outage(req,timeout):raise URLError('injected outage')
        t=ChatTransport(model,opener=outage,test_double=True);ledger=Ledger(path,4,{'outage':4},test_double=True)
        failure=RemoteCompiler(path,t,ledger).compile(q,'outage',0,'text')
        record('provider_failure_no_fallback',failure['status']=='provider_error' and failure['response'] is None and len(ledger.rows())==1,test_double=True)
    finally:
        if original_key is None:os.environ.pop('E5_FAULT_TEST_KEY',None)
        else:os.environ['E5_FAULT_TEST_KEY']=original_key
    return rows
