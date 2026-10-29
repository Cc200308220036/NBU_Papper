"""O5 Direct-Text handoff for pallet_vlm. Only run-preflight/run-pilot send API requests."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from ..o5.common import ROOT,O5Error,atomic,digest,read,new_directory,offline_guard,sha
from ..o5 import remote_experiment as experiment
from ..o5.remote_authorized import preflight,verify_preflight,prepare_pilot_from_preflight,run_pilot
from ..o5.remote_config import require_cost

PROFILE=ROOT/'semantic_pallet_planner/configs/o5_direct_text_deepseek_flash.json'
DATASET=ROOT/'semantic_pallet_planner/outputs/DATA_O5_DIRECT_MEMORY_20261028_03'


def paths(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_]+',run_id):raise O5Error('INVALID_HANDOFF_ID')
    output=ROOT/'semantic_pallet_planner/outputs'
    return {'preflight_plan':output/f'PLAN_O5_DIRECT_TEXT_PREFLIGHT_{run_id}',
            'preflight_run':output/f'EXP_O5_DIRECT_TEXT_PREFLIGHT_{run_id}',
            'pilot_plan':output/f'PLAN_O5_DIRECT_TEXT_PILOT_{run_id}',
            'pilot_run':output/f'EXP_O5_DIRECT_TEXT_PILOT_{run_id}',
            'campaign':output/f'CAMPAIGN_O5_DIRECT_TEXT_{run_id}',
            'handoff':ROOT/f'report/analysis/O5_DIRECT_TEXT_HANDOFF_{run_id}',
            'pilot_report':ROOT/f'report/analysis/O5_DIRECT_TEXT_PILOT_{run_id}'}


def operator_record(plan_path,campaign,stage,run_id):
    plan=read(plan_path/'plan.json')
    return {'schema_version':'o5_s2_operator_authorization_v2','amount_policy':'unlimited',
            'plan_digest':digest(plan),'profile_digest':digest(plan['profile']),
            'account_id':plan['profile']['account_id'],'stage':stage,'campaign_path':str(campaign),
            'instruction_reference':f'2026-10-28 user explicitly authorized independent Direct-Text, existing DeepSeek Flash / pallet_vlm configuration and unlimited amount policy; operator explicitly runs {stage} command for handoff {run_id}. No automatic next-stage execution.'}


def prepare_handoff(run_id):
    p=paths(run_id)
    # Early directory collision checks, no overwriting historical plans/runs/campaigns.
    if any(path.exists() for path in p.values()):raise O5Error('HANDOFF_ID_ALREADY_USED')
    profile=require_cost(read(PROFILE))
    if profile['schema_version']!='o5_direct_text_provider_profile_v1':raise O5Error('TEXT_PROFILE_REQUIRED')
    if profile['amount_policy']!='unlimited':raise O5Error('HANDOFF_REQUIRES_UNLIMITED_PROFILE')
    prepared=experiment.prepare(DATASET,p['preflight_plan'],profile,stage='preflight')
    if prepared['gaps']:raise O5Error('DEEPSEEK_PROFILE_INCOMPLETE')
    dest=new_directory(p['handoff'])
    auth=operator_record(p['preflight_plan'],p['campaign'],'preflight',run_id)
    atomic(dest/'preflight_authorization.json',auth)
    plan=read(p['preflight_plan']/'plan.json')
    result={'schema_version':'o5_direct_text_handoff_v1','status':'READY_FOR_USER_TEXT_PREFLIGHT',
            'id':run_id,'provider':'deepseek','model':'deepseek-flash','credential_env':'DEEPSEEK_API_KEY',
            'amount_policy':'unlimited','maximum_preflight_requests':4,'maximum_pilot_requests':290,
            'plan_digest':digest(plan),'profile_sha256':sha(PROFILE),
            'paths':{k:str(v) for k,v in p.items()},'python_dependencies':plan['dependencies'],'protocol_version':plan['protocol_version'],
            'real_api_attempts':0,'not_claimed':'Real Direct-Text preflight pending; D0 Pilot performance unverified. Offline API calls: zero.',
            'commands':{name:f'python -B -m semantic_pallet_planner.runners.o5_direct_text {name} --id {run_id}'
                        for name in ('validate-plan','run-preflight','verify-preflight','report-preflight','prepare-pilot','run-pilot','verify-pilot','report-pilot')}}
    atomic(dest/'handoff.json',result)
    return result


def operate(command,run_id,resume=False):
    p=paths(run_id);handoff=read(p['handoff']/'handoff.json')
    if handoff['id']!=run_id or handoff['paths']!={k:str(v) for k,v in p.items()}:
        raise O5Error('HANDOFF_CHANGED')
    if digest(read(p['preflight_plan']/'plan.json'))!=handoff['plan_digest']:
        raise O5Error('HANDOFF_PLAN_CHANGED')
    if handoff.get('protocol_version')!='o5_direct_text_v1':raise O5Error('TEXT_PROTOCOL_REQUIRED')
    if command=='validate-plan':
        plan,tasks=experiment.validate_plan(p['preflight_plan'])
        return {'status':'READY_FOR_USER_TEXT_PREFLIGHT','plan_digest':digest(plan),'protocol_version':plan['protocol_version'],'gaps':plan['gaps'],'real_api_attempts':0}
    if command=='report-preflight':
        checked=verify_preflight(p['preflight_run'])
        dest=new_directory(ROOT/f'report/analysis/O5_DIRECT_TEXT_PREFLIGHT_{run_id}')
        checked={k:v for k,v in checked.items() if k!='plan'}
        atomic(dest/'verification.json',checked)
        return checked
    if command=='run-preflight':
        return preflight(p['preflight_plan'],p['preflight_run'],p['handoff']/'preflight_authorization.json',resume=resume)
    if command=='verify-preflight':
        checked=verify_preflight(p['preflight_run'])
        return {k:v for k,v in checked.items() if k!='plan'}
    if command=='prepare-pilot':
        evidence=verify_preflight(p['preflight_run'])
        if evidence['plan'].get('protocol_version')!='o5_direct_text_v1':raise O5Error('TEXT_PROTOCOL_REQUIRED')
        result=prepare_pilot_from_preflight(p['preflight_run'],p['pilot_plan'])
        atomic(p['handoff']/'pilot_authorization.json',operator_record(p['pilot_plan'],p['campaign'],'pilot',run_id))
        return result
    if command=='run-pilot':
        return run_pilot(p['pilot_plan'],p['pilot_run'],p['handoff']/'pilot_authorization.json',resume=resume)
    if command=='verify-pilot':
        checked=experiment.verify(p['pilot_run'])
        return {k:v for k,v in checked.items() if k!='results'}
    return experiment.report(p['pilot_run'],p['pilot_report'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','validate-plan','report-preflight','run-preflight','verify-preflight','prepare-pilot','run-pilot','verify-pilot','report-pilot'])
    parser.add_argument('--id')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args(argv)
    if args.id is None:
        if args.command!='prepare':parser.error('--id is required for existing handoffs')
        args.id=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S')
    if args.resume and args.command not in ('run-preflight','run-pilot'):parser.error('--resume only applies to API execution')
    def invoke():return prepare_handoff(args.id) if args.command=='prepare' else operate(args.command,args.id,args.resume)
    try:
        if args.command in ('run-preflight','run-pilot'):result=invoke()
        else:
            with offline_guard():result=invoke()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except O5Error as error:
        print(json.dumps({'status':'ERROR','error':error.code,'message':'Stopped; preserve artifacts. No automatic retries or model changes.'},ensure_ascii=False))
        raise SystemExit(1) from None
    if result.get('status') in ('HOLD_ENGINEERING','INVALID_OR_PARTIAL','PARTIAL'):raise SystemExit(1)


if __name__=='__main__':main()
