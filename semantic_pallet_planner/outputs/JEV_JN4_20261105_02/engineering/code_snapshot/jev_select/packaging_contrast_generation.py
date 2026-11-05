"""JN3-B two-task durable generation using the existing credential/single-send IO.

No prepare/review/validation path reads credentials. No repair, extra reviewer
model, connectivity request, model listing or inherited J4 generation allowance.
"""
from __future__ import annotations
import argparse
import base64
from pathlib import Path
import shutil
from .contracts import canonical,digest,validate_schema
from .ledger import read,write,exclusive
from .experiment import source_manifest
from .packaging_experience import require,sha
from . import packaging_experience as t
from . import packaging_contrast as e
from .memory_generation import _send,_response_metadata
from .transport import strict_json

REPO=Path(__file__).resolve().parents[4]
A=REPO/'semantic_pallet_planner/outputs/JEV_JN3_20261104_01'
PARENT=REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03'
ACCOUNT='semantic_pallet_planner/outputs/JEV_JN3_B_ACCOUNTING_V1'
CONFIG={'endpoint':'https://api.deepseek.com/chat/completions','model':'deepseek-v4-pro',
        'documented_version':'DeepSeek-V4-Pro-0813','thinking':{'type':'disabled'},'temperature':0,
        'max_tokens':2048,'response_format':{'type':'json_object'},'timeout_s':60,'max_retries':0,
        'response_max_bytes':1000000,'cost_status':'UNKNOWN; usage saved, no inferred billing receipt'}


def prepare(root,*,fixture_only=False):
    from .packaging_comparisons import checked_manifest
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    require(not (root/'generation_plan.json').exists(),'contrast_generation_already_prepared')
    parents={'T':checked_manifest(A),'comparisons':checked_manifest(PARENT)}
    parent=read(A/'trajectory_snapshot.json');t.validate_snapshot(parent)
    require(len(parent['cases'])==2 and [c['provenance']['comparison_id'] for c in parent['cases']]==['F00_B02','F02_B02'],'contrast_generation_input_scope')
    jobs=[]
    for i,case in enumerate(parent['cases']):
        pack=e.build_fact_pack(case,REPO,PARENT)
        if fixture_only:
            pack['fixture_only']=True;pack=e.sealed({k:v for k,v in pack.items() if k!='pack_digest'},'pack_digest')
        e.validate_fact_pack(pack,REPO)
        jid=f'G{i:02d}';body=e.generation_body(pack)
        request={'version':'packaging_contrast_request_v1','config':CONFIG,'prompt_version':'packaging_contrast_prompt_v1',
                 'pack_digest':pack['pack_digest'],'grammar_digest':digest(e.GRAMMAR),'body':body,'wire_digest':digest(body)}
        request['request_digest']=digest(request)
        jobs.append({'job_id':jid,'comparison_id':case['provenance']['comparison_id'],'pack_digest':pack['pack_digest'],
           'request_digest':request['request_digest'],'attempt_id':digest({'stage':'JN3-B','parent':parents['comparisons']['manifest_sha256'],'comparison_id':case['provenance']['comparison_id']})})
        write(root/'facts'/f'{jid}.json',pack);write(root/'generation_requests'/f'{jid}.json',request)
    from datetime import datetime,timezone
    plan={'version':'JN3-B_generation_plan_v1','frozen_at':datetime.now(timezone.utc).isoformat(),'parents':parents,'T_snapshot_digest':parent['snapshot_digest'],
          'jobs':jobs,'config':CONFIG,'grammar':e.GRAMMAR,'fixture_only':fixture_only,
          'source_manifest':source_manifest(),'source_digest':digest(source_manifest()),
          'max_generation_sends':2,'max_sends_per_job':1,'max_Jev_E_sends':1,'review_model_sends':0,
          'query_rule':'same first parent JN1-B task and receive-only initial prefix as JN3-A; whole-source exclusion; no replacement query',
          'stop_on_unknown_send':True,'no_repair_or_regeneration':True}
    plan=e.sealed(plan,'plan_digest');write(root/'generation_plan.json',plan);write(root/'source_manifest.json',source_manifest())
    package=Path(__file__).resolve().parents[1]
    for n in source_manifest():
        target=root/'code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(package/n,target)
    return plan


def validate_plan(root):
    from .packaging_comparisons import checked_manifest
    root=Path(root);p=read(root/'generation_plan.json');e.verify_seal(p,'plan_digest')
    require(p['config']==CONFIG and p['grammar']==e.GRAMMAR,'contrast_generation_contract_changed')
    require(p['parents']=={'T':checked_manifest(A),'comparisons':checked_manifest(PARENT)},'contrast_generation_parent_changed')
    require(p['source_manifest']==source_manifest()==read(root/'source_manifest.json') and digest(source_manifest())==p['source_digest'],'contrast_generation_source_changed')
    require(all(sha(root/'code_snapshot'/n)==h for n,h in p['source_manifest'].items()),'contrast_generation_archive_changed')
    parent=read(A/'trajectory_snapshot.json')
    for j,case in zip(p['jobs'],parent['cases']):
        expected=e.build_fact_pack(case,REPO,PARENT)
        if p['fixture_only']:
            expected['fixture_only']=True;expected=e.sealed({k:v for k,v in expected.items() if k!='pack_digest'},'pack_digest')
        pack=read(root/'facts'/f"{j['job_id']}.json");request=read(root/'generation_requests'/f"{j['job_id']}.json")
        require(pack==expected and j['pack_digest']==pack['pack_digest'],'contrast_generation_fact_binding_changed')
        require(request['body']==e.generation_body(pack) and request['wire_digest']==digest(request['body']) and request['request_digest']==digest({k:v for k,v in request.items() if k!='request_digest'})==j['request_digest'],'contrast_generation_request_changed')
    require(len(p['jobs'])==2 and [j['comparison_id'] for j in p['jobs']]==['F00_B02','F02_B02'],'contrast_generation_jobs_changed')
    return p


def parse_generation(result):
    if result.get('status')!='OK':return None,['transport_'+result.get('status','UNKNOWN')],{}
    try:
        raw=base64.b64decode(result['raw_body_b64'],validate=True);require(len(raw)<=CONFIG['response_max_bytes'],'contrast_generation_response_too_large')
        value=strict_json(raw);require(isinstance(value,dict) and value.get('model')==CONFIG['model'],'contrast_generation_served_model_changed')
        require(len(value['choices'])==1 and value['choices'][0]['finish_reason']=='stop','contrast_generation_incomplete')
        content=value['choices'][0]['message']['content'];require(isinstance(content,str) and content.strip(),'contrast_generation_empty')
        candidate=strict_json(content.encode());validate_schema('packaging_contrast_generation_v1',candidate)
        return candidate,[],{k:value.get(k) for k in ('model','id','usage','system_fingerprint')}
    except (ValueError,KeyError,IndexError,TypeError,AttributeError):return None,['invalid_json_schema_or_model_or_finish'],{}


def review_result(root,job,result,*,origin):
    root=Path(root);pack=read(root/'facts'/f"{job['job_id']}.json");candidate,errors,metadata=parse_generation(result)
    record={'job_id':job['job_id'],'comparison_id':job['comparison_id'],'candidate':candidate,'parse_errors':errors,'metadata':metadata,
            'pack_digest':pack['pack_digest'],'request_digest':job['request_digest'],'origin':origin,
            'raw_response_digest':digest(result),'fact_audit':None,'semantic_review':None,'status':'REJECTED','card':None}
    if result.get('status')=='UNKNOWN_IN_FLIGHT':record['status']='UNKNOWN_SEND'
    elif result.get('status') in ('HTTP_FAILURE','NOT_SENT'):record['status']='FAILED'
    if candidate is not None:
        audit=e.fact_audit(candidate,pack);review=e.semantic_review(candidate,pack,audit)
        record.update(fact_audit=audit,semantic_review=review,status=review['status'])
        if review['status']=='APPROVED':
            attempt={'origin':origin,'candidate_digest':digest(candidate),'pack_digest':pack['pack_digest'],
                     'request_digest':job['request_digest'],'response_digest':digest(result),'attempt_id':job['attempt_id'],
                     'prompt_version':'packaging_contrast_prompt_v1','grammar_digest':digest(e.GRAMMAR),'requested_model':CONFIG['model'],**metadata}
            record['card']=e.make_card(candidate,pack,attempt)
    return e.sealed(record,'review_record_digest')


def collect(root):
    root=Path(root);plan=validate_plan(root);rows=[]
    for j in plan['jobs']:
        path=root/'generation_accounting/responses'/f"{j['attempt_id']}.json"
        if path.exists():rows.append(review_result(root,j,read(path),origin='fixture' if plan['fixture_only'] else 'deepseek'))
        else:
            attempt=root/'generation_accounting/attempts'/f"{j['attempt_id']}.json"
            rows.append({'job_id':j['job_id'],'comparison_id':j['comparison_id'],'status':'UNKNOWN_SEND' if attempt.exists() else 'NOT_RUN','card':None})
    return rows


def run(root,*,fixture_paths=None,hook=None):
    root=Path(root).resolve();plan=validate_plan(root)
    fixture=plan['fixture_only'];require(fixture==(fixture_paths is not None),'contrast_generation_transport_mode_changed')
    budget=root/'fixture_global_budget' if fixture else REPO/ACCOUNT
    budget.mkdir(parents=True,exist_ok=True)
    with exclusive(budget):
        owner={'output':str(root.relative_to(REPO)) if root.is_relative_to(REPO) else str(root),'plan_digest':plan['plan_digest'],'jobs':[j['attempt_id'] for j in plan['jobs']]}
        if (budget/'owner.json').exists():require(read(budget/'owner.json')==owner,'contrast_stage_budget_already_owned')
        else:write(budget/'owner.json',owner)
        account=root/'generation_accounting'
        for j in plan['jobs']:
            if any((read(f).get('state')=='UNKNOWN_IN_FLIGHT' or read(f).get('transport_status')=='UNKNOWN_IN_FLIGHT') for f in (account/'attempts').glob('*.json')):break
            request=read(root/'generation_requests'/f"{j['job_id']}.json")
            result=_send(account,j['attempt_id'],request,request['body'],'offline_fixture' if fixture else 'remote_text',REPO,
                         fixture_paths[j['job_id']] if fixture else None,hook,operation='JN3-B_extract_once')
            record=review_result(root,j,result,origin='fixture' if fixture else 'deepseek')
            write(root/'reviews'/f"{j['job_id']}.json",record)
            if result['status']=='UNKNOWN_IN_FLIGHT':break
        rows=collect(root)
        write(root/'generation_reviews.json',rows)
        # All outcomes retained. Only both independent approvals can enter frozen E.
        cards=[r['card'] for r in rows if r.get('card') is not None]
        if (root/'contrast_snapshot.json').exists():
            existing=read(root/'contrast_snapshot.json');e.validate_snapshot(existing)
            frozen=e.freeze_snapshot(cards,frozen_at=existing['frozen_at'])
            require(frozen.data==existing,'contrast_frozen_snapshot_changed')
        else:
            frozen=e.freeze_snapshot(cards);write(root/'contrast_snapshot.json',frozen.data)
        ledger=statistics(root,plan,rows);write(root/'generation_ledger.json',ledger)
        return ledger


def statistics(root,plan,rows):
    root=Path(root);attempts=[]
    for j in plan['jobs']:
        f=root/'generation_accounting/attempts'/f"{j['attempt_id']}.json"
        if f.exists():attempts.append(read(f))
    unknown=sum(a['state'] in ('UNKNOWN_IN_FLIGHT','RESERVED_POSSIBLY_SENT') or a.get('transport_status')=='UNKNOWN_IN_FLIGHT' for a in attempts)
    return {'stage':'JN3-B','version':'packaging_contrast_generation_ledger_v1','fixture_only':plan['fixture_only'],
            'send_reservations':len(attempts),'confirmed_request_results':sum(a.get('transport_status') in ('OK','HTTP_FAILURE') for a in attempts),
            'unknown_sends':unknown,'not_sent':sum(a.get('transport_status')=='NOT_SENT' for a in attempts),
            'transport_failures':sum(a.get('transport_status')=='HTTP_FAILURE' for a in attempts),
            'parse_failures':sum(bool(r.get('parse_errors')) for r in rows),'approved':sum(r['status']=='APPROVED' for r in rows),
            'rejected':sum(r['status']=='REJECTED' for r in rows),'pending':sum(r['status']=='PENDING_REVIEW' for r in rows),
            'not_run':sum(r['status']=='NOT_RUN' for r in rows),'usage':[a.get('usage') for a in attempts],
            'requested_model':CONFIG['model'],'served_models':[a.get('served_model') for a in attempts],
            'latency_s':[a.get('latency_s') for a in attempts],'cost_usd':'UNKNOWN' if attempts and not plan['fixture_only'] else 0,
            'review_model_calls':0,'retry_count':0,'historical_T_Jev_calls':1}


def validate_saved(root):
    root=Path(root);plan=validate_plan(root);expected=collect(root)
    require(read(root/'generation_reviews.json')==expected,'contrast_saved_reviews_changed')
    require(read(root/'generation_ledger.json')==statistics(root,plan,expected),'contrast_saved_account_changed')
    s=read(root/'contrast_snapshot.json');e.validate_snapshot(s)
    require(e.freeze_snapshot([r['card'] for r in expected if r.get('card')],frozen_at=s['frozen_at']).data==s,'contrast_saved_snapshot_changed')
    for j in plan['jobs']:
        account=root/'generation_accounting';path=account/'attempts'/f"{j['attempt_id']}.json";rawpath=account/'responses'/f"{j['attempt_id']}.json"
        if not path.exists():continue
        row=read(path);request=read(root/'generation_requests'/f"{j['job_id']}.json")
        require(row['request_digest']==j['request_digest'] and row['wire_digest']==request['wire_digest'] and row['mode']==('offline_fixture' if plan['fixture_only'] else 'remote_text') and row['operation']=='JN3-B_extract_once','contrast_attempt_binding_changed')
        require(read(account/'wire_requests'/f"{j['attempt_id']}.json")['body']==read(root/'generation_requests'/f"{j['job_id']}.json")['body'],'contrast_saved_wire_changed')
        if rawpath.exists():
            response=read(rawpath);require(row['response_digest']==digest(response),'contrast_generation_response_changed')
            require(response['raw_digest']==digest(response['raw_body_b64']),'contrast_raw_envelope_changed')
            require(response['raw_sha256']==__import__('hashlib').sha256(base64.b64decode(response['raw_body_b64'])).hexdigest(),'contrast_raw_response_changed')
            m=copy_metadata(row,response);require(m==row,'contrast_generation_usage_changed')
    return {'status':'PASS','cards':len(s['cards']),'generation':read(root/'generation_ledger.json')}


def copy_metadata(row,result):
    import copy
    r=copy.deepcopy(row);_response_metadata(r,result);return r


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','validate']);p.add_argument('--output',required=True);a=p.parse_args()
    result=prepare(a.output) if a.command=='prepare' else run(a.output) if a.command=='run' else validate_saved(a.output)
    print(canonical(result if a.command!='prepare' else {'plan_digest':result['plan_digest'],'jobs':len(result['jobs'])}))
if __name__=='__main__':main()
